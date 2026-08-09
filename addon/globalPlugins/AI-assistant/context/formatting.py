# -*- coding: utf-8 -*-
"""User-facing formatting of extracted context for conversation seeding.

These helpers produce readable, translatable-neutral text blocks that can be
placed into chat user/context messages.  They intentionally do not know about
conversations, prompts, or providers — they only render extracted context
data into text.
"""
from __future__ import annotations

from typing import Any

from .types import ExtractionStructure


def format_page_context(title: str | None, app_title: str | None, text: str) -> str:
	"""Render page content as a readable context block for a chat message.

	Matches the composer preload format used by ``open_chat_with_page_content``
	so context seeded from a result is consistent with direct chat opening.
	"""
	lines = ["Page content:"]
	if title:
		lines.append(f"Title: {title}")
	if app_title:
		lines.append(f"App: {app_title}")
	if lines[-1] != "Page content:":
		lines.append("")
	lines.append(text)
	return "\n".join(lines).strip()


def has_page_structure_data(structure: ExtractionStructure | None) -> bool:
	"""Return True when *structure* carries at least one extracted element."""
	if structure is None:
		return False
	return bool(
		structure.headings
		or structure.links
		or structure.buttons
		or structure.landmarks
		or structure.inputs
		or structure.comboboxes
		or structure.checkboxes
		or structure.radios
	)


def format_page_structure(structure: ExtractionStructure | None) -> str | None:
	"""Render page structure as a readable context block, or None when empty."""
	if structure is None or not has_page_structure_data(structure):
		return None

	lines = ["Page structure:"]
	headings = structure.headings
	if headings:
		lines.append("Headings:")
		for level, heading in headings:
			label = f"H{level}" if level is not None else ""
			lines.append(f"- {label + ': ' if label else ''}{heading}")
	for name, items in (
		("Landmarks", structure.landmarks),
		("Links", structure.links),
		("Buttons", structure.buttons),
		("Inputs", structure.inputs),
		("Combo boxes", structure.comboboxes),
		("Checkboxes", structure.checkboxes),
		("Radio buttons", structure.radios),
	):
		if items:
			lines.append(f"{name}:")
			lines.extend(f"- {item}" for item in items)
	return "\n".join(lines).strip()


def format_focus_capture_text(metadata: dict[str, Any] | None) -> str:
	"""Render focused-object capture metadata as a readable context block."""
	metadata = metadata or {}
	lines = []
	object_role = metadata.get("object_role")
	if object_role:
		lines.append(f"Focused element role: {object_role}")
	object_name = metadata.get("object_name")
	if object_name:
		lines.append(f"Name: {object_name}")
	app_name = metadata.get("app_name")
	if app_name:
		lines.append(f"Application: {app_name}")
	window_title = metadata.get("window_title")
	if window_title:
		lines.append(f"Window: {window_title}")
	return "\n".join(lines).strip()
