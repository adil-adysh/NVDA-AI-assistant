import pytest

from tests.support import load_addon_module


settings = load_addon_module('config.settings', namespace='one_shot_settings_tests')
store = load_addon_module('config.yaml_store', namespace='one_shot_settings_tests')


@pytest.mark.parametrize('value', [None, '', 'unknown', 42])
def test_missing_or_invalid_output_setting_defaults_to_display(tmp_path, monkeypatch, value):
	config = store.YamlConfigStore(path=tmp_path / 'config.yaml')
	if value is not None:
		config.set('oneShotOutputMode', value)
	monkeypatch.setattr(settings, '_config_store', config)
	assert settings.get_one_shot_output_mode() == 'display_only'


@pytest.mark.parametrize('mode', ['speak_then_display', 'display_only', 'speak_only'])
def test_output_choice_survives_yaml_reload(tmp_path, monkeypatch, mode):
	path = tmp_path / 'config.yaml'
	monkeypatch.setattr(settings, '_config_store', store.YamlConfigStore(path=path))
	settings.set_one_shot_output_mode(mode)
	settings.save()
	monkeypatch.setattr(settings, '_config_store', store.YamlConfigStore(path=path))
	assert settings.get_one_shot_output_mode() == mode
	with pytest.raises(ValueError):
		settings.set_one_shot_output_mode('invalid')
	assert settings.get_one_shot_output_mode() == mode


def test_chat_preferences_have_independent_defaults_and_persist(tmp_path, monkeypatch):
	path = tmp_path / 'chat.yaml'
	monkeypatch.setattr(settings, '_config_store', store.YamlConfigStore(path=path))
	assert settings.get_chat_auto_read() is False
	assert settings.get_chat_status_announcements() is True
	settings.set_chat_auto_read(True)
	settings.set_chat_status_announcements(False)
	monkeypatch.setattr(settings, '_config_store', store.YamlConfigStore(path=path))
	assert settings.get_chat_auto_read() is True
	assert settings.get_chat_status_announcements() is False
