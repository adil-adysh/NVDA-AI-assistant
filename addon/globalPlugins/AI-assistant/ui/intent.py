# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Literal, TypedDict

InteractionMode = Literal["display", "chat"]
AttentionPolicy = Literal["none", "foreground_if_background", "activate_and_focus"]
FocusTarget = Literal["content", "composer", "primary_action", "status"]
DisplayVariant = Literal["standard", "result_actions"]
DisplayToolbarAction = Literal["copy_text", "copy_markdown", "clear", "close"]
ToolbarPlacement = Literal["after_content"]

INTERACTION_MODE_DISPLAY: InteractionMode = "display"
INTERACTION_MODE_CHAT: InteractionMode = "chat"

ATTENTION_POLICY_NONE: AttentionPolicy = "none"
ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND: AttentionPolicy = "foreground_if_background"
ATTENTION_POLICY_ACTIVATE_AND_FOCUS: AttentionPolicy = "activate_and_focus"

FOCUS_TARGET_CONTENT: FocusTarget = "content"
FOCUS_TARGET_COMPOSER: FocusTarget = "composer"
FOCUS_TARGET_PRIMARY_ACTION: FocusTarget = "primary_action"
FOCUS_TARGET_STATUS: FocusTarget = "status"

DISPLAY_VARIANT_STANDARD: DisplayVariant = "standard"
DISPLAY_VARIANT_RESULT_ACTIONS: DisplayVariant = "result_actions"

TOOLBAR_ACTION_COPY_TEXT: DisplayToolbarAction = "copy_text"
TOOLBAR_ACTION_COPY_MARKDOWN: DisplayToolbarAction = "copy_markdown"
TOOLBAR_ACTION_CLEAR: DisplayToolbarAction = "clear"
TOOLBAR_ACTION_CLOSE: DisplayToolbarAction = "close"

TOOLBAR_PLACEMENT_AFTER_CONTENT: ToolbarPlacement = "after_content"


class PresentationIntent(TypedDict, total=False):
	interaction_mode: InteractionMode
	controls_visible: bool
	attention_policy: AttentionPolicy
	focus_target: FocusTarget


class DisplayToolbarIntent(TypedDict):
	actions: list[DisplayToolbarAction]
	placement: ToolbarPlacement


class DisplayPresentationIntent(TypedDict, total=False):
	variant: DisplayVariant
	initial_focus: FocusTarget
	toolbar: DisplayToolbarIntent


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


def build_display_presentation(
	*,
	variant: DisplayVariant = DISPLAY_VARIANT_STANDARD,
	initial_focus: FocusTarget | None = None,
	toolbar_actions: tuple[DisplayToolbarAction, ...] | list[DisplayToolbarAction] = (),
	toolbar_placement: ToolbarPlacement = TOOLBAR_PLACEMENT_AFTER_CONTENT,
) -> DisplayPresentationIntent:
	presentation: DisplayPresentationIntent = {
		"variant": variant,
		"toolbar": {
			"actions": [action for action in toolbar_actions],
			"placement": toolbar_placement,
		},
	}
	if initial_focus is not None:
		presentation["initial_focus"] = initial_focus
	return presentation


def merge_display_presentation(
	metadata: dict[str, object] | None = None,
	*,
	variant: DisplayVariant = DISPLAY_VARIANT_STANDARD,
	initial_focus: FocusTarget | None = None,
	toolbar_actions: tuple[DisplayToolbarAction, ...] | list[DisplayToolbarAction] = (),
	toolbar_placement: ToolbarPlacement = TOOLBAR_PLACEMENT_AFTER_CONTENT,
) -> dict[str, object]:
	merged = dict(metadata or {})
	merged["display_presentation"] = build_display_presentation(
		variant=variant,
		initial_focus=initial_focus,
		toolbar_actions=toolbar_actions,
		toolbar_placement=toolbar_placement,
	)
	return merged
