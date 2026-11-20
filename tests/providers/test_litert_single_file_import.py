import shutil
from unittest.mock import Mock

import pytest

from tests.support import load_addon_module

manager_module = load_addon_module("providers.litert_manager", namespace="litert_import_policy")
requests = load_addon_module("providers.model_import", namespace="litert_import_policy")
downloads = load_addon_module("providers.runtime.model_download", namespace="litert_import_policy")


def test_local_import_stages_one_file_and_preserves_user_source(tmp_path):
	source = tmp_path / "source.litertlm"
	source.write_bytes(b"container")
	supervisor = Mock()
	service = downloads.ModelDownloadService(cache_dir=tmp_path / "cache")
	manager = manager_module.LiteRTModelManager(supervisor=supervisor, download_service=service)
	request = requests.parse_model_import_source(str(source), "custom", "litert-lm")
	manager.import_model(request, Mock())
	args, kwargs = supervisor.import_model.call_args
	assert args[0].read_bytes() == source.read_bytes()
	assert args[1] == "custom"
	assert kwargs["delete_source"] is False
	assert source.exists()


def test_huggingface_import_passes_only_selected_container():
	supervisor = Mock()
	service = Mock()
	manager = manager_module.LiteRTModelManager(supervisor=supervisor, download_service=service)
	request = requests.parse_model_import_source("owner/model#file=variants/model.litertlm", "custom", "litert-lm")
	manager.import_model(request, Mock())
	assert supervisor.import_huggingface_model.call_args.args == ("owner/model", "variants/model.litertlm", "custom")
	service.download_huggingface.assert_not_called()
	service.stage_local_file.assert_not_called()


def test_huggingface_import_passes_optional_token_to_supervisor():
	supervisor = Mock()
	manager = manager_module.LiteRTModelManager(supervisor=supervisor)
	request = requests.parse_model_import_source("owner/model#file=model.litertlm", "custom", "litert-lm")
	manager.import_model(request, Mock(), huggingface_token="hf-test-token")
	assert supervisor.import_huggingface_model.call_args.kwargs["huggingface_token"] == "hf-test-token"


def test_unknown_registered_artifact_name_is_removed_by_exact_id(tmp_path):
	supervisor = Mock()
	supervisor.list_server_models.return_value = ["model.litertlm"]
	service = downloads.ModelDownloadService(cache_dir=tmp_path / "cache")
	staged = service.model_path("model.litertlm.litertlm")
	staged.parent.mkdir(parents=True)
	staged.write_bytes(b"owned staged artifact")
	manager = manager_module.LiteRTModelManager(supervisor=supervisor, download_service=service)
	manager.delete_model("model.litertlm")
	supervisor.delete_model.assert_called_once_with("model.litertlm")
	assert not staged.exists()


def test_ambiguous_catalog_artifact_filename_is_not_mapped_to_catalog():
	models = load_addon_module("providers.litert_models", namespace="litert_import_policy")
	assert models.lookup_catalog_friendly_name("model.litertlm") is None
	assert models.lookup_catalog_artifact_alias("model.litertlm") is None
	assert models.resolve_identity("model.litertlm") == "model.litertlm"


def test_registered_custom_artifact_alias_can_become_active():
	supervisor = Mock()
	supervisor.list_server_models.return_value = ["model.litertlm"]
	manager = manager_module.LiteRTModelManager(supervisor=supervisor)
	with pytest.MonkeyPatch.context() as monkeypatch:
		set_active = Mock()
		monkeypatch.setattr(manager_module, "set_litert_model_name", set_active)
		manager.set_active_model("model.litertlm")
	set_active.assert_called_once_with("model.litertlm")
	supervisor.rename_model.assert_not_called()


def test_staging_local_model_replaces_cached_file_after_copy(tmp_path):
	source = tmp_path / "source.litertlm"
	source.write_bytes(b"new-model")
	service = downloads.ModelDownloadService(cache_dir=tmp_path / "cache")
	destination = service.model_path("custom.litertlm")
	destination.parent.mkdir(parents=True)
	destination.write_bytes(b"previous-model")

	assert service.stage_local_file(source, "custom.litertlm") == destination
	assert destination.read_bytes() == b"new-model"
	assert not list(destination.parent.glob("*.tmp"))


def test_staging_copy_failure_preserves_existing_cached_file(tmp_path, monkeypatch):
	source = tmp_path / "source.litertlm"
	source.write_bytes(b"new-model")
	service = downloads.ModelDownloadService(cache_dir=tmp_path / "cache")
	destination = service.model_path("custom.litertlm")
	destination.parent.mkdir(parents=True)
	destination.write_bytes(b"previous-model")

	def fail_copy(*_args, **_kwargs):
		raise OSError("simulated copy failure")

	monkeypatch.setattr(shutil, "copy2", fail_copy)
	with pytest.raises(OSError, match="simulated"):
		service.stage_local_file(source, "custom.litertlm")
	assert destination.read_bytes() == b"previous-model"
	assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.parametrize("artifact", ["model.tflite", "model.json", "model-00001-of-00002.litertlm"])
def test_manager_rejects_components_without_starting_worker(artifact):
	supervisor = Mock()
	manager = manager_module.LiteRTModelManager(supervisor=supervisor)
	request = requests.parse_model_import_source(f"owner/model#file={artifact}", "custom", "litert-lm")
	with pytest.raises(manager_module.LLMProviderError, match="single"):
		manager.import_model(request, Mock())
	supervisor.import_huggingface_model.assert_not_called()


def test_cancelled_import_never_stages_or_launches():
	import threading
	cancel = threading.Event()
	cancel.set()
	supervisor, downloads = Mock(), Mock()
	manager = manager_module.LiteRTModelManager(supervisor=supervisor, download_service=downloads)
	request = requests.parse_model_import_source("owner/model#file=model.litertlm", "custom", "litert-lm")
	with pytest.raises(manager_module.DownloadCancelledError):
		manager.import_model(request, Mock(), cancel_event=cancel)
	supervisor.import_huggingface_model.assert_not_called()
	downloads.stage_local_file.assert_not_called()
