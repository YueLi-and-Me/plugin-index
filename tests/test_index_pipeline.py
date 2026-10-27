"""确定性检查、固定版本打包与索引的离线验收。

Git 仅操作测试临时仓库；PyPI、GitHub API 均使用内存桩，保留实现前失败证据。
"""
from importlib import import_module
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import hashlib
import json
import subprocess
import httpx
import pytest


def module(name):
    """延迟导入，让实现前各用例均能报告缺失模块。"""
    return import_module('scripts.'+name)


def files(payload):
    """以 Git 模式及原始字节表示树，不执行插件入口。"""
    return {'_manifest.json':('100644',json.dumps(payload).encode()),'plugin.py':('100644',b'from src.plugin_system import ToolPlugin\n')}


@pytest.mark.parametrize('case', ['manifest','id','tag','author','license','bounds','import_from','import_direct','config','symlink','size','dependency'])
def test_checks_reject_each_rule(payload,case):
    """各项硬规则单独拒绝，不受模型结论影响。"""
    tree=files(payload)
    tag='v1.0.0'; size=100
    if case in ('manifest','id','author','license','bounds','dependency'):
        if case=='manifest': payload['manifest_version']=1
        elif case=='id': payload['id']='other.plugin'
        elif case in ('author','license'): payload.pop(case)
        elif case=='bounds': payload['host_application'].pop('max_version')
        else: payload['python_dependencies']=['does-not-exist>=1']
        tree=files(payload)
    elif case=='tag': tag='v2.0.0'
    elif case=='import_from': tree['plugin.py']=('100644',b'from src.core.config import Config')
    elif case=='import_direct': tree['plugin.py']=('100644',b'import src.plugin_system.manifest')
    elif case=='config': tree['nested/config.toml']=('100644',b'')
    elif case=='symlink': tree['link']=('120000',b'outside')
    elif case=='size': size=20*1024*1024+1
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(404))) as client:
        result=module('checks').check_tree(tree,plugin_id='test.plugin',tag=tag,archive_size=size,pypi=client)
    assert not result.passed and result.errors


@pytest.mark.parametrize('case', ['binary','added','changed'])
def test_checks_force_manual(payload,case):
    """二进制与新增、改动依赖不判失败，但必须转人工。"""
    payload['python_dependencies']=['httpx>=0.28']
    tree=files(payload)
    if case=='binary': tree['native.dll']=('100644',b'bin')
    previous=['httpx>=0.28'] if case=='binary' else [] if case=='added' else ['httpx>=0.27']
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={}))) as client:
        result=module('checks').check_tree(tree,plugin_id='test.plugin',tag='1.0.0',archive_size=100,pypi=client,previous_dependencies=previous)
    assert result.passed and result.manual_reasons


def test_checks_never_execute_source(payload):
    """源码中的调用只作为 AST 数据读取，正常门面导入通过。"""
    tree=files(payload)
    tree['plugin.py']=('100644',b'from src.plugin_system import ToolPlugin\nraise RuntimeError("must not execute")')
    with httpx.Client(transport=httpx.MockTransport(lambda request:pytest.fail('无依赖不查 PyPI'))) as client:
        result=module('checks').check_tree(tree,plugin_id='test.plugin',tag='v1.0.0',archive_size=100,pypi=client)
    assert result.passed and not result.manual_reasons


def test_package_once_and_single_top_level(tmp_path,payload):
    """真实本地 Git 归档顶层固定，已记摘要时不可再次调用打包器。"""
    repo=tmp_path/'source'; repo.mkdir()
    for args in [('init',),('config','user.name','测试'),('config','user.email','test@example.invalid')]:
        subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True)
    (repo/'_manifest.json').write_text(json.dumps(payload),encoding='utf-8')
    (repo/'plugin.py').write_text('pass\n',encoding='utf-8')
    subprocess.run(['git','-C',str(repo),'add','_manifest.json','plugin.py'],check=True)
    subprocess.run(['git','-C',str(repo),'commit','-m','test'],check=True,capture_output=True)
    commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    row={'commit':commit,'status':'approved','tag':'v1.0.0'}
    calls=[]
    def archive(target):
        calls.append(target)
        subprocess.run(['git','-C',str(repo),'archive','--format=zip','--prefix=test.plugin/','-o',str(target),commit],check=True)
    path=module('package').prepare_package(tmp_path/'packages','test.plugin','1.0.0',row,archive)
    data=path.read_bytes()
    with ZipFile(BytesIO(data)) as zipped:
        assert {name.split('/')[0] for name in zipped.namelist()}=={'test.plugin'}
    assert row['sha256']==hashlib.sha256(data).hexdigest() and row['size']==len(data)
    module('package').prepare_package(tmp_path/'packages','test.plugin','1.0.0',row,lambda path:pytest.fail('同版本重打'))
    assert len(calls)==1


def test_sync_skip_cap_and_moved_tag():
    """已有状态和拒绝名单全部跳过，最多取五版；移动 Tag 保留原提交并撤回。"""
    states={'1.0.0':{'commit':'a'*40,'status':'approved'},'1.1.0':{'commit':'a'*40,'status':'rejected'},'1.2.0':{'commit':'a'*40,'status':'pending'}}
    tags={f'1.{i}.0':{'tag':f'v1.{i}.0','commit':('b' if i==0 else 'a')*40} for i in range(11)}
    new,moved=module('sync').discover_versions(tags,states,['1.3.0'])
    assert list(new)==['1.10.0','1.9.0','1.8.0','1.7.0','1.6.0']
    assert moved==['1.0.0'] and states['1.0.0']['commit']=='a'*40 and states['1.0.0']['yanked'] is True


