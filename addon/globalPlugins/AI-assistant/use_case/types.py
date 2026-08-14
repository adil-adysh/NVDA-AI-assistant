# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from ..context.types import ExtractionIntent, PromptContext


UseCaseId = str
"""Stable identifier for a use case, including third-party extensions."""


_BUILTIN_USE_CASE_IDS = Literal[
	"summary",
	"structure_summary",
	"describe_image",
	"describe_focused_image",
	"open_chat",
	"open_chat_with_page_content",
	"open_chat_with_screenshot",
	"attach_focused_image_to_chat",
	"proofread",
]

SUMMARY: Final[UseCaseId] = "summary"
STRUCTURE_SUMMARY: Final[UseCaseId] = "structure_summary"
DESCRIBE_IMAGE: Final[UseCaseId] = "describe_image"
DESCRIBE_FOCUSED_IMAGE: Final[UseCaseId] = "describe_focused_image"
OPEN_CHAT: Final[UseCaseId] = "open_chat"
OPEN_CHAT_WITH_PAGE_CONTENT: Final[UseCaseId] = "open_chat_with_page_content"
OPEN_CHAT_WITH_SCREENSHOT: Final[UseCaseId] = "open_chat_with_screenshot"
ATTACH_FOCUSED_IMAGE_TO_CHAT: Final[UseCaseId] = "attach_focused_image_to_chat"
PROOFREAD: Final[UseCaseId] = "proofread"


@dataclass(frozen=True, slots=True)
class ResultContextItem:
	"""A use-case input/context artifact that can be added to a conversation.

	``id`` is a stable capability id (for example ``"page_content"``,
	``"page_structure"``, ``"screenshot"``, ``"focused_image"``) used to derive
	the result action id (``add_{id}_to_chat``) and its user-facing label.

	Context items are conversation *user/context material*, never
	assistant-generated answers.
	"""

	id: str
	content: str | None = None
	image_base64: str | None = None


@dataclass(frozen=True, slots=True)
class ResultOutputItem:
	"""A use-case output artifact that can be added to a conversation.

	``id`` is a stable capability id (for example ``"summary"``,
	``"structure_summary"``, ``"image_description"``,
	``"focused_image_description"``).

	Output items are assistant-generated results and must keep the assistant
	message role when seeded into a conversation.
	"""

	id: str
	content: str


@dataclass(frozen=True, slots=True)
class UseCaseSpec:
	id: UseCaseId
	description: str
	extraction_intent: ExtractionIntent
	prompt_key: str
	tools: tuple[str, ...] = ()
	requires_input: bool = False
	# If True, the UseCaseResult will carry "result_actions" in metadata,
	# signalling the presenter to build context/output result actions.
	result_actions: bool = False
	# Context reduction is declared by the use case so orchestration does not
	# need use-case-ID conditionals.
	context_policy: str = "none"
	context_token_budget: int | None = None


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
	# Structured, data-driven result actions: context items are user-side
	# material, output items are assistant results.  The presenter derives
	# "Add X to Chat" / "Open in New Chat" actions from these.
	context_items: tuple[ResultContextItem, ...] = ()
	output_items: tuple[ResultOutputItem, ...] = ()
