# -*- coding: utf-8 -*-
from __future__ import annotations

from logHandler import log
import threading
from collections.abc import Callable
from typing import Any

from .factory import ProviderFactory
from .base import LLMProvider, LLMResponse, PartialCallback, ProgressCallback
from ..core.canonical import Message, Tool
from ..settings import get_active_provider_config



class ProviderProxy(LLMProvider):
    def __init__(self) -> None:
        self._active_config = get_active_provider_config()
        self._provider = ProviderFactory.create_provider(self._active_config)

    def _refresh(self) -> None:
        current_config = get_active_provider_config()
        if current_config == self._active_config:
            return

        log.debug("ProviderProxy detected config change, recreating provider")
        self._active_config = current_config
        try:
            self._provider.close()
        except Exception:
            log.exception("Error closing previous provider")
        self._provider = ProviderFactory.create_provider(self._active_config)

    def _warn_if_main_thread(self, method_name: str) -> None:
        if threading.current_thread() is threading.main_thread():
            log.warning("ProviderProxy.%s called on main thread; this may block NVDA UI", method_name)

    def provider_name(self) -> str:
        self._refresh()
        return self._provider.provider_name()

    def supports_streaming(self) -> bool:
        self._refresh()
        return self._provider.supports_streaming()

    def supports_image_description(self) -> bool:
        self._refresh()
        return self._provider.supports_image_description()

    def summarize(self, prompt: str, stream_handler: PartialCallback | None = None) -> Any:
        self._warn_if_main_thread("summarize")
        self._refresh()
        return self._provider.summarize(prompt, stream_handler=stream_handler)

    def describe_image(
        self,
        image_base64: str,
        prompt: str,
        stream_handler: PartialCallback | None = None,
    ) -> Any:
        self._warn_if_main_thread("describe_image")
        self._refresh()
        return self._provider.describe_image(
            image_base64=image_base64,
            prompt=prompt,
            stream_handler=stream_handler,
        )

    def generate(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream_handler: Callable[[str, int], None] | None = None,
    ) -> LLMResponse:
        self._warn_if_main_thread("generate")
        self._refresh()
        return self._provider.generate(messages=messages, tools=tools, stream_handler=stream_handler)

    def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
        self._warn_if_main_thread("ensure_model_available")
        self._refresh()
        return self._provider.ensure_model_available(on_progress=on_progress)

    def close(self) -> None:
        try:
            self._provider.close()
        except Exception:
            log.exception("Error closing provider in ProviderProxy.close")
