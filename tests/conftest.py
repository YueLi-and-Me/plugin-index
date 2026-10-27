"""索引脚本离线测试装配，直接使用外部检出的宿主清单解析器。

YUELI_SOURCE_ROOT 指向待验宿主代码；仅装载契约子模块，避免导入不参与清单
校验的宿主运行服务。测试禁止 HTTP 实际出网，网络数据通过 MockTransport 提供。
"""
from pathlib import Path
from types import ModuleType
import os
import sys
import httpx
import pytest

host = Path(os.environ['YUELI_SOURCE_ROOT']).resolve()
sys.path.insert(0, str(host))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
package = ModuleType('src.plugin_system')
package.__path__ = [str(host / 'src/plugin_system')]
sys.modules['src.plugin_system'] = package


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """真实 HTTP 传输一律报错，防止漏注入桩时访问外部服务。"""
    def deny(*args, **kwargs):
        raise AssertionError('测试禁止真实 HTTP 请求')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', deny)


@pytest.fixture
def payload():
    """提供收录时必填的清单字段，版本和宿主区间固定。"""
    return dict(manifest_version=2,id='test.plugin',name='测试插件',plugin_type='tool',version='1.0.0',
                description='测试',author='测试作者',license='MIT',host_application={'min_version':'0.2.0','max_version':'0.2.5'})
