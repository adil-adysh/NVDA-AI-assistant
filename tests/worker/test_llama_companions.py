import io
import json
import struct
from unittest.mock import Mock
import pytest
from tests.support import load_addon_module


def test_hf_resolution_is_metadata_only_and_role_sensitive(monkeypatch):
    mod = load_addon_module('worker.executors.llama_hf', namespace='hf_companions')
    body = {'sha': 'a'*40, 'siblings': [{'rfilename': 'model.gguf', 'size': 44}, {'rfilename': 'mmproj.gguf'}, {'rfilename': 'model-00001-of-00002.gguf'}]}
    calls = []
    def open_url(request, timeout):
        calls.append(request.full_url)
        return io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr(mod.urllib.request, 'urlopen', open_url)
    result = mod.resolve_hf('org/model')
    assert [x['eligible'] for x in result['files']] == [True, False, False]
    assert result['files'][1]['size_bytes'] is None
    assert len(calls) == 1 and '/api/models/' in calls[0]
    assert mod.resolve_hf('org/model', role='vision')['files'][1]['eligible']


def test_local_companions_verify_header_without_network(tmp_path, monkeypatch):
    mod = load_addon_module('worker.executors.llama_hf', namespace='hf_companions')
    path = tmp_path/'mmproj.gguf'
    path.write_bytes(b'GGUF'+struct.pack('<IQQ',3,1,1))
    monkeypatch.setattr(mod.urllib.request,'urlopen',Mock(side_effect=AssertionError('network')))
    result = mod.resolve_companions([dict(role='vision',kind='local_file',source=str(path))])
    assert result['companions'][0]['local_path'] == str(path)
    path.write_bytes(b'bad')
    with pytest.raises(ValueError, match='GGUF'):
        mod.resolve_companions([dict(role='vision',kind='local_file',source=str(path))])


def test_unload_requires_observed_unloaded_and_fences_old_cleanup():
    mod = load_addon_module('worker.executors.llama', namespace='unload_companions')
    instance = mod.LlamaWorkerExecutor(supervisor=Mock())
    instance.get_status = Mock(return_value={'is_running':True,'is_adopted':False,'pid':1,'generation':2})
    instance._preparations['x'] = object()
    instance._model_request = Mock(return_value={})
    instance.list_models = Mock(side_effect=[[{'id':'x','status':{'value':'loaded'}}], [{'id':'x','status':{'value':'unloaded'}}]])
    assert instance.unload_model('x', 2)['state'] == 'unloaded'
    assert 'x' not in instance._preparations


def test_unload_unknown_is_error_not_success():
    mod = load_addon_module('worker.executors.llama', namespace='unload_companions')
    instance = mod.LlamaWorkerExecutor(supervisor=Mock())
    instance.get_status = Mock(return_value={'is_running':True,'is_adopted':False,'pid':1,'generation':2})
    instance._model_request = Mock(return_value={})
    instance.list_models = Mock(return_value=[])
    with pytest.raises(ValueError, match='observe'):
        instance.unload_model('x', .01)


def test_cached_projector_verified_only_with_explicit_vision_role(tmp_path):
    mod = load_addon_module('worker.executors.model_assets', namespace='hf_companions')
    path = tmp_path/'mmproj.gguf'
    path.write_bytes(b'GGUF'+struct.pack('<IQQ',3,1,1))
    executor = mod.ModelAssetExecutor()
    asset = executor.discover_model_assets([{'path':str(tmp_path)}],1).assets[0]
    with pytest.raises(ValueError):
        executor.verify_model_asset(asset.token)
    assert executor.verify_model_asset(asset.token, role='vision').path == str(path)


