# -*- coding: utf-8 -*-
"""Persistence for captured accessibility graphs.

The ``.ag`` format is versioned JSON and contains no live NVDA objects.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any

from .types import AccessibilityGraph

GRAPH_SCHEMA_VERSION = 1
GRAPH_FILE_EXTENSION = ".ag"


def accessibility_graph_directory() -> Path:
	appdata = os.getenv("APPDATA")
	base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
	directory = base / "nvda" / "AIAssistant" / "accessibility_graphs"
	directory.mkdir(parents=True, exist_ok=True)
	return directory


def serialize_accessibility_graph(
	graph: AccessibilityGraph,
	*,
	captured_at: datetime | None = None,
	title: str = "",
	app_title: str = "",
	source: str = "",
) -> dict[str, Any]:
	if captured_at is None:
		captured_at = datetime.now(timezone.utc)
	if captured_at.tzinfo is None:
		captured_at = captured_at.replace(tzinfo=timezone.utc)
	return {
		"schema_version": GRAPH_SCHEMA_VERSION,
		"captured_at": captured_at.astimezone(timezone.utc).isoformat(),
		"source": source,
		"title": title,
		"app_title": app_title,
		"graph": {
			"nodes": [
				{
					"id": node.id, "role": node.role, "name": node.name,
					"order": node.order, "parent_id": node.parent_id, "text": node.text,
					"heading_level": node.heading_level, "landmark": node.landmark,
					"control_type": node.control_type,
				}
				for node in graph.nodes
			],
			"sections": [
				{
					"id": section.id, "title": section.title, "text": section.text,
					"order": section.order, "heading_node_id": section.heading_node_id,
					"node_ids": list(section.node_ids),
				}
				for section in graph.sections
			],
		},
	}


def _new_graph_filename(now: datetime | None = None) -> str:
	if now is None:
		now = datetime.now()
	return f"accessibility-{now.strftime('%Y%m%d-%H%M%S-%f')}{GRAPH_FILE_EXTENSION}"


def save_accessibility_graph(
	graph: AccessibilityGraph,
	*,
	directory: Path | None = None,
	filename: str | None = None,
	captured_at: datetime | None = None,
	title: str = "",
	app_title: str = "",
	source: str = "",
) -> Path:
	destination_dir = (directory or accessibility_graph_directory()).resolve()
	destination_dir.mkdir(parents=True, exist_ok=True)
	if filename is None:
		filename = _new_graph_filename(captured_at)
	if not re.fullmatch(r"[A-Za-z0-9._-]+\.ag", filename, re.IGNORECASE):
		raise ValueError("Accessibility graph filename must be a simple .ag filename")
	destination = destination_dir / filename
	payload = serialize_accessibility_graph(
		graph, captured_at=captured_at, title=title, app_title=app_title, source=source,
	)
	temporary = destination_dir / f".{filename}.{uuid.uuid4().hex}.tmp"
	try:
		with temporary.open("w", encoding="utf-8", newline="\n") as stream:
			json.dump(payload, stream, ensure_ascii=False, indent=2)
			stream.write("\n")
		os.replace(temporary, destination)
	except Exception:
		try:
			temporary.unlink(missing_ok=True)
		except OSError:
			pass
		raise
	return destination
