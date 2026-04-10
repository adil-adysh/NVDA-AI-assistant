# -*- coding: utf-8 -*-
"""Types for Gemini dependency-free client responses."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypedDict, Union


class PartDict(TypedDict, total=False):
    text: Optional[str]
    role: Optional[str]
    inline_data: Optional[Dict[str, Any]]


@dataclass
class Part:
    """A single content part for Gemini requests.

    Use ``text`` for normal text parts. Use ``data`` and ``mime_type`` for
    inline binary content such as images.
    """
    text: Optional[str] = None
    role: Optional[str] = None
    data: Optional[str] = None
    mime_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.text is not None:
            result["text"] = self.text
        if self.role is not None:
            result["role"] = self.role
        if self.data is not None:
            if self.mime_type is None:
                raise ValueError("mime_type is required when data is provided")
            result["inline_data"] = {
                "data": self.data,
                "mime_type": self.mime_type,
            }
        return result

    @staticmethod
    def from_dict(data: Union[Dict[str, Any], "Part"] | None) -> "Part":
        if data is None:
            return Part()
        if isinstance(data, Part):
            return data
        inline_data = None
        if isinstance(data, dict):
            inline_data = data.get("inline_data")
        if isinstance(inline_data, dict):
            data_value = inline_data.get("data")
            mime_type_value = inline_data.get("mime_type")
        else:
            data_value = data.get("data")
            mime_type_value = data.get("mime_type")
        return Part(
            text=data.get("text"),
            role=data.get("role"),
            data=data_value,
            mime_type=mime_type_value,
        )

    @classmethod
    def from_bytes(cls, data: bytes, mime_type: str, role: Optional[str] = None) -> "Part":
        return cls(
            data=base64.b64encode(data).decode("ascii"),
            mime_type=mime_type,
            role=role,
        )

    @classmethod
    def from_base64(cls, data: str, mime_type: str, role: Optional[str] = None) -> "Part":
        return cls(
            data=data,
            mime_type=mime_type,
            role=role,
        )


class ContentDict(TypedDict, total=False):
    parts: Optional[List[PartDict]]
    role: Optional[str]


@dataclass
class Content:
    parts: List[Part] = field(default_factory=list)
    role: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.parts:
            result["parts"] = [part.to_dict() for part in self.parts]
        if self.role is not None:
            result["role"] = self.role
        return result

    @staticmethod
    def from_dict(data: Union[Dict[str, Any], "Content"] | None) -> "Content":
        if data is None:
            return Content()
        if isinstance(data, Content):
            return data
        parts_data = data.get("parts") or []
        if not parts_data and isinstance(data, dict):
            maybe_part = Part.from_dict(data)
            if maybe_part.text is not None or maybe_part.data is not None:
                parts_data = [data]
        parts: List[Part] = []
        for item in parts_data:
            if isinstance(item, dict):
                parts.append(Part.from_dict(item))
            elif isinstance(item, Part):
                parts.append(item)
        return Content(parts=parts, role=data.get("role"))

    @classmethod
    def from_text(cls, text: str, role: Optional[str] = None) -> "Content":
        return cls(parts=[Part(text=text)], role=role)


class SafetySettingDict(TypedDict, total=False):
    category: Optional[str]
    threshold: Optional[str]


@dataclass
class SafetySetting:
    category: Optional[str] = None
    threshold: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.category is not None:
            result["category"] = self.category
        if self.threshold is not None:
            result["threshold"] = self.threshold
        return result

    @staticmethod
    def from_dict(data: Union[Dict[str, Any], "SafetySetting"] | None) -> "SafetySetting":
        if data is None:
            return SafetySetting()
        if isinstance(data, SafetySetting):
            return data
        return SafetySetting(
            category=data.get("category"),
            threshold=data.get("threshold"),
        )


class GenerateContentConfigDict(TypedDict, total=False):
    temperature: Optional[float]
    top_p: Optional[float]
    top_k: Optional[int]
    candidate_count: Optional[int]
    max_output_tokens: Optional[int]
    stop_sequences: Optional[List[str]]
    response_mime_type: Optional[str]
    response_schema: Optional[Dict[str, Any]]
    response_json_schema: Optional[Dict[str, Any]]
    safety_settings: Optional[List[SafetySettingDict]]
    labels: Optional[Dict[str, str]]


@dataclass
class GenerateContentConfig:
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    candidate_count: Optional[int] = None
    max_output_tokens: Optional[int] = None
    stop_sequences: Optional[List[str]] = None
    response_mime_type: Optional[str] = None
    response_schema: Optional[Dict[str, Any]] = None
    response_json_schema: Optional[Dict[str, Any]] = None
    safety_settings: Optional[List[SafetySetting]] = None
    labels: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.temperature is not None:
            result["temperature"] = self.temperature
        if self.top_p is not None:
            result["topP"] = self.top_p
        if self.top_k is not None:
            result["topK"] = self.top_k
        if self.candidate_count is not None:
            result["candidateCount"] = self.candidate_count
        if self.max_output_tokens is not None:
            result["maxOutputTokens"] = self.max_output_tokens
        if self.stop_sequences is not None:
            result["stopSequences"] = self.stop_sequences
        if self.response_mime_type is not None:
            result["responseMimeType"] = self.response_mime_type
        if self.response_schema is not None:
            result["responseSchema"] = self.response_schema
        if self.response_json_schema is not None:
            result["responseJsonSchema"] = self.response_json_schema
        if self.safety_settings is not None:
            result["safetySettings"] = [setting.to_dict() for setting in self.safety_settings]
        if self.labels is not None:
            result["labels"] = self.labels
        return result


class ModelDict(TypedDict, total=False):
    name: Optional[str]
    baseModelId: Optional[str]
    version: Optional[str]
    displayName: Optional[str]
    description: Optional[str]
    inputTokenLimit: Optional[int]
    outputTokenLimit: Optional[int]
    supportedGenerationMethods: Optional[List[str]]
    thinking: Optional[bool]
    temperature: Optional[float]
    maxTemperature: Optional[float]
    topP: Optional[float]
    topK: Optional[int]


@dataclass
class ModelInfo:
    name: Optional[str] = None
    base_model_id: Optional[str] = None
    version: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    input_token_limit: Optional[int] = None
    output_token_limit: Optional[int] = None
    supported_generation_methods: Optional[List[str]] = None
    thinking: Optional[bool] = None
    temperature: Optional[float] = None
    max_temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(data: Union[Dict[str, Any], "ModelInfo"] | None) -> "ModelInfo":
        if data is None:
            return ModelInfo()
        if isinstance(data, ModelInfo):
            return data
        return ModelInfo(
            name=data.get("name"),
            base_model_id=data.get("baseModelId"),
            version=data.get("version"),
            display_name=data.get("displayName"),
            description=data.get("description"),
            input_token_limit=data.get("inputTokenLimit"),
            output_token_limit=data.get("outputTokenLimit"),
            supported_generation_methods=data.get("supportedGenerationMethods"),
            thinking=data.get("thinking"),
            temperature=data.get("temperature"),
            max_temperature=data.get("maxTemperature"),
            top_p=data.get("topP"),
            top_k=data.get("topK"),
            raw=data,
        )


@dataclass
class ListModelsResponse:
    models: List[ModelInfo] = field(default_factory=list)
    next_page_token: Optional[str] = None

    @staticmethod
    def from_dict(data: Optional[Dict[str, Any]]) -> "ListModelsResponse":
        if not data:
            return ListModelsResponse()
        models_data = data.get("models") or []
        models = [ModelInfo.from_dict(item) for item in models_data if isinstance(item, dict)]
        return ListModelsResponse(
            models=models,
            next_page_token=data.get("nextPageToken"),
        )


class CandidateDict(TypedDict, total=False):
    content: Optional[Dict[str, Any]]
    finish_reason: Optional[str]
    index: Optional[int]
    token_count: Optional[int]


@dataclass
class Candidate:
    content: Optional[Content] = None
    finish_reason: Optional[str] = None
    index: Optional[int] = None
    token_count: Optional[int] = None

    @staticmethod
    def from_dict(data: Union[Dict[str, Any], "Candidate"] | None) -> "Candidate":
        if data is None:
            return Candidate()
        if isinstance(data, Candidate):
            return data
        return Candidate(
            content=Content.from_dict(data.get("content")),
            finish_reason=data.get("finishReason") or data.get("finish_reason"),
            index=data.get("index"),
            token_count=data.get("tokenCount") or data.get("token_count"),
        )

    @property
    def text(self) -> str:
        if not self.content or not self.content.parts:
            return ""
        return "".join(part.text or "" for part in self.content.parts)


class GenerateContentResponseDict(TypedDict, total=False):
    candidates: Optional[List[CandidateDict]]
    modelVersion: Optional[str]
    responseId: Optional[str]
    usageMetadata: Optional[Dict[str, Any]]


@dataclass
class GenerateContentResponse:
    text: str
    raw: Dict[str, Any]
    candidates: List[Candidate] = field(default_factory=list)
    model_version: Optional[str] = None
    response_id: Optional[str] = None
    usage_metadata: Optional[Dict[str, Any]] = None

    @staticmethod
    def from_dict(data: Optional[Dict[str, Any]]) -> "GenerateContentResponse":
        if not data:
            return GenerateContentResponse(text="", raw={})

        candidates_data = data.get("candidates") or []
        candidates: List[Candidate] = []
        for item in candidates_data:
            if isinstance(item, dict):
                candidates.append(Candidate.from_dict(item))
        text = ""
        if candidates:
            text = candidates[0].text
        return GenerateContentResponse(
            text=text,
            raw=data,
            candidates=candidates,
            model_version=data.get("modelVersion"),
            response_id=data.get("responseId"),
            usage_metadata=data.get("usageMetadata"),
        )




ContentInput = Union[str, Part, Content, Dict[str, Any]]
ContentList = Union[ContentInput, List[ContentInput]]
ContentOrDict = Union[Content, Dict[str, Any]]
