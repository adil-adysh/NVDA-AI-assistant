# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
from typing import Any, TypedDict


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


class OllamaFunction(TypedDict, total=False):
    name: str
    arguments: dict[str, Any]
    index: int


class OllamaToolCall(TypedDict, total=False):
    type: str
    function: OllamaFunction


class OllamaChatMessage(TypedDict, total=False):
    role: str
    content: str
    images: list[str]
    tool_name: str
    tool_calls: list[OllamaToolCall]


class OllamaToolDefinition(TypedDict, total=False):
    type: str
    function: OllamaFunction


class OllamaChatRequest(TypedDict, total=False):
    model: str
    messages: list[OllamaChatMessage]
    stream: bool
    think: bool
    options: dict[str, Any]
    keep_alive: str
    tools: list[OllamaToolDefinition]


class OllamaMessageResponse(TypedDict, total=False):
    role: str
    content: str
    thinking: str
    tool_calls: list[OllamaToolCall]


class OllamaChatResponse(OllamaGenerateResponse, total=False):
    message: OllamaMessageResponse


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


@dataclass(frozen=True)
class OllamaModelMetadata:
    name: str
    details: dict[str, Any] = field(default_factory=dict)
    model_info: dict[str, Any] = field(default_factory=dict)
    parameter_defaults: dict[str, str] = field(default_factory=dict)
    modelfile: str = ""
    template: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_show_response(name: str, response: OllamaShowResponse | None = None) -> "OllamaModelMetadata":
        payload = dict(response or {})
        parameters = OllamaModelMetadata._parse_parameter_defaults(str(payload.get("parameters", "")))
        details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        model_info = payload.get("model_info") if isinstance(payload.get("model_info"), dict) else {}
        return OllamaModelMetadata(
            name=str(name or "").strip(),
            details=dict(details),
            model_info=dict(model_info),
            parameter_defaults=parameters,
            modelfile=str(payload.get("modelfile", "") or ""),
            template=str(payload.get("template", "") or ""),
            raw=payload,
        )

    @staticmethod
    def _parse_parameter_defaults(parameters: str) -> dict[str, str]:
        parsed: dict[str, str] = {}
        for raw_line in parameters.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            key, _, value = line.partition(" ")
            if not key or not value:
                continue
            parsed[key.strip()] = value.strip()
        return parsed


class OllamaErrorResponse(TypedDict, total=False):
    error: str
