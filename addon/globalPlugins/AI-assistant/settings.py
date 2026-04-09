# -*- coding: utf-8 -*-
from typing import Any

import config as nvda_config

from . import defaults


def _get_ai_assistant_section() -> Any:
    conf = getattr(nvda_config, "conf", None)
    if conf is None:
        return None

    if hasattr(conf, "get"):
        section = conf.get("aiAssistant")
    else:
        try:
            section = conf["aiAssistant"]
        except Exception:
            section = None

    return section


def _ensure_ai_assistant_section() -> Any:
    conf = getattr(nvda_config, "conf", None)
    if conf is None:
        return None

    section = _get_ai_assistant_section()
    if section is None:
        conf["aiAssistant"] = {}
        section = _get_ai_assistant_section()
    return section


def _set_value(key: str, value: Any) -> None:
    section = _ensure_ai_assistant_section()
    if section is None:
        return

    try:
        section[key] = value
    except Exception:
        if isinstance(section, dict):
            section[key] = value


def _read_string(key: str, default: str) -> str:
    section = _get_ai_assistant_section()
    if section is None:
        return default

    if isinstance(section, dict):
        value = section.get(key)
    elif hasattr(section, "get"):
        value = section.get(key)
    else:
        try:
            value = section[key]
        except Exception:
            value = None

    return value if isinstance(value, str) else default


def _read_bool(key: str, default: bool) -> bool:
    section = _get_ai_assistant_section()
    if section is None:
        return default

    if isinstance(section, dict):
        value = section.get(key)
    elif hasattr(section, "get"):
        value = section.get(key)
    else:
        try:
            value = section[key]
        except Exception:
            value = None

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def get_model_name() -> str:
    """Return the configured Ollama model name."""
    return _read_string("modelName", defaults.DEFAULT_OLLAMA_MODEL)


def get_server_url() -> str:
    """Return the configured Ollama server URL."""
    return _read_string("serverUrl", defaults.DEFAULT_OLLAMA_URL)


def is_streaming_enabled() -> bool:
    """Return whether AI response streaming is enabled."""
    return _read_bool("enableStreaming", defaults.DEFAULT_ENABLE_STREAMING)


def is_progress_enabled() -> bool:
    """Return whether progress announcements are enabled."""
    return _read_bool("enableProgressAnnouncements", defaults.DEFAULT_ENABLE_PROGRESS_ANNOUNCEMENTS)


def set_model_name(modelName: str) -> None:
    _set_value("modelName", str(modelName).strip())


def set_server_url(serverUrl: str) -> None:
    _set_value("serverUrl", str(serverUrl).strip())


def set_streaming_enabled(enabled: bool) -> None:
    _set_value("enableStreaming", bool(enabled))


def set_progress_enabled(enabled: bool) -> None:
    _set_value("enableProgressAnnouncements", bool(enabled))


def save() -> None:
    conf = getattr(nvda_config, "conf", None)
    if conf is not None and hasattr(conf, "save"):
        conf.save()
