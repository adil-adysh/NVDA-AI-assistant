# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from logHandler import log
from collections.abc import Callable
from typing import Any

from .base_coordinator import BaseCoordinator
from .models import ChatMessage, LLMRequest, TaskType, ToolCall
from .providers.base import LLMProvider
from .tool_registry import ToolRegistry
from .metrics_reporter import MetricsReporter


class ChatCoordinator(BaseCoordinator):
    MAX_TOOL_STEPS = 5

    def __init__(
        self,
        client: LLMProvider,
        tool_registry: ToolRegistry,
        metrics_reporter: MetricsReporter | None = None,
    ) -> None:
        super().__init__(metrics_reporter)
        self._provider = client
        self._tool_registry = tool_registry
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
        log.debug(
            "ChatCoordinator.send_message: user_text=%r image_attached=%s tool_defs=%s",
            text,
            bool(image_base64),
            [tool.get("name") for tool in tools] if tools else None,
        )

        response = self._provider.generate(request)
        log.debug(
            "ChatCoordinator response: text_len=%d tool_calls=%s raw=%s",
            len(response.text or ""),
            [tc.name for tc in response.tool_calls] if response.tool_calls else None,
            getattr(response, "raw", None),
        )
        steps = 0

        while response.tool_calls and steps < self.MAX_TOOL_STEPS:
            for tool_call in response.tool_calls:
                log.debug("ChatCoordinator tool call: name=%s arguments=%s", tool_call.name, tool_call.arguments)
                try:
                    result = self._execute_tool(tool_call)
                except Exception as error:
                    result = f"Tool error: {error}"
                log.debug("ChatCoordinator tool result: %r", result)

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

    def get_history(self) -> list[ChatMessage]:
        return list(self._history)

    def reset(self) -> None:
        self._history = []

    def _execute_tool(self, tool_call: ToolCall) -> str:
        try:
            return self._tool_registry.execute(tool_call)
        except Exception as error:
            return f"Tool error: {error}"
