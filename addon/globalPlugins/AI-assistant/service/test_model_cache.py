# -*- coding: utf-8 -*-
"""Provider-wide tests for the model catalog and capability caches."""
from __future__ import annotations

import importlib.util
import sys
import threading
import time
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "model_cache_testpkg"


def _register_package(name: str, path: Path | None = None) -> None:
	module = types.ModuleType(name)
	if path is not None:
		module.__path__ = [str(path)]
	sys.modules[name] = module


def _load(module_name: str, path: Path):
	spec = importlib.util.spec_from_file_location(module_name, path)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[module_name] = module
	spec.loader.exec_module(module)
	return module


_register_package(PACKAGE_NAME, ROOT_DIR)
_register_package(f"{PACKAGE_NAME}.core", ROOT_DIR / "core")
_register_package(f"{PACKAGE_NAME}.config", ROOT_DIR / "config")
_register_package(f"{PACKAGE_NAME}.providers", ROOT_DIR / "providers")
_register_package(f"{PACKAGE_NAME}.service", MODULE_DIR)

log_handler = types.ModuleType("logHandler")
log_handler.log = types.SimpleNamespace(
	debug=lambda *args, **kwargs: None,
	info=lambda *args, **kwargs: None,
	warning=lambda *args, **kwargs: None,
	exception=lambda *args, **kwargs: None,
)
sys.modules["logHandler"] = log_handler

settings = types.ModuleType(f"{PACKAGE_NAME}.config.settings")
settings.build_provider_config = lambda provider_id: types.SimpleNamespace(provider=provider_id)
settings.get_enabled_providers = lambda: ("ollama", "gemini", "openai", "litert-lm", "llama-cpp-server")
sys.modules[settings.__name__] = settings

_load(f"{PACKAGE_NAME}.core.canonical", ROOT_DIR / "core" / "canonical.py")
_load(f"{PACKAGE_NAME}.core.messages", ROOT_DIR / "core" / "messages.py")
interfaces = _load(f"{PACKAGE_NAME}.providers.interfaces", ROOT_DIR / "providers" / "interfaces.py")
_load(f"{PACKAGE_NAME}.providers.capabilities", ROOT_DIR / "providers" / "capabilities.py")
cache_module = _load(f"{PACKAGE_NAME}.service.model_cache", MODULE_DIR / "model_cache.py")

ModelCatalogCache = cache_module.ModelCatalogCache
ModelCapabilityCache = cache_module.ModelCapabilityCache
ProviderModelInfo = interfaces.ProviderModelInfo

PROVIDERS = ("ollama", "gemini", "openai", "litert-lm", "llama-cpp-server")


class _FakeCatalog:
	def __init__(self, calls: list[str], delay: float = 0.0) -> None:
		self.calls = calls
		self.delay = delay

	def list_models(self, config: object):
		provider = config.provider
		self.calls.append(provider)
		if self.delay:
			time.sleep(self.delay)
		return (ProviderModelInfo(
			id=f"{provider}-model",
			provider=provider,
			capabilities=("image_input",),
		),)


class ModelCacheTests(unittest.TestCase):
	def test_empty_discovery_result_is_retried(self) -> None:
		calls: list[str] = []

		class _StartsLateCatalog(_FakeCatalog):
			def list_models(self, config: object):
				calls.append(config.provider)
				if len(calls) == 1:
					return ()
				return (ProviderModelInfo(id="late-model", provider=config.provider),)

		cache = ModelCatalogCache(catalog_factory=lambda: _StartsLateCatalog(calls))
		self.assertEqual(cache.get_models("ollama"), ())
		self.assertEqual(
			cache.get_models("ollama"),
			(ProviderModelInfo(id="late-model", provider="ollama"),),
		)
		self.assertEqual(calls, ["ollama", "ollama"])

	def test_each_registered_provider_is_cached_and_invalidated(self) -> None:
		calls: list[str] = []
		catalog = _FakeCatalog(calls)
		cache = ModelCatalogCache(catalog_factory=lambda: catalog)

		for provider in PROVIDERS:
			first = cache.get_models(provider)
			self.assertEqual(first, cache.get_models(provider))
			self.assertEqual(calls.count(provider), 1)
			self.assertTrue(cache.has(provider))
			cache.invalidate(provider)
			self.assertFalse(cache.has(provider))
			self.assertEqual(cache.version(provider), 1)
			self.assertEqual(cache.get_models(provider), first)
			self.assertEqual(calls.count(provider), 2)

	def test_preload_async_completes_and_does_not_deadlock(self) -> None:
		calls: list[str] = []
		cache = ModelCatalogCache(catalog_factory=lambda: _FakeCatalog(calls, delay=0.01))

		for provider in PROVIDERS:
			cache.preload_async(provider)
		deadline = time.monotonic() + 2.0
		while time.monotonic() < deadline and not cache.has(provider):
			time.sleep(0.005)
		self.assertTrue(cache.has(provider), provider)
		self.assertEqual(calls.count(provider), 1)

	def test_concurrent_misses_are_deduplicated(self) -> None:
		calls: list[str] = []
		cache = ModelCatalogCache(catalog_factory=lambda: _FakeCatalog(calls, delay=0.03))
		results: list[tuple[ProviderModelInfo, ...]] = []
		threads = [threading.Thread(target=lambda: results.append(cache.get_models("gemini"))) for _ in range(8)]

		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join(timeout=2)
			self.assertFalse(thread.is_alive())
		self.assertEqual(len(results), 8)
		self.assertEqual(calls, ["gemini"])

	def test_capability_cache_tracks_catalog_generation(self) -> None:
		calls: list[str] = []
		cache = ModelCatalogCache(catalog_factory=lambda: _FakeCatalog(calls))
		capabilities = ModelCapabilityCache(cache)

		first = capabilities.get(" OPENAI ", "openai-model")
		self.assertTrue(first.supports("image_input"))
		self.assertIs(first, capabilities.get("openai", "openai-model"))
		cache.invalidate("openai")
		second = capabilities.get("openai", "openai-model")
		self.assertTrue(second.supports("image_input"))
		self.assertIsNot(first, second)
		self.assertEqual(calls.count("openai"), 2)


if __name__ == "__main__":
	unittest.main()
