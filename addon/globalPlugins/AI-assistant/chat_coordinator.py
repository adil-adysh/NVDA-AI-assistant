# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from logHandler import log
import threading
from collections.abc import Callable
from typing import Any

from .base_coordinator import BaseCoordinator
from .models import ChatMessage, ToolCall
from .providers.base import LLMProvider
from .tool_registry import ToolRegistry
from .metrics_reporter import MetricsReporter
from .core.canonical import Message as CanonicalMessage, Part as CanonicalPart, Tool as CanonicalTool


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

    def _convert_to_canonical_message(self, message: ChatMessage) -> CanonicalMessage:
        parts: list[CanonicalPart] = []
        if message.role == "tool":
            parts.append(
                CanonicalPart(
                    type="tool_result",
                    text=message.content,
                    tool_name=message.tool_name,
                )
            )
        else:
            if message.content is not None:
                parts.append(CanonicalPart(type="text", text=message.content))
        if message.image_base64 is not None:
            try:
                import base64

                image_bytes = base64.b64decode(message.image_base64)
            except Exception:
                image_bytes = None
            if image_bytes is not None:
                parts.append(CanonicalPart(type="image", image=image_bytes))
        if message.tool_calls:
            for tool_call in message.tool_calls:
                if isinstance(tool_call, dict):
                    parts.append(
                        CanonicalPart(
                            type="tool_call",
                            tool_name=str(tool_call.get("name", "")),
                            tool_args=tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {},
                        )
                    )
        return CanonicalMessage(role=message.role, parts=tuple(parts))

    def _get_canonical_history(self) -> list[CanonicalMessage]:
        return [self._convert_to_canonical_message(msg) for msg in self._history]

    def _convert_tool_definition(self, tool_def: dict[str, Any]) -> CanonicalTool:
        function_payload = None
        if isinstance(tool_def, dict) and tool_def.get("type") == "function" and isinstance(tool_def.get("function"), dict):
            function_payload = tool_def["function"]
        if function_payload is None:
            raise ValueError(f"Unsupported tool definition: {tool_def}")

        name = str(function_payload.get("name", "")).strip()
        description = str(function_payload.get("description", ""))
        params = function_payload.get("parameters") if isinstance(function_payload.get("parameters"), dict) else {}
        required = tuple(
            item for item in params.get("required", [])
            if isinstance(item, str)
        ) if isinstance(params, dict) else ()
        return CanonicalTool(
            name=name,
            description=description,
            parameters=params,
            required=required,
        )

    def _get_canonical_tools(self, tools: list[dict[str, Any]] | None) -> list[CanonicalTool] | None:
        if tools is None:
            return None
        canonical_tools: list[CanonicalTool] = []
        for tool_def in tools:
            if not isinstance(tool_def, dict):
                continue
            try:
                canonical_tools.append(self._convert_tool_definition(tool_def))
            except ValueError:
                continue
        return canonical_tools if canonical_tools else None

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

        canonical_history = self._get_canonical_history()
        canonical_tools = self._get_canonical_tools(tools)
        if threading.current_thread() is threading.main_thread():
            log.warning("ChatCoordinator.send_message called on main thread; should be invoked from a background worker")
        log.debug(
            "ChatCoordinator.send_message: user_text=%r image_attached=%s tool_defs=%s canonical_history=%s",
            text,
            bool(image_base64),
            [tool.name for tool in canonical_tools] if canonical_tools else None,
            [(msg.role, len(msg.parts)) for msg in canonical_history],
        )

        response = self._provider.generate(
            messages=canonical_history,
            tools=canonical_tools,
            stream_handler=progress_callback,
        )
        log.debug(
            "ChatCoordinator response: text_len=%d tool_calls=%s raw=%s",
            len(response.text or ""),
            [tc.name for tc in response.tool_calls] if response.tool_calls else None,
            getattr(response, "raw", None),
        )
        steps = 0
        tool_loop_executed = False

        while response.tool_calls and steps < self.MAX_TOOL_STEPS:
            tool_loop_executed = True
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

            canonical_history = self._get_canonical_history()
            response = self._provider.generate(
                messages=canonical_history,
                tools=canonical_tools,
                stream_handler=progress_callback,
            )
            log.debug(
                "ChatCoordinator follow-up response: text_len=%d tool_calls=%s raw=%s",
                len(response.text or ""),
                [tc.name for tc in response.tool_calls] if response.tool_calls else None,
                getattr(response, "raw", None),
            )
            steps += 1

        if response.text or not tool_loop_executed:
            self._history.append(
                ChatMessage(
                    role="assistant",
                    content=response.text,
                )
            )
        else:
            log.debug(
                "ChatCoordinator send_message: tool loop completed without assistant text; not appending blank assistant message"
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
