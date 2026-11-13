import struct
from unittest.mock import Mock

import pytest
from tests.support import load_addon_module


def setup(tmp_path):
    mod = load_addon_module("providers.llama_manager", namespace="cached_ux")
    assets = load_addon_module("core.model_assets", namespace="cached_ux")
    source = tmp_path / "cached.gguf"
    source.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 0))
    asset = assets.ModelAssetSnapshot("asset", "token", str(source), "llama_cache", "present", 24)
    client = Mock()
    client.send_command.return_value = {"success": True, "result": asset.to_dict()}
    manager = mod.LlamaCppModelManager(supervisor=Mock(), worker_client=client, cache_dir=tmp_path / "managed")
    return manager, client, source


def test_cache_create_preserves_weights_and_has_friendly_name(tmp_path):
    manager, client, source = setup(tmp_path)
    manager.create_configuration_from_asset("token", "everyday", "Everyday", {})
    manager.create_configuration_from_asset("token", "long", "Long context", {"ctx-size": "8192"})
    records = manager._catalog.list_records()
    assert len(records) == 2 and records[0].display_name == "Everyday"
    assert all(record.asset_id == "asset" and record.ownership == "user" for record in records)
    assert source.exists()
    assert client.send_command.call_args.args[0]["command"] == "llama_verify_asset"


def test_failed_verification_creates_nothing(tmp_path):
    manager, client, unused = setup(tmp_path)
    client.send_command.return_value = {"success": False, "error_message": "File changed"}
    with pytest.raises(Exception, match="changed"):
        manager.create_configuration_from_asset("token", "new", "New", {})
    assert not manager._catalog.list_records()


def test_creation_does_not_overwrite_an_existing_configuration(tmp_path):
    manager, client, source = setup(tmp_path)
    manager.create_configuration_from_asset("token", "same", "Original", {})
    with pytest.raises(ValueError, match="already"):
        manager.create_configuration_from_asset("token", "same", "Replacement", {})
    assert manager._catalog.find_exact("same").display_name == "Original"
