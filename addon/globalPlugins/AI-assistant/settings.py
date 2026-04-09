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


def _read_int(key: str, default: int, minimum: int | None = None) -> int:
    section = _get_ai_assistant_section()
    if section is None:
        return default

    if isinstance(section, dict):
        raw = section.get(key)
    elif hasattr(section, "get"):
        raw = section.get(key)
    else:
        try:
            raw = section[key]
        except Exception:
            raw = None

    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        try:
            value = int(raw.strip())
        except ValueError:
            return default
    else:
        return default

    if minimum is not None and value < minimum:
        return minimum
    return value


def _read_float(key: str, default: float, minimum: float | None = None) -> float:
    section = _get_ai_assistant_section()
    if section is None:
        return default

    if isinstance(section, dict):
        raw = section.get(key)
    elif hasattr(section, "get"):
        raw = section.get(key)
    else:
        try:
            raw = section[key]
        except Exception:
            raw = None

    if isinstance(raw, float):
        value = raw
    elif isinstance(raw, int):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw.strip())
        except ValueError:
            return default
    else:
        return default

    if minimum is not None and value < minimum:
        return minimum
    return value


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


def get_streaming_enabled() -> bool:
    """Return whether AI response streaming is enabled."""
    return is_streaming_enabled()


def is_progress_enabled() -> bool:
    """Return whether progress announcements are enabled."""
    return _read_bool("enableProgressAnnouncements", defaults.DEFAULT_ENABLE_PROGRESS_ANNOUNCEMENTS)


def get_progress_enabled() -> bool:
    """Return whether progress announcements are enabled."""
    return is_progress_enabled()


def get_timeout_seconds() -> float:
    return _read_float("timeoutSeconds", defaults.DEFAULT_TIMEOUT_SECONDS, minimum=1)


def get_num_ctx() -> int:
    return _read_int("numCtx", defaults.DEFAULT_NUM_CTX, minimum=256)


def get_keep_alive() -> str:
    return _read_string("keepAlive", defaults.DEFAULT_KEEP_ALIVE)


def get_max_retries() -> int:
    return _read_int("maxRetries", defaults.DEFAULT_MAX_RETRIES, minimum=0)


def get_retry_backoff_seconds() -> float:
    return _read_float("retryBackoffSeconds", defaults.DEFAULT_RETRY_BACKOFF_SECONDS, minimum=0)


def get_generate_temperature() -> float:
    return _read_float("generateTemperature", defaults.DEFAULT_GENERATE_TEMPERATURE, minimum=0.0)


def get_generate_top_k() -> int:
    return _read_int("generateTopK", defaults.DEFAULT_GENERATE_TOP_K, minimum=0)


def get_generate_top_p() -> float:
    return _read_float("generateTopP", defaults.DEFAULT_GENERATE_TOP_P, minimum=0.0)


def get_generate_presence_penalty() -> float:
    return _read_float("generatePresencePenalty", defaults.DEFAULT_GENERATE_PRESENCE_PENALTY)


def set_model_name(modelName: str) -> None:
    _set_value("modelName", str(modelName).strip())


def set_server_url(serverUrl: str) -> None:
    _set_value("serverUrl", str(serverUrl).strip())


def set_streaming_enabled(enabled: bool) -> None:
    _set_value("enableStreaming", bool(enabled))


def set_progress_enabled(enabled: bool) -> None:
    _set_value("enableProgressAnnouncements", bool(enabled))


def set_timeout_seconds(timeoutSeconds: float) -> None:
    _set_value("timeoutSeconds", float(timeoutSeconds))


def set_num_ctx(numCtx: int) -> None:
    _set_value("numCtx", int(numCtx))


def set_keep_alive(keepAlive: str) -> None:
    _set_value("keepAlive", str(keepAlive).strip())


def set_max_retries(maxRetries: int) -> None:
    _set_value("maxRetries", int(maxRetries))


def set_retry_backoff_seconds(retryBackoffSeconds: float) -> None:
    _set_value("retryBackoffSeconds", float(retryBackoffSeconds))


def set_generate_temperature(generateTemperature: float) -> None:
    _set_value("generateTemperature", float(generateTemperature))


def set_generate_top_k(generateTopK: int) -> None:
    _set_value("generateTopK", int(generateTopK))


def set_generate_top_p(generateTopP: float) -> None:
    _set_value("generateTopP", float(generateTopP))


def set_generate_presence_penalty(generatePresencePenalty: float) -> None:
    _set_value("generatePresencePenalty", float(generatePresencePenalty))


def save() -> None:
    conf = getattr(nvda_config, "conf", None)
    if conf is not None and hasattr(conf, "save"):
        conf.save()
