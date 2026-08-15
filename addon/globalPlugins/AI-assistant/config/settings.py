# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TYPE_CHECKING

import languageHandler
from . import defaults
from .state import (
	ProviderState,
	_notify_llama_server_config_changed as _notify_llama_server_config_changed_impl,
	_notify_litert_server_config_changed as _notify_litert_server_config_changed_impl,
	_notify_provider_state_changed as _notify_provider_state_changed_impl,
	get_provider_state as _build_provider_state,
)
from .yaml_store import YamlConfigStore
from .provider_specs import get_provider_config_spec, get_provider_ids

if TYPE_CHECKING:
	from ..providers.config import OpenAICompatConfig, ProviderConfig


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


def _notify_litert_server_config_changed() -> None:
	_notify_litert_server_config_changed_impl()


def _notify_llama_server_config_changed() -> None:
	_notify_llama_server_config_changed_impl()


def get_provider() -> str:
	"""Return the selected LLM provider."""
	return _read_string("provider", defaults.DEFAULT_PROVIDER).strip().lower()


def get_embedding_model() -> str:
	return _read_string("embeddingModel", defaults.DEFAULT_EMBEDDING_MODEL).strip()


def get_embedding_enabled() -> bool:
	return bool(_get_raw_setting("embeddingEnabled", defaults.DEFAULT_EMBEDDING_ENABLED))


def get_embedding_page_summary_enabled() -> bool:
	return bool(_get_raw_setting("embeddingPageSummaryEnabled", defaults.DEFAULT_EMBEDDING_PAGE_SUMMARY_ENABLED))


def get_embedding_page_chat_enabled() -> bool:
	return bool(_get_raw_setting("embeddingPageChatEnabled", defaults.DEFAULT_EMBEDDING_PAGE_CHAT_ENABLED))


def get_embedding_conversation_memory_enabled() -> bool:
	return bool(_get_raw_setting("embeddingConversationMemoryEnabled", defaults.DEFAULT_EMBEDDING_CONVERSATION_MEMORY_ENABLED))


def set_embedding_model(model_id: str) -> None:
	model_id = str(model_id).strip()
	if not model_id:
		raise ValueError("Embedding model cannot be empty")
	_set_value("embeddingModel", model_id)


def set_embedding_enabled(enabled: bool) -> None:
	_set_value("embeddingEnabled", bool(enabled))


def set_embedding_page_summary_enabled(enabled: bool) -> None:
	_set_value("embeddingPageSummaryEnabled", bool(enabled))


def set_embedding_page_chat_enabled(enabled: bool) -> None:
	_set_value("embeddingPageChatEnabled", bool(enabled))


def set_embedding_conversation_memory_enabled(enabled: bool) -> None:
	_set_value("embeddingConversationMemoryEnabled", bool(enabled))


def set_provider(provider: str) -> None:
	provider_value = str(provider or "").strip().lower()
	if provider_value not in get_provider_ids() | {"openai_compat"}:
		raise ValueError(f"Unsupported provider: {provider}")
	_set_value("provider", provider_value, notify=True)


def get_enabled_providers() -> list[str]:
	"""Return the list of enabled provider IDs."""
	raw = _get_raw_setting("enabledProviders", None)
	if isinstance(raw, list) and raw:
		known = get_provider_ids()
		return [str(p).strip().lower() for p in raw if str(p).strip().lower() in known]
	return list(defaults.DEFAULT_ENABLED_PROVIDERS)


def set_enabled_providers(providers: list[str]) -> None:
	"""Persist the list of enabled provider IDs."""
	known = get_provider_ids()
	valid = [str(p).strip().lower() for p in providers if str(p).strip().lower() in known]
	if not valid:
		valid = ["ollama"]  # at least one must be enabled
	_set_value("enabledProviders", valid, notify=True)


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


# ---------------------------------------------------------------------------
# Unified per-provider property getters (backward-compatible YAML keys)
# ---------------------------------------------------------------------------

def _get_model_name_for(provider: str) -> str:
	"""Read the model name for a given provider from its legacy YAML key."""
	spec = get_provider_config_spec(provider)
	if spec is None:
		return ""
	return _read_string(spec.model_key, spec.model_default)


def _get_base_url_for(provider: str) -> str:
	"""Read the base URL for a given provider from its legacy YAML key."""
	spec = get_provider_config_spec(provider)
	if spec is None:
		return ""
	return _read_string(spec.base_url_key, spec.base_url_default).rstrip("/")


