"""从已登记元数据和已发布状态生成客户端索引。

不读取或执行插件源码；摘要、版本区间与依赖来自固定提交的检查结果，
供打包作业及后续静态网站生成复用。
"""
from packaging.version import Version
from pathlib import Path
from typing import Any, Dict
import argparse
import os

from .common import read_json, records, timestamp, write_json


def build_index(entries: Dict[str,Any], states: Dict[str,Any], *, repository: str) -> Dict[str,Any]:
    """生成协议版本 1 的索引，未批准或未发布的条目不对外展示。

    :param entries: 插件登记信息，包含仓库、分类与可选撤回版本。
    :param states: 按插件与版本分组的持久状态。
    :param repository: 索引仓库 owner/repo，组成 Release 正本链接。
    :return: 可 JSON 编码的索引，下载地址固定为商店优先、Release 次之。
    """
    plugins=[]
    for plugin_id,entry in sorted(entries.items()):
        versions=[]
        metadata=None
        for version,row in sorted(states.get(plugin_id,{}).items(),key=lambda item:Version(item[0]),reverse=True):
            if row['status']!='approved' or not row.get('release_tag'): continue
            manifest=row['manifest']
            if metadata is None: metadata=manifest
            versions.append(dict(version=version,commit=row['commit'],host_application=manifest['host_application'],
                python_dependencies=manifest.get('python_dependencies',[]),sha256=row['sha256'],size=row['size'],published_at=row['published_at'],
                yanked=version in entry.get('yanked',[]) or row.get('yanked',False),
                downloads=[f'https://plugins.yuelibot.org/packages/{plugin_id}/{version}.zip',
                           f'https://github.com/{repository}/releases/download/{row["release_tag"]}/{plugin_id}-{version}.zip']))
        if metadata is not None:
            plugins.append(dict(id=plugin_id,name=metadata['name'],description=metadata['description'],author=metadata['author'],
                license=metadata['license'],repository=entry['repository'],tags=entry['tags'],versions=versions))
    return dict(schema_version=1,generated_at=timestamp(),stats_url='https://plugins.yuelibot.org/stats.json',plugins=plugins)


def keep_generated_at(previous: Any, current: Dict[str,Any]) -> Dict[str,Any]:
    """除生成时间外内容未变时沿用上一份索引的 generated_at。

    定时发布每天运行两次，若每次都写入新时间，index.json 总会变化，打包作业便会提交一笔
    没有实际内容的「更新索引」。

    :param previous: 仓库中现有的索引；文件不存在时为 None。
    :param current: 本次生成的索引，会被原地修改。
    :return: current 本身。
    """
    if isinstance(previous,dict) and 'generated_at' in previous:
        if {key:value for key,value in previous.items() if key!='generated_at'}=={key:value for key,value in current.items() if key!='generated_at'}:
            current['generated_at']=previous['generated_at']
    return current


def main() -> None:
    """读取仓库状态并原子更新 index.json，不访问任何外部服务。"""
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('.'))
    args=parser.parse_args()
    target=args.root/'index.json'
    index=build_index(records(args.root,'entries'),records(args.root,'state'),repository=os.environ['GITHUB_REPOSITORY'])
    write_json(target,keep_generated_at(read_json(target),index))


if __name__=='__main__':
    main()
