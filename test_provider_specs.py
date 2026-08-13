# -*- coding: utf-8 -*-
"""Regression tests for provider configuration schemas."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


_ROOT = Path(__file__).parent / "addon" / "globalPlugins" / "AI-assistant" / "config"
_PACKAGE = "provider_specs_testpkg"
package = types.ModuleType(_PACKAGE)
package.__path__ = [str(_ROOT)]
sys.modules[_PACKAGE] = package


def _load(name: str, path: Path) -> types.ModuleType:
	spec = importlib.util.spec_from_file_location(name, path)
	assert spec is not None and spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)
	return module


_load(f"{_PACKAGE}.defaults", _ROOT / "defaults.py")
_MODULE = _load(f"{_PACKAGE}.provider_specs", _ROOT / "provider_specs.py")


class ProviderConfigSpecTests(unittest.TestCase):
	def test_every_registered_provider_has_isolated_persistence_keys(self) -> None:
		specs = _MODULE.PROVIDER_CONFIG_SPECS
		self.assertEqual(set(specs), {"ollama", "gemini", "openai", "litert-lm"})
		self.assertEqual(len({spec.model_key for spec in specs.values()}), len(specs))
		self.assertEqual(len({spec.base_url_key for spec in specs.values()}), len(specs))

	def test_openai_compat_alias_uses_openai_schema(self) -> None:
		self.assertIs(
			_MODULE.get_provider_config_spec("openai_compat"),
			_MODULE.get_provider_config_spec("openai"),
		)


if __name__ == "__main__":
	unittest.main()