def test_hf_download_reuses_complete_cache_and_cleans_cancelled_partial(tmp_path, monkeypatch):
    mod = load_addon_module('worker.executors.llama_hf', namespace='hf_companions')
    monkeypatch.setenv('HF_HUB_CACHE',str(tmp_path))
    gguf = b'GGUF'+struct.pack('<IQQ',3,1,1)
    body = {'sha':'a'*40,'siblings':[{'rfilename':'mmproj.gguf','size':len(gguf)}]}
    calls = []
    def open_url(request, timeout):
        calls.append(request.full_url)
        return io.BytesIO(json.dumps(body).encode() if '/api/' in request.full_url else gguf)
    monkeypatch.setattr(mod.urllib.request,'urlopen',open_url)
    entry = dict(role='vision',kind='hugging_face',source='org/model',artifact='mmproj.gguf')
    result = mod.resolve_companions([entry])
    assert result['companions'][0]['ownership'] == 'user'
    assert len(calls) == 2
    mod.resolve_companions([entry])
    assert len(calls) == 3
    from pathlib import Path
    Path(result['companions'][0]['local_path']).unlink()
    def cancel():
        if len(calls) >= 5:
            raise RuntimeError('cancelled')
    monkeypatch.setattr(mod,'check_job_cancelled',cancel)
    with pytest.raises(RuntimeError,match='cancelled'):
        mod.resolve_companions([entry])
    assert not list(tmp_path.rglob('*.incomplete'))
    assert not list(tmp_path.rglob('*.gguf'))


def test_worker_delete_blocks_other_configuration_companion_reference(tmp_path):
    mod = load_addon_module('worker.executors.llama', namespace='unload_companions')
    root = tmp_path/'cache'
    root.mkdir()
    path = root/'shared.gguf'
    path.write_bytes(b'weights')
    (tmp_path/'models.json').write_text(json.dumps({'version':1,'models':[
        {'model_id':'a','ownership':'addon','cached_path':str(path)},
        {'model_id':'b','source':'other.gguf','companions':[{'role':'draft','kind':'local_file','source':str(path)}]}
    ]}))
    instance = mod.LlamaWorkerExecutor(supervisor=Mock(),owned_cache_root=root)
    with pytest.raises(ValueError,match='another'):
        instance.delete_cache(str(root),str(path),'a')
    assert path.exists()


def test_preset_rejects_mtp_when_installed_help_supports_only_simple(tmp_path, monkeypatch):
    mod = load_addon_module('worker.executors.llama', namespace='unload_companions')
    binary = tmp_path/'llama.exe'
    binary.write_bytes(b'exe')
    process = Mock()
    process.communicate.return_value = (b'--spec-draft-model FNAME\n--spec-type none,draft-simple\n--mmproj FILE',None)
    process.poll.return_value = 0
    process.returncode = 0
    monkeypatch.setattr(mod.subprocess,'Popen',Mock(return_value=process))
    instance = mod.LlamaWorkerExecutor(supervisor=Mock())
    with pytest.raises(ValueError,match='draft-mtp'):
        instance.configure_preset([{'model_id':'x','source':'main.gguf','preset_options':{'spec-type':'draft-mtp','spec-draft-model':'draft.gguf'}}],preset_path=tmp_path/'models.ini',executable=str(binary))
    assert not (tmp_path/'models.ini').exists()


def test_worker_delete_fails_closed_when_dependency_manifest_is_unreadable(tmp_path):
    mod = load_addon_module('worker.executors.llama', namespace='unload_companions')
    root = tmp_path/'cache'
    root.mkdir()
    path = root/'shared.gguf'
    path.write_bytes(b'weights')
    (tmp_path/'models.json').write_text(json.dumps({'version':1,'models':[{'model_id':'a','ownership':'addon','cached_path':str(path)}]}))
    (tmp_path/'models-legacy.json').write_text('{broken')
    with pytest.raises(ValueError, match='catalog'):
        mod.LlamaWorkerExecutor(supervisor=Mock(),owned_cache_root=root).delete_cache(str(root),str(path),'a')
    assert path.exists()


def test_cached_companion_progress_does_not_claim_download(tmp_path, monkeypatch):
    mod = load_addon_module('worker.executors.llama_hf', namespace='hf_companions')
    monkeypatch.setenv('HF_HUB_CACHE',str(tmp_path))
    gguf=b'GGUF'+struct.pack('<IQQ',3,1,1)
    body={'sha':'a'*40,'siblings':[{'rfilename':'mmproj.gguf','size':len(gguf)}]}
    monkeypatch.setattr(mod.urllib.request,'urlopen',lambda request,timeout:io.BytesIO(json.dumps(body).encode() if '/api/' in request.full_url else gguf))
    entry=dict(role='vision',kind='hugging_face',source='org/model',artifact='mmproj.gguf')
    stages=[]
    result=mod.resolve_companions([entry],on_stage=stages.append)
    assert stages == ['checking_companions','downloading_companion']
    assert result['companions'][0]['source_size'] == len(gguf)
    stages.clear()
    mod.resolve_companions([entry],on_stage=stages.append)
    assert stages == ['checking_companions']
