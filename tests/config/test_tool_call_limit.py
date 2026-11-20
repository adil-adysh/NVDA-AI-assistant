import pytest

from tests.support import load_addon_module

settings = load_addon_module("config.settings", namespace="tool_limit_settings_tests")
store = load_addon_module("config.yaml_store", namespace="tool_limit_settings_tests")


@pytest.mark.parametrize("value", [None, True, "100", 0, -1, 1001, 1.5])
def test_invalid_saved_limit_uses_default(tmp_path, monkeypatch, value):
	config = store.YamlConfigStore(path=tmp_path / "settings.yaml")
	config.set("maxToolCalls", value)
	monkeypatch.setattr(settings, "_config_store", config)
	assert settings.get_max_tool_calls() == 100


@pytest.mark.parametrize("value", [1, 100, 1000])
def test_limit_persists_and_rejects_invalid_values(tmp_path, monkeypatch, value):
	path = tmp_path / "settings.yaml"
	monkeypatch.setattr(settings, "_config_store", store.YamlConfigStore(path=path))
	settings.set_max_tool_calls(value)
	monkeypatch.setattr(settings, "_config_store", store.YamlConfigStore(path=path))
	assert settings.get_max_tool_calls() == value
	for invalid in (True, 0, 1001, "4", 1.5):
		with pytest.raises(ValueError):
			settings.set_max_tool_calls(invalid)
	assert settings.get_max_tool_calls() == value
