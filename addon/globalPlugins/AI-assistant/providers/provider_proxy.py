# -*- coding: utf-8 -*-
from __future__ import annotations

from logHandler import log
import threading
from collections.abc import Callable

from .interfaces import LLMProvider, PartialCallback, ProgressCallback
from ..core.messages import LLMResponse, SummaryResponse
from ..core.canonical import Message, Tool
from .session import ProviderSession
from ..config.state import ProviderState, subscribe_provider_state_change, unsubscribe_provider_state_change



class ProviderProxy(LLMProvider):
    def __init__(self) -> None:
        self._session: ProviderSession | None = None
        subscribe_provider_state_change(self._on_provider_state_change)

    def _ensure_session(self) -> ProviderSession:
        if self._session is None:
            self._session = ProviderSession.from_active_config()
        return self._session

    def _refresh(self) -> None:
        if self._session is None:
            self._session = ProviderSession.from_active_config()
            return
        self._session.refresh()

    def _on_provider_state_change(self, provider_state: ProviderState) -> None:
        self._refresh()

    def _warn_if_main_thread(self, method_name: str) -> None:
        if threading.current_thread() is threading.main_thread():
            log.warning("ProviderProxy.%s called on main thread; this may block NVDA UI", method_name)

    def provider_name(self) -> str:
        self._refresh()
        return self._ensure_session().provider_name()

    def supports_streaming(self) -> bool:
        self._refresh()
        return self._ensure_session().supports_streaming()

    def supports_image_description(self) -> bool:
        self._refresh()
        return self._ensure_session().supports_image_description()

    def summarize(self, prompt: str, stream_handler: PartialCallback | None = None) -> SummaryResponse:
        self._warn_if_main_thread("summarize")
        self._refresh()
        return self._ensure_session().summarize(prompt, stream_handler=stream_handler)

    def describe_image(
        self,
        image_base64: str,
        prompt: str,
        stream_handler: PartialCallback | None = None,
    ) -> SummaryResponse:
        self._warn_if_main_thread("describe_image")
        self._refresh()
        return self._ensure_session().describe_image(
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
        return self._ensure_session().generate(messages=messages, tools=tools, stream_handler=stream_handler)

    def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
        self._warn_if_main_thread("ensure_model_available")
        self._refresh()
        return self._ensure_session().ensure_model_available(on_progress=on_progress)

    def close(self) -> None:
        try:
            unsubscribe_provider_state_change(self._on_provider_state_change)
        except Exception:
            log.exception("Error unsubscribing provider state listener")
        if self._session is None:
            return
        try:
            self._session.close()
        except Exception:
            log.exception("Error closing provider in ProviderProxy.close")
