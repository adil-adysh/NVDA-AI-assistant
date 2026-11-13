from unittest.mock import Mock

import pytest
from tests.support import load_addon_module


def manager(tmp_path):
    mod = load_addon_module("providers.llama_manager", namespace="transactions_ux")
    return mod.LlamaCppModelManager(cache_dir=tmp_path / "managed", supervisor=Mock())


def test_named_configuration_is_committed_in_one_catalog_write(tmp_path, monkeypatch):
    m = manager(tmp_path)
    write = Mock(wraps=m._catalog.upsert)
    monkeypatch.setattr(m._catalog, "upsert", write)
    m.create_configuration("owner/model", "daily", "Everyday")
    assert write.call_count == 1
    assert write.call_args.args[0].display_name == "Everyday"


def test_preview_has_replacements_and_cancel_has_no_side_effects(tmp_path):
    m = manager(tmp_path)
    source = tmp_path / "preset.ini"
    source.write_text("version = 1\n[a]\nhf-repo = owner/a\n", encoding="utf-8")
    m.import_preset(source)
    before = (tmp_path / "managed/models.json").read_bytes()
    preview = m.preview_preset_import(str(source))
    assert preview.replace_ids == ("a",)
    assert (tmp_path / "managed/models.json").read_bytes() == before
    with pytest.raises(ValueError, match="Replace"):
        m.commit_preset_import(preview, replace_ids=())


def test_source_changes_invalidate_preview(tmp_path):
    m = manager(tmp_path)
    source = tmp_path / "preset.ini"
    source.write_text("version = 1\n[a]\nhf-repo = owner/a\n", encoding="utf-8")
    preview = m.preview_preset_import(str(source))
    source.write_text("version = 1\n[b]\nhf-repo = owner/b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        m.commit_preset_import(preview, replace_ids=())
    assert not m._catalog.list_records()


def test_unsupported_options_are_reviewable_but_not_committable(tmp_path):
    m = manager(tmp_path)
    source = tmp_path / "preset.ini"
    source.write_text("version = 1\n[a]\nhf-repo = owner/a\nunknown = value\n", encoding="utf-8")
    preview = m.preview_preset_import(str(source))
    assert preview.unsupported == ("[a] unknown",)
    with pytest.raises(ValueError, match="Unsupported"):
        m.commit_preset_import(preview, replace_ids=())
    assert not m._catalog.list_records()


def test_catalog_changes_invalidate_replacement_preview(tmp_path):
    m = manager(tmp_path)
    source = tmp_path / "preset.ini"
    source.write_text("version = 1\n[a]\nhf-repo = owner/a\n", encoding="utf-8")
    m.import_preset(source)
    preview = m.preview_preset_import(str(source))
    m.set_runtime_options("a", {"ctx-size": "4096"})
    with pytest.raises(ValueError, match="changed"):
        m.commit_preset_import(preview, replace_ids=("a",))
    assert m.get_runtime_options("a") == {"ctx-size": "4096"}
