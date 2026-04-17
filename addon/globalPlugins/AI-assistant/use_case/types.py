# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..context.types import ContextProfileList, PromptContext

LLMMethod = Literal["summarize", "describe_image", "generate"]
OutputFormat = Literal["text", "html", "markdown"]


@dataclass(frozen=True, slots=True)
class UseCaseSpec:
	id: str
	description: str
	context_profile: ContextProfileList
	prompt_template: str | None = None
	prompt_template_key: str | None = None
	llm_method: LLMMethod | None = None
	tools: tuple[str, ...] = ()
	requires_input: bool = False


@dataclass(frozen=True, slots=True)
class UseCaseResult:
	success: bool
	message: str | None = None
	prompt_context: PromptContext | None = None
	initial_text: str | None = None
	initial_image_base64: str | None = None
	output_format: OutputFormat | None = None
	metadata: dict[str, Any] | None = None
