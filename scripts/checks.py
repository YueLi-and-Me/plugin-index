"""收录前的确定性检查，不执行插件代码。

清单复用已检出主程序的 manifest_from_payload；AST 约束宿主导入边界，
PyPI 客户端由调用者注入。二进制与依赖变化只转人工，不伪装成检查失败。
"""
from dataclasses import dataclass, field
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Sequence, Tuple
import ast
import json
import httpx

from .common import TAG_PATTERN

# 归档最大字节数，20 MiB；超过即拒绝，等于允许。
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
# 需人工审查的原生可执行文件扩展名，匹配时忽略大小写。
BINARY_SUFFIXES = {'.so','.pyd','.dll','.exe','.dylib'}


@dataclass
class CheckResult:
    """保存硬错误、转人工原因与原清单；passed 仅由硬错误决定。"""
    errors: List[str] = field(default_factory=list)
    manual_reasons: List[str] = field(default_factory=list)
    manifest: Dict[str,Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """返回是否所有确定性检查通过，不考虑人工审核需求。"""
        return not self.errors


def check_tree(tree: Dict[str,Tuple[str,bytes]], *, plugin_id: str, tag: str, archive_size: int,
               pypi: httpx.Client, previous_dependencies: Optional[Sequence[str]] = None) -> CheckResult:
    """检查固定 Git 树，返回所有可确定的错误与人工原因。

    :param tree: 路径到 Git 文件模式、原始字节的映射，不需要检出源码。
    :param plugin_id: 登记 id；必须与清单相等。
    :param tag: vX.Y.Z 或 X.Y.Z。
    :param archive_size: 实际 ZIP 字节数，不得超过 20 MiB。
    :param pypi: 由入口配置的 HTTP 客户端；测试传入内存传输。
    :param previous_dependencies: 上个已收录版本的原始依赖，首次登记为 None。
    :return: 硬错误、人工原因与清单；HTTP 失败以检查错误原样记录。
    """
    from src.plugin_system.manifest import manifest_from_payload
    result=CheckResult()
    if not TAG_PATTERN.fullmatch(tag):
        result.errors.append('Tag 必须为 vX.Y.Z 或 X.Y.Z')
    try:
        raw=json.loads(tree['_manifest.json'][1])
        manifest=manifest_from_payload(raw)
        result.manifest=raw
        if manifest.plugin_id!=plugin_id: result.errors.append('清单 id 与登记不一致')
        if manifest.version!=tag.removeprefix('v'): result.errors.append('清单 version 与 Tag 不一致')
        bounds=raw.get('host_application',{})
        if not all(bounds.get(key) for key in ('min_version','max_version')): result.errors.append('host_application 两端必填')
        if not raw.get('author'): result.errors.append('收录必须填写 author')
        if not raw.get('license'): result.errors.append('收录必须填写 license')
    except (KeyError,ValueError,TypeError) as exc:
        result.errors.append(f'清单不合法：{exc}')
    if archive_size>MAX_ARCHIVE_BYTES: result.errors.append('归档超过 20 MiB')
    for name,(mode,data) in tree.items():
        path=PurePosixPath(name)
        if path.name=='config.toml': result.errors.append(f'不得提交运行配置：{name}')
        if mode=='120000': result.errors.append(f'不得包含符号链接：{name}')
        if path.suffix.lower() in BINARY_SUFFIXES: result.manual_reasons.append(f'包含二进制文件：{name}')
        if path.suffix=='.py':
            try:
                syntax=ast.parse(data,filename=name)
                for node in ast.walk(syntax):
                    imports=[alias.name for alias in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
                    if isinstance(node,ast.ImportFrom) and node.module=='src':
                        result.errors.append(f'越过宿主门面导入：{name}:{node.lineno}')
                    for imported in imports:
                        if (imported=='src' or imported.startswith('src.')) and imported!='src.plugin_system':
                            result.errors.append(f'越过宿主门面导入：{name}:{node.lineno} {imported}')
            except (SyntaxError,UnicodeError) as exc:
                result.errors.append(f'源码无法解析：{name}：{exc}')
    dependencies=result.manifest.get('python_dependencies',[])
    if not isinstance(dependencies,list):
        result.errors.append('python_dependencies 必须是数组')
        dependencies=[]
    names=set()
    for text in dependencies:
        try:
            if not isinstance(text,str) or not text.strip(): raise ValueError('依赖必须是非空字符串')
            requirement=Requirement(text)
            if requirement.url: raise ValueError('不接受 URL 依赖')
            name=canonicalize_name(requirement.name)
            if name in names: raise ValueError('重复包名')
            names.add(name)
            response=pypi.get(f'https://pypi.org/pypi/{name}/json')
            response.raise_for_status()
        except (ValueError,InvalidRequirement,httpx.HTTPError) as exc:
            result.errors.append(f'依赖 {text!r} 检查失败：{exc}')
    if previous_dependencies is not None and set(dependencies)-set(previous_dependencies):
        result.manual_reasons.append('Python 依赖有新增或改动')
    return result
