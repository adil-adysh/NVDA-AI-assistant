# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TYPE_CHECKING

import languageHandler
from . import defaults
from .state import (
	ProviderState,
	_notify_provider_state_changed as _notify_provider_state_changed_impl,
	get_provider_state as _build_provider_state,
)
from .yaml_store import YamlConfigStore

if TYPE_CHECKING:
	from ..providers.config import GeminiConfig, LiteRTConfig, OllamaConfig, OpenAIConfig, ProviderConfig


_config_store = YamlConfigStore()


def _get_raw_setting(key: str, default: Any) -> Any:
	return _config_store.get(key, default)


def _set_value(key: str, value: Any, notify: bool = False) -> None:
	_config_store.set(key, value)
	if notify:
		_notify_provider_state_changed()


def _set_values(values: dict[str, Any], notify: bool = False) -> None:
	_config_store.set_many(values)
	if notify:
		_notify_provider_state_changed()


def save() -> None:
	"""Persist current configuration to storage."""
	_config_store.save()


def _read_string(key: str, default: str) -> str:
	value = _get_raw_setting(key, default)
	return value if isinstance(value, str) else default


def _parse_number(raw: Any, default: float) -> float:
	if isinstance(raw, bool):
		return default
	if isinstance(raw, int):
		return float(raw)
	if isinstance(raw, float):
		return raw
	if isinstance(raw, str):
		try:
			return float(raw.strip())
		except ValueError:
			return default
	return default


def _read_int(key: str, default: int, minimum: int | None = None) -> int:
	raw = _get_raw_setting(key, default)
	value = _parse_number(raw, default)
	try:
		result = int(value)
	except (TypeError, ValueError):
		return default
	if minimum is not None and result < minimum:
		return minimum
	return result


def _read_float(key: str, default: float, minimum: float | None = None) -> float:
	value = _parse_number(_get_raw_setting(key, default), default)
	if minimum is not None and value < minimum:
		return minimum
	return value


def _read_bool(key: str, default: bool) -> bool:
	value = _get_raw_setting(key, default)
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		normalized = value.strip().lower()
		if normalized in {"1", "true", "yes", "on"}:
			return True
		if normalized in {"0", "false", "no", "off"}:
			return False
	return default


def _notify_provider_state_changed() -> None:
	_notify_provider_state_changed_impl(get_provider_state)


def get_provider() -> str:
	"""Return the selected LLM provider."""
	return _read_string("provider", defaults.DEFAULT_PROVIDER).strip().lower()


def set_provider(provider: str) -> None:
	provider_value = str(provider or "").strip().lower()
	if provider_value not in {"ollama", "gemini", "openai", "litert-lm"}:
		raise ValueError(f"Unsupported provider: {provider}")
	_set_value("provider", provider_value, notify=True)


def get_language() -> str:
	"""Return the stored prompt language setting.

	This may be an explicit locale code or the automatic default value.
	"""
	return _read_string("language", defaults.DEFAULT_LANGUAGE).strip() or defaults.DEFAULT_LANGUAGE


def get_effective_language() -> str:
	"""Return the effective prompt language to use for prompt generation.

	If the stored setting is unset or set to the auto default, use NVDA's current UI language.
	"""
	language_value = get_language()
	if not language_value or language_value == defaults.DEFAULT_LANGUAGE:
		language_value = languageHandler.getLanguage() or "en"
	return language_value


def set_language(language: str) -> None:
	language_value = str(language or "").strip()
	if not language_value:
		language_value = defaults.DEFAULT_LANGUAGE
	_set_value("language", language_value, notify=False)


def get_ollama_model_name() -> str:
	return _read_string("ollamaModelName", defaults.DEFAULT_OLLAMA_MODEL)


def get_ollama_server_url() -> str:
	return _read_string("ollamaServerUrl", defaults.DEFAULT_OLLAMA_URL)


def get_ollama_think() -> bool:
	return _read_bool("ollamaThink", defaults.DEFAULT_OLLAMA_THINK)


def get_gemini_model_name() -> str:
	return _read_string("geminiModelName", defaults.DEFAULT_GEMINI_MODEL)


def get_gemini_api_key() -> str:
	return _read_string("geminiApiKey", "")


def get_gemini_api_token() -> str:
	return _read_string("geminiApiToken", "")


