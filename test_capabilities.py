# -*- coding: utf-8 -*-
"""Tests for provider-independent capability semantics."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


_MODULE_PATH = (
	Path(__file__).parent
	/ "addon"
	/ "globalPlugins"
	/ "AI-assistant"
	/ "providers"
	/ "capabilities.py"
)
_SPEC = importlib.util.spec_from_file_location("provider_capabilities", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
CachedCapabilityInspector = _MODULE.CachedCapabilityInspector
ModelCapabilities = _MODULE.ModelCapabilities


class ModelCapabilitiesTests(unittest.TestCase):
	def test_normalizes_and_checks_capabilities(self) -> None:
		capabilities = ModelCapabilities.from_iterable([" Chat ", "IMAGE_INPUT", ""])
		self.assertTrue(capabilities.supports("chat"))
		self.assertTrue(capabilities.supports("image_input"))
		self.assertFalse(capabilities.supports("tools"))

	def test_invalid_metadata_is_empty(self) -> None:
		self.assertEqual(ModelCapabilities.from_iterable(None).values, frozenset())


class CachedCapabilityInspectorTests(unittest.TestCase):
	def test_loads_each_model_once_and_supports_invalidation(self) -> None:
		calls: list[str] = []

		def load(model_id: str) -> object:
			calls.append(model_id)
			return ModelCapabilities.from_iterable(["chat"])

		cache = CachedCapabilityInspector(load)
		self.assertTrue(cache.inspect("model-a").supports("chat"))
		self.assertTrue(cache.inspect("model-a").supports("chat"))
		self.assertEqual(calls, ["model-a"])
		cache.invalidate("model-a")
		cache.inspect("model-a")
		self.assertEqual(calls, ["model-a", "model-a"])


if __name__ == "__main__":
	unittest.main()
