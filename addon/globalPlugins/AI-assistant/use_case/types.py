# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from ..context.types import ContextProfileList, PromptContext


UseCaseId = Literal[
	"summary",
	"structure_summary",
	"describe_image",
	"open_chat",
	"open_chat_with_page_content",
	"open_chat_with_screenshot",
]

SUMMARY: Final[UseCaseId] = "summary"
STRUCTURE_SUMMARY: Final[UseCaseId] = "structure_summary"
DESCRIBE_IMAGE: Final[UseCaseId] = "describe_image"
OPEN_CHAT: Final[UseCaseId] = "open_chat"
OPEN_CHAT_WITH_PAGE_CONTENT: Final[UseCaseId] = "open_chat_with_page_content"
OPEN_CHAT_WITH_SCREENSHOT: Final[UseCaseId] = "open_chat_with_screenshot"


@dataclass(frozen=True, slots=True)
class UseCaseSpec:
	id: UseCaseId
	description: str
	context_profile: ContextProfileList
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
	output_text: str | None = None
	output_html: str | None = None
	is_browseable: bool = False
	error_message: str | None = None
	metadata: dict[str, Any] | None = None
