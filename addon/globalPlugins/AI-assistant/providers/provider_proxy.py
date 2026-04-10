# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from typing import Any

from .factory import ProviderFactory
from .base import LLMProvider, PartialCallback, ProgressCallback
from ..settings import get_active_provider_config

logger = logging.getLogger(__name__)


class ProviderProxy(LLMProvider):
    def __init__(self) -> None:
        self._active_config = get_active_provider_config()
        self._provider = ProviderFactory.create_provider(self._active_config)

    def _refresh(self) -> None:
        current_config = get_active_provider_config()
        if current_config == self._active_config:
            return

        logger.debug("ProviderProxy detected config change, recreating provider")
        self._active_config = current_config
        try:
            self._provider.close()
        except Exception:
            logger.exception("Error closing previous provider")
        self._provider = ProviderFactory.create_provider(self._active_config)

    def provider_name(self) -> str:
        self._refresh()
        return self._provider.provider_name()

    def supports_streaming(self) -> bool:
        self._refresh()
        return self._provider.supports_streaming()

    def supports_image_description(self) -> bool:
        self._refresh()
        return self._provider.supports_image_description()

    def summarize(self, prompt: str, on_partial: PartialCallback | None = None) -> Any:
        self._refresh()
        return self._provider.summarize(prompt, on_partial=on_partial)

    def describe_image(
        self,
        image_base64: str,
        prompt: str,
        on_partial: PartialCallback | None = None,
    ) -> Any:
        self._refresh()
        return self._provider.describe_image(
            image_base64=image_base64,
            prompt=prompt,
            on_partial=on_partial,
        )

    def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
        self._refresh()
        return self._provider.ensure_model_available(on_progress=on_progress)

    def close(self) -> None:
        try:
            self._provider.close()
        except Exception:
            logger.exception("Error closing provider in ProviderProxy.close")
