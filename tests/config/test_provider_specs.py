# -*- coding: utf-8 -*-
"""Regression tests for provider configuration schemas."""

from __future__ import annotations

import unittest

from tests.support import ADDON_ROOT, load_module, register_package

_ROOT = ADDON_ROOT / "config"
_PACKAGE = "provider_specs_testpkg"
register_package(_PACKAGE, _ROOT)
load_module(f"{_PACKAGE}.defaults", _ROOT / "defaults.py")
_MODULE = load_module(f"{_PACKAGE}.provider_specs", _ROOT / "provider_specs.py")


class ProviderConfigSpecTests(unittest.TestCase):
	def test_every_registered_provider_has_isolated_persistence_keys(self) -> None:
		specs = _MODULE.PROVIDER_CONFIG_SPECS
		self.assertEqual(set(specs), {"ollama", "gemini", "openai", "litert-lm", "llama-cpp-server"})
		self.assertEqual(len({spec.model_key for spec in specs.values()}), len(specs))
		self.assertEqual(len({spec.base_url_key for spec in specs.values()}), len(specs))

	def test_openai_compat_alias_uses_openai_schema(self) -> None:
		self.assertIs(
			_MODULE.get_provider_config_spec("openai_compat"),
			_MODULE.get_provider_config_spec("openai"),
		)


if __name__ == "__main__":
	unittest.main()
