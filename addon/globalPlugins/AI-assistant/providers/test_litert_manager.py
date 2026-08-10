# -*- coding: utf-8 -*-
# Pylint cannot infer attributes assigned to types.ModuleType() fakes used
# to stub NVDA-internal modules (E1101 ``__name__`` false positives).
# Test files deliberately duplicate the self-contained synthetic-package
# bootstrap so each suite can run standalone (R0801).
# pylint: disable=no-member,duplicate-code
"""Tests for LiteRTModelManager.delete_model coordination logic."""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "litert_manager_testpkg"


def _register_package(name: str, path: Path | None = None) -> types.ModuleType:
	module = types.ModuleType(name)
	if path is not None:
		module.__path__ = [str(path)]
	sys.modules[name] = module
	return module


def _load_file(module_name: str, file_path: Path):
	import importlib.util

	spec = importlib.util.spec_from_file_location(module_name, file_path)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[module_name] = module
	spec.loader.exec_module(module)
	return module


# ── Package registration ──────────────────────────────────────────
_register_package(PACKAGE_NAME, ROOT_DIR)
_register_package(f"{PACKAGE_NAME}.config", ROOT_DIR / "config")
_register_package(f"{PACKAGE_NAME}.providers", ROOT_DIR / "providers")
_register_package(f"{PACKAGE_NAME}.providers.adapters", [])
_register_package(f"{PACKAGE_NAME}.providers.runtime", [])
_register_package(f"{PACKAGE_NAME}.core", [])
_register_package(f"{PACKAGE_NAME}.ui", [])
_register_package(f"{PACKAGE_NAME}.ui_host", [])
_register_package(f"{PACKAGE_NAME}.service", [])
_register_package(f"{PACKAGE_NAME}.service.chat", [])
_register_package(f"{PACKAGE_NAME}.context", [])

# ── NVDA stubs ────────────────────────────────────────────────────
log_handler_module = types.ModuleType("logHandler")
log_handler_module.log = types.SimpleNamespace(
	debug=lambda *args, **kwargs: None,
	info=lambda *args, **kwargs: None,
	warning=lambda *args, **kwargs: None,
	exception=lambda *args, **kwargs: None,
)
sys.modules["logHandler"] = log_handler_module

language_handler_module = types.ModuleType("languageHandler")
language_handler_module.getLanguage = lambda: "en"
sys.modules["languageHandler"] = language_handler_module

# ── Stub config submodules ───────────────────────────────────────
class _FakeYamlStore:
	def get(self, key, default=None):
		return default
	def set(self, key, value):
		pass
	def set_many(self, values):
		pass

defaults_module = types.ModuleType(f"{PACKAGE_NAME}.config.defaults")
defaults_module.DEFAULT_LITERT_MODEL = "litert-community/gemma-4-E2B-it-litert-lm"
defaults_module.DEFAULT_LITERT_URL = "http://127.0.0.1:9379"
defaults_module.DEFAULT_LITERT_THINK = False
sys.modules[defaults_module.__name__] = defaults_module

yaml_store_module = types.ModuleType(f"{PACKAGE_NAME}.config.yaml_store")
yaml_store_module.YamlConfigStore = _FakeYamlStore
sys.modules[yaml_store_module.__name__] = yaml_store_module

state_module = types.ModuleType(f"{PACKAGE_NAME}.config.state")
state_module.ProviderState = type("ProviderState", (), {})
state_module.get_provider_state = mock.MagicMock()
state_module._notify_provider_state_changed = mock.MagicMock()
sys.modules[state_module.__name__] = state_module

# ── Stub core modules that interfaces.py transitively imports ────
canonical_module = types.ModuleType(f"{PACKAGE_NAME}.core.canonical")
canonical_module.Message = type("Message", (), {})
canonical_module.Tool = type("Tool", (), {})
sys.modules[canonical_module.__name__] = canonical_module

messages_module = types.ModuleType(f"{PACKAGE_NAME}.core.messages")
messages_module.ChatMessage = type("ChatMessage", (), {})
messages_module.LLMResponse = type("LLMResponse", (), {})
messages_module.SummaryResponse = type("SummaryResponse", (), {})
sys.modules[messages_module.__name__] = messages_module

# ── Load real modules we depend on ────────────────────────────────
# Stub runtime modules that litert_manager.py imports but we don't test directly
model_download_stub = types.ModuleType(
	f"{PACKAGE_NAME}.providers.runtime.model_download"
)
model_download_stub.ModelDownloadService = (
	mock.MagicMock(name="ModelDownloadServiceStub")
)
model_download_stub.ModelDownloadError = type(
	"ModelDownloadError", (RuntimeError,), {}
)
sys.modules[model_download_stub.__name__] = model_download_stub

