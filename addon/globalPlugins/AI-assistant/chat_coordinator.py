# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from collections.abc import Callable
from typing import Any

from .base_coordinator import BaseCoordinator
from .models import ChatMessage, LLMRequest, LLMResponse, TaskType
from .providers.base import LLMProvider
from .metrics_reporter import MetricsReporter


class ChatCoordinator(BaseCoordinator):
    def __init__(
        self,
        client: LLMProvider,
        metrics_reporter: MetricsReporter | None = None,
    ) -> None:
        super().__init__(metrics_reporter)
        self._provider = client
        self._history: list[ChatMessage] = []

    def send_message(
        self,
        text: str | None = None,
        image_base64: str | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> str:
        self._history.append(
            ChatMessage(
                role="user",
                content=text,
                image_base64=image_base64,
            )
        )

        request = LLMRequest(
            task_type=TaskType.CHAT,
            messages=self._history,
            stream=progress_callback is not None,
            stream_handler=progress_callback,
        )

        response = self._provider.generate(request)

        self._history.append(
            ChatMessage(
                role="assistant",
                content=response.text,
            )
        )

        return response.text
