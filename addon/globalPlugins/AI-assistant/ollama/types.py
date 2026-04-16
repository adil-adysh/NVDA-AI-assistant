# -*- coding: utf-8 -*-
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


class OllamaErrorResponse(TypedDict, total=False):
    error: str