# Use a local LLMProviderError for the server stub; the real one is
# extracted from litert_manager_module after loading.
_StubLiteRTServerError = type("_StubLiteRTServerError", (RuntimeError,), {})

server_stub = types.ModuleType(
	f"{PACKAGE_NAME}.providers.runtime.server"
)
server_stub.LiteRTServerError = _StubLiteRTServerError
server_stub.get_litert_supervisor = mock.MagicMock()
sys.modules[server_stub.__name__] = server_stub

# Load config modules first (they have NVDA dependencies we've stubbed)
config_module = _load_file(
	f"{PACKAGE_NAME}.providers.config",
	ROOT_DIR / "providers" / "config.py",
)
settings_module = _load_file(
	f"{PACKAGE_NAME}.config.settings",
	ROOT_DIR / "config" / "settings.py",
)
litert_models_module = _load_file(
	f"{PACKAGE_NAME}.providers.litert_models",
	ROOT_DIR / "providers" / "litert_models.py",
)
model_manager_module = _load_file(
	f"{PACKAGE_NAME}.providers.model_manager",
	ROOT_DIR / "providers" / "model_manager.py",
)
# Overwrite the stubs with real module after loading
sys.modules[server_stub.__name__] = server_stub
sys.modules[model_download_stub.__name__] = model_download_stub
litert_manager_module = _load_file(
	f"{PACKAGE_NAME}.providers.litert_manager",
	ROOT_DIR / "providers" / "litert_manager.py",
)

# Extract symbols under test
LiteRTModelManager = litert_manager_module.LiteRTModelManager
resolve_identity = litert_models_module.resolve_identity
lookup_model = litert_models_module.lookup_model
ModelDownloadService = mock.MagicMock(name="ModelDownloadService")
# LiteRTServerError from the real module (for isinstance checks in tests)
LiteRTServerError = litert_manager_module.LiteRTServerError


