"""生成并发布固定提交的插件包，Release 附件是分发正本。

摘要一经写入不再重新归档；本地缓存缺失时只从已有 Release 取回并核对。
发布入口复查确定性规则，不执行插件源码，供 publish.yml 的打包作业调用。
"""
from pathlib import Path
from typing import Any, Callable, Dict
from urllib.parse import quote
import argparse
import hashlib
import os
import httpx

from .checks import MAX_ARCHIVE_BYTES, check_tree
from .common import GitRepository, identity, read_json, records, timestamp, write_json
from .github import GitHub


def prepare_package(directory: Path, plugin_id: str, version: str, row: Dict[str,Any], archive: Callable[[Path],None]) -> Path:
    """只为未有摘要的版本生成归档，并把摘要与大小写入可变状态。

    :param directory: 包缓存目录，按 id 和版本命名文件。
    :param plugin_id: 已验证的插件身份。
    :param version: 清单与 Tag 共同确认的版本。
    :param row: 可变状态，已有 sha256 时仅验证缓存，不重新打包。
    :param archive: 固定 commit 的归档函数，仅首次调用。
    :return: 归档路径；已有摘要但本地缺包时由发布入口取回正本。
    :raises ValueError: 缓存摘要不一致或归档超过 20 MiB。
    """
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/f'{identity(plugin_id)}-{version}.zip'
    if row.get('sha256'):
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('本地包与已登记摘要不同，禁止重新打包覆盖')
        return target
    archive(target)
    size=target.stat().st_size
    if size>MAX_ARCHIVE_BYTES:
        target.unlink()
        raise ValueError('归档超过 20 MiB')
    row.update(sha256=hashlib.sha256(target.read_bytes()).hexdigest(),size=size)
    return target


def publish_asset(github: GitHub, plugin_id: str, version: str, row: Dict[str,Any], path: Path) -> None:
    """创建 Release 并上传正本；重试时验证已有附件，不覆盖不同字节。

    :param github: 带仓库身份和认证的 API 接口。
    :param plugin_id: 插件 id，用于 Release 标签。
    :param version: 已批准版本号。
    :param row: 摘要、大小与固定 commit 状态；成功后填入发布时间和 Release 标签。
    :param path: 本地包路径；已发布但缓存缺失时恢复该文件。
    :raises ValueError: 远端附件摘要不一致、未上传的原包丢失。
    """
    tag=f'{plugin_id}-v{version}'
    try:
        release=github.request('GET',f'releases/tags/{quote(tag,safe="")}')
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code!=404: raise
        release=github.request('POST','releases',json={'tag_name':tag,'name':f'{plugin_id} {version}','body':'插件固定版本归档。','draft':False,'prerelease':False})
    asset=next((asset for asset in release['assets'] if asset['name']==path.name),None)
    if asset is not None:
        response=github.client.get(asset['url'],headers={'Accept':'application/octet-stream'},follow_redirects=True)
        response.raise_for_status()
        data=response.content
        if len(data)!=row['size'] or hashlib.sha256(data).hexdigest()!=row['sha256']:
            raise ValueError('Release 附件与已登记摘要不同，禁止覆盖')
        path.write_bytes(data)
    else:
        if not path.exists(): raise ValueError('原始归档丢失且 Release 无附件，禁止重新打包')
        response=github.client.post(release['upload_url'].split('{',1)[0],params={'name':path.name},content=path.read_bytes(),headers={'Content-Type':'application/zip'})
        response.raise_for_status()
    row.setdefault('published_at',release.get('published_at') or timestamp())
    row['release_tag']=tag


def publish(root: Path, github: GitHub, pypi: httpx.Client) -> None:
    """发布已批准状态；Git 树只按固定提交读取，检查失败立即中止。

    :param root: 索引仓库根目录。
    :param github: 发布 API；测试使用 MockTransport。
    :param pypi: 不携带仓库凭证的依赖存在性检查客户端。
    :raises ValueError: 固定规则失败或历史包发生变化。
    """
    for plugin_id,entry in records(root,'entries').items():
        state=read_json(root/'state'/f'{plugin_id}.json',{})
        repository=None
        for version,row in state.items():
            if row['status']!='approved': continue
            target=root/'.cache/packages'/f'{plugin_id}-{version}.zip'
            if not row.get('sha256'):
                if repository is None: repository=GitRepository(entry['repository'],root/'.cache/sources'/plugin_id)
                repository.fetch(row['commit'])
                tree=repository.tree(row['commit'])
                target=prepare_package(target.parent,plugin_id,version,row,lambda path:repository.archive(row['commit'],plugin_id,path))
                result=check_tree(tree,plugin_id=plugin_id,tag=row['tag'],archive_size=row['size'],pypi=pypi)
                if not result.passed: raise ValueError('\n'.join(result.errors))
                row['manifest']=result.manifest
                readme=next((data for name,(_,data) in tree.items() if name.lower() in ('readme.md','readme')),b'')
                readme_path=root/'readme'/plugin_id/f'{version}.md'
                readme_path.parent.mkdir(parents=True,exist_ok=True)
                readme_path.write_bytes(readme)
            target.parent.mkdir(parents=True,exist_ok=True)
            publish_asset(github,plugin_id,version,row,target)
        write_json(root/'state'/f'{plugin_id}.json',state)


def main() -> None:
    """从工作流读取仓库令牌；依赖检查使用独立无认证客户端。"""
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('.'))
    args=parser.parse_args()
    with httpx.Client(headers={'Authorization':f'Bearer {os.environ["GITHUB_TOKEN"]}'},timeout=60) as client, httpx.Client(timeout=30) as pypi:
        publish(args.root,GitHub(os.environ['GITHUB_REPOSITORY'],client),pypi)


if __name__=='__main__':
    main()
