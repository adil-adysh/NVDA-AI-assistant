# -*- coding: utf-8 -*-
import json
import logging
import socket
import time
from collections.abc import Callable
from typing import Any, TypedDict, cast
from urllib import error as urllibError
from urllib import request as urllibRequest

from . import defaults
from .models import PageSnapshot, SummaryResponse
from .settings import (
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

logger = logging.getLogger(__name__)



class OllamaModelEntry(TypedDict):
    name: str


class OllamaTagsResponse(TypedDict, total=False):
    models: list[OllamaModelEntry]


class OllamaGenerateResponse(TypedDict, total=False):
    model: str
    created_at: str
    response: str
    done: bool
    done_reason: str
    context: list[int]
    total_duration: int
    load_duration: int
    prompt_eval_count: int
    prompt_eval_duration: int
    eval_count: int
    eval_duration: int


class OllamaRunningModel(TypedDict, total=False):
    name: str
    model: str
    size: int
    digest: str
    expires_at: str
    size_vram: int


class OllamaRunningModelsResponse(TypedDict, total=False):
    models: list[OllamaRunningModel]


class OllamaShowResponse(TypedDict, total=False):
    modelfile: str
    parameters: str
    template: str
    details: dict[str, Any]
    model_info: dict[str, Any]


class OllamaErrorResponse(TypedDict, total=False):
    error: str


class OllamaClientError(RuntimeError):
    pass


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

    def __init__(self, baseURL: str | None = None, model: str | None = None, timeoutSeconds: float | None = None):
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
        logger.debug(
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
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "options": self._defaultGenerateOptions(),
            "keep_alive": get_keep_alive(),
        }

        promptLength = len(payload["prompt"])
        logger.debug("Prompt length=%d", promptLength)

        if onPartial is None:
            payload["stream"] = False
            logger.debug("Starting non-stream /api/generate request for model=%s", model)
            response = self._requestJSON("POST", "/api/generate", payload)
            logger.debug("Raw response: %s", response)
            typedResponse = self._validateGenerateResponse(response, "/api/generate")
            summaryText = str(typedResponse.get("response", "")).strip()
            finalResponse = typedResponse
        else:
            logger.debug("Starting stream /api/generate request for model=%s", model)
            summaryText, finalResponse = self._requestGenerateStream(payload, onPartial)
            logger.debug("Final generated summary length=%d", len(summaryText))

        if not summaryText:
            logger.debug(
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
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "images": [imageBase64],
            "options": self._defaultGenerateOptions(),
            "keep_alive": get_keep_alive(),
        }

        if onPartial is None:
            payload["stream"] = False
            logger.debug("Starting non-stream image generate request for model=%s", model)
            response = self._requestJSON("POST", "/api/generate", payload)
            typedResponse = self._validateGenerateResponse(response, "/api/generate")
            descriptionText = str(typedResponse.get("response", "")).strip()
            finalResponse = typedResponse
        else:
            logger.debug("Starting stream image generate request for model=%s", model)
            descriptionText, finalResponse = self._requestGenerateStream(payload, onPartial)
            logger.debug("Final generated description length=%d", len(descriptionText))

        if not descriptionText:
            logger.debug(
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

    def listLocalModels(self) -> list[str]:
        logger.debug("Listing local Ollama models")
        return self._listModels()

    def listRunningModels(self) -> tuple[str, ...]:
        logger.debug("Listing running Ollama models")
        response = self._requestJSON("GET", "/api/ps")
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
        logger.debug("Showing Ollama model details model=%s", model.strip())
        response = self._requestJSON("POST", "/api/show", {"model": model.strip()})
        return cast(OllamaShowResponse, response)

    def loadModel(self, model: str | None = None, keepAlive: str | int | None = None):
        modelName = model or self._resolveModel()
        payload: dict[str, Any] = {
            "model": modelName,
            "stream": False,
            "prompt": "",
        }
        if keepAlive is not None:
            payload["keep_alive"] = keepAlive
        logger.debug("Loading model %s with keep_alive=%s", modelName, keepAlive)
        response = self._requestJSON("POST", "/api/generate", payload)
        return self._validateGenerateResponse(response, "/api/generate")

    def unloadModel(self, model: str | None = None):
        modelName = model or self._resolveModel()
        payload = {
            "model": modelName,
            "stream": False,
            "prompt": "",
            "keep_alive": 0,
        }
        response = self._requestJSON("POST", "/api/generate", payload)
        return self._validateGenerateResponse(response, "/api/generate")

    def ensureModelInstalled(self, model: str | None = None, onProgress: Callable[[dict[str, Any]], None] | None = None) -> str:
        modelName = self._selectModelName(model)
        if not modelName:
            raise OllamaClientError("A model name is required to ensure model installation.")

        installed = self._listModels()
        normalized = self._normalizeModelNames(installed)
        if modelName.lower() in normalized:
            self._model = normalized[modelName.lower()]
            return self._model

        logger.info("Ollama model %s not installed; pulling it now.", modelName)
        self._pullModel(modelName, onProgress=onProgress)

        installed = self._listModels()
        normalized = self._normalizeModelNames(installed)
        if modelName.lower() not in normalized:
            raise OllamaClientError(f"Ollama model {modelName} could not be installed.")

        self._model = normalized[modelName.lower()]
        return self._model

    def _pullModel(self, model: str, onProgress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        if not model.strip():
            raise OllamaClientError("Model name is required for /api/pull.")
        payload = {"model": model.strip()}
        logger.debug("Pulling Ollama model %s", model)
        response = self._requestPullStream("POST", "/api/pull", payload, onProgress)
        errorMessage = str(response.get("error", "")).strip()
        if errorMessage:
            raise OllamaClientError(f"Ollama pull failed for {model}: {errorMessage}")
        return response

    def supportedEndpoints(self) -> tuple[str, ...]:
        return self.SUPPORTED_ENDPOINTS

    def _resolveModel(self) -> str:
        configured = self._configuredModel()
        if configured is not None:
            logger.debug("Using configured Ollama model %s", configured)
            return self.ensureModelInstalled(configured)

        return self.ensureModelInstalled()

    def _listModels(self) -> list[str]:
        response = self._requestJSON("GET", "/api/tags")
        typedResponse = cast(OllamaTagsResponse, response)
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

    def _requestJSON(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None
        headers = {
            "Accept": "application/json",
            "Connection": "keep-alive",
            "User-Agent": "browser-assistant/0.1",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllibRequest.Request(
            url=self._baseURL + path,
            data=body,
            headers=headers,
            method=method,
        )
        lastErrorMessage = ""
        attempts = self._maxRetries + 1

        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            logger.debug("HTTPRequest attempt=%d method=%s path=%s", attempt, method, path)
            try:
                with urllibRequest.urlopen(request, timeout=self._timeoutSeconds) as response:
                    try:
                        raw = response.read().decode("utf-8")
                    except UnicodeDecodeError as error:
                        raise OllamaClientError(
                            f"Ollama returned non-UTF-8 content for {path}: {error}"
                        )
                    logger.debug("HTTPRequest succeeded method=%s path=%s bytes=%d", method, path, len(raw))
                return self._parseJSON(raw, path)
            except urllibError.HTTPError as error:
                details = self._readErrorBody(error)
                lastErrorMessage = f"HTTP {error.code}. {details}" if details else f"HTTP {error.code}."
                if not self._isRetryableStatus(error.code) or attempt >= attempts:
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
                if attempt >= attempts:
                    raise OllamaClientError(lastErrorMessage)
            except socket.timeout:
                elapsed = time.monotonic() - started
                lastErrorMessage = (
                    f"Timed out waiting for response from {self._baseURL}{path} "
                    f"after {elapsed:.1f}s (timeout={self._timeoutSeconds:.1f}s)."
                )
                if attempt >= attempts:
                    raise OllamaClientError(lastErrorMessage)
            except OSError as error:
                lastErrorMessage = f"Ollama request failed: {error}"
                if attempt >= attempts:
                    raise OllamaClientError(lastErrorMessage)

            time.sleep(self._retryDelaySeconds(attempt))

        raise OllamaClientError(lastErrorMessage or "Ollama request failed.")

    def _requestGenerateStream(
        self,
        payload: dict[str, Any],
        onPartial: Callable[[str, int], None],
    ) -> tuple[str, OllamaGenerateResponse]:
        path = "/api/generate"
        streamPayload: dict[str, Any] = dict(payload)
        streamPayload["stream"] = True
        body = json.dumps(streamPayload).encode("utf-8")
        headers = {
            "Accept": "application/json",
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
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            logger.debug("Stream request attempt=%d path=%s", attempt, path)
            chunks: list[str] = []
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

                        parsed = self._validateGenerateResponse(self._parseJSON(line, path), path, requireDone=False)
                        lastParsed = parsed
                        logger.debug(
                            "Stream chunk path=%s done=%s response_len=%d",
                            path,
                            parsed.get("done"),
                            len(str(parsed.get("response", ""))),
                        )
                        piece = str(parsed.get("response", ""))
                        if piece:
                            chunks.append(piece)
                            generatedChars += len(piece)
                            emittedPartial = True
                            if not callbackFailed:
                                try:
                                    onPartial(piece, generatedChars)
                                except Exception:
                                    logger.exception("onPartial callback failed")
                                    callbackFailed = True

                        if parsed.get("done") is True:
                            logger.debug("Stream finished path=%s total_chars=%d", path, generatedChars)
                            return "".join(chunks).strip(), parsed
            except urllibError.HTTPError as error:
                details = self._readErrorBody(error)
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
                    logger.debug(
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
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/x-ndjson",
            "Connection": "keep-alive",
            "Content-Type": "application/json",
            "User-Agent": "browser-assistant/0.1",
        }
        request = urllibRequest.Request(
            url=self._baseURL + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllibRequest.urlopen(request, timeout=self._timeoutSeconds) as response:
                lastParsed: dict[str, Any] = {}
                while True:
                    rawLine = response.readline()
                    if not rawLine:
                        break
                    try:
                        line = rawLine.decode("utf-8").strip()
                    except UnicodeDecodeError as error:
                        raise OllamaClientError(
                            f"Ollama pull stream contained non-UTF-8 content for {path}: {error}"
                        )
                    if not line:
                        continue
                    parsed = self._parseJSON(line, path)
                    errorMessage = str(parsed.get("error", "")).strip()
                    if errorMessage:
                        raise OllamaClientError(f"Ollama pull failed for {path}: {errorMessage}")
                    if onProgress is not None:
                        try:
                            onProgress(parsed)
                        except Exception:
                            logger.exception("onProgress callback failed")
                    lastParsed = parsed
                return lastParsed
        except urllibError.HTTPError as error:
            details = self._readErrorBody(error)
            raise OllamaClientError(f"Ollama request failed for {path}: HTTP {error.code}. {details}")
        except urllibError.URLError as error:
            reason = getattr(error, "reason", None)
            if self._isTimeoutReason(reason):
                raise OllamaClientError(
                    f"Timed out waiting for response from {self._baseURL}{path} "
                    f"after {self._timeoutSeconds:.1f}s (timeout={self._timeoutSeconds:.1f}s)."
                )
            raise OllamaClientError(
                f"Unable to reach Ollama at {self._baseURL}. "
                f"Reason: {str(reason or error).strip() or 'unknown network error'}."
            )
        except socket.timeout:
            raise OllamaClientError(
                f"Timed out waiting for response from {self._baseURL}{path} "
                f"after {self._timeoutSeconds:.1f}s (timeout={self._timeoutSeconds:.1f}s)."
            )
        except OSError as error:
            raise OllamaClientError(f"Ollama request failed: {error}")

    def _parseJSON(self, raw: str, path: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            snippet = raw[:240].strip().replace("\n", " ")
            if snippet:
                raise OllamaClientError(
                    f"Ollama returned invalid JSON for {path}: {error}. Response starts with: {snippet}"
                )
            raise OllamaClientError(f"Ollama returned invalid JSON for {path}: {error}")

        if not isinstance(parsed, dict):
            raise OllamaClientError(f"Ollama returned an unexpected response payload for {path}.")
        return cast(dict[str, Any], parsed)

    def _validateGenerateResponse(
        self,
        response: dict[str, Any],
        path: str,
        requireDone: bool = True,
    ) -> OllamaGenerateResponse:
        typedResponse = cast(OllamaGenerateResponse, response)
        errorMessage = str(response.get("error", "")).strip()
        if errorMessage:
            raise OllamaClientError(f"Ollama returned an error for {path}: {errorMessage}")
        if requireDone and typedResponse.get("done") is not True:
            raise OllamaClientError("Ollama returned an incomplete non-stream response (done=false).")
        return typedResponse

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

    def _readErrorBody(self, error: urllibError.HTTPError) -> str:
        try:
            raw = error.read().decode("utf-8").strip()
        except Exception:
            raw = ""
        if not raw:
            return ""

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw[:500]

        if isinstance(parsed, dict):
            typed = cast(OllamaErrorResponse, parsed)
            message = str(typed.get("error", "")).strip()
            if message:
                return message
        return raw[:500]
