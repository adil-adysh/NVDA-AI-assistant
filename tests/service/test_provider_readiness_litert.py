# -*- coding: utf-8 -*-
# Pylint cannot infer attributes assigned to types.ModuleType() fakes used
# to stub NVDA-internal modules (E1101 ``__name__`` false positives).
# Test files deliberately duplicate the self-contained synthetic-package
# bootstrap so each suite can run standalone (R0801).
# pylint: disable=no-member,duplicate-code
"""Tests for the LiteRT branch of ProviderReadinessService.evaluate().

The LiteRT branch is the only readiness path that consults the runtime
supervisor.  It must report READY when the server is running *or* has been
adopted after an NVDA restart (process handle lost but server reachable),
and UNCONFIGURED otherwise.  These tests exercise that contract without a
live server by patching ``get_litert_supervisor``.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from tests.support import ADDON_ROOT, load_module as _load_module, register_package as _register_package


ROOT_DIR = ADDON_ROOT
MODULE_DIR = ROOT_DIR / "service"
PACKAGE_NAME = "provider_readiness_litert_testpkg"


_register_package(PACKAGE_NAME, ROOT_DIR)
_register_package(f"{PACKAGE_NAME}.config", ROOT_DIR / "config")
_register_package(f"{PACKAGE_NAME}.providers", ROOT_DIR / "providers")
_register_package(f"{PACKAGE_NAME}.service", ROOT_DIR / "service")

config_module = _load_module(
	f"{PACKAGE_NAME}.providers.config",
	ROOT_DIR / "providers" / "config.py",
)

settings_module = types.ModuleType(f"{PACKAGE_NAME}.config.settings")
settings_module.get_active_provider_config = lambda: None
sys.modules[settings_module.__name__] = settings_module

provider_readiness_module = _load_module(
	f"{PACKAGE_NAME}.service.provider_readiness",
	ROOT_DIR / "service" / "provider_readiness.py",
)

LiteRTConfig = config_module.LiteRTConfig
ProviderReadinessReason = provider_readiness_module.ProviderReadinessReason
ProviderReadinessService = provider_readiness_module.ProviderReadinessService
ProviderReadinessState = provider_readiness_module.ProviderReadinessState


class LiteRTReadinessTests(unittest.TestCase):
	"""LiteRT readiness must honor adopted servers, not only process handles."""

	def setUp(self) -> None:
		self.readiness_service = ProviderReadinessService()

	def _litert_config(self) -> LiteRTConfig:
		return LiteRTConfig(
			provider="litert-lm",
			model_name="litert-community/gemma-4-E2B-it-litert-lm",
			timeout_seconds=30.0,
			enable_progress=False,
			num_ctx=0,
			max_retries=1,
			retry_backoff_seconds=0.1,
			generate_temperature=0.2,
			generate_top_k=0,
			generate_top_p=0.9,
			generate_max_tokens=512,
			base_url="http://127.0.0.1:9379",
		)

	def test_litert_running_is_ready(self) -> None:
		fake_supervisor = types.SimpleNamespace(is_running=True, is_adopted=False)
		with mock.patch.object(
			provider_readiness_module,
			"get_litert_supervisor",
			return_value=fake_supervisor,
		):
			readiness = self.readiness_service.evaluate(self._litert_config())
		self.assertEqual(readiness.state, ProviderReadinessState.READY)
		self.assertTrue(readiness.can_infer)
		self.assertTrue(readiness.can_list_models)

	def test_litert_adopted_is_ready(self) -> None:
		"""A healthy-but-handleless server (NVDA restart) is still ready."""
		fake_supervisor = types.SimpleNamespace(is_running=False, is_adopted=True)
		with mock.patch.object(
			provider_readiness_module,
			"get_litert_supervisor",
			return_value=fake_supervisor,
		):
			readiness = self.readiness_service.evaluate(self._litert_config())
		self.assertEqual(readiness.state, ProviderReadinessState.READY)
		self.assertTrue(readiness.can_infer)

	def test_litert_not_running_or_adopted_is_unconfigured(self) -> None:
		fake_supervisor = types.SimpleNamespace(is_running=False, is_adopted=False)
		with mock.patch.object(
			provider_readiness_module,
			"get_litert_supervisor",
			return_value=fake_supervisor,
		):
			readiness = self.readiness_service.evaluate(self._litert_config())
		self.assertEqual(readiness.state, ProviderReadinessState.UNCONFIGURED)
		self.assertEqual(readiness.reason, ProviderReadinessReason.MISSING_SERVER_URL)
		self.assertFalse(readiness.can_infer)
		self.assertFalse(readiness.can_list_models)


if __name__ == "__main__":
	unittest.main()
