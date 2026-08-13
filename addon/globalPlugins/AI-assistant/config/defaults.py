# -*- coding: utf-8 -*-
"""Static default configuration values for the NVDA AI assistant."""

import os
from pathlib import Path

DEFAULT_PROVIDER = "ollama"
DEFAULT_OLLAMA_MODEL = "ministral-3:3b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_CLI = "ollama"
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"

DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
DEFAULT_LANGUAGE = "auto"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_CHAT_PATH = "/v1/chat/completions"
DEFAULT_OPENAI_MODELS_PATH = "/v1/models"
DEFAULT_GEMINI_CHAT_PATH = "/v1beta/openai/chat/completions"
DEFAULT_GEMINI_MODELS_PATH = "/v1beta/openai/models"
DEFAULT_ENABLE_STREAMING = True
DEFAULT_ENABLE_PROGRESS_ANNOUNCEMENTS = True
DEFAULT_ENABLE_STREAMING_TONE = True

DEFAULT_TIMEOUT_SECONDS = 450
DEFAULT_NUM_CTX = 8192
DEFAULT_KEEP_ALIVE = "5m"
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 0.75

DEFAULT_GENERATE_TEMPERATURE = 0.2
DEFAULT_GENERATE_TOP_K = 10
DEFAULT_GENERATE_TOP_P = 0.85
DEFAULT_GENERATE_MAX_TOKENS = 1024
DEFAULT_GENERATE_PRESENCE_PENALTY = 0
DEFAULT_OLLAMA_THINK = False

DEFAULT_LITERT_MODEL = "litert-community/gemma-4-E2B-it-litert-lm"
DEFAULT_LITERT_URL = "http://127.0.0.1:9379"
DEFAULT_LITERT_THINK = False

# LiteRT-LM server engine defaults.  An empty backend/cache means "use the
# engine default" — the key is omitted from config.json entirely and litert-lm
# falls back to the model's metadata default (CPU inference, disk cache).
# cpu_threads 0 means "let the runtime decide".
DEFAULT_LITERT_BACKEND = ""
DEFAULT_LITERT_CACHE = ""
DEFAULT_LITERT_CPU_THREADS = 0

DEFAULT_LLAMA_CPP_MODEL = ""
DEFAULT_LLAMA_CPP_URL = "http://127.0.0.1:8080"
DEFAULT_LLAMA_CPP_EXECUTABLE = "llama-server"

DEFAULT_ENABLED_PROVIDERS = ["ollama", "gemini", "openai", "litert-lm"]

# Local embedding/retrieval defaults.  Embedding models are independent from
# the active generation provider and model.
DEFAULT_EMBEDDING_MODEL = "harrier-oss-v1-270m"
DEFAULT_EMBEDDING_ENABLED = True
DEFAULT_EMBEDDING_PAGE_SUMMARY_ENABLED = True
DEFAULT_EMBEDDING_PAGE_CHAT_ENABLED = True
DEFAULT_EMBEDDING_CONVERSATION_MEMORY_ENABLED = False

DEFAULT_IMAGE_MAX_SIDE = 1024
DEFAULT_IMAGE_FORMAT = "PNG"
DEFAULT_IMAGE_QUALITY = 80

DEFAULT_REQUEST_METRICS_LOGGING = False
APPDATA = os.getenv("APPDATA")
DEFAULT_REQUEST_METRICS_LOG_PATH = str(
    Path(APPDATA if APPDATA else Path.home() / "AppData" / "Roaming")
    / "nvda"
    / "nvda_ai_assistant_request_metrics.jsonl"
)
DEFAULT_CONFIG_PATH = str(
    Path(APPDATA if APPDATA else Path.home() / "AppData" / "Roaming")
    / "nvda"
    / "AIAssistant"
    / "config.yaml"
)
