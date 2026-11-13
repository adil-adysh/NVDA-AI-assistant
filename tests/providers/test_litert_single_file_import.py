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
