"""定时发现登记插件的新版本，创建带审核标签的 Issue。

状态中的任何版本及拒绝名单均不重复提交；移动的已收录 Tag 标记撤回并通知。
新建审核编号写入输出文件，由 sync.yml 显式分发 review.yml。
"""
from packaging.version import Version
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple
import argparse
import json
import os
import httpx

from .common import GitRepository, read_json, records, write_json
from .github import GitHub, REVIEW_LABEL

# 每个插件每轮最多创建的待审版本数，正整数；按版本号从新到旧取前五个。
DISCOVERY_LIMIT = 5


def discover_versions(tags: Dict[str,Dict[str,str]], state: Dict[str,Dict[str,Any]], blocked: Sequence[str]) -> Tuple[Dict[str,Any],List[str]]:
    """比较远端 Tag 和已知状态，返回新版本与首次发现的移动版本。

    :param tags: 版本号到 Tag、commit 的映射。
    :param state: 可变状态字典，移动 Tag 仅增添 yanked，不覆盖原提交。
    :param blocked: 永久拒绝的版本号。
    :return: 最多五个待审版本以及本轮新增撤回通知的版本号。
    """
    moved=[]
    for version,row in state.items():
        if row['status']=='approved' and version in tags and row['commit']!=tags[version]['commit'] and not row.get('yanked',False):
            row['yanked']=True
            moved.append(version)
    new={version:tags[version] for version in sorted(tags,key=Version,reverse=True) if version not in state and version not in blocked}
    return dict(list(new.items())[:DISCOVERY_LIMIT]),moved


def sync(root: Path, github: GitHub) -> List[int]:
    """同步全部登记项并保存状态，返回需显式分发的审核编号。

    :param root: 索引仓库根目录。
    :param github: 注入的 API 接口，测试可使用内存桩。
    :raises Exception: Git、API 或磁盘错误直接终止，已保存状态可在下轮继续。
    """
    blocked=read_json(root/'blocked_versions.json',{})
    issues=[]
    for plugin_id,entry in records(root,'entries').items():
        repository=GitRepository(entry['repository'],root/'.cache/sources'/plugin_id)
        state=read_json(root/'state'/f'{plugin_id}.json',{})
        new,moved=discover_versions(repository.tags(),state,blocked.get(plugin_id,[]))
        for version in moved:
            github.create_issue(f'插件 Tag 指向变化：{plugin_id} {version}',f'原提交 {state[version]["commit"]} 保留，版本已撤回。请维护者检查。',[])
        if new:
            body='<!-- plugin-review -->\n'+json.dumps({'id':plugin_id,'versions':list(new)},ensure_ascii=False)
            number=github.create_issue(f'审核 {plugin_id}：'+', '.join(new),body,[REVIEW_LABEL])
            for version,row in new.items():
                state[version]=dict(**row,status='pending',review_issue=number)
            issues.append(number)
        write_json(root/'state'/f'{plugin_id}.json',state)
    return issues


def main() -> None:
    """读取环境认证与 CLI 路径，输出审核编号供工作流接力。"""
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('.'))
    parser.add_argument('--issues-output',type=Path,required=True)
    args=parser.parse_args()
    with httpx.Client(headers={'Authorization':f'Bearer {os.environ["GITHUB_TOKEN"]}'},timeout=30) as client:
        issues=sync(args.root,GitHub(os.environ['GITHUB_REPOSITORY'],client))
    args.issues_output.write_text(''.join(f'{number}\n' for number in issues),encoding='utf-8')


if __name__=='__main__':
    main()
