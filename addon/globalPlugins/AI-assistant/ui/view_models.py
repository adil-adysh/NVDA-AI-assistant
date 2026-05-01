# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field


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

	def transport_metadata(self) -> dict[str, object]:
		metadata = dict(self.metadata)
		if self.actions:
			metadata["actions"] = [action.to_transport() for action in self.actions]
		return metadata


@dataclass(frozen=True, slots=True)
class ChatWindowViewModel:
	use_case_id: str | None
	title: str
	initial_text: str | None = None
	initial_image_base64: str | None = None
	metadata: dict[str, object] = field(default_factory=dict)