def test_build_index_protocol(payload):
    """协议元数据完整，下载源顺序固定，撤回与统计字段不丢失。"""
    entries={'test.plugin':{'repository':'https://example.org/repo','maintainers':['maintainer'],'tags':['测试'],'yanked':['1.0.0']}}
    states={'test.plugin':{'1.0.0':{'status':'approved','commit':'a'*40,'sha256':'b'*64,'size':123,
        'published_at':'2026-10-27T00:00:00Z','release_tag':'test.plugin-v1.0.0','manifest':payload}}}
    raw=module('build_index').build_index(entries,states,repository='owner/index')
    assert raw['schema_version']==1 and raw['stats_url']=='https://plugins.yuelibot.org/stats.json'
    row=raw['plugins'][0]; record=row['versions'][0]
    assert set(row)=={'id','name','description','author','license','repository','tags','versions'}
    assert record['downloads']==['https://plugins.yuelibot.org/packages/test.plugin/1.0.0.zip','https://github.com/owner/index/releases/download/test.plugin-v1.0.0/test.plugin-1.0.0.zip']
    assert record['yanked'] is True and record['python_dependencies']==[]
    assert set(record)=={'version','commit','host_application','python_dependencies','downloads','sha256','size','published_at','yanked'}


def test_workflow_privilege_boundary():
    """发布仅允许手动和定时；审核工作流禁止部署凭证。"""
    root=Path(__file__).resolve().parents[1]/'.github/workflows'
    publish=(root/'publish.yml').read_text(encoding='utf-8')
    sync=(root/'sync.yml').read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in publish and 'schedule:' in publish
    for name in ('pull_request','pull_request_target','issues:','issue_comment:'):
        assert name not in publish
    assert '0 18 * * *' in sync and '0 7 * * *' in sync
    assert 'actions: write' in sync and 'gh workflow run review.yml' in sync
    for path in root.glob('*.yml'):
        if path.name!='publish.yml': assert 'CLOUDFLARE_' not in path.read_text(encoding='utf-8')


def test_git_snapshot_and_issue_dispatch_list(tmp_path,payload,monkeypatch):
    """真实浅克隆读取固定 Tag；新 Issue 创建即带标签，编号交给显式分发。"""
    source=tmp_path/'upstream'; source.mkdir()
    def git(*args):
        return subprocess.check_output(['git','-C',str(source),*args])
    git('init'); git('config','user.email','test@example.invalid'); git('config','user.name','测试')
    (source/'_manifest.json').write_text(json.dumps(payload),encoding='utf-8')
    (source/'plugin.py').write_text('from src.plugin_system import ToolPlugin\n',encoding='utf-8')
    git('add','_manifest.json','plugin.py'); git('commit','-m','test'); git('tag','-a','v1.0.0','-m','release')
    root=tmp_path/'index'
    module('common').write_json(root/'entries/test.plugin.json',{'repository':source.as_uri(),'maintainers':['maintainer'],'tags':['测试']})
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.url.path=='/repos/owner/index/issues'
        body=json.loads(request.content)
        assert body['labels']==['插件审核'] and 'test.plugin' in body['title'] and '1.0.0' in body['title']
        return httpx.Response(201,json={'number':42})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        github=module('github').GitHub('owner/index',client)
        assert module('sync').sync(root,github)==[42]
        assert module('sync').sync(root,github)==[]
    state=module('common').read_json(root/'state/test.plugin.json')
    assert state['1.0.0']['status']=='pending' and state['1.0.0']['review_issue']==42
    repo=module('common').GitRepository(source.as_uri(),root/'.cache/sources/test.plugin')
    repo.fetch(state['1.0.0']['commit'])
    assert json.loads(repo.tree(state['1.0.0']['commit'])['_manifest.json'][1])==payload
    assert len(calls)==1


def test_release_upload_and_existing_asset(tmp_path):
    """Release 首次上传固定字节，已有附件仅校验取回，不调用覆盖上传。"""
    path=tmp_path/'test.plugin-1.0.0.zip'; path.write_bytes(b'archive')
    row={'sha256':hashlib.sha256(b'archive').hexdigest(),'size':7}
    uploads=[]
    def handler(request):
        if request.url.host=='uploads.example':
            uploads.append(request.content)
            return httpx.Response(201,json={})
        if request.url.path.endswith('/releases/tags/test.plugin-v1.0.0'):
            return httpx.Response(404)
        return httpx.Response(201,json={'assets':[],'upload_url':'https://uploads.example/upload{?name}','published_at':'2026-10-27T00:00:00Z'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        module('package').publish_asset(module('github').GitHub('owner/index',client),'test.plugin','1.0.0',row,path)
    assert uploads==[b'archive'] and row['release_tag']=='test.plugin-v1.0.0'
    path.unlink()
    def existing(request):
        if request.url.host=='assets.example': return httpx.Response(200,content=b'archive')
        return httpx.Response(200,json={'assets':[{'name':path.name,'url':'https://assets.example/file'}],'published_at':'2026-10-27T00:00:00Z'})
    with httpx.Client(transport=httpx.MockTransport(existing)) as client:
        module('package').publish_asset(module('github').GitHub('owner/index',client),'test.plugin','1.0.0',row,path)
    assert path.read_bytes()==b'archive'
