import os
import struct

import pytest

from tests.support import load_addon_module


def worker():
    return load_addon_module("worker.executors.model_assets", namespace="assets_ux")


def gguf(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 0) + bytes(32))
    return path


def test_discovery_is_local_and_deduplicates_roots(tmp_path):
    source = gguf(tmp_path / "model.gguf")
    executor = worker().ModelAssetExecutor()
    result = executor.discover_model_assets([{"path": str(tmp_path), "source": "user_folder"}] * 2, 3)
    assert result.generation == 3 and len(result.assets) == 1
    assert result.assets[0].path == str(source)
    assert executor.verify_model_asset(result.assets[0].token).availability == "present"


def test_changed_asset_is_rejected_before_reuse(tmp_path):
    source = gguf(tmp_path / "model.gguf")
    executor = worker().ModelAssetExecutor()
    result = executor.discover_model_assets([{"path": str(tmp_path), "source": "user_folder"}], 1)
    source.write_bytes(b"replacement")
    with pytest.raises(ValueError, match="changed|missing"):
        executor.verify_model_asset(result.assets[0].token)


def test_partial_and_invalid_files_do_not_become_configurable(tmp_path):
    (tmp_path / "broken.gguf").write_bytes(b"wrong")
    gguf(tmp_path / "model-00001-of-00002.gguf")
    (tmp_path / "incomplete.gguf").write_bytes(b"GGUF")
    result = worker().ModelAssetExecutor().discover_model_assets([{"path": str(tmp_path), "source": "user_folder"}], 1)
    assert all(asset.availability != "present" for asset in result.assets)


def test_root_failures_do_not_hide_successes(tmp_path):
    gguf(tmp_path / "model.gguf")
    result = worker().ModelAssetExecutor().discover_model_assets([
        {"path": str(tmp_path), "source": "user_folder"}, {"path": str(tmp_path / "missing"), "source": "user_folder"}], 1)
    assert len(result.assets) == 1 and result.errors


def test_windows_default_cache_is_discovered_without_starting_runtime(tmp_path, monkeypatch):
    root = tmp_path / "llama.cpp"
    gguf(root / "cached.gguf")
    monkeypatch.delenv("LLAMA_CACHE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    roots = worker().default_cache_roots()
    assert {"path": str(root), "source": "llama_cache"} in roots


def test_cancelled_scan_returns_no_success(tmp_path):
    execution = load_addon_module("core.job.execution", namespace="assets_ux")
    cancellation = load_addon_module("core.job.cancellation", namespace="assets_ux")
    token = cancellation.CancellationToken("scan")
    token.cancel()
    with execution.job_execution_scope(token), pytest.raises(cancellation.JobCancelledError):
        worker().ModelAssetExecutor().discover_model_assets([{"path": str(tmp_path), "source": "user_folder"}], 1)


def test_file_symlink_outside_root_is_not_configurable(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    outside = gguf(tmp_path / "outside.gguf")
    try:
        os.symlink(outside, root / "model.gguf")
    except OSError:
        pytest.skip("File symlinks unavailable")
    result = worker().ModelAssetExecutor().discover_model_assets([{"path": str(root), "source": "user_folder"}], 1)
    assert all(asset.availability != "present" for asset in result.assets)
