# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Literal, TypedDict

InteractionMode = Literal["display", "chat", "result_action_only"]
AttentionPolicy = Literal["none", "foreground_if_background", "activate_and_focus"]
FocusTarget = Literal["content", "composer", "first_result_action", "status"]

INTERACTION_MODE_DISPLAY: InteractionMode = "display"
INTERACTION_MODE_CHAT: InteractionMode = "chat"
INTERACTION_MODE_RESULT_ACTION_ONLY: InteractionMode = "result_action_only"

ATTENTION_POLICY_NONE: AttentionPolicy = "none"
ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND: AttentionPolicy = "foreground_if_background"
ATTENTION_POLICY_ACTIVATE_AND_FOCUS: AttentionPolicy = "activate_and_focus"

FOCUS_TARGET_CONTENT: FocusTarget = "content"
FOCUS_TARGET_COMPOSER: FocusTarget = "composer"
FOCUS_TARGET_FIRST_RESULT_ACTION: FocusTarget = "first_result_action"
FOCUS_TARGET_STATUS: FocusTarget = "status"


class PresentationIntent(TypedDict, total=False):
	interaction_mode: InteractionMode
	controls_visible: bool
	attention_policy: AttentionPolicy
	focus_target: FocusTarget


def build_presentation_intent(
	*,
	interaction_mode: InteractionMode | None = None,
	controls_visible: bool | None = None,
	attention_policy: AttentionPolicy | None = None,
	focus_target: FocusTarget | None = None,
) -> PresentationIntent:
	intent: PresentationIntent = {}
	if interaction_mode is not None:
		intent["interaction_mode"] = interaction_mode
	if controls_visible is not None:
		intent["controls_visible"] = controls_visible
	if attention_policy is not None:
		intent["attention_policy"] = attention_policy
	if focus_target is not None:
		intent["focus_target"] = focus_target
	return intent


def merge_presentation_intent(
	metadata: dict[str, object] | None = None,
	*,
	interaction_mode: InteractionMode | None = None,
	controls_visible: bool | None = None,
	attention_policy: AttentionPolicy | None = None,
	focus_target: FocusTarget | None = None,
) -> dict[str, object]:
	merged = dict(metadata or {})
	merged.update(
		build_presentation_intent(
			interaction_mode=interaction_mode,
			controls_visible=controls_visible,
			attention_policy=attention_policy,
			focus_target=focus_target,
		)
	)
	return merged