def get_gemini_base_url() -> str:
	return _read_string("geminiBaseUrl", defaults.DEFAULT_GEMINI_BASE_URL)


def get_openai_model_name() -> str:
	return _read_string("openaiModelName", defaults.DEFAULT_OPENAI_MODEL)


def get_openai_api_key() -> str:
	return _read_string("openaiApiKey", "")


def get_openai_base_url() -> str:
	return _read_string("openaiBaseUrl", defaults.DEFAULT_OPENAI_BASE_URL)


def get_openai_chat_path() -> str:
	return _read_string("openaiChatPath", defaults.DEFAULT_OPENAI_CHAT_PATH)


def get_litert_model_name() -> str:
	return _read_string("litertModelName", defaults.DEFAULT_LITERT_MODEL)


def get_litert_backend() -> str:
	return _read_string("litertBackend", defaults.DEFAULT_LITERT_BACKEND)


def get_openai_config() -> "OpenAIConfig":
	from ..providers.config import OpenAIConfig

	return OpenAIConfig(
		provider="openai",
		model_name=get_openai_model_name(),
		timeout_seconds=get_timeout_seconds(),
		enable_progress=is_progress_enabled(),
		num_ctx=get_num_ctx(),
		max_retries=get_max_retries(),
		retry_backoff_seconds=get_retry_backoff_seconds(),
		generate_temperature=get_generate_temperature(),
		generate_top_k=get_generate_top_k(),
		generate_top_p=get_generate_top_p(),
		generate_max_tokens=get_generate_max_tokens(),
		api_key=get_openai_api_key(),
		base_url=get_openai_base_url(),
		chat_path=get_openai_chat_path(),
		organization=None,
	)


def get_ollama_config() -> "OllamaConfig":
	from ..providers.config import OllamaConfig

	return OllamaConfig(
		provider="ollama",
		model_name=get_ollama_model_name(),
		timeout_seconds=get_timeout_seconds(),
		enable_progress=is_progress_enabled(),
		num_ctx=get_num_ctx(),
		max_retries=get_max_retries(),
		retry_backoff_seconds=get_retry_backoff_seconds(),
		generate_temperature=get_generate_temperature(),
		generate_top_k=get_generate_top_k(),
		generate_top_p=get_generate_top_p(),
		generate_max_tokens=get_generate_max_tokens(),
		generate_presence_penalty=get_generate_presence_penalty(),
		server_url=get_ollama_server_url(),
		keep_alive=get_keep_alive(),
		think=get_ollama_think(),
	)


def get_gemini_config() -> "GeminiConfig":
	from ..providers.config import GeminiConfig

	return GeminiConfig(
		provider="gemini",
		model_name=get_gemini_model_name(),
		timeout_seconds=get_timeout_seconds(),
		enable_progress=is_progress_enabled(),
		num_ctx=get_num_ctx(),
		max_retries=get_max_retries(),
		retry_backoff_seconds=get_retry_backoff_seconds(),
		generate_temperature=get_generate_temperature(),
		generate_top_k=get_generate_top_k(),
		generate_top_p=get_generate_top_p(),
		generate_max_tokens=get_generate_max_tokens(),
		api_key=get_gemini_api_key(),
		api_token=get_gemini_api_token(),
		base_url=get_gemini_base_url(),
	)


def get_litert_config() -> "LiteRTConfig":
	from ..providers.config import LiteRTConfig

	return LiteRTConfig(
		provider="litert-lm",
		model_name=get_litert_model_name(),
		timeout_seconds=get_timeout_seconds(),
		enable_progress=is_progress_enabled(),
		num_ctx=get_num_ctx(),
		max_retries=get_max_retries(),
		retry_backoff_seconds=get_retry_backoff_seconds(),
		generate_temperature=get_generate_temperature(),
		generate_top_k=get_generate_top_k(),
		generate_top_p=get_generate_top_p(),
		generate_max_tokens=get_generate_max_tokens(),
		backend=get_litert_backend(),
	)


def get_active_provider_config() -> "ProviderConfig":
	provider = get_provider()
	if provider == "gemini":
		return get_gemini_config()
	if provider == "openai":
		return get_openai_config()
	if provider == "litert-lm":
		return get_litert_config()
	return get_ollama_config()


def get_model_name() -> str:
	"""Return the configured model name for the selected provider."""
	return get_active_provider_config().model_name


