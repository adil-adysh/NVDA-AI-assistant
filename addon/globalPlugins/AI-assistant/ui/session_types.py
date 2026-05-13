# -*- coding: utf-8 -*-
"""Session state type definitions (TypedDicts only).

See ``docs/specs/presentation-intent.md`` for how these types relate
to presentation metadata.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

from .intent import AttentionPolicy, FocusTarget, InteractionMode

Translator = Callable[[str], str]


class SessionProviderInfo(TypedDict):
	provider: str
	model: str


class SessionProviderOption(TypedDict):
	id: str
	label: str


class SessionProviderStatus(TypedDict, total=False):
	state: str
	reason: str
	can_infer: bool
	can_list_models: bool


class SessionConversationSummary(TypedDict):
	id: str
	title: str
	preview: str
	message_count: int
	updated_at: float


class UISessionMetadata(TypedDict, total=False):
	conversation_id: str
	provider_state: SessionProviderInfo
	provider_status: SessionProviderStatus
	available_providers: list[SessionProviderOption]
	available_models: list[str]
	conversation_summaries: list[SessionConversationSummary]
	localized_strings: dict[str, str]
	think_enabled: bool
	chat_enabled: bool
	status_message: str
	interaction_mode: InteractionMode
	controls_visible: bool
	attention_policy: AttentionPolicy
	focus_target: FocusTarget
