# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

from collections.abc import Callable
import base64
import threading
from typing import Any

from logHandler import log

from .base_coordinator import BaseCoordinator
from .core.canonical import Message, Part, Tool
from .llm_service import LLMService
from .metrics_reporter import MetricsReporter
from .models import ChatMessage, LLMResponse, ProgressHandler


class ChatCoordinator(BaseCoordinator):
    def __init__(
        self,
        client: LLMService,
        tool_executor: Any | None = None,
        metrics_reporter: MetricsReporter | None = None,
    ) -> None:
        super().__init__(metrics_reporter)
        self._llm_service = client
        self._tool_executor = tool_executor
        self._history: list[ChatMessage] = []

    def send(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        progress: ProgressHandler | None = None,
    ) -> LLMResponse:
        return self._send(messages, tools=tools, stream_handler=None, progress=progress)

    def send_message(
        self,
        text: str | None = None,
        image_base64: str | None = None,
        progress_callback: Callable[[str, int], None] | None = None,
        tools: list[dict[str, Any]] | None = None,
        progress: ProgressHandler | None = None,
    ) -> str:
        user_message = self._build_user_message(text=text, image_base64=image_base64)
        canonical_tools = self._convert_tool_definitions(tools)
        response = self._send(
            [user_message],
            tools=canonical_tools,
            stream_handler=progress_callback,
            progress=progress,
        )
        return response.text

    def get_history(self) -> list[ChatMessage]:
        return list(self._history)

    def reset(self) -> None:
        self._history = []

    def _send(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream_handler: Callable[[str, int], None] | None = None,
        progress: ProgressHandler | None = None,
    ) -> LLMResponse:
        if not messages:
            raise ValueError("ChatCoordinator.send requires at least one message")

        self._append_history_from_messages(messages)
        if threading.current_thread() is threading.main_thread():
            log.warning("ChatCoordinator.send called on main thread; should be invoked from a background worker")

        response = self._llm_service.generate(
            messages=messages,
            tools=tools,
            stream_handler=stream_handler,
            progress=progress,
        )
        self._history.append(
            ChatMessage(
                role="assistant",
                content=response.text,
            )
        )
        return response

    def _append_history_from_messages(self, messages: list[Message]) -> None:
        for message in messages:
            self._history.append(self._convert_message_to_chat_message(message))

    def _convert_message_to_chat_message(self, message: Message) -> ChatMessage:
        text_parts: list[str] = []
        image_base64_text = None
        tool_name = None
        tool_calls: list[dict[str, Any]] = []

        for part in message.parts:
            if part.type == "text" and part.text is not None:
                text_parts.append(part.text)
            elif part.type == "image" and part.image is not None:
                image_base64_text = base64.b64encode(part.image).decode("ascii")
            elif part.type == "tool_call":
                tool_name = part.tool_name or tool_name
                tool_calls.append({"name": part.tool_name or "", "arguments": part.tool_args or {}})
            elif part.type == "tool_result":
                tool_name = part.tool_name or tool_name
                if part.tool_result is not None:
                    text_parts.append(str(part.tool_result))
                elif part.text is not None:
                    text_parts.append(part.text)

        return ChatMessage(
            role=message.role,
            content="\n".join(text_parts) if text_parts else None,
            image_base64=image_base64_text,
            tool_name=tool_name,
            tool_calls=tool_calls or None,
        )

    def _build_user_message(self, text: str | None, image_base64: str | None) -> Message:
        parts: list[Part] = []
        if text:
            parts.append(Part(type="text", text=text))
        if image_base64:
            try:
                parts.append(Part(type="image", image=base64.b64decode(image_base64)))
            except Exception as error:
                raise ValueError(f"Invalid image base64: {error}") from error
        return Message(role="user", parts=tuple(parts))

    def _convert_tool_definitions(self, tools: list[dict[str, Any]] | None) -> list[Tool] | None:
        if tools is None:
            return None

        canonical_tools: list[Tool] = []
        for tool_def in tools:
            function_payload = None
            if tool_def.get("type") == "function" and isinstance(tool_def.get("function"), dict):
                function_payload = tool_def["function"]
            if function_payload is None:
                continue
            name = str(function_payload.get("name", "")).strip()
            if not name:
                continue
            description = str(function_payload.get("description", ""))
            parameters = function_payload.get("parameters") if isinstance(function_payload.get("parameters"), dict) else {}
            required = tuple(item for item in parameters.get("required", []) if isinstance(item, str)) if isinstance(parameters, dict) else ()
            canonical_tools.append(
                Tool(
                    name=name,
                    description=description,
                    parameters=parameters,
                    required=required,
                )
            )
        return canonical_tools if canonical_tools else None
