# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from collections.abc import Callable
from typing import Any

from .base_coordinator import BaseCoordinator
from .models import ChatMessage, LLMRequest, LLMResponse, TaskType, ToolCall
from .providers.base import LLMProvider
from .metrics_reporter import MetricsReporter


class ChatCoordinator(BaseCoordinator):
    MAX_TOOL_STEPS = 5

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
        progress_callback: Callable[[str, int], None] | None = None,
        tools: list[dict[str, Any]] | None = None,
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
            tools=tools,
            stream=progress_callback is not None,
            stream_handler=progress_callback,
        )

        response = self._provider.generate(request)
        steps = 0

        while response.tool_calls and steps < self.MAX_TOOL_STEPS:
            for tool_call in response.tool_calls:
                try:
                    result = self._execute_tool(tool_call)
                except Exception as error:
                    result = f"Tool error: {error}"

                self._history.append(
                    ChatMessage(
                        role="tool",
                        content=result,
                        tool_name=tool_call.name,
                    )
                )

            request = LLMRequest(
                task_type=TaskType.CHAT,
                messages=self._history,
                tools=tools,
                stream=progress_callback is not None,
                stream_handler=progress_callback,
            )
            response = self._provider.generate(request)
            steps += 1

        self._history.append(
            ChatMessage(
                role="assistant",
                content=response.text,
            )
        )

        return response.text

    def _execute_tool(self, tool_call: ToolCall) -> str:
        if tool_call.name == "get_time":
            import datetime

            return str(datetime.datetime.now())

        return f"Unknown tool: {tool_call.name}"
