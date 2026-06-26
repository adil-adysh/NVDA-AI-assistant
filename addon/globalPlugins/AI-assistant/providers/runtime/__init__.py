# -*- coding: utf-8 -*-
"""Runtime management for on-demand inference backends.

This package provides a generic infrastructure for downloading, verifying,
and loading local runtime backends (e.g., litert-lm, llama.cpp, ONNX Runtime).
"""

from __future__ import annotations

from .config import DefaultRuntimeConfig, RuntimeConfig, RuntimeType
from .download import RuntimeDownloadError, RuntimeDownloadService
from .loader import RuntimeImportError, RuntimeLoader, RuntimeLoadError
from .manager import RuntimeManager, RuntimeManagerError
from .model_download import ModelDownloadError, ModelDownloadService
from .paths import get_runtime_dir

__all__ = [
    "DefaultRuntimeConfig",
    "ModelDownloadError",
    "ModelDownloadService",
    "RuntimeConfig",
    "RuntimeDownloadError",
    "RuntimeDownloadService",
    "RuntimeImportError",
    "RuntimeLoadError",
    "RuntimeLoader",
    "RuntimeManager",
    "RuntimeManagerError",
    "RuntimeType",
    "get_runtime_dir",
]
