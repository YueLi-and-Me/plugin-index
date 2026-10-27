"""索引持久化和只读 Git 访问，供同步、审核与打包入口调用。

插件源码按 Git 对象与 git archive 读取，不检出工作树、不运行插件命令；JSON 原子替换，
异常向上传递，避免把读取失败误认为空登记或新版本。
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple
import io
import json
import os
import re
import subprocess
import tarfile

# 发布版本只接受三段非负整数，可带一个 v 前缀；不接受预发布或路径字符。
TAG_PATTERN = re.compile(r'^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')
# 插件身份用于文件名和归档前缀，仅允许字母、数字、点、下划线、连字符。
ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
# Git 子进程超时秒数，正整数；网络异常应结束作业并留下错误。
GIT_TIMEOUT_SECONDS = 120


def identity(value: str) -> str:
    """验证可作为目录名的插件 id，非法值抛出 ValueError。"""
    if not isinstance(value,str) or not ID_PATTERN.fullmatch(value):
        raise ValueError('插件 id 格式非法')
    return value


def timestamp() -> str:
    """返回 UTC ISO 时间文本，用于生成与发布记录。"""
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')


def read_json(path: Path, default: Any = None) -> Any:
    """读取 UTF-8 JSON；仅文件不存在时返回 default，损坏直接抛错。"""
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path: Path, value: Any) -> None:
    """原子替换 JSON 文件，创建父目录；编码或磁盘错误向上传递。"""
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temporary,path)


def records(root: Path, folder: str) -> Dict[str, Any]:
    """读取指定登记或状态目录的 JSON，以经校验的文件名作为插件 id。"""
    return {identity(path.stem):read_json(path) for path in sorted((root/folder).glob('*.json'))}


class GitRepository:
    """插件仓库的浅克隆对象访问器；不创建第三方工作树。"""

    def __init__(self, url: str, directory: Path) -> None:
        """浅克隆 url 到 directory，已有克隆须属于相同来源；失败抛错。"""
        if not isinstance(url,str) or not url or url.startswith('-') or '\n' in url:
            raise ValueError('仓库地址非法')
        self.directory=directory
        if not (directory/'.git').exists():
            directory.parent.mkdir(parents=True,exist_ok=True)
            subprocess.run(['git','clone','--depth','1','--no-checkout','--no-tags','--',url,str(directory)],
                           check=True,capture_output=True,timeout=GIT_TIMEOUT_SECONDS)
        elif self.run('remote','get-url','origin').decode().strip()!=url:
            raise ValueError('缓存克隆来源与登记不一致')

    def run(self, *args: str) -> bytes:
        """执行固定参数 Git 命令，返回原始 stdout；超时与非零退出直接抛出。"""
        return subprocess.run(['git','-C',str(self.directory),*args],check=True,capture_output=True,
                              timeout=GIT_TIMEOUT_SECONDS).stdout

    def tags(self) -> Dict[str, Dict[str,str]]:
        """列出轻量与注释 Tag 的实际 commit；同版本不同指向拒绝猜测。"""
        refs={}
        for line in self.run('ls-remote','--tags','origin').decode().splitlines():
            commit,ref=line.split('\t')
            refs[ref]=commit
        result={}
        for ref,object_id in refs.items():
            tag=ref.removeprefix('refs/tags/')
            if not TAG_PATTERN.fullmatch(tag):
                continue
            commit=refs.get(ref+'^{}',object_id)
            version=tag.removeprefix('v')
            if version in result and result[version]['commit']!=commit:
                raise ValueError(f'版本 {version} 有多个不同指向的 Tag')
            result[version]={'tag':tag,'commit':commit}
        return result

    def fetch(self, commit: str) -> None:
        """取得固定四十位提交，不跟随可变 Tag；非法摘要抛出 ValueError。"""
        if not re.fullmatch('[0-9a-f]{40}',commit):
            raise ValueError('commit 必须是四十位小写十六进制')
        self.run('fetch','--depth','1','origin',commit)

    def tree(self, commit: str) -> Dict[str, Tuple[str,bytes]]:
        """读取固定 commit 实际发布的文件，返回路径到 Git 模式与原始字节的映射。

        内容取自 git archive，与 archive() 打出的插件包同源：作者在 .gitattributes 中以
        export-ignore 排除的测试等开发文件不进入发布包，也不参与检查与模型审核。
        若改回读取完整提交树，测试里导入宿主内部模块会被判为越界，而这些文件从不随包发布。

        :param commit: 已 fetch 的四十位提交。
        :return: 发布文件映射；符号链接以 120000 模式记录链接目标，只作为数据。
        :raises ValueError: 仓库含子模块，或归档出现文件与链接以外的条目。
        """
        for entry in self.run('ls-tree','-rz',commit).split(b'\0'):
            if entry and entry.split(b'\t',1)[0].split()[1]!=b'blob':
                raise ValueError('插件仓库不能包含子模块')
        result={}
        with tarfile.open(fileobj=io.BytesIO(self.run('archive','--format=tar',commit)),mode='r:') as archive:
            for member in archive.getmembers():
                if member.isdir():
                    continue
                if member.issym():
                    result[member.name]=('120000',member.linkname.encode('utf-8'))
                elif member.isfile():
                    result[member.name]=('100755' if member.mode&0o111 else '100644',archive.extractfile(member).read())
                else:
                    raise ValueError(f'归档中有不支持的条目：{member.name}')
        return result

    def archive(self, commit: str, plugin_id: str, target: Path) -> None:
        """固定 commit 打包到 target，顶层目录固定为已校验的插件 id。"""
        self.run('archive','--format=zip',f'--prefix={identity(plugin_id)}/','-o',str(target),commit)

    def diff(self, previous: str, current: str) -> str:
        """读取两个固定提交的差异，关闭外部 diff 与文本转换器。"""
        return self.run('diff','--no-ext-diff','--no-textconv',previous,current,'--').decode('utf-8',errors='replace')
