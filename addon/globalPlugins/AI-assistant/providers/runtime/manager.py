# -*- coding: utf-8 -*-
"""RuntimeManager — top-level facade for managing on-demand runtimes.

Handles the lifecycle: download → verify → load.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

from logHandler import log

from .config import RuntimeConfig
from .download import RuntimeDownloadError, RuntimeDownloadService
from .loader import RuntimeImportError, RuntimeLoadError, RuntimeLoader
from .paths import get_runtime_path


class RuntimeManagerError(RuntimeError):
    """Raised when the runtime manager encounters an error."""


class RuntimeManager:
    """Manages the lifecycle of on-demand runtime backends.

    Resolution order:
      1. Check if the runtime is already downloaded locally → load.
      2. Download from releases → extract → load.

    Usage::

        mgr = RuntimeManager()
        lm = mgr.load(RuntimeConfig.for_runtime("litert-lm", "0.13.1"))
        engine = lm.Engine(model_path)
    """

    def __init__(
        self,
        download_service: RuntimeDownloadService | None = None,
    ) -> None:
        self._download_service = download_service or RuntimeDownloadService()

    def ensure_downloaded(
        self,
        config: RuntimeConfig,
        on_progress=None,
    ) -> Path:
        """Ensure the runtime is downloaded and verified.

        Returns the path to the extracted runtime directory.
        """
        if not self._download_service.is_downloaded(config.runtime, config.version):
            log.info("Runtime %s %s not found locally; downloading", config.runtime, config.version)
            return self._download_service.download(
                runtime=config.runtime,
                version=config.version,
                platform=config.platform,
                on_progress=on_progress,
            )
        return get_runtime_path(config.runtime, config.version)

    def load(
        self,
        config: RuntimeConfig,
        on_progress=None,
    ) -> ModuleType:
        """Ensure the runtime is downloaded and import the package.

        The imported module persists in ``sys.modules`` for the
        lifetime of the provider.

        Raises:
            RuntimeManagerError: If download or import fails.
        """
        try:
            runtime_path = self.ensure_downloaded(config, on_progress=on_progress)
        except RuntimeDownloadError as exc:
            raise RuntimeManagerError(str(exc)) from exc

        loader = RuntimeLoader(runtime_path)
        try:
            return loader.import_package(config.package_name)
        except (RuntimeLoadError, RuntimeImportError) as exc:
            raise RuntimeManagerError(str(exc)) from exc

    def is_available(self, config: RuntimeConfig) -> bool:
        """Check if a runtime is downloaded and ready."""
        return self._download_service.is_downloaded(config.runtime, config.version)
