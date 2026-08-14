# -*- coding: utf-8 -*-
"""Actionable navigation targets for browser structure results.

Targets are deliberately small, serializable descriptors.  NVDA objects and
TextInfo instances are thread-affine and short-lived, so they must be
resolved again when the user invokes a result action.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
import time
from typing import Any

from .types import AccessibilityGraph, ExtractionStructure


@dataclass(frozen=True, slots=True)
class NavigationTarget:
	"""A useful page destination, without a live NVDA object reference."""

	id: str
	role: str
	name: str
	order: int
	reason: str

	def to_dict(self) -> dict[str, object]:
		return asdict(self)


_IMPORTANT_TERMS = re.compile(
	r"\b(search|find|reply|download|start|getting started|read|article|main|next|previous|github|project|follow|subscribe|submit|buy|apply|login|sign in)\b",
	re.IGNORECASE,
)


def _target_id(role: str, name: str, order: int) -> str:
	value = f"{role}:{name.casefold()}:{order}".encode("utf-8")
	return "nav-" + hashlib.sha256(value).hexdigest()[:12]


def build_navigation_targets(
	structure: ExtractionStructure | None,
	*,
	graph: AccessibilityGraph | None = None,
	max_targets: int = 8,
) -> tuple[NavigationTarget, ...]:
	"""Select a short, deterministic list of likely useful destinations.

	This is intentionally heuristic.  A future ranking model can select from
	these same descriptors, but it must return their IDs rather than inventing
	new destinations.
	"""
	if max_targets <= 0:
		return ()
	if graph is not None and graph.nodes:
		return _build_graph_navigation_targets(graph, max_targets)
	if structure is None:
		return ()
	candidates: list[tuple[int, NavigationTarget]] = []

	def add(role: str, name: str, order: int, score: int, reason: str) -> None:
		name = " ".join(str(name).split()).strip()
		if not name:
			return
		term_bonus = 12 if _IMPORTANT_TERMS.search(name) else 0
		candidates.append(
			(
				score + term_bonus,
				NavigationTarget(_target_id(role, name, order), role, name, order, reason),
			)
		)

	for order, (level, name) in enumerate(structure.headings):
		if level in (1, 2) or order == 0:
			add("heading", name, order, 100 - min(order, 20), "Important page section")
	for order, name in enumerate(structure.landmarks):
		landmark = name.split(":", 1)[0].strip().lower()
		if landmark in {"main", "article", "search", "navigation", "form"}:
			add("landmark", name, order, 78, "Useful page region")
	for order, name in enumerate(structure.inputs):
		add("formField", name, order, 88, "Useful form field")
	for order, name in enumerate(structure.comboboxes):
		add("formField", name, order, 76, "Useful form control")
	for order, name in enumerate(structure.buttons):
		add("button", name, order, 84, "Useful page action")
	for order, name in enumerate(structure.links):
		add("link", name, order, 70, "Useful page link")

	# Preserve page order for equal scores and avoid repeated labels/roles.
	selected: list[NavigationTarget] = []
	seen: set[tuple[str, str]] = set()
	for _score, target in sorted(candidates, key=lambda item: (-item[0], item[1].order)):
		key = (target.role, target.name.casefold())
		if key in seen:
			continue
		seen.add(key)
		selected.append(target)
		if len(selected) >= max_targets:
			break
	return tuple(selected)


def _build_graph_navigation_targets(
	graph: AccessibilityGraph, max_targets: int
) -> tuple[NavigationTarget, ...]:
	candidates: list[tuple[int, NavigationTarget]] = []
	for node in graph.nodes:
		if not node.name or node.role not in {"heading", "landmark", "link", "button", "formField"}:
			continue
		if node.role == "heading":
			score = 100 if node.heading_level in (1, 2) else 65
			reason = "Important page section"
		elif node.role == "formField":
			score, reason = 88, "Useful form field"
		elif node.role == "button":
			score, reason = 84, "Useful page action"
		elif node.role == "landmark":
			score, reason = 78, "Useful page region"
		else:
			score, reason = 70, "Useful page link"
		if _IMPORTANT_TERMS.search(node.name):
			score += 12
		# Keep the concrete control role in the descriptor.  NVDA's
		# ``_iterNodesByType`` cannot resolve an abstract ``formField`` role.
		role = node.control_type if node.role == "formField" and node.control_type else node.role
		candidates.append((score, NavigationTarget(
			f"nav-{node.id}", role, node.name, node.order, reason,
		)))
	selected: list[NavigationTarget] = []
	seen: set[tuple[str, str]] = set()
	for _score, target in sorted(candidates, key=lambda item: (-item[0], item[1].order)):
		key = (target.role, target.name.casefold())
		if key in seen:
			continue
		seen.add(key)
		selected.append(target)
		if len(selected) == max_targets:
			break
	return tuple(selected)


def _tree_interceptor(preferred: object | None = None) -> Any | None:
	if preferred is not None and callable(getattr(preferred, "_iterNodesByType", None)):
		return preferred
	try:
		import api
	except ImportError:
		return None
	for getter in (api.getFocusObject, api.getNavigatorObject, api.getForegroundObject):
		try:
			obj = getter()
			ti = getattr(obj, "treeInterceptor", None)
			if ti is not None and callable(getattr(ti, "_iterNodesByType", None)):
				return ti
		except Exception:
			continue
	return None


def _role_candidates(role: str) -> tuple[object, ...]:
	"""Translate stable descriptor roles to NVDA quick-nav item names."""
	names = {
		"heading": ("heading",),
		"link": ("link",),
		"button": ("button",),
		"landmark": ("landmark",),
		"input": ("edit",),
		"combobox": ("comboBox",),
		"checkbox": ("checkBox",),
		"radio": ("radioButton",),
		# Legacy structure-only descriptors do not carry a concrete type.
		"formField": ("formField",),
	}.get(role, ())
	return names


def _node_label(item: object) -> str:
	"""Return the accessible name exposed by an NVDA quick-nav node."""
	for attribute in ("name", "label", "displayText", "value", "description"):
		try:
			value = getattr(item, attribute, None)
		except Exception:
			continue
		label = " ".join(str(value or "").split())
		if label:
			return label
	return ""


def _restore_browser_focus(ti: object) -> None:
	"""Reactivate the source browser window after the UI host took focus."""
	root = getattr(ti, "rootNVDAObject", None)
	window_handle = getattr(root, "windowHandle", None)
	if window_handle:
		try:
			import ctypes
			import winUser
			# The document often exposes a child WebView handle. Windows requires
			# the top-level owner for reliable foreground activation.
			top_level_handle = int(ctypes.windll.user32.GetAncestor(int(window_handle), 2))
			top_level_handle = top_level_handle or int(window_handle)
			winUser.setForegroundWindow(top_level_handle)
			winUser.setFocus(top_level_handle)
			get_foreground = getattr(winUser, "getForegroundWindow", None)
			if callable(get_foreground):
				deadline = time.monotonic() + 1.0
				while time.monotonic() < deadline and get_foreground() != top_level_handle:
					time.sleep(0.02)
		except Exception:
			# The NVDA object fallback below is still useful for embedded documents.
			pass
	set_focus = getattr(root, "setFocus", None)
	if callable(set_focus):
		set_focus()


def resolve_and_move_target(
	target: dict[str, object], navigation_context: object | None = None
) -> tuple[bool, str]:
	"""Resolve a target on the live NVDA document and move to it."""
	try:
		import textInfos
	except ImportError:
		return False, "NVDA browser navigation is unavailable."
	ti = _tree_interceptor(navigation_context)
	if ti is None:
		return False, "The current window is not an active browser document."
	role = str(target.get("role") or "")
	name = " ".join(str(target.get("name") or "").split()).casefold()
	match_names = {name}
	if role == "landmark" and ":" in name:
		match_names.add(name.split(":", 1)[1].strip())
	try:
		# The one-shot result window owns focus when this action is invoked.
		# Restore the browser window before resolving its text positions.
		_restore_browser_focus(ti)
		position = ti.makeTextInfo(textInfos.POSITION_FIRST)
		role_values = _role_candidates(role)
		if not role_values:
			return False, "Unable to locate that page target. The page may have changed."
		for role_value in role_values:
			items = ti._iterNodesByType(role_value, direction="next", pos=position)
			for item in items:
				raw_label = _node_label(item)
				label = raw_label.casefold()
				if any(candidate == label or (candidate and candidate in label) for candidate in match_names):
					move_to = getattr(item, "moveTo", None)
					if not callable(move_to):
						return False, "Unable to move to that page target. The page may have changed."
					move_to()
					return True, raw_label or str(target.get("name") or "")
	except Exception:
		return False, "Unable to locate that page target. The page may have changed."
	return False, "Unable to locate that page target. The page may have changed."
