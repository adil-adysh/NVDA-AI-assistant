# -*- coding: utf-8 -*-
import json
import socket
import time
from collections.abc import Callable
from typing import Any, cast
from urllib import error as urllibError
from urllib import request as urllibRequest

from logHandler import log

from ..config import defaults
from .errors import OllamaClientError
from .http import _parseJSON, _requestJSON, _requestPullStream, _readErrorBody
from .response import (
    _attach_accumulated_tool_calls,
    _extractGenerateText,
    _responseHasToolCalls,
    _validateGenerateResponse,
)
from .types import (
    OllamaChatMessage,
    OllamaChatRequest,
    OllamaGenerateResponse,
    OllamaMessageResponse,
    OllamaModelEntry,
    OllamaModelMetadata,
    OllamaRunningModelsResponse,
    OllamaShowResponse,
    OllamaToolDefinition,
    OllamaToolCall,
)
from ..core.messages import SummaryResponse
from ..config.settings import (
    get_generate_presence_penalty,
    get_generate_top_k,
    get_generate_top_p,
    get_generate_temperature,
    get_keep_alive,
    get_max_retries,
    get_model_name,
    get_num_ctx,
    get_retry_backoff_seconds,
    get_server_url,
    get_timeout_seconds,
)


class OllamaClient:
    SUPPORTED_ENDPOINTS: tuple[str, ...] = (
        "POST /api/generate",
        "POST /api/chat",
        "GET /api/tags",
        "POST /api/show",
        "GET /api/ps",
        "POST /api/embed",
        "POST /api/embeddings (legacy)",
        "POST /api/create",
        "POST /api/copy",
        "DELETE /api/delete",
        "POST /api/pull",
        "POST /api/push",
        "HEAD /api/blobs/:digest",
        "POST /api/blobs/:digest",
    )

    def __init__(
        self,
        baseURL: str | None = None,
        model: str | None = None,
        timeoutSeconds: float | None = None,
        think: bool = False,
    ):
        super().__init__()
        baseUrlValue = baseURL or get_server_url()
        self._baseURL: str = str(baseUrlValue).rstrip("/")
        self._explicitModel: str | None = model
        self._model: str | None = str(model).strip() if model is not None else None
        self._timeoutSeconds: float = timeoutSeconds if timeoutSeconds is not None else get_timeout_seconds()
        self._numCtx: int = get_num_ctx()
        self._keepAlive: str = get_keep_alive()
        self._maxRetries: int = get_max_retries()
        self._retryBackoffSeconds: float = get_retry_backoff_seconds()
        self._think: bool = think
        log.debug(
            "OllamaClient initialized baseURL=%s model=%s timeout=%.1fs num_ctx=%d keep_alive=%s max_retries=%d backoff=%.2fs",
            self._baseURL,
            self._model,
            self._timeoutSeconds,
            self._numCtx,
            self._keepAlive,
            self._maxRetries,
            self._retryBackoffSeconds,
        )

    def _configuredModel(self) -> str | None:
        if self._explicitModel is not None:
            return str(self._model).strip() if self._model is not None else None
        return get_model_name()

    def _selectModelName(self, model: str | None = None) -> str:
        candidate = str(model).strip() if model is not None else ""
        if candidate:
            return candidate
        configured = self._configuredModel()
        if configured is not None:
            return configured
        return defaults.DEFAULT_OLLAMA_MODEL

    def _defaultGenerateOptions(self) -> dict[str, Any]:
        return {
            "num_ctx": get_num_ctx(),
            "temperature": get_generate_temperature(),
            "top_k": get_generate_top_k(),
            "top_p": get_generate_top_p(),
            "presence_penalty": get_generate_presence_penalty(),
        }

    def _normalizeModelNames(self, modelNames: list[str]) -> dict[str, str]:
        return {name.lower(): name for name in modelNames if name.strip()}

    def summarize(
        self,
        prompt: str,
        onPartial: Callable[[str, int], None] | None = None,
    ) -> SummaryResponse:
        model = self._resolveModel()
        prompt_text = str(prompt)
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt_text,
            "options": self._defaultGenerateOptions(),
            "keep_alive": get_keep_alive(),
        }

        promptLength = len(payload["prompt"])
        log.debug("Prompt length=%d", promptLength)

        if onPartial is None:
            payload["stream"] = False
            log.debug("Starting non-stream /api/generate request for model=%s", model)
            response = _requestJSON(
                self._baseURL,
                "/api/generate",
                "POST",
                self._timeoutSeconds,
                {
                    "Accept": "application/json",
                    "Connection": "keep-alive",
                    "User-Agent": "browser-assistant/0.1",
                },
                payload,
            )
            log.debug("Raw response: %s", response)
            typedResponse = _validateGenerateResponse(response, "/api/generate")
            summaryText = _extractGenerateText(typedResponse)
            finalResponse = typedResponse
        else:
            log.debug("Starting stream /api/generate request for model=%s", model)
            summaryText, finalResponse, _ = self._requestGenerateStream(payload, onPartial, "/api/generate")
            log.debug("Final generated summary length=%d", len(summaryText))

        if not summaryText:
            log.debug(
                "Empty response detected prompt_length=%d final_response=%s",
                promptLength,
                {
                    "done": finalResponse.get("done"),
                    "done_reason": finalResponse.get("done_reason"),
                    "response_len": len(str(finalResponse.get("response", ""))),
                },
            )
            raise OllamaClientError(
                f"Empty response. Prompt size={promptLength}. final_response={{'done': {finalResponse.get('done')}, 'done_reason': {finalResponse.get('done_reason')}}}"
            )
        return SummaryResponse(text=summaryText, model=model)

    def describeImage(
        self,
        imageBase64: str,
        prompt: str,
        onPartial: Callable[[str, int], None] | None = None,
    ) -> SummaryResponse:
        model = self._resolveModel()
        prompt_text = str(prompt)
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt_text,
            "images": [imageBase64],
            "options": self._defaultGenerateOptions(),
            "keep_alive": get_keep_alive(),
        }

        if onPartial is None:
            payload["stream"] = False
            log.debug("Starting non-stream image generate request for model=%s", model)
            response = _requestJSON(
                self._baseURL,
                "/api/generate",
                "POST",
                self._timeoutSeconds,
                {
                    "Accept": "application/json",
                    "Connection": "keep-alive",
                    "User-Agent": "browser-assistant/0.1",
                },
                payload,
            )
            typedResponse = _validateGenerateResponse(response, "/api/generate")
            descriptionText = _extractGenerateText(typedResponse)
            finalResponse = typedResponse
        else:
            log.debug("Starting stream image generate request for model=%s", model)
            descriptionText, finalResponse, _ = self._requestGenerateStream(payload, onPartial, "/api/generate")
            log.debug("Final generated description length=%d", len(descriptionText))

        if not descriptionText:
            log.debug(
                "Empty image description detected prompt_length=%d final_response=%s",
                len(payload["prompt"]),
                {
                    "done": finalResponse.get("done"),
                    "done_reason": finalResponse.get("done_reason"),
                    "response_len": len(str(finalResponse.get("response", ""))),
                },
            )
            raise OllamaClientError(
                f"Empty image description. Prompt size={len(payload['prompt'])}. final_response={{'done': {finalResponse.get('done')}, 'done_reason': {finalResponse.get('done_reason')}}}"
            )
        return SummaryResponse(text=descriptionText, model=model)

    def chat(
        self,
        messages: list[OllamaChatMessage],
        tools: list[OllamaToolDefinition] | None = None,
        onPartial: Callable[[str, int], None] | None = None,
    ) -> SummaryResponse:
        model = self._resolveModel()
        payload: OllamaChatRequest = {
            "model": model,
            "messages": messages,
            "options": self._defaultGenerateOptions(),
            "keep_alive": get_keep_alive(),
        }
        payload["think"] = self._think
        if tools:
            payload["tools"] = tools

        log.debug(
            "OllamaClient.chat payload: model=%s messages=%s think=%s tools=%s",
            model,
            messages,
            self._think,
            [tool.get("type") or tool.get("function", {}).get("name") for tool in tools] if tools else None,
        )

        message = None
        if onPartial is None:
            payload["stream"] = False
            log.debug("Starting non-stream /api/chat request for model=%s", model)
            response = _requestJSON(
                self._baseURL,
                "/api/chat",
                "POST",
                self._timeoutSeconds,
                {
                    "Accept": "application/json",
                    "Connection": "keep-alive",
                    "User-Agent": "browser-assistant/0.1",
                },
                payload,
            )
            log.debug("OllamaClient.chat raw response: %s", response)
            typedResponse = _validateGenerateResponse(response, "/api/chat")
            message = typedResponse.get("message")
            chatText = ""
            if isinstance(message, dict):
                chatText = str(message.get("content", "")).strip()
            else:
                chatText = str(typedResponse.get("response", "")).strip()
            thinking_trace = None
            if isinstance(message, dict):
                thinking_value = message.get("thinking")
                if isinstance(thinking_value, str):
                    thinking_trace = thinking_value.strip() or None
            log.debug("OllamaClient.chat parsed message=%s chatText=%r thinking_trace=%s", message, chatText, thinking_trace)
            finalResponse = typedResponse
            metadata = {"raw": typedResponse, "thinking_trace": thinking_trace}
        else:
            log.debug("Starting stream /api/chat request for model=%s", model)
            chatText, finalResponse, thinking_trace = self._requestGenerateStream(payload, onPartial, "/api/chat")
            log.debug("Final generated chat length=%d thinking_trace=%r", len(chatText), thinking_trace)
            if thinking_trace is None and isinstance(finalResponse, dict):
                message = finalResponse.get("message")
                if isinstance(message, dict):
                    thinking_value = message.get("thinking")
                    if isinstance(thinking_value, str):
                        thinking_trace = thinking_value.strip() or None
            metadata = {"raw": finalResponse, "thinking_trace": thinking_trace}

        if not chatText and not _responseHasToolCalls(finalResponse):
            log.debug(
                "Empty chat response detected finalResponse=%s message=%s chatText=%r",
                finalResponse,
                message,
                chatText,
            )
            raise OllamaClientError(
                f"Empty chat response. final_response={{'done': {finalResponse.get('done')}, 'done_reason': {finalResponse.get('done_reason')}}}"
            )
        log.debug("OllamaClient.chat returning chatText=%r thinking_trace=%r metadata_keys=%s", chatText, metadata.get("thinking_trace"), list(metadata.keys()))
        return SummaryResponse(text=chatText, model=model, metadata=metadata)

    def listLocalModels(self) -> list[str]:
        log.debug("Listing local Ollama models")
        return self._listModels()

    def listModelMetadata(self, includeDetails: bool = False) -> tuple[OllamaModelMetadata, ...]:
        names = self.listLocalModels()
        if not includeDetails:
            return tuple(OllamaModelMetadata(name=name) for name in names)
        return tuple(self.getModelMetadata(name) for name in names)

    def listRunningModels(self) -> tuple[str, ...]:
        log.debug("Listing running Ollama models")
        response = _requestJSON(
            self._baseURL,
            "/api/ps",
            "GET",
            self._timeoutSeconds,
            {
                "Accept": "application/json",
                "Connection": "keep-alive",
                "User-Agent": "browser-assistant/0.1",
            },
        )
        typedResponse = cast(OllamaRunningModelsResponse, response)
        models: Any = typedResponse.get("models", [])
        if not isinstance(models, list):
            return tuple()
        names: list[str] = []
        for item in cast(list[Any], models):
            if not isinstance(item, dict):
                continue
            entry = cast(dict[str, Any], item)
            name = str(entry.get("name", "")).strip()
            if name:
                names.append(name)
        return tuple(names)

    def showModel(self, model: str) -> OllamaShowResponse:
        if not model.strip():
            raise OllamaClientError("Model name is required for /api/show.")
        log.debug("Showing Ollama model details model=%s", model.strip())
        response = _requestJSON(
            self._baseURL,
            "/api/show",
            "POST",
            self._timeoutSeconds,
            {
                "Accept": "application/json",
                "Connection": "keep-alive",
                "User-Agent": "browser-assistant/0.1",
            },
            {"model": model.strip()},
        )
        return cast(OllamaShowResponse, response)

    def getModelMetadata(self, model: str) -> OllamaModelMetadata:
        normalized = str(model or "").strip()
        if not normalized:
            raise OllamaClientError("Model name is required for model metadata.")
        return OllamaModelMetadata.from_show_response(normalized, self.showModel(normalized))

    def loadModel(self, model: str | None = None, keepAlive: str | int | None = None):
        modelName = model or self._resolveModel()
        payload: dict[str, Any] = {
            "model": modelName,
            "stream": False,
            "prompt": "",
        }
        if keepAlive is not None:
            payload["keep_alive"] = keepAlive
        log.debug("Loading model %s with keep_alive=%s", modelName, keepAlive)
        response = _requestJSON(
            self._baseURL,
            "/api/generate",
            "POST",
            self._timeoutSeconds,
            {
                "Accept": "application/json",
                "Connection": "keep-alive",
                "User-Agent": "browser-assistant/0.1",
            },
            payload,
        )
        return _validateGenerateResponse(response, "/api/generate")

    def unloadModel(self, model: str | None = None):
        modelName = model or self._resolveModel()
        payload = {
            "model": modelName,
            "stream": False,
            "prompt": "",
            "keep_alive": 0,
        }
        response = _requestJSON(
            self._baseURL,
            "/api/generate",
            "POST",
            self._timeoutSeconds,
            {
                "Accept": "application/json",
                "Connection": "keep-alive",
                "User-Agent": "browser-assistant/0.1",
            },
            payload,
        )
        return _validateGenerateResponse(response, "/api/generate")

    def ensureModelInstalled(
        self,
        model: str | None = None,
        onProgress: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        modelName = self._selectModelName(model)
        if not modelName:
            raise OllamaClientError("A model name is required to ensure model installation.")

        installed = self._listModels()
        normalized = self._normalizeModelNames(installed)
        if modelName.lower() in normalized:
            self._model = normalized[modelName.lower()]
            return self._model

        raise OllamaClientError(
            f"Ollama model \"{modelName}\" not found locally. "
            f"Use 'ollama pull {modelName}' to download it first."
        )

    def _pullModel(
        self,
        model: str,
        onProgress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if not model.strip():
            raise OllamaClientError("Model name is required for /api/pull.")
        payload = {"model": model.strip()}
        log.debug("Pulling Ollama model %s", model)
        response = _requestPullStream(self._baseURL, "/api/pull", self._timeoutSeconds, payload, onProgress)
        errorMessage = str(response.get("error", "")).strip()
        if errorMessage:
            raise OllamaClientError(f"Ollama pull failed for {model}: {errorMessage}")
        return response

    def supportedEndpoints(self) -> tuple[str, ...]:
        return self.SUPPORTED_ENDPOINTS

    def _resolveModel(self) -> str:
        configured = self._configuredModel()
        if configured is not None:
            log.debug("Using configured Ollama model %s", configured)
            return self.ensureModelInstalled(configured)

        return self.ensureModelInstalled()

    def _listModels(self) -> list[str]:
        response = _requestJSON(
            self._baseURL,
            "/api/tags",
            "GET",
            self._timeoutSeconds,
            {
                "Accept": "application/json",
                "Connection": "keep-alive",
                "User-Agent": "browser-assistant/0.1",
            },
        )
        typedResponse = cast(OllamaRunningModelsResponse, response)
        models: Any = typedResponse.get("models", [])
        if not isinstance(models, list):
            return []

        return [
            name.strip()
            for item in cast(list[Any], models)
            if isinstance(item, dict)
            for name in [str(cast(OllamaModelEntry, item).get("name", ""))]
            if name.strip()
        ]

    def _formatHeadings(self, headings: tuple[tuple[int | None, str], ...]) -> str:
        if not headings:
            return "- None"
        lines: list[str] = []
        for level, text in headings:
            if level is None:
                lines.append(f"- {text}")
            else:
                lines.append(f"- H{level}: {text}")
        return "\n".join(lines)

    def _formatList(self, items: tuple[str, ...]) -> str:
        if not items:
            return "- None"
        return "\n".join(f"- {item}" for item in items)

    def _requestGenerateStream(
        self,
        payload: dict[str, Any],
        onPartial: Callable[[str, int], None],
        path: str = "/api/generate",
    ) -> tuple[str, OllamaGenerateResponse, str | None]:
        streamPayload: dict[str, Any] = dict(payload)
        streamPayload["stream"] = True
        if "prompt" in streamPayload:
            streamPayload["prompt"] = str(streamPayload["prompt"])
        payload_types = {key: type(value).__name__ for key, value in streamPayload.items()}
        log.debug("Ollama stream payload shape=%s", payload_types)
        try:
            body = json.dumps(streamPayload).encode("utf-8")
        except (TypeError, ValueError) as error:
            log.exception("Failed to serialize Ollama stream payload: %s", error)
            raise OllamaClientError(
                f"Ollama stream payload is not JSON serializable: {error}. "
                f"Payload keys and types: {payload_types}"
            ) from error
        headers = {
            "Accept": "application/x-ndjson, application/json",
            "Connection": "keep-alive",
            "Content-Type": "application/json",
            "User-Agent": "browser-assistant/0.1",
        }
        request = urllibRequest.Request(
            url=self._baseURL + path,
            data=body,
            headers=headers,
            method="POST",
        )
        lastErrorMessage = ""
        attempts = self._maxRetries + 1

        lastParsed: Any | None = None
        accumulatedToolCalls: list[dict[str, Any]] = []

        def _record_tool_metadata(parsed_response: dict[str, Any]) -> None:
            nonlocal accumulatedToolCalls
            message = parsed_response.get("message")
            if isinstance(message, dict):
                tool_calls = message.get("tool_calls") or message.get("toolCalls")
                if isinstance(tool_calls, list):
                    accumulatedToolCalls.extend([tc for tc in tool_calls if isinstance(tc, dict)])
                function_call = message.get("function_call") or message.get("tool_call")
                if isinstance(function_call, dict):
                    accumulatedToolCalls.append(function_call)
                return

            tool_calls = parsed_response.get("tool_calls") or parsed_response.get("toolCalls")
            if isinstance(tool_calls, list):
                accumulatedToolCalls.extend([tc for tc in tool_calls if isinstance(tc, dict)])
            function_call = parsed_response.get("function_call") or parsed_response.get("tool_call")
            if isinstance(function_call, dict):
                accumulatedToolCalls.append(function_call)

        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            log.debug("Stream request attempt=%d path=%s", attempt, path)
            contentChunks: list[str] = []
            thinkingChunks: list[str] = []
            generatedChars = 0
            emittedPartial = False
            callbackFailed = False

            try:
                with urllibRequest.urlopen(request, timeout=self._timeoutSeconds) as response:
                    while True:
                        rawLine = response.readline()
                        if not rawLine:
                            break

                        try:
                            line = rawLine.decode("utf-8").strip()
                        except UnicodeDecodeError as error:
                            raise OllamaClientError(
                                f"Ollama stream contained non-UTF-8 content for {path}: {error}"
                            )
                        if not line:
                            continue

                        parsed = _validateGenerateResponse(_parseJSON(line, path), path, requireDone=False)
                        _record_tool_metadata(parsed)
                        lastParsed = parsed
                        content_piece = ""
                        message = parsed.get("message")
                        if isinstance(message, dict):
                            thinking_value = message.get("thinking")
                            if isinstance(thinking_value, str) and thinking_value:
                                thinkingChunks.append(thinking_value)

                            content_value = message.get("content")
                            if isinstance(content_value, str) and content_value:
                                contentChunks.append(content_value)
                                content_piece = content_value

                        if not content_piece:
                            content_piece = str(parsed.get("response", ""))
                            if content_piece:
                                contentChunks.append(content_piece)

                        log.debug(
                            "Stream chunk path=%s done=%s response_len=%d",
                            path,
                            parsed.get("done"),
                            len(content_piece),
                        )
                        if content_piece:
                            generatedChars += len(content_piece)
                            emittedPartial = True
                            if not callbackFailed:
                                try:
                                    onPartial(content_piece, generatedChars)
                                except Exception:
                                    log.exception("onPartial callback failed")
                                    callbackFailed = True

                        if parsed.get("done") is True:
                            final_parsed = _attach_accumulated_tool_calls(parsed, accumulatedToolCalls)
                            thinking_trace = "".join(thinkingChunks).strip() or None
                            log.debug("Stream finished path=%s total_chars=%d thinking_trace=%s", path, generatedChars, thinking_trace)
                            return "".join(contentChunks).strip(), final_parsed, thinking_trace
            except urllibError.HTTPError as error:
                details = _readErrorBody(error)
                lastErrorMessage = f"HTTP {error.code}. {details}" if details else f"HTTP {error.code}."
                if emittedPartial or not self._isRetryableStatus(error.code) or attempt >= attempts:
                    raise OllamaClientError(
                        f"Ollama request failed for {path} after {attempt} attempt(s): {lastErrorMessage}"
                    )
            except urllibError.URLError as error:
                reason = getattr(error, "reason", None)
                if self._isTimeoutReason(reason):
                    elapsed = time.monotonic() - started
                    lastErrorMessage = (
                        f"Timed out waiting for response from {self._baseURL}{path} "
                        f"after {elapsed:.1f}s (timeout={self._timeoutSeconds:.1f}s)."
                    )
                else:
                    reasonText = str(reason or error).strip()
                    lastErrorMessage = (
                        f"Unable to reach Ollama at {self._baseURL}. "
                        f"Reason: {reasonText or 'unknown network error'}."
                    )
                if emittedPartial or attempt >= attempts:
                    raise OllamaClientError(lastErrorMessage)
            except socket.timeout:
                elapsed = time.monotonic() - started
                lastErrorMessage = (
                    f"Timed out waiting for response from {self._baseURL}{path} "
                    f"after {elapsed:.1f}s (timeout={self._timeoutSeconds:.1f}s)."
                )
                if emittedPartial or attempt >= attempts:
                    raise OllamaClientError(lastErrorMessage)
            except OSError as error:
                lastErrorMessage = f"Ollama request failed: {error}"
                if emittedPartial or attempt >= attempts:
                    raise OllamaClientError(lastErrorMessage)

            if not lastErrorMessage:
                lastErrorMessage = f"Ollama stream ended before done=true for {path}."
            if emittedPartial or attempt >= attempts:
                if lastParsed is not None:
                    if emittedPartial:
                        partial_response = _attach_accumulated_tool_calls(lastParsed, accumulatedToolCalls)
                        thinking_trace = "".join(thinkingChunks).strip() or None
                        log.debug(
                            "Returning partial stream response after incomplete stream path=%s total_chars=%d",
                            path,
                            generatedChars,
                        )
                        return "".join(contentChunks).strip(), partial_response, thinking_trace
                    log.debug(
                        "Stream terminated with lastParsed=%s",
                        {"done": lastParsed.get("done"), "done_reason": lastParsed.get("done_reason"), "response_len": len(str(lastParsed.get("response", ""))),},
                    )
                raise OllamaClientError(lastErrorMessage)

            time.sleep(self._retryDelaySeconds(attempt))

        raise OllamaClientError(lastErrorMessage or "Ollama stream request failed.")

    def _requestPullStream(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
        onProgress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return _requestPullStream(self._baseURL, path, self._timeoutSeconds, payload, onProgress)

    def _parseJSON(self, raw: str, path: str) -> dict[str, Any]:
        return _parseJSON(raw, path)

    def _extractGenerateText(self, response: dict[str, Any]) -> str:
        return _extractGenerateText(response)

    def _responseHasToolCalls(self, response: dict[str, Any]) -> bool:
        return _responseHasToolCalls(response)

    def _validateGenerateResponse(
        self,
        response: dict[str, Any],
        path: str,
        requireDone: bool = True,
    ) -> OllamaGenerateResponse:
        return _validateGenerateResponse(response, path, requireDone=requireDone)

    def _isRetryableStatus(self, statusCode: int) -> bool:
        return statusCode in {408, 429, 500, 502, 503, 504}

    def _isTimeoutReason(self, reason: object | None) -> bool:
        if isinstance(reason, socket.timeout):
            return True
        reasonText = str(reason or "").strip().lower()
        return "timed out" in reasonText or reasonText == "timeout"

    def _retryDelaySeconds(self, attempt: int) -> float:
        if self._retryBackoffSeconds <= 0:
            return 0.0
        return self._retryBackoffSeconds * (2 ** (attempt - 1))
