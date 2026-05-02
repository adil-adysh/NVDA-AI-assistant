# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field

from .intent import AttentionPolicy, FocusTarget, InteractionMode


@dataclass(frozen=True, slots=True)
class ResultActionViewModel:
	id: str
	label: str
	kind: str
	payload: dict[str, object] = field(default_factory=dict)

	def to_transport(self) -> dict[str, object]:
		return {
			"id": self.id,
			"label": self.label,
			"kind": self.kind,
			"payload": dict(self.payload),
		}


@dataclass(frozen=True, slots=True)
class DisplayResultViewModel:
	use_case_id: str | None
	title: str
	output_text: str | None = None
	output_html: str | None = None
	is_html: bool = False
	success: bool = True
	message: str | None = None
	close_button: bool = True
	copy_button: bool = True
	copy_text: str | None = None
	copy_markdown: str | None = None
	metadata: dict[str, object] = field(default_factory=dict)
	actions: tuple[ResultActionViewModel, ...] = ()
	interaction_mode: InteractionMode | None = None
	controls_visible: bool | None = None
	attention_policy: AttentionPolicy | None = None
	focus_target: FocusTarget | None = None

	def transport_metadata(self) -> dict[str, object]:
		metadata = dict(self.metadata)
		if self.actions:
			metadata["actions"] = [action.to_transport() for action in self.actions]
		if self.interaction_mode:
			metadata["interaction_mode"] = self.interaction_mode
		if self.controls_visible is not None:
			metadata["controls_visible"] = self.controls_visible
		if self.attention_policy:
			metadata["attention_policy"] = self.attention_policy
		if self.focus_target:
			metadata["focus_target"] = self.focus_target
		return metadata


@dataclass(frozen=True, slots=True)
class ChatWindowViewModel:
	use_case_id: str | None
	title: str
	initial_text: str | None = None
	initial_image_base64: str | None = None
	metadata: dict[str, object] = field(default_factory=dict)