def _get_api_key_for(provider: str) -> str:
	"""Read the API key for a given provider from its legacy YAML key."""
	spec = get_provider_config_spec(provider)
	return _read_string(spec.api_key_key, "") if spec and spec.api_key_key else ""


def _get_think_for(provider: str, model_id: str | None = None) -> bool:
	"""Read the per-model thinking toggle; thinking is disabled by default."""
	if not model_id:
		return False
	from .model_config import get_model_thinking
	return get_model_thinking(provider, model_id)


# ---------------------------------------------------------------------------
# Legacy getter aliases (kept for backward compat during migration)
# ---------------------------------------------------------------------------

def get_ollama_model_name() -> str:
	return _get_model_name_for("ollama")

def get_ollama_server_url() -> str:
	return _get_base_url_for("ollama")

def get_gemini_model_name() -> str:
	return _get_model_name_for("gemini")

def get_gemini_api_key() -> str:
	return _get_api_key_for("gemini")

def get_gemini_api_token() -> str:
	return _read_string("geminiApiToken", "")

def get_gemini_base_url() -> str:
	return _get_base_url_for("gemini")

def get_openai_model_name() -> str:
	return _get_model_name_for("openai")

def get_openai_api_key() -> str:
	return _get_api_key_for("openai")

def get_openai_base_url() -> str:
	return _get_base_url_for("openai")

def get_openai_chat_path() -> str:
	return _read_string("openaiChatPath", defaults.DEFAULT_OPENAI_CHAT_PATH)

def get_litert_model_name() -> str:
	return _get_model_name_for("litert-lm")

def get_litert_server_url() -> str:
	return _get_base_url_for("litert-lm")

def get_litert_backend() -> str:
	"""Return the LiteRT-LM compute backend, or ``""`` when left at the default.

	``""`` means "let litert-lm decide" — no ``backend`` key is written to
	``config.json``.  Non-default values: ``'cpu'``, ``'gpu'``, ``'npu'``.
	"""
	value = _read_string(
		"litertBackend", defaults.DEFAULT_LITERT_BACKEND
	).strip().lower()
	if value in {"cpu", "gpu", "npu"}:
		return value
	return ""


def get_litert_cache() -> str:
	"""Return the LiteRT-LM cache policy, or ``""`` when left at the default.

	``""`` means "let litert-lm decide" — no ``cache`` key is written to
	``config.json``.  Non-default values: ``'disk'``, ``'memory'``, ``'no'``.
	"""
	value = _read_string(
		"litertCache", defaults.DEFAULT_LITERT_CACHE
	).strip().lower()
	if value in {"disk", "memory", "no"}:
		return value
	return ""


def get_litert_cpu_threads() -> int:
	"""Return the LiteRT-LM CPU thread count; ``0`` means let the runtime decide."""
	return _read_int(
		"litertCpuThreads", defaults.DEFAULT_LITERT_CPU_THREADS, minimum=0
	)


def get_litert_start_on_startup() -> bool:
	"""Return whether the active LiteRT-LM server starts with the add-on."""
	return _read_bool(
		"litertStartOnStartup", defaults.DEFAULT_LITERT_START_ON_STARTUP
	)


def get_llama_start_on_startup() -> bool:
	"""Return whether the active llama-server starts with the add-on."""
	return _read_bool(
		"llamaStartOnStartup", defaults.DEFAULT_LLAMA_START_ON_STARTUP
	)


def _get_openai_endpoint_paths(provider: str) -> tuple[str, str]:
	"""Return the OpenAI-compatible endpoint paths for *provider*."""
	spec = get_provider_config_spec(provider)
	if spec is None:
		raise ValueError(f"Unsupported provider: {provider}")
	chat_path = (
		_read_string(spec.chat_path_key, spec.chat_path_default)
		if spec.chat_path_key
		else spec.chat_path_default
	)
	return chat_path, spec.models_path


# ---------------------------------------------------------------------------
# Unified config builder
# ---------------------------------------------------------------------------

