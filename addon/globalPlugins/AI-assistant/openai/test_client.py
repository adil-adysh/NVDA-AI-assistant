# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
	sys.path.insert(0, str(MODULE_DIR))


PACKAGE_NAME = "openai_wrapper_testpkg"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(MODULE_DIR)]
sys.modules.setdefault(PACKAGE_NAME, package)


log_handler_module = types.ModuleType("logHandler")
log_handler_module.log = types.SimpleNamespace(debug=lambda *args, **kwargs: None, info=lambda *args, **kwargs: None)
sys.modules.setdefault("logHandler", log_handler_module)


def _load_module(module_name: str, file_name: str):
	spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.{module_name}", MODULE_DIR / file_name)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = module
	spec.loader.exec_module(module)
	return module


errors = _load_module("errors", "errors.py")
client_module = _load_module("client", "client.py")

OpenAIClient = client_module.OpenAIClient
OpenAIClientConfigurationError = errors.OpenAIClientConfigurationError


class OpenAIClientImageTests(unittest.TestCase):
	def setUp(self) -> None:
		self.client = OpenAIClient(api_key="test-key", base_url="https://api.openai.com")

	def test_describe_image_builds_vision_message_shape(self) -> None:
		captured: dict[str, object] = {}

		def fake_request_json(path: str, payload: dict[str, object], method: str = "POST"):
			captured["path"] = path
			captured["payload"] = payload
			captured["method"] = method
			return {"ok": True}

		self.client._request_json = fake_request_json  # type: ignore[method-assign]

		result = self.client.describe_image(
			model="gpt-4o-mini",
			image_base64="abc123",
			prompt="Describe the image",
			detail="high",
		)

		self.assertEqual(result, {"ok": True})
		self.assertEqual(captured["path"], "/v1/chat/completions")
		self.assertEqual(captured["method"], "POST")
		payload = captured["payload"]
		self.assertIsInstance(payload, dict)
		self.assertEqual(payload["model"], "gpt-4o-mini")
		self.assertEqual(payload["messages"][0]["role"], "user")
		self.assertEqual(payload["messages"][0]["content"][0], {"type": "text", "text": "Describe the image"})
		self.assertEqual(
			payload["messages"][0]["content"][1],
			{
				"type": "image_url",
				"image_url": {"url": "data:image/png;base64,abc123", "detail": "high"},
			},
		)

	def test_describe_image_rejects_empty_image_data(self) -> None:
		with self.assertRaises(OpenAIClientConfigurationError):
			self.client.describe_image(model="gpt-4o-mini", image_base64="", prompt="Describe")

	def test_describe_image_rejects_empty_prompt(self) -> None:
		with self.assertRaises(OpenAIClientConfigurationError):
			self.client.describe_image(model="gpt-4o-mini", image_base64="abc123", prompt="")


if __name__ == "__main__":
	unittest.main()
