# -*- coding: utf-8 -*-
from typing import Any

from .errors import OllamaClientError
from .types import OllamaGenerateResponse


def _validateGenerateResponse(
    response: dict[str, Any],
    path: str,
    requireDone: bool = True,
) -> OllamaGenerateResponse:
    typedResponse = response  # type: ignore[assignment]
    errorMessage = str(response.get("error", "")).strip()
    if errorMessage:
        raise OllamaClientError(f"Ollama returned an error for {path}: {errorMessage}")
    if requireDone and typedResponse.get("done") is not True:
        raise OllamaClientError("Ollama returned an incomplete non-stream response (done=false).")
    return typedResponse


def _extractGenerateText(response: dict[str, Any]) -> str:
    text = str(response.get("response", "")).strip()
    if text:
        return text
    message = response.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
    return ""


def _responseHasToolCalls(response: dict[str, Any]) -> bool:
    message = response.get("message")
    if isinstance(message, dict):
        tool_calls = message.get("tool_calls") or message.get("toolCalls")
        if isinstance(tool_calls, list) and tool_calls:
            return True
        function_call = message.get("function_call") or message.get("tool_call")
        if isinstance(function_call, dict):
            return True

    tool_calls = response.get("tool_calls") or response.get("toolCalls")
    if isinstance(tool_calls, list) and tool_calls:
        return True

    return False


def _attach_accumulated_tool_calls(parsed_response: dict[str, Any], accumulatedToolCalls: list[dict[str, Any]]) -> dict[str, Any]:
    if not accumulatedToolCalls:
        return parsed_response

    final_response = dict(parsed_response)
    message = dict(parsed_response.get("message") or {}) if isinstance(parsed_response.get("message"), dict) else {}
    merged_tool_calls = list(accumulatedToolCalls)
    message["tool_calls"] = merged_tool_calls
    final_response["message"] = message
    final_response["tool_calls"] = merged_tool_calls
    return final_response
