from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock

from tests.support import ADDON_ROOT, load_module, register_package

ROOT = ADDON_ROOT
PACKAGE = "llama_server_testpkg"


def _load_module():
	for name, path in (
		(PACKAGE, ROOT),
		(f"{PACKAGE}.providers", ROOT / "providers"),
		(f"{PACKAGE}.providers.runtime", ROOT / "providers" / "runtime"),
	):
		register_package(name, path)
	interfaces = types.ModuleType(f"{PACKAGE}.providers.interfaces")
	interfaces.LLMProviderError = RuntimeError
	sys.modules[interfaces.__name__] = interfaces
	name = f"{PACKAGE}.providers.runtime.llama_server"
	return load_module(name, ROOT / "providers" / "runtime" / "llama_server.py")


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
		mock_native = Mock()
		mock_status = Mock(is_ready=True, is_running=True)
		mock_native.ensure_ready.return_value = mock_status
		supervisor = MODULE.LlamaServerSupervisor(native_supervisor=mock_native)
		supervisor.start("C:/models/model.gguf", model_id="model")
		self.assertTrue(mock_native.ensure_ready.called)
		args = mock_native.ensure_ready.call_args.args[1]
		self.assertEqual(args[-4:], ["-m", "C:/models/model.gguf", "--alias", "model"])
		self.assertIn("--host", args)
		supervisor.stop()
		mock_native.stop.assert_called_once()


if __name__ == "__main__":
	unittest.main()