class DeleteModelCoordinationTests(unittest.TestCase):
	"""Tests for LiteRTModelManager.delete_model."""

	def setUp(self) -> None:
		# Patch the module-level supervisor singleton getter
		self._supervisor_patcher = mock.patch.object(
			litert_manager_module,
			"get_litert_supervisor",
		)
		self.mock_get_supervisor = self._supervisor_patcher.start()

		# Mock supervisor
		self.mock_supervisor = mock.MagicMock()
		self.mock_get_supervisor.return_value = self.mock_supervisor

		# Use a real temp dir for fake cache/catalog paths so
		# Path.touch() and Path.mkdir() work on Windows.
		self._temp_dir = tempfile.TemporaryDirectory()
		self._temp_path = Path(self._temp_dir.name)
		self._cache_dir = self._temp_path / "cache"
		self._catalog_dir = self._temp_path / "catalog"
		self._cache_dir.mkdir()
		self._catalog_dir.mkdir()

		# Mock download service
		self.mock_download_svc = mock.MagicMock()
		self.mock_download_svc.cache_dir = self._cache_dir

		# Create manager under test
		self.manager = LiteRTModelManager(
			download_service=self.mock_download_svc,
		)

	def tearDown(self) -> None:
		self._supervisor_patcher.stop()
		self._temp_dir.cleanup()

	def _make_cache_file(self, filename: str) -> Path:
		"""Create a real cache file in the temp dir and wire model_path."""
		path = self._cache_dir / filename
		self.mock_download_svc.model_path.return_value = path
		return path

	def _make_catalog_dir(self, canonical_id: str) -> Path:
		"""Create a real catalog dir and wire catalog_model_dir."""
		dir_name = canonical_id.replace("/", "--")
		path = self._catalog_dir / "models" / dir_name
		path.mkdir(parents=True, exist_ok=True)
		self.mock_supervisor.catalog_model_dir.return_value = path
		return path

	def _set_no_catalog(self) -> None:
		"""Wire catalog_model_dir to return a non-existent path."""
		self.mock_supervisor.catalog_model_dir.return_value = (
			self._catalog_dir / "models" / "nonexistent"
		)

	# ── Normal deletion (both catalog + cache exist) ─────────────

	def test_delete_both_catalog_and_cache(self) -> None:
		cache_path = self._make_cache_file("gemma-4-E2B-it.litertlm")
		cache_path.touch()
		self._make_catalog_dir("litert-community/gemma-4-E2B-it-litert-lm")

		self.manager.delete_model("litert-community/gemma-4-E2B-it-litert-lm")

		# Catalog unregister must be called BEFORE cache deletion
		self.mock_supervisor.delete_model.assert_called_once_with(
			"litert-community/gemma-4-E2B-it-litert-lm"
		)
		self.assertFalse(cache_path.exists(), "Cache file should be deleted")

	def test_delete_with_variant_filename(self) -> None:
		"""Variant filename (e.g. gemma-4-E2B-it-gpu.litertlm) should
		resolve to canonical ID for catalog and to variant name for cache."""
		cache_path = self._make_cache_file("gemma-4-E2B-it-gpu.litertlm")
		cache_path.touch()
		self._make_catalog_dir("litert-community/gemma-4-E2B-it-litert-lm")

		self.manager.delete_model("gemma-4-E2B-it-gpu.litertlm")

		# Catalog uses canonical ID
		self.mock_supervisor.delete_model.assert_called_once_with(
			"litert-community/gemma-4-E2B-it-litert-lm"
		)
		# Cache uses variant filename
		self.mock_download_svc.model_path.assert_called_once_with(
			"gemma-4-E2B-it-gpu.litertlm"
		)
		self.assertFalse(cache_path.exists())

	# ── Catalog deletion failure must preserve cache ─────────────

	def test_catalog_failure_preserves_cache(self) -> None:
		"""If supervisor.delete_model raises, the cache must NOT be deleted."""
		cache_path = self._make_cache_file("gemma-4-E2B-it.litertlm")
		cache_path.touch()
		self._make_catalog_dir("litert-community/gemma-4-E2B-it-litert-lm")
		self.mock_supervisor.delete_model.side_effect = LiteRTServerError(
			"Failed to delete model from catalog"
		)

		with self.assertRaises(LiteRTServerError):
			self.manager.delete_model("litert-community/gemma-4-E2B-it-litert-lm")

		# Cache must survive
		self.assertTrue(
			cache_path.exists(),
			"Cache should NOT be deleted after catalog failure",
		)

	# ── Cache-only model (no catalog entry) ──────────────────────

	def test_delete_cache_only_model(self) -> None:
		"""When the catalog dir does NOT exist, only cache deletion happens."""
		cache_path = self._make_cache_file("gemma-4-E2B-it.litertlm")
		cache_path.touch()
		self._set_no_catalog()

		self.manager.delete_model("litert-community/gemma-4-E2B-it-litert-lm")

		# CLI delete must NOT be called (nothing to unregister)
		self.mock_supervisor.delete_model.assert_not_called()
		# Cache must be deleted
		self.assertFalse(cache_path.exists())

	# ── Catalog-only model (no cache) ────────────────────────────

	def test_delete_catalog_only_model(self) -> None:
		"""When cache does not exist but catalog does, unregister succeeds."""
		self._make_cache_file("gemma-4-E2B-it.litertlm")
		# cache_path NOT touched → simulates "not in cache"
		self._make_catalog_dir("litert-community/gemma-4-E2B-it-litert-lm")

		# Should not raise
		self.manager.delete_model("litert-community/gemma-4-E2B-it-litert-lm")

		self.mock_supervisor.delete_model.assert_called_once_with(
			"litert-community/gemma-4-E2B-it-litert-lm"
		)

	# ── Neither exists (already deleted) ─────────────────────────

	def test_delete_neither_exists(self) -> None:
		"""Deleting an already-absent model should be a no-op."""
		self._make_cache_file("gemma-4-E2B-it.litertlm")
		# cache_path NOT touched
		self._set_no_catalog()

		# Should not raise
		self.manager.delete_model("litert-community/gemma-4-E2B-it-litert-lm")

		self.mock_supervisor.delete_model.assert_not_called()

	# ── Unknown model ID ─────────────────────────────────────────

	def test_delete_unknown_model_id(self) -> None:
		"""Deleting a model not in the catalog definitions should still
		attempt cache cleanup."""
		cache_path = self._make_cache_file("unknown-model.litertlm")
		cache_path.touch()

		# Unknown model → catalog_model_dir returns a possibly-nonexistent path
		self.mock_supervisor.catalog_model_dir.return_value = None

		self.manager.delete_model("unknown-model")

		# No catalog deletion (catalog_model_dir returned None)
		self.mock_supervisor.delete_model.assert_not_called()
		# Still called model_path for cache cleanup
		self.mock_download_svc.model_path.assert_called_once_with("unknown-model")

	# ── supervisor.catalog_model_dir returns None ─────────────────

	def test_delete_none_catalog_dir(self) -> None:
		"""When catalog_model_dir returns None, skip CLI delete."""
		cache_path = self._make_cache_file("gemma-4-E2B-it.litertlm")
		cache_path.touch()

		self.mock_supervisor.catalog_model_dir.return_value = None

		self.manager.delete_model(
			"litert-community/gemma-4-E2B-it-litert-lm"
		)

		self.mock_supervisor.delete_model.assert_not_called()


if __name__ == "__main__":
	unittest.main()
