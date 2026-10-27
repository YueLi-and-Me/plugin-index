"""商店网站生成的离线验收：README 清洗、页面齐全、索引逐字节复制与撤回版本。

使用 tests/fixtures/storefront 的样例索引；插件包按样例摘要现场生成，
不访问 GitHub 或 Cloudflare。
"""
from html.parser import HTMLParser
from importlib import import_module
from pathlib import Path
from typing import List
import json
import shutil
import pytest

FIXTURE = Path(__file__).resolve().parent/'fixtures/storefront'


def site():
    """延迟导入，让实现前各用例均能报告缺失模块。"""
    return import_module('scripts.build_site')


def prepare(tmp_path):
    """复制样例索引并按摘要写入插件包，返回索引根与输出目录。"""
    root=tmp_path/'index'
    shutil.copytree(FIXTURE,root)
    output=tmp_path/'site'
    for plugin in json.loads((root/'index.json').read_text(encoding='utf-8'))['plugins']:
        for version in plugin['versions']:
            target=output/'packages'/plugin['id']/f'{version["version"]}.zip'
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(f'{plugin["id"]}-{version["version"]}'.encode())
    return root,output


class Anchors(HTMLParser):
    """收集链接的 href 与链接内文字，用于判断某段文字是否处在链接里。"""

    def __init__(self) -> None:
        """初始化空的链接列表与嵌套深度。"""
        super().__init__()
        self.links: List[List[str]] = []
        self.depth=0

    def handle_starttag(self, tag, attrs):
        """进入 a 元素时登记 href，后续文字归入该链接。"""
        if tag=='a':
            self.links.append([dict(attrs).get('href') or '',''])
            self.depth+=1

    def handle_endtag(self, tag):
        """离开 a 元素。"""
        if tag=='a': self.depth-=1

    def handle_data(self, data):
        """链接内部文字累加到最近的链接。"""
        if self.depth: self.links[-1][1]+=data


def anchors(html: str) -> List[List[str]]:
    """返回页面全部链接的 [href, 文字]。"""
    parser=Anchors()
    parser.feed(html)
    return parser.links


def test_readme_sanitized():
    """脚本、事件属性、内嵌框架、危险链接与明文图片全部去掉，安全内容保留。"""
    text=(FIXTURE/'readme/yueli.web-search/0.2.5.md').read_text(encoding='utf-8')
    html=site().render_readme(text)
    lowered=html.lower()
    for marker in ('<script','readme-script','onclick','<iframe','<style','<form','http://example.org/insecure.png'):
        assert marker not in lowered
    # markdown-it 把 javascript: 目标的 Markdown 链接退回为纯文本，nh3 去掉 HTML 链接的危险 href；
    # 两者都不再是可点击的链接。
    assert anchors(html) and all(not href.lower().startswith('javascript:') for href,_ in anchors(html))
    assert 'href="javascript' not in lowered
    assert 'src="https://example.org/secure.png"' in html
    assert '<table>' in html and '<code>web_search</code>' in html


def test_build_site_pages_and_index(tmp_path):
    """每个插件生成详情页，index.json 逐字节相同，固定页面齐全且清洗结果进入页面。"""
    root,output=prepare(tmp_path)
    site().build_site(root,output)
    assert (output/'index.json').read_bytes()==(root/'index.json').read_bytes()
    for name in ('index.html','submit/index.html','404.html','logo.png','favicon.png','static/install.js','static/fonts/OFL.txt'):
        assert (output/name).is_file(), name
    index=json.loads((root/'index.json').read_text(encoding='utf-8'))
    for plugin in index['plugins']:
        page=(output/'plugins'/plugin['id']/'index.html').read_text(encoding='utf-8')
        assert f'plugin show {plugin["id"]}' in page
    page=(output/'plugins/yueli.web-search/index.html').read_text(encoding='utf-8')
    for marker in ('readme-script','onclick','<iframe','href="javascript','http://example.org/insecure.png'):
        assert marker not in page.lower()
    listing=(output/'index.html').read_text(encoding='utf-8')
    assert '已收录 3 · 全部经过审核' in listing and '[ 全部 3 ]' in listing and '3 个插件' in listing
    for tag in ('搜索','信息获取','效率'):
        assert f'[ {tag} ]' in listing
    submit=(output/'submit/index.html').read_text(encoding='utf-8')
    assert 'https://github.com/YueLi-and-Me/plugin-index/issues/new?template=register.yml' in submit
    assert 'https://docs.yuelibot.org/dev/guide/plugins/' in submit


def test_yanked_version_and_author_link(tmp_path):
    """撤回版本没有下载链接；没有 author.url 时开发者只显示文字。"""
    root,output=prepare(tmp_path)
    site().build_site(root,output)
    pages=[path.read_text(encoding='utf-8') for path in output.rglob('*.html')]
    assert all('/packages/yueli.web-search/0.2.4.zip' not in page for page in pages)
    detail=(output/'plugins/yueli.web-search/index.html').read_text(encoding='utf-8')
    hrefs=[href for href,_ in anchors(detail)]
    assert '/packages/yueli.web-search/0.2.5.zip' in hrefs and '/packages/yueli.web-search/0.2.3.zip' in hrefs
    assert '已撤回' in detail
    rss=(output/'plugins/example.rss-reader/index.html').read_text(encoding='utf-8')
    assert '示例作者' in rss and all('示例作者' not in text for _,text in anchors(rss))
    assert 'feedparser&gt;=6.0' in rss and '自动安装' in rss
    listing=(output/'index.html').read_text(encoding='utf-8')
    assert all('示例作者' not in text for _,text in anchors(listing))
    assert ['https://example.org/team','示例团队 ↗'] in anchors(listing)


def test_build_site_rejects_bad_package(tmp_path):
    """包缺失或摘要不符直接报错，不生成指向错误字节的下载链接。"""
    root,output=prepare(tmp_path)
    (output/'packages/example.schedule/1.0.2.zip').write_bytes(b'tampered')
    with pytest.raises(ValueError,match='摘要'):
        site().build_site(root,output)
    (output/'packages/example.schedule/1.0.2.zip').unlink()
    with pytest.raises(ValueError,match='缺少'):
        site().build_site(root,output)
    site().build_site(root,output,allow_missing_packages=True)
    assert (output/'plugins/example.schedule/index.html').is_file()
