"""从 index.json 与归档 README 生成插件商店静态站点，供 publish.yml 的 deploy 作业调用。

输出目录（默认 site/）结构：插件列表 /、插件详情 /plugins/<id>/、登记说明 /submit/、
/404.html、与仓库逐字节相同的 /index.json，以及静态资源、字体、头像与图标。
/packages/<id>/<版本>.zip 由部署作业从 Release 下载到输出目录，本脚本只核对其摘要与大小，
不重新打包、不删除。README 来自 package.py 写入的 readme/<id>/<版本>.md，
经 markdown-it-py 渲染后用 nh3 白名单清洗；模板位于 site-templates/，使用 Jinja2。
下载次数由浏览器从 Worker 的 /stats.json 读取，生成时不访问任何外部服务。
"""
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markdown_it import MarkdownIt
from markupsafe import Markup
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import argparse
import hashlib
import json
import nh3
import shutil

from .common import identity

# 模板与静态资源目录，相对仓库根目录。
TEMPLATES = Path(__file__).resolve().parents[1]/'site-templates'
# 复制到站点根目录的图片：头像与浏览器图标，取自主程序 docs/images/。
ROOT_FILES = ('logo.png','favicon.png')
# 管理面板默认地址，与 site-templates/static/install.js 的 DEFAULT_PANEL 一致；
# 页面先用它生成链接，脚本加载后按访客保存的地址改写。
DEFAULT_PANEL = 'http://127.0.0.1:7999'
# README 允许保留的元素；script、style、iframe、form 及其他未列出的元素一律去掉。
README_TAGS = {'a','abbr','b','blockquote','br','code','dd','del','details','div','dl','dt','em','h1','h2','h3','h4','h5','h6',
               'hr','i','img','kbd','li','ol','p','pre','s','span','strong','sub','summary','sup','table','tbody','td','th',
               'thead','tr','ul'}
# README 元素允许保留的属性；未列出的属性（含全部 on* 事件属性与 style）一律去掉。
README_ATTRIBUTES = {'a':{'href','title'},'img':{'src','alt','title','width','height'},'td':{'align'},'th':{'align'},
                     'ol':{'start'},'code':{'class'}}
# README 链接允许的协议；javascript:、data: 等协议的 href 会被去掉。
README_SCHEMES = {'http','https','mailto'}


def _keep_attribute(tag: str, attribute: str, value: str) -> Optional[str]:
    """nh3 属性回调：img 只保留 https:// 来源。

    明文 http 图片会在 https 商店页面上触发混合内容警告，也可能被中间人替换，
    相对路径图片在商店域名下不存在，统一去掉 src。

    :param tag: 元素名。
    :param attribute: 属性名。
    :param value: 属性原值。
    :return: 保留时返回原值，返回 None 表示删除该属性。
    """
    if tag=='img' and attribute=='src' and not value.startswith('https://'):
        return None
    return value


def render_readme(text: str) -> Markup:
    """把第三方 README 渲染为可直接嵌入页面的安全 HTML。

    :param text: Markdown 原文，可含内嵌 HTML。
    :return: 经白名单清洗的 HTML；链接统一加 rel="noopener noreferrer nofollow"。
    """
    html=MarkdownIt('commonmark',{'html':True}).enable(['table','strikethrough']).render(text)
    return Markup(nh3.clean(html,tags=README_TAGS,attributes=README_ATTRIBUTES,url_schemes=README_SCHEMES,
                            attribute_filter=_keep_attribute,link_rel='noopener noreferrer nofollow'))


def safe_url(value: Optional[str]) -> Optional[str]:
    """只把 http(s) 绝对地址当作可点击链接，防止清单里的 javascript: 等地址进入 href。

    :param value: 清单或登记里的地址，可为 None。
    :return: 原地址或 None（不生成链接）。
    """
    if not value: return None
    parsed=urlparse(value)
    return value if parsed.scheme in ('http','https') and parsed.netloc else None


def repository_label(url: str) -> str:
    """把仓库地址显示为 owner/repo，去掉协议、主机与 .git 后缀。"""
    path=urlparse(url).path.strip('/').removesuffix('.git')
    return path or url


def verify_packages(index: Dict[str,Any], output: Path, *, allow_missing: bool) -> None:
    """核对输出目录中的插件包与索引摘要一致，避免页面链接指向错误字节。

    :param index: 解析后的 index.json。
    :param output: 站点输出目录，包位于 packages/<id>/<版本>.zip。
    :param allow_missing: 仅供本地预览：允许包缺失，但已存在的包仍须摘要一致。
    :raises ValueError: 包缺失（未允许时）或大小、摘要与索引不符。
    """
    for plugin in index['plugins']:
        for row in plugin['versions']:
            path=output/'packages'/identity(plugin['id'])/f'{row["version"]}.zip'
            if not path.is_file():
                if allow_missing: continue
                raise ValueError(f'缺少插件包：{path}')
            data=path.read_bytes()
            if len(data)!=row['size'] or hashlib.sha256(data).hexdigest()!=row['sha256']:
                raise ValueError(f'插件包大小或摘要与索引不符：{path}')