def get_provider_state() -> "ProviderState":
	active = get_active_provider_config()
	return _build_provider_state(active)


def get_server_url() -> str:
	"""Return the configured backend URL for the selected provider."""
	from ..providers.config import GeminiConfig, LiteRTConfig, OllamaConfig

	active = get_active_provider_config()
	if isinstance(active, GeminiConfig):
		return active.base_url
	if isinstance(active, OllamaConfig):
		return active.server_url
	if isinstance(active, LiteRTConfig):
		return "local"
	return ""


def is_streaming_enabled() -> bool:
	"""Return whether AI response streaming is enabled."""
	return _read_bool("enableStreaming", defaults.DEFAULT_ENABLE_STREAMING)


def get_streaming_enabled() -> bool:
	"""Return whether AI response streaming is enabled."""
	return is_streaming_enabled()


def is_streaming_tone_enabled() -> bool:
	"""Return whether streaming tone feedback is enabled."""
	return _read_bool("enableStreamingTone", defaults.DEFAULT_ENABLE_STREAMING_TONE)


def get_streaming_tone_enabled() -> bool:
	"""Return whether streaming tone feedback is enabled."""
	return is_streaming_tone_enabled()


def set_streaming_tone_enabled(value: bool) -> None:
	_set_value("enableStreamingTone", bool(value))


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


def get_generate_max_tokens() -> int:
	return _read_int("generateMaxTokens", defaults.DEFAULT_GENERATE_MAX_TOKENS, minimum=1)


def get_generate_presence_penalty() -> float:
	return _read_float("generatePresencePenalty", defaults.DEFAULT_GENERATE_PRESENCE_PENALTY)


def get_image_max_side() -> int:
	return _read_int("imageMaxSide", defaults.DEFAULT_IMAGE_MAX_SIDE, minimum=128)


def get_image_format() -> str:
	image_format = _read_string("imageFormat", defaults.DEFAULT_IMAGE_FORMAT).strip().upper()
	return image_format if image_format in {"PNG", "JPEG"} else defaults.DEFAULT_IMAGE_FORMAT


def get_image_quality() -> int:
	return _read_int("imageQuality", defaults.DEFAULT_IMAGE_QUALITY, minimum=1)


def get_request_metrics_logging_enabled() -> bool:
	return _read_bool("requestMetricsLoggingEnabled", defaults.DEFAULT_REQUEST_METRICS_LOGGING)


def get_request_metrics_log_path() -> str:
	path = _read_string("requestMetricsLogPath", defaults.DEFAULT_REQUEST_METRICS_LOG_PATH)
	resolved = Path(path).expanduser()
	if resolved.is_absolute():
		return str(resolved)

	appdata_path = Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming") / "nvda"
	return str((appdata_path / resolved).resolve())


def set_ollama_model_name(modelName: str) -> None:
	_set_value("ollamaModelName", str(modelName).strip(), notify=True)


def set_ollama_server_url(serverUrl: str) -> None:
	_set_value("ollamaServerUrl", str(serverUrl).strip(), notify=True)


def set_ollama_think(think: bool) -> None:
	_set_value("ollamaThink", bool(think), notify=True)


def set_gemini_model_name(modelName: str) -> None:
	_set_value("geminiModelName", str(modelName).strip(), notify=True)


def set_gemini_api_key(apiKey: str) -> None:
	_set_value("geminiApiKey", str(apiKey).strip())


def set_gemini_api_token(apiToken: str | None) -> None:
	_set_value("geminiApiToken", str(apiToken or "").strip())


def set_litert_model_name(modelName: str) -> None:
	_set_value("litertModelName", str(modelName).strip(), notify=True)


def set_litert_backend(backend: str) -> None:
	_set_value("litertBackend", str(backend).strip().lower(), notify=True)


def set_litert_config(config: LiteRTConfig) -> None:
	_set_values(
		{
			"provider": config.provider,
			"litertModelName": config.model_name,
			"litertBackend": config.backend,
			"timeoutSeconds": config.timeout_seconds,
			"numCtx": config.num_ctx,
			"maxRetries": config.max_retries,
			"retryBackoffSeconds": config.retry_backoff_seconds,
			"generateTemperature": config.generate_temperature,
			"generateTopK": config.generate_top_k,
			"generateTopP": config.generate_top_p,
			"generateMaxTokens": config.generate_max_tokens,
			"enableProgressAnnouncements": config.enable_progress,
		},
		notify=False,
	)
	_notify_provider_state_changed()


