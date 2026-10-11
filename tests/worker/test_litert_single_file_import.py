from unittest.mock import Mock

import pytest

from tests.support import load_addon_module

executor_module = load_addon_module("worker.executors.litert", namespace="single_file_litert")


@pytest.mark.parametrize("artifact", ["model.tflite", "model.json", "model.litert", "model-00001-of-00002.litertlm", "model.litertlm.part1", "models/", "../model.litertlm"])
def test_worker_rejects_non_container_huggingface_import_before_cli(artifact):
	executor = executor_module.LiteRTWorkerExecutor()
	executor._run_cli = Mock()
	with pytest.raises(ValueError, match="single|artifact"):
		executor.import_huggingface_model("owner/model", artifact, "model")
	executor._run_cli.assert_not_called()


@pytest.mark.parametrize("filename", ["model.tflite", "model.litert", "model-00001-of-00002.litertlm"])
def test_worker_rejects_multi_file_components_before_cli(tmp_path, filename):
	path = tmp_path / filename
	path.write_bytes(b"component")
	executor = executor_module.LiteRTWorkerExecutor()
	executor._run_cli = Mock()
	with pytest.raises(ValueError, match="single"):
		executor.import_model(path, "model")
	executor._run_cli.assert_not_called()


def test_runtime_version_defaults_agree():
	server = load_addon_module("providers.runtime.server", namespace="single_file_litert")
	config = load_addon_module("providers.runtime.config", namespace="single_file_litert")
	assert executor_module.DEFAULT_LITERT_VERSION == server.DEFAULT_LITERT_VERSION == config.DefaultRuntimeConfig().litert_lm == "0.18.0"
