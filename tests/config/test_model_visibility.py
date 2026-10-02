"""Tests for ModelVisibilityStore preference persistence and migration."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from tests.support import load_addon_module


enabled_models = load_addon_module("config.enabled_models", namespace="model_visibility_testpkg")
ModelVisibilityStore = enabled_models.ModelVisibilityStore


def test_default_visibility_new_models(tmp_path: Path) -> None:
	"""All newly discovered models are visible by default."""
	store = ModelVisibilityStore(path=tmp_path / "model_visibility.json")
	assert store.is_model_visible("litert-lm", "gemma-4-e2b-cpu")
	assert store.is_model_visible("litert-lm", "gemma-4-e4b-gpu")

	candidates = ("gemma-4-e2b-cpu", "gemma-4-e4b-gpu", "custom-model")
	visible = store.get_visible_models("litert-lm", candidates)
	assert visible == candidates


def test_explicitly_disabling_model_persists(tmp_path: Path) -> None:
	"""An explicitly disabled model remains disabled and is persisted to disk."""
	store_path = tmp_path / "model_visibility.json"
	store1 = ModelVisibilityStore(path=store_path)

	store1.set_model_visible("litert-lm", "gemma-4-e2b-gpu", False)
	assert not store1.is_model_visible("litert-lm", "gemma-4-e2b-gpu")
	assert store1.is_model_visible("litert-lm", "gemma-4-e2b-cpu")

	# Verify on-disk persistence with a brand new store instance
	store2 = ModelVisibilityStore(path=store_path)
	assert not store2.is_model_visible("litert-lm", "gemma-4-e2b-gpu")
	assert store2.is_model_visible("litert-lm", "gemma-4-e2b-cpu")

	visible = store2.get_visible_models("litert-lm", ["gemma-4-e2b-cpu", "gemma-4-e2b-gpu"])
	assert visible == ("gemma-4-e2b-cpu",)


def test_disabling_all_models_persists_and_does_not_fallback(tmp_path: Path) -> None:
	"""Disabling all models persists and does NOT fallback to 'first run' / show all."""
	store_path = tmp_path / "model_visibility.json"
	store = ModelVisibilityStore(path=store_path)

	store.set_model_visible("ollama", "llama3:latest", False)
	store.set_model_visible("ollama", "mistral:latest", False)

	visible = store.get_visible_models("ollama", ["llama3:latest", "mistral:latest"])
	assert visible == ()

	# Reload from disk
	reloaded = ModelVisibilityStore(path=store_path)
	assert reloaded.get_visible_models("ollama", ["llama3:latest", "mistral:latest"]) == ()


def test_newly_discovered_models_do_not_re_enable_disabled_models(tmp_path: Path) -> None:
	"""Newly discovered models are visible, but previously disabled models stay disabled."""
	store_path = tmp_path / "model_visibility.json"
	store = ModelVisibilityStore(path=store_path)

	store.set_model_visible("gemini", "gemini-1.5-pro", False)

	# A new model gemini-2.5-flash is now discovered
	candidates = ("gemini-1.5-pro", "gemini-2.5-flash")
	visible = store.get_visible_models("gemini", candidates)

	assert visible == ("gemini-2.5-flash",)
	assert not store.is_model_visible("gemini", "gemini-1.5-pro")
	assert store.is_model_visible("gemini", "gemini-2.5-flash")


def test_re_enabling_previously_disabled_model(tmp_path: Path) -> None:
	"""A disabled model can be re-enabled and appears in visible models again."""
	store_path = tmp_path / "model_visibility.json"
	store = ModelVisibilityStore(path=store_path)

	store.set_model_visible("litert-lm", "gemma-4-e2b-cpu", False)
	assert not store.is_model_visible("litert-lm", "gemma-4-e2b-cpu")

	store.set_model_visible("litert-lm", "gemma-4-e2b-cpu", True)
	assert store.is_model_visible("litert-lm", "gemma-4-e2b-cpu")
	assert store.get_visible_models("litert-lm", ["gemma-4-e2b-cpu"]) == ("gemma-4-e2b-cpu",)


def test_legacy_migration_from_enabled_models_json(tmp_path: Path) -> None:
	"""Migrates legacy enabled_models.json smoothly when model_visibility.json does not exist."""
	legacy_path = tmp_path / "enabled_models.json"
	legacy_path.write_text(
		json.dumps({"litert-lm": ["gemma-4-e2b-cpu"]}),
		encoding="utf-8",
	)
	store_path = tmp_path / "model_visibility.json"
	store = ModelVisibilityStore(path=store_path, legacy_path=legacy_path)

	# In legacy mode, explicit enabled list was gemma-4-e2b-cpu
	assert store.get_enabled("litert-lm") == {"gemma-4-e2b-cpu"}


def test_corrupted_json_recovery(tmp_path: Path) -> None:
	"""Corrupted or malformed store file does not crash the application."""
	store_path = tmp_path / "model_visibility.json"
	store_path.write_text("{corrupt json[", encoding="utf-8")

	store = ModelVisibilityStore(path=store_path)
	# Should recover to empty preferences (all models visible by default)
	assert store.is_model_visible("litert-lm", "any-model")
	assert store.get_visible_models("litert-lm", ["model1", "model2"]) == ("model1", "model2")


def test_concurrent_visibility_updates(tmp_path: Path) -> None:
	"""Concurrent reads and writes from multiple threads remain consistent."""
	store_path = tmp_path / "model_visibility.json"
	store = ModelVisibilityStore(path=store_path)

	def toggle_worker(model_idx: int) -> None:
		for _ in range(20):
			store.set_model_visible("test-prov", f"m-{model_idx}", False)
			store.set_model_visible("test-prov", f"m-{model_idx}", True)

	threads = [threading.Thread(target=toggle_worker, args=(i,)) for i in range(5)]
	for t in threads:
		t.start()
	for t in threads:
		t.join(timeout=5.0)
		assert not t.is_alive()

	# Store should be in a valid readable state
	assert isinstance(store.get_disabled_models("test-prov"), set)