def set_gemini_base_url(baseUrl: str) -> None:
	_set_value("geminiBaseUrl", str(baseUrl).strip(), notify=True)


def set_ollama_config(config: OllamaConfig) -> None:
	_set_values(
		{
			"provider": config.provider,
			"ollamaModelName": config.model_name,
			"ollamaServerUrl": config.server_url,
			"ollamaThink": config.think,
			"timeoutSeconds": config.timeout_seconds,
			"numCtx": config.num_ctx,
			"keepAlive": config.keep_alive,
			"maxRetries": config.max_retries,
			"retryBackoffSeconds": config.retry_backoff_seconds,
			"generateTemperature": config.generate_temperature,
			"generateTopK": config.generate_top_k,
			"generateTopP": config.generate_top_p,
			"generateMaxTokens": config.generate_max_tokens,
			"generatePresencePenalty": config.generate_presence_penalty,
			"enableProgressAnnouncements": config.enable_progress,
		},
		notify=False,
	)
	_notify_provider_state_changed()


def set_gemini_config(config: GeminiConfig) -> None:
	_set_values(
		{
			"provider": config.provider,
			"geminiModelName": config.model_name,
			"geminiApiKey": config.api_key,
			"geminiApiToken": str(config.api_token or "").strip(),
			"geminiBaseUrl": config.base_url,
			"timeoutSeconds": config.timeout_seconds,
			"numCtx": config.num_ctx,
			"maxRetries": config.max_retries,
			"retryBackoffSeconds": config.retry_backoff_seconds,
			"generateTemperature": config.generate_temperature,
			"generateTopK": config.generate_top_k,
			"generateTopP": config.generate_top_p,
			"generateMaxTokens": config.generate_max_tokens,
			"enableProgressAnnouncements": config.enable_progress,
		},
		notify=False,
	)
	_notify_provider_state_changed()


def set_openai_config(config: OpenAIConfig) -> None:
	_set_values(
		{
			"provider": config.provider,
			"openaiModelName": config.model_name,
			"openaiApiKey": config.api_key,
			"openaiBaseUrl": config.base_url,
			"openaiChatPath": config.chat_path,
			"timeoutSeconds": config.timeout_seconds,
			"numCtx": config.num_ctx,
			"maxRetries": config.max_retries,
			"retryBackoffSeconds": config.retry_backoff_seconds,
			"generateTemperature": config.generate_temperature,
			"generateTopK": config.generate_top_k,
			"generateTopP": config.generate_top_p,
			"generateMaxTokens": config.generate_max_tokens,
			"enableProgressAnnouncements": config.enable_progress,
		},
		notify=False,
	)
	_notify_provider_state_changed()


def set_model_name(modelName: str) -> None:
	provider = get_provider()
	if provider == "gemini":
		set_gemini_model_name(modelName)
	elif provider == "openai":
		_set_value("openaiModelName", str(modelName).strip(), notify=True)
	else:
		set_ollama_model_name(modelName)


def set_server_url(serverUrl: str) -> None:
	if get_provider() == "gemini":
		set_gemini_base_url(serverUrl)
	else:
		set_ollama_server_url(serverUrl)


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


def set_generate_max_tokens(generateMaxTokens: int) -> None:
	_set_value("generateMaxTokens", int(generateMaxTokens))


def set_generate_top_p(generateTopP: float) -> None:
	_set_value("generateTopP", float(generateTopP))


def set_generate_presence_penalty(generatePresencePenalty: float) -> None:
	_set_value("generatePresencePenalty", float(generatePresencePenalty))


def set_image_max_side(imageMaxSide: int) -> None:
	_set_value("imageMaxSide", int(imageMaxSide))


def set_image_format(imageFormat: str) -> None:
	_set_value("imageFormat", str(imageFormat).strip().upper())


def set_image_quality(imageQuality: int) -> None:
	_set_value("imageQuality", int(imageQuality))


def set_request_metrics_logging_enabled(enabled: bool) -> None:
	_set_value("requestMetricsLoggingEnabled", bool(enabled))


def set_request_metrics_log_path(path: str) -> None:
	_set_value("requestMetricsLogPath", str(path).strip())
