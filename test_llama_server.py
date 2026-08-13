from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).parent / "addon" / "globalPlugins" / "AI-assistant"
PACKAGE = "llama_server_testpkg"


def _load_module():
	for name, path in (
		(PACKAGE, ROOT),
		(f"{PACKAGE}.providers", ROOT / "providers"),
		(f"{PACKAGE}.providers.runtime", ROOT / "providers" / "runtime"),
	):
		module = types.ModuleType(name)
		module.__path__ = [str(path)]
		sys.modules[name] = module
	interfaces = types.ModuleType(f"{PACKAGE}.providers.interfaces")
	interfaces.LLMProviderError = RuntimeError
	sys.modules[interfaces.__name__] = interfaces
	name = f"{PACKAGE}.providers.runtime.llama_server"
	spec = importlib.util.spec_from_file_location(name, ROOT / "providers" / "runtime" / "llama_server.py")
	assert spec is not None and spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)
	return module


MODULE = _load_module()


class LlamaServerTests(unittest.TestCase):
	def test_builds_hugging_face_variant_command_without_shell(self) -> None:
		self.assertEqual(
			MODULE.build_llama_server_args(
				"hf://unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL",
				alias="qwen",
				threads=8,
				context=8192,
			),
			[
				"--host", "127.0.0.1", "--port", "8080",
				"-hf", "unsloth/Qwen3-8B-GGUF:UD-Q4_K_XL",
				"--alias", "qwen", "-t", "8", "-c", "8192",
			],
		)

	def test_start_uses_argument_list_and_can_stop_process(self) -> None:
		process = Mock()
		process.poll.return_value = None
		factory = Mock(return_value=process)
		supervisor = MODULE.LlamaServerSupervisor(process_factory=factory)
		supervisor.start("C:/models/model.gguf", model_id="model")
		command = factory.call_args.args[0]
		self.assertEqual(command[-4:], ["-m", "C:/models/model.gguf", "--alias", "model"])
		self.assertIn("--host", command)
		supervisor.stop()
		process.terminate.assert_called_once()


if __name__ == "__main__":
	unittest.main()