def build_provider_config(provider: str) -> "OpenAICompatConfig":
	"""Build a unified ``OpenAICompatConfig`` for *provider* from its YAML keys.

	Unlike :func:`get_openai_compat_config` (which always returns the
	config for the *active* provider), this builds the config for any
	provider by reading its own per-provider YAML keys.  This is needed
	by the model manager dialog, which manages providers other than the
	active one.
	"""
	from ..providers.config import OpenAICompatConfig

	spec = get_provider_config_spec(provider)
	if spec is None:
		raise ValueError(f"Unsupported provider: {provider}")
	model_name = _get_model_name_for(provider)
	chat_path, models_path = _get_openai_endpoint_paths(provider)
	return OpenAICompatConfig(
		provider=str(provider).strip().lower(),
		model_name=model_name,
		base_url=_get_base_url_for(provider),
		api_key=_get_api_key_for(provider),
		api_token=_read_string(spec.api_token_key, "") if spec.api_token_key else None,
		chat_path=chat_path,
		models_path=models_path,
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
		think=_get_think_for(provider, model_name),
		litert_backend=get_litert_backend() if spec.litert_engine_settings else "",
		litert_cache=get_litert_cache() if spec.litert_engine_settings else "",
		litert_cpu_threads=get_litert_cpu_threads() if spec.litert_engine_settings else 0,
		server_executable=(
			_read_string(spec.executable_key, spec.executable_default)
			if spec.executable_key else ""
		),
		models_preset=(
			_read_string(spec.models_preset_key, spec.models_preset_default)
			if spec.models_preset_key else ""
		),
	)


def get_openai_compat_config() -> "OpenAICompatConfig":
	"""Build a unified OpenAICompatConfig from the active provider's YAML keys."""
	return build_provider_config(get_provider())


# Legacy config builders (dispatch to unified)
def get_openai_config() -> "OpenAICompatConfig":
	return get_openai_compat_config()

def get_ollama_config() -> "OpenAICompatConfig":
	return get_openai_compat_config()

def get_gemini_config() -> "OpenAICompatConfig":
	return get_openai_compat_config()

def get_litert_config() -> "OpenAICompatConfig":
	return get_openai_compat_config()


def get_active_provider_config() -> "ProviderConfig":
	return get_openai_compat_config()


def get_model_name() -> str:
	"""Return the configured model name for the selected provider."""
	return get_active_provider_config().model_name


def get_provider_state() -> "ProviderState":
	active = get_active_provider_config()
	return _build_provider_state(active)


def get_server_url() -> str:
	"""Return the configured backend URL for the selected provider."""
	return _get_base_url_for(get_provider())


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


def get_image_mime_type() -> str:
	"""Return the MIME type matching the configured image format.

	The declared MIME must match the bytes produced by ``ImagePreprocessor``,
	which encodes captures in ``get_image_format()`` (PNG or JPEG).
	"""
	return "image/jpeg" if get_image_format() == "JPEG" else "image/png"


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


def set_gemini_model_name(modelName: str) -> None:
	_set_value("geminiModelName", str(modelName).strip(), notify=True)


def set_gemini_api_key(apiKey: str) -> None:
	_set_value("geminiApiKey", str(apiKey).strip())


def set_gemini_api_token(apiToken: str | None) -> None:
	_set_value("geminiApiToken", str(apiToken or "").strip())


def set_litert_model_name(modelName: str) -> None:
	_set_value("litertModelName", str(modelName).strip(), notify=True)
	_notify_litert_server_config_changed()


def set_litert_server_url(serverUrl: str) -> None:
	_set_value("litertServerUrl", str(serverUrl).strip().rstrip("/"), notify=True)
	_notify_litert_server_config_changed()


def set_litert_backend(backend: str) -> None:
	"""Persist the LiteRT compute backend; anything invalid or ``"default"`` → ``""``."""
	value = str(backend or "").strip().lower()
	_set_value(
		"litertBackend",
		value if value in {"cpu", "gpu", "npu"} else "",
		notify=True,
	)
	_notify_litert_server_config_changed()


def set_litert_cache(cache: str) -> None:
	"""Persist the LiteRT cache policy; anything invalid or ``"default"`` → ``""``."""
	value = str(cache or "").strip().lower()
	_set_value(
		"litertCache",
		value if value in {"disk", "memory", "no"} else "",
		notify=True,
	)
	_notify_litert_server_config_changed()


def set_litert_cpu_threads(threads: int) -> None:
	_set_value("litertCpuThreads", int(threads), notify=True)
	_notify_litert_server_config_changed()


def set_litert_start_on_startup(enabled: bool) -> None:
	"""Persist whether the active LiteRT-LM server starts with the add-on."""
	_set_value("litertStartOnStartup", bool(enabled))


def set_llama_start_on_startup(enabled: bool) -> None:
	"""Persist whether the active llama-server starts with the add-on."""
	_set_value("llamaStartOnStartup", bool(enabled))


