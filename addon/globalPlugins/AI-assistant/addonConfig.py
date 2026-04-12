# -*- coding: utf-8 -*-
from __future__ import annotations

import config as nvda_config
from logHandler import log

from .config import defaults

SECTION_NAME = "aiAssistant"

config_spec: dict[str, str] = {
	"provider": f"string(default=\"{defaults.DEFAULT_PROVIDER}\")",
	"ollamaModelName": f"string(default=\"{defaults.DEFAULT_OLLAMA_MODEL}\")",
	"ollamaServerUrl": f"string(default=\"{defaults.DEFAULT_OLLAMA_URL}\")",
	"geminiModelName": f"string(default=\"{defaults.DEFAULT_GEMINI_MODEL}\")",
	"geminiApiKey": "string(default=)",
	"geminiApiToken": "string(default=)",
	"geminiBaseUrl": f"string(default=\"{defaults.DEFAULT_GEMINI_BASE_URL}\")",
	"enableStreaming": f"boolean(default={str(defaults.DEFAULT_ENABLE_STREAMING).lower()})",
	"enableProgressAnnouncements": f"boolean(default={str(defaults.DEFAULT_ENABLE_PROGRESS_ANNOUNCEMENTS).lower()})",
	"timeoutSeconds": f"float(default={defaults.DEFAULT_TIMEOUT_SECONDS})",
	"numCtx": f"float(default={defaults.DEFAULT_NUM_CTX})",
	"keepAlive": f"string(default=\"{defaults.DEFAULT_KEEP_ALIVE}\")",
	"maxRetries": f"float(default={defaults.DEFAULT_MAX_RETRIES})",
	"retryBackoffSeconds": f"float(default={defaults.DEFAULT_RETRY_BACKOFF_SECONDS})",
	"generateTemperature": f"float(default={defaults.DEFAULT_GENERATE_TEMPERATURE})",
	"generateTopK": f"float(default={defaults.DEFAULT_GENERATE_TOP_K})",
	"generateTopP": f"float(default={defaults.DEFAULT_GENERATE_TOP_P})",
	"generatePresencePenalty": f"float(default={defaults.DEFAULT_GENERATE_PRESENCE_PENALTY})",
	"imageMaxSide": f"float(default={defaults.DEFAULT_IMAGE_MAX_SIDE})",
	"imageFormat": f"string(default=\"{defaults.DEFAULT_IMAGE_FORMAT}\")",
	"imageQuality": f"float(default={defaults.DEFAULT_IMAGE_QUALITY})",
	"requestMetricsLoggingEnabled": f"boolean(default={str(defaults.DEFAULT_REQUEST_METRICS_LOGGING).lower()})",
	"requestMetricsLogPath": f"string(default=\"{defaults.DEFAULT_REQUEST_METRICS_LOG_PATH}\")",
}


def initialize() -> None:
	conf = getattr(nvda_config, "conf", None)
	if conf is None:
		log.warning("AI assistant config initialization skipped because nvda config is unavailable.")
		return

	if not hasattr(conf, "spec"):
		log.warning("AI assistant config initialization skipped because nvda config has no spec attribute.")
		return

	conf.spec.setdefault(SECTION_NAME, {})
	conf.spec[SECTION_NAME].update(config_spec)

	if SECTION_NAME not in conf:
		conf[SECTION_NAME] = {}