def plugin_view(plugin: Dict[str,Any], root: Path) -> Dict[str,Any]:
    """把索引里的插件条目整理成模板直接使用的字段。

    :param plugin: index.json 中的单个插件。
    :param root: 索引仓库根目录，用于读取 readme/<id>/<版本>.md。
    :return: 显示用字典；latest 为最新未撤回版本，全部撤回时为 None。
    :raises FileNotFoundError: 展示版本的 README 归档缺失。
    """
    author=plugin['author']
    # 宿主清单允许 author 写成字符串或 {name, url}；字符串即名称，没有链接。
    name,url=(author,None) if isinstance(author,str) else (author['name'],author.get('url'))
    versions=[]
    for row in plugin['versions']:
        bounds=row['host_application']
        versions.append(dict(version=row['version'],range=f'{bounds["min_version"]} – {bounds["max_version"]}',
                             date=row['published_at'][:10],yanked=row['yanked'],sha256=row['sha256'],
                             dependencies=row['python_dependencies'],
                             package=None if row['yanked'] else f'/packages/{plugin["id"]}/{row["version"]}.zip'))
    latest=next((row for row in versions if not row['yanked']),None)
    current=latest or versions[0]
    readme=(root/'readme'/identity(plugin['id'])/f'{current["version"]}.md').read_text(encoding='utf-8')
    return dict(id=plugin['id'],name=plugin['name'],description=plugin['description'],license=plugin['license'],
                tags=plugin['tags'],author_name=name,author_url=safe_url(url),repository_url=safe_url(plugin['repository']),
                repository_label=repository_label(plugin['repository']),versions=versions,latest=latest,current=current,
                readme=render_readme(readme) if readme.strip() else None,
                search=' '.join((plugin['name'],plugin['description'],plugin['id'])).lower())


def collect_tags(plugins: List[Dict[str,Any]]) -> List[str]:
    """取全部插件 tags 的并集，按首次出现顺序排列，作为分类按钮。"""
    result=[]
    for plugin in plugins:
        for tag in plugin['tags']:
            if tag not in result: result.append(tag)
    return result


def build_site(root: Path, output: Path, *, templates: Path = TEMPLATES, allow_missing_packages: bool = False) -> None:
    """生成完整静态站点。

    :param root: 索引仓库根目录，读取 index.json 与 readme/。
    :param output: 输出目录；会替换其中的页面与静态资源，保留 packages/。
    :param templates: 模板目录，默认 site-templates/。
    :param allow_missing_packages: 本地预览时允许 packages/ 缺包，部署时必须为 False。
    :raises ValueError: 插件包缺失或摘要不符。
    :raises jinja2.UndefinedError: 模板引用了不存在的字段。
    """
    raw=(root/'index.json').read_bytes()
    index=json.loads(raw)
    verify_packages(index,output,allow_missing=allow_missing_packages)
    plugins=[plugin_view(plugin,root) for plugin in index['plugins']]
    environment=Environment(loader=FileSystemLoader(templates),autoescape=select_autoescape(['html']),
                            undefined=StrictUndefined,trim_blocks=True,lstrip_blocks=True)
    shared=dict(plugins=plugins,tags=collect_tags(plugins),default_panel=DEFAULT_PANEL,
                stats_path=urlparse(index['stats_url']).path)
    # 移除上次生成的页面与静态资源，已下线的插件不留下孤立详情页；packages/ 由部署作业维护。
    for name in ('plugins','submit','static'):
        shutil.rmtree(output/name,ignore_errors=True)
    output.mkdir(parents=True,exist_ok=True)
    shutil.copytree(templates/'static',output/'static')
    for name in ROOT_FILES:
        shutil.copyfile(templates/name,output/name)
    # 站点上的索引必须与仓库里的逐字节相同；解析后重新序列化会改变空白、转义与键序，只能原样复制。
    (output/'index.json').write_bytes(raw)
    # page 决定当前标签页高亮与 store.js 绑定哪组快捷键。
    pages={'index.html':('index.html',dict(page='list')),'submit/index.html':('submit.html',dict(page='submit')),
           '404.html':('404.html',dict(page='404'))}
    for plugin in plugins:
        pages[f'plugins/{plugin["id"]}/index.html']=('plugin.html',dict(page='detail',plugin=plugin))
    for target,(template,context) in pages.items():
        path=output/target
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(environment.get_template(template).render(**shared,**context),encoding='utf-8')


def main() -> None:
    """命令入口：python -m scripts.build_site [--root .] [--output site] [--allow-missing-packages]。"""
    parser=argparse.ArgumentParser(description='生成插件商店静态站点')
    parser.add_argument('--root',type=Path,default=Path('.'))
    parser.add_argument('--output',type=Path,default=Path('site'))
    parser.add_argument('--allow-missing-packages',action='store_true',help='仅本地预览使用：允许 site/packages 缺包')
    args=parser.parse_args()
    build_site(args.root,args.output,allow_missing_packages=args.allow_missing_packages)


if __name__=='__main__':
    main()
