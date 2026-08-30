"""Persistence recovery and secret-migration contracts."""

from __future__ import annotations

from pathlib import Path

import yaml

from tests.support import load_addon_module


yaml_store = load_addon_module("config.yaml_store", namespace="yaml_store_testpkg")


def _deterministic_crypto(monkeypatch) -> None:
	monkeypatch.setattr(yaml_store, "is_encrypted", lambda value: value.startswith("enc:"))
	monkeypatch.setattr(yaml_store, "encrypt_value", lambda value: f"enc:{value}")
	monkeypatch.setattr(yaml_store, "decrypt_value", lambda value: value.removeprefix("enc:"))


def test_corrupted_yaml_recovers_to_empty_configuration(tmp_path: Path) -> None:
	config_path = tmp_path / "config.yaml"
	config_path.write_text("aiAssistant: [unterminated", encoding="utf-8")

	store = yaml_store.YamlConfigStore(config_path)

	assert store.get("provider", "fallback") == "fallback"


def test_plaintext_secret_is_migrated_on_next_save(monkeypatch, tmp_path: Path) -> None:
	_deterministic_crypto(monkeypatch)
	config_path = tmp_path / "config.yaml"
	config_path.write_text(
		"aiAssistant:\n  openaiApiKey: legacy-plaintext\n  provider: openai\n",
		encoding="utf-8",
	)
	store = yaml_store.YamlConfigStore(config_path)
	assert store.get("openaiApiKey", "") == "legacy-plaintext"

	store.set("model", "example-model")

	raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))["aiAssistant"]
	assert raw["openaiApiKey"] == "enc:legacy-plaintext"
	assert raw["provider"] == "openai"
	assert raw["model"] == "example-model"


def test_encrypted_secret_is_transparently_decrypted(monkeypatch, tmp_path: Path) -> None:
	_deterministic_crypto(monkeypatch)
	config_path = tmp_path / "config.yaml"
	config_path.write_text('aiAssistant:\n  openaiApiKey: "enc:secret"\n', encoding="utf-8")

	store = yaml_store.YamlConfigStore(config_path)

	assert store.get("openaiApiKey", "") == "secret"
