# -*- coding: utf-8 -*-
"""Regression tests for the declarative provider policy boundary."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


_PATH = Path(__file__).parent / "addon" / "globalPlugins" / "AI-assistant" / "providers" / "policy.py"
_SPEC = importlib.util.spec_from_file_location("provider_policy", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
get_provider_policy = _MODULE.get_provider_policy


class ProviderPolicyTests(unittest.TestCase):
	def test_known_provider_policy_is_complete(self) -> None:
		for provider_id in ("ollama", "gemini", "openai", "litert-lm"):
			policy = get_provider_policy(provider_id)
			self.assertIsNotNone(policy)
			assert policy is not None
			self.assertEqual(policy.provider_id, provider_id)
			self.assertTrue(policy.display_name)

	def test_unknown_provider_is_not_silently_ready(self) -> None:
		self.assertIsNone(get_provider_policy("future-backend"))

	def test_credentials_are_policy_driven(self) -> None:
		openai = get_provider_policy("openai")
		gemini = get_provider_policy("gemini")
		assert openai is not None and gemini is not None
		self.assertFalse(openai.has_credentials(type("Config", (), {"api_key": ""})()))
		self.assertTrue(openai.has_credentials(type("Config", (), {"api_key": "key"})()))
		self.assertTrue(gemini.has_credentials(type("Config", (), {"api_key": "", "api_token": "token"})()))

	def test_unsupported_model_markers_are_not_duplicated_in_consumers(self) -> None:
		gemini = get_provider_policy("gemini")
		assert gemini is not None
		self.assertFalse(gemini.supports_model("gemini-3.1-flash-live-preview"))
		self.assertTrue(gemini.supports_model("gemini-2.5-flash"))


if __name__ == "__main__":
	unittest.main()
