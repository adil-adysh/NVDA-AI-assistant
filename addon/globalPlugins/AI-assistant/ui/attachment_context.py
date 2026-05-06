# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AttachmentContext:
	image_base64: str | None
	file_context: str
	image_count: int


def extract_attachment_context(
	attachments: list[dict[str, Any]] | None,
	*,
	attached_file_label: str = "Attached file",
) -> AttachmentContext:
	if not isinstance(attachments, list):
		return AttachmentContext(image_base64=None, file_context="", image_count=0)

	image_base64 = None
	image_count = 0
	file_sections: list[str] = []

	for attachment in attachments:
		if not isinstance(attachment, dict):
			continue

		kind = attachment.get("kind")
		name = str(attachment.get("name") or "attachment")
		if kind == "image":
			image_count += 1
			if image_base64 is None:
				candidate = attachment.get("image_base64")
				if isinstance(candidate, str) and candidate.strip():
					image_base64 = candidate.strip()
			continue

		if kind == "file":
			text = attachment.get("text")
			if isinstance(text, str) and text.strip():
				file_sections.append(f"{attached_file_label}: {name}\n{text.strip()}")

	return AttachmentContext(image_base64=image_base64, file_context="\n\n".join(file_sections), image_count=image_count)
