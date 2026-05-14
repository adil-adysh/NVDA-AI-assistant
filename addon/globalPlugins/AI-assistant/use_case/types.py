# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from ..context.types import ExtractionIntent, PromptContext


UseCaseId = Literal[
	"summary",
	"structure_summary",
	"describe_image",
	"describe_focused_image",
	"open_chat",
	"open_chat_with_page_content",
	"open_chat_with_screenshot",
	"attach_focused_image_to_chat",
]

SUMMARY: Final[UseCaseId] = "summary"
STRUCTURE_SUMMARY: Final[UseCaseId] = "structure_summary"
DESCRIBE_IMAGE: Final[UseCaseId] = "describe_image"
DESCRIBE_FOCUSED_IMAGE: Final[UseCaseId] = "describe_focused_image"
OPEN_CHAT: Final[UseCaseId] = "open_chat"
OPEN_CHAT_WITH_PAGE_CONTENT: Final[UseCaseId] = "open_chat_with_page_content"
OPEN_CHAT_WITH_SCREENSHOT: Final[UseCaseId] = "open_chat_with_screenshot"
ATTACH_FOCUSED_IMAGE_TO_CHAT: Final[UseCaseId] = "attach_focused_image_to_chat"


@dataclass(frozen=True, slots=True)
class UseCaseSpec:
	id: UseCaseId
	description: str
	extraction_intent: ExtractionIntent
	prompt_key: str
	tools: tuple[str, ...] = ()
	requires_input: bool = False
	# If True, the UseCaseResult will carry "result_actions" in metadata,
	# signalling the presenter to show "Open Chat" / "Add to current chat" buttons.
	result_actions: bool = False


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
