from unittest.mock import Mock

from tests.support import load_addon_module


def manager(tmp_path):
    mod = load_addon_module("providers.llama_manager", namespace="transactions_ux")
    return mod.LlamaCppModelManager(cache_dir=tmp_path / "managed", supervisor=Mock())


def test_named_preset_is_committed_in_one_catalog_write(tmp_path, monkeypatch):
    m = manager(tmp_path)
    write = Mock(wraps=m._catalog.upsert)
    monkeypatch.setattr(m._catalog, "upsert", write)
    m.create_preset("owner/model", "daily", "Everyday")
    assert write.call_count == 1
    assert write.call_args.args[0].display_name == "Everyday"


def test_preset_creation_never_reads_a_preset_file(tmp_path):
    source = tmp_path / "preset.ini"
    source.write_text("version = 1\n[ignored]\nhf-repo = owner/ignored\n", encoding="utf-8")
    m = manager(tmp_path)
    m.create_preset("owner/model", "daily", "Everyday")
    assert [record.model_id for record in m.list_presets()] == ["daily"]
    assert not hasattr(m, "import_preset")


def test_duplicate_preset_id_is_rejected_without_writes(tmp_path):
    m = manager(tmp_path)
    m.create_preset("owner/model", "daily", "Everyday")
    before = (tmp_path / "managed/models.json").read_bytes()
    try:
        m.create_preset("owner/other", "daily", "Duplicate")
    except ValueError as error:
        assert "already exists" in str(error)
    else:
        raise AssertionError("duplicate ID was accepted")
    assert (tmp_path / "managed/models.json").read_bytes() == before