def get_think(provider_id: str, model_id: str | None = None) -> bool:
	"""Return the per-model thinking toggle, disabled when no model is given."""
	return _get_think_for(provider_id, model_id)


def set_think(provider_id: str, enabled: bool, model_id: str | None = None) -> None:
	"""Persist thinking for one model; calls without a model are ignored."""
	if not model_id:
		return
	from .model_config import set_model_thinking
	set_model_thinking(provider_id, model_id, enabled)
	_notify_provider_state_changed()


# ---------------------------------------------------------------------------
# Unified config setter
# ---------------------------------------------------------------------------

def set_openai_compat_config(config: "OpenAICompatConfig", activate: bool = True) -> None:
	"""Persist a unified OpenAICompatConfig to YAML using legacy per-provider keys.

	With ``activate=True`` (the default, preserving historical behavior)
	the persisted provider becomes the active provider.  Provider
	Configure dialogs pass ``activate=False`` so configuring a provider
	never silently changes which provider AI Assistant currently uses —
	active selection is owned by the settings page / host UI.
	"""
	provider = str(config.provider or "").strip().lower()
	spec = get_provider_config_spec(provider)
	if spec is None:
		raise ValueError(f"Unsupported provider: {provider}")

	values: dict[str, Any] = {
		spec.model_key: config.model_name,
		"timeoutSeconds": config.timeout_seconds,
		"numCtx": config.num_ctx,
		"maxRetries": config.max_retries,
		"retryBackoffSeconds": config.retry_backoff_seconds,
		"generateTemperature": config.generate_temperature,
		"generateTopK": config.generate_top_k,
		"generateTopP": config.generate_top_p,
		"generateMaxTokens": config.generate_max_tokens,
		"generatePresencePenalty": config.generate_presence_penalty,
		"enableProgressAnnouncements": config.enable_progress,
	}
	if activate:
		values["provider"] = provider

	values[spec.base_url_key] = config.base_url

	if spec.api_key_key:
		values[spec.api_key_key] = config.api_key

	if spec.api_token_key:
		values[spec.api_token_key] = config.api_token or ""

	if spec.chat_path_key:
		values[spec.chat_path_key] = config.chat_path

	if spec.litert_engine_settings:
		values["litertBackend"] = config.litert_backend
		values["litertCache"] = config.litert_cache
		values["litertCpuThreads"] = config.litert_cpu_threads

	if spec.executable_key:
		values[spec.executable_key] = config.server_executable
	if spec.models_preset_key:
		values[spec.models_preset_key] = config.models_preset

	_set_values(values, notify=False)
	if spec.litert_engine_settings:
		_notify_litert_server_config_changed()
	if provider == "llama-cpp-server":
		_notify_llama_server_config_changed()
	_notify_provider_state_changed()


# Legacy set_config aliases
def set_ollama_config(config: "OpenAICompatConfig") -> None:
	set_openai_compat_config(config)

def set_gemini_config(config: "OpenAICompatConfig") -> None:
	set_openai_compat_config(config)

def set_openai_config(config: "OpenAICompatConfig") -> None:
	set_openai_compat_config(config)

def set_litert_config(config: "OpenAICompatConfig") -> None:
	set_openai_compat_config(config)


def set_model_name(modelName: str) -> None:
	provider = get_provider()
	spec = get_provider_config_spec(provider)
	if spec is None:
		raise ValueError(f"Unsupported provider: {provider}")
	_set_value(spec.model_key, str(modelName).strip(), notify=True)


def set_gemini_base_url(baseUrl: str) -> None:
	_set_value("geminiBaseUrl", str(baseUrl).strip(), notify=True)


def set_server_url(serverUrl: str) -> None:
	provider = get_provider()
	spec = get_provider_config_spec(provider)
	if spec is None:
		raise ValueError(f"Unsupported provider: {provider}")
	_set_value(spec.base_url_key, str(serverUrl).strip(), notify=True)


def set_streaming_enabled(enabled: bool) -> None:
	_set_value("enableStreaming", bool(enabled))


def set_progress_enabled(enabled: bool) -> None:
	_set_value("enableProgressAnnouncements", bool(enabled))


def set_timeout_seconds(timeoutSeconds: float) -> None:
	_set_value("timeoutSeconds", float(timeoutSeconds))


def set_num_ctx(numCtx: int) -> None:
	_set_value("numCtx", int(numCtx))
	_notify_litert_server_config_changed()


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
