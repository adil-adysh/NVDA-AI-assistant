import threading
from unittest.mock import Mock

import pytest
from tests.support import load_addon_module


def setup(tmp_path):
    mod = load_addon_module("providers.llama_manager", namespace="recovery_ux")
    records = load_addon_module("providers.runtime.llama_models", namespace="recovery_ux")
    manager = mod.LlamaCppModelManager(cache_dir=tmp_path / "managed", supervisor=Mock(), worker_client=Mock())
    manager._catalog.upsert(records.LlamaModelRecord("original", "owner/model", "hugging_face",
        display_name="Original", preset_options={"ctx-size": "4096"}))
    return manager


def test_relocation_preserves_id_settings_and_source_ownership(tmp_path):
    manager = setup(tmp_path)
    path = tmp_path / "recovered.gguf"
    path.write_bytes(b"GGUF")
    manager.relocate_configuration("original", str(path))
    record = manager._catalog.find_exact("original")
    assert record.local_path == str(path)
    assert record.preset_options == {"ctx-size": "4096"} and record.display_name == "Original"


def test_duplicate_preserves_options_and_rejects_collisions(tmp_path, monkeypatch):
    manager = setup(tmp_path)
    sampling = load_addon_module("config.model_config", namespace="recovery_ux")
    monkeypatch.setattr(sampling, "set_model_sampling", Mock())
    manager.duplicate_configuration("original", "copy", "Copy")
    assert manager._catalog.find_exact("copy").preset_options == {"ctx-size": "4096"}
    with pytest.raises(ValueError, match="already"):
        manager.duplicate_configuration("original", "copy", "Another")


def test_prepare_is_not_successful_until_worker_reports_loaded(tmp_path, monkeypatch):
    manager = setup(tmp_path)
    monkeypatch.setattr(manager, "ensure_running", Mock())
    manager._worker_client.send_command.return_value = {"success": False, "error_message": "Load failed"}
    with pytest.raises(Exception, match="Load failed"):
        manager.prepare_configuration("original", None, threading.Event())
