from tests.support import load_addon_module
import pytest


def test_companions_explicit_mtp_and_vision_options():
    mod = load_addon_module('core.llama_companions', namespace='companion_contract')
    entries = [dict(role='vision', kind='local_file', source='mmproj.gguf'), dict(role='mtp', kind='local_file', source='mtp.gguf')]
    normalized = mod.validate_companions(entries)
    assert isinstance(normalized, tuple)
    assert mod.companion_options(normalized) == {'mmproj': 'mmproj.gguf', 'spec-draft-model': 'mtp.gguf', 'spec-type': 'draft-mtp'}


@pytest.mark.parametrize('entries', [
    [dict(role='vision', kind='hugging_face', source='org/repo')],
    [dict(role='draft', kind='local_file', source='x-00001-of-00002.gguf')],
    [dict(role='draft', kind='local_file', source='x.gguf'), dict(role='mtp', kind='local_file', source='y.gguf')],
])
def test_invalid_companions_rejected(entries):
    mod = load_addon_module('core.llama_companions', namespace='companion_contract')
    with pytest.raises(ValueError):
        mod.validate_companions(entries)


def test_remote_companion_omitted_until_resolved():
    mod = load_addon_module('core.llama_companions', namespace='companion_contract')
    assert mod.companion_options([dict(role='vision', kind='hugging_face', source='org/repo', artifact='mmproj.gguf')]) == {}


def test_speculative_options_aliases():
    mod = load_addon_module('core.llama_options', namespace='companion_contract')
    assert mod.validate_options({'model-draft': 'draft.gguf', 'spec-type': 'draft-mtp', 'parallel': '2'}) == {'spec-draft-model': 'draft.gguf', 'spec-type': 'draft-mtp', 'parallel': '2'}


def test_catalog_roundtrips_companions_without_downloading(tmp_path):
    mod = load_addon_module('providers.runtime.llama_models', namespace='companion_catalog')
    entry = dict(role='vision',kind='hugging_face',source='org/repo',artifact='mmproj.gguf')
    record = mod.LlamaModelRecord('x','main.gguf','local_file',companions=[entry])
    catalog = mod.LlamaModelCatalog(tmp_path)
    catalog.upsert(record)
    loaded = catalog.list_records()[0]
    assert loaded.companions[0]['revision'] == 'main'
    assert 'mmproj =' not in catalog.preset_path.read_text()
