# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..context.types import PromptContext


@dataclass(frozen=True, slots=True)
class UseCaseSpec:
	id: str
	description: str
	context_profile: tuple[str, ...]
	prompt_key: str
	tools: tuple[str, ...] = ()
	requires_input: bool = False


@dataclass(frozen=True, slots=True)
class UseCaseResult:
	success: bool
	message: str | None = None
	prompt_context: PromptContext | None = None
	initial_text: str | None = None
	initial_image_base64: str | None = None
	metadata: dict[str, Any] | None = None
