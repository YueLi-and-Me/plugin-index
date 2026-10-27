"""索引仓库的 GitHub API 窄接口。

只创建 Issue、查询权限和发布固定附件；客户端由入口注入，离线测试使用
MockTransport。所有模型或第三方文本在审核层清理后才提交评论。
"""
from typing import Any, Dict, List
from urllib.parse import quote
import httpx

# 审核 Issue 的标签名；同步、表单与审核入口须保持一致。
REVIEW_LABEL = '插件审核'


class GitHub:
    """为指定 owner/repo 提供审查流水线所需的最小 API。"""

    def __init__(self, repository: str, client: httpx.Client) -> None:
        """保存仓库和带认证的 HTTP 客户端，不发起请求。"""
        self.repository=repository
        self.client=client

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """请求仓库下的相对 API；非成功状态抛出 HTTPStatusError。"""
        response=self.client.request(method,f'https://api.github.com/repos/{self.repository}/{path}',**kwargs)
        response.raise_for_status()
        return response.json() if response.content else None

    def issue(self, number: int) -> Dict[str,Any]:
        """读取最新 Issue 状态与标签，避免仅信任旧事件快照。"""
        return self.request('GET',f'issues/{number}')

    def create_issue(self, title: str, body: str, labels: List[str]) -> int:
        """创建带指定标签的 Issue，返回服务端编号。"""
        return self.request('POST','issues',json={'title':title,'body':body,'labels':labels})['number']

    def comment(self, number: int, body: str) -> None:
        """向指定 Issue 添加已清理的评论；失败直接抛错。"""
        self.request('POST',f'issues/{number}/comments',json={'body':body})

    def close(self, number: int) -> None:
        """关闭完成的审核 Issue，失败直接抛错。"""
        self.request('PATCH',f'issues/{number}',json={'state':'closed'})

    def can_write(self, user: str) -> bool:
        """向仓库权限 API 核实维护者身份，不信任评论里的自述。"""
        data=self.request('GET',f'collaborators/{quote(user,safe="")}/permission')
        return data['permission'] in ('admin','maintain','write')
