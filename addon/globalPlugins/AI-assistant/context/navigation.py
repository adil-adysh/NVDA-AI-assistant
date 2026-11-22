# -*- coding: utf-8 -*-
"""Actionable navigation targets for browser structure results.

Targets are deliberately small, serializable descriptors.  NVDA objects and
TextInfo instances are thread-affine and short-lived, so they must be
resolved again when the user invokes a result action.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from ..core.translation import _

try:
	from .types import AccessibilityGraph, ExtractionStructure
except ImportError:  # Lightweight synthetic test packages may omit type exports.
	AccessibilityGraph = Any  # type: ignore[misc,assignment]
	ExtractionStructure = Any  # type: ignore[misc,assignment]


@dataclass(frozen=True, slots=True)
class NavigationTarget:
	"""A useful page destination, without a live NVDA object reference."""

	id: str
	role: str
	name: str
	order: int
	reason: str
	score: int = 0
	kind: str = "action"
	source_node_id: str | None = None
	section_id: str | None = None
	ancestor_names: tuple[str, ...] = ()
	occurrence: int = 0
	context_text: str = ""
	parent_name: str = ""
	child_names: tuple[str, ...] = ()

	def to_dict(self) -> dict[str, object]:
		# Ranking is an internal selection detail; do not expose it through the
		# result-action/UI payload.
		return {
			"id": self.id,
			"kind": self.kind,
			"role": self.role,
			"name": self.name,
			"order": self.order,
			"reason": self.reason,
			"source_node_id": self.source_node_id,
			"section_id": self.section_id,
			"ancestor_names": list(self.ancestor_names),
			"occurrence": self.occurrence,
			"context_text": self.context_text,
			"parent_name": self.parent_name,
			"child_names": list(self.child_names),
		}


def _compact_context(text: str, max_length: int = 240) -> str:
	text = " ".join(str(text or "").split()).strip()
	if len(text) <= max_length:
		return text
	return text[: max_length - 1].rsplit(" ", 1)[0] + "…"


def _target_id(role: str, name: str, order: int) -> str:
	value = f"{role}:{name.casefold()}:{order}".encode("utf-8")
	return "nav-" + hashlib.sha256(value).hexdigest()[:12]


def build_navigation_targets(
	structure: ExtractionStructure | None = None,
	*,
	graph: AccessibilityGraph | None = None,
	max_targets: int = 8,
) -> tuple[NavigationTarget, ...]:
	"""Select a short, deterministic list of likely useful destinations.

	This is intentionally heuristic.  A future ranking model can select from
	these same descriptors, but it must return their IDs rather than inventing
	new destinations.
	"""
	return select_navigation_targets(
		build_navigation_candidates(structure, graph=graph), max_targets=max_targets,
	)


def build_llm_navigation_candidates(
	structure: ExtractionStructure | None = None,
	*,
	graph: AccessibilityGraph | None = None,
	max_candidates: int = 256,
) -> tuple[NavigationTarget, ...]:
	"""Build a bounded, coverage-oriented inventory for LLM selection.

	This deliberately does not try to decide which page targets are important.
	It preserves section coverage and role diversity, leaving semantic selection
	to the model while keeping prompt size bounded.
	"""
	if max_candidates <= 0:
		return ()
	candidates = build_navigation_candidates(structure, graph=graph)
	if len(candidates) <= max_candidates:
		return candidates

	selected: list[NavigationTarget] = []
	selected_ids: set[str] = set()
	# Reserve space for section destinations so the LLM can see the page outline.
	section_targets = [target for target in candidates if target.kind == "section"]
	for target in section_targets[: max_candidates // 3]:
		selected.append(target)
		selected_ids.add(target.id)

	# Then cover sections and control roles in source order. This is a recall
	# strategy, not an importance ranking.
	for target in candidates:
		if len(selected) >= max_candidates:
			break
		if target.id in selected_ids:
			continue
		selected.append(target)
		selected_ids.add(target.id)
	return tuple(selected)


def build_navigation_candidates(
	structure: ExtractionStructure | None = None,
	*,
	graph: AccessibilityGraph | None = None,
) -> tuple[NavigationTarget, ...]:
	"""Build the complete navigable target inventory before selection.

	The inventory intentionally retains repeated labels.  Selection for a
	structure summary may be bounded, while future query navigation must be
	able to search every useful target.
	"""
	if graph is not None and graph.nodes:
		return _build_graph_navigation_candidates(graph)
	if structure is None:
		return ()
	candidates: list[tuple[int, NavigationTarget]] = []

	def add(role: str, name: str, order: int, score: int, reason: str) -> None:
		name = " ".join(str(name).split()).strip()
		if not name:
			return
		candidates.append((
			score,
			NavigationTarget(
				_target_id(role, name, order), role, name, order, reason, score,
				kind="section" if role in {"heading", "landmark"} else "action",
				context_text=f"{role}: {name}",
			),
		))

	for order, (level, name) in enumerate(structure.headings):
		if level in (1, 2) or order == 0:
			add("heading", name, order, 100 - min(order, 20), _("Important page section"))
	for order, name in enumerate(structure.landmarks):
		landmark = name.split(":", 1)[0].strip().lower()
		if landmark in {"main", "article", "search", "navigation", "form"}:
			add("landmark", name, order, 78, _("Useful page region"))
	for order, name in enumerate(structure.inputs):
		add("formField", name, order, 88, _("Useful form field"))
	for order, name in enumerate(structure.comboboxes):
		add("formField", name, order, 76, _("Useful form control"))
	for order, name in enumerate(structure.buttons):
		add("button", name, order, 84, _("Useful page action"))
	for order, name in enumerate(structure.links):
		add("link", name, order, 70, _("Useful page link"))

	return tuple(target for _score, target in candidates)


def build_navigation_index(
	structure: ExtractionStructure | None = None,
	*,
	graph: AccessibilityGraph | None = None,
) -> "NavigationIndex":
	"""Build an index for ranking primary actions."""
	return NavigationIndex(
		build_navigation_candidates(structure, graph=graph),
	)


def _build_graph_navigation_candidates(graph: AccessibilityGraph) -> tuple[NavigationTarget, ...]:
	section_by_node: dict[str, str] = {}
	section_title_by_id: dict[str, str] = {}
	for section in graph.sections:
		section_title_by_id[section.id] = section.title
		if section.heading_node_id is not None:
			section_by_node[section.heading_node_id] = section.id
		for node_id in section.node_ids:
			section_by_node[node_id] = section.id

	by_id = {node.id: node for node in graph.nodes}
	children_by_parent: dict[str, list[str]] = {}
	for child in graph.nodes:
		if child.parent_id is None or not child.name.strip():
			continue
		if child.role not in {"heading", "landmark", "link", "button", "formField"}:
			continue
		children_by_parent.setdefault(child.parent_id, []).append(child.name)
	occurrences: dict[tuple[str, str], int] = {}
	candidates: list[NavigationTarget] = []
	for node in graph.nodes:
		if not node.name or node.role not in {"heading", "landmark", "link", "button", "formField"}:
			continue
		if node.role == "heading":
			score = 100 if node.heading_level in (1, 2) else 65
			reason = _("Important page section")
		elif node.role == "formField":
			score, reason = 88, _("Useful form field")
		elif node.role == "button":
			score, reason = 84, _("Useful page action")
		elif node.role == "landmark":
			score, reason = 78, _("Useful page region")
		else:
			score, reason = 70, _("Useful page link")
		role = node.control_type if node.role == "formField" and node.control_type else node.role
		key = (role, node.name.casefold())
		occurrence = occurrences.get(key, 0)
		occurrences[key] = occurrence + 1
		ancestor_names: list[str] = []
		parent_id = node.parent_id
		seen_parent_ids: set[str] = set()
		while parent_id is not None and parent_id not in seen_parent_ids:
			seen_parent_ids.add(parent_id)
			parent = by_id.get(parent_id)
			if parent is None:
				break
			if parent.name:
				ancestor_names.append(parent.name)
			parent_id = parent.parent_id
		ancestor_names.reverse()
		parent_name = ancestor_names[-1] if ancestor_names else ""
		child_names: list[str] = []
		seen_child_names: set[str] = set()
		for child_name in children_by_parent.get(node.id, ()):
			child_key = child_name.casefold()
			if child_key in seen_child_names:
				continue
			seen_child_names.add(child_key)
			child_names.append(_compact_context(child_name, 100))
			if len(child_names) >= 6:
				break
		section_id = section_by_node.get(node.id)
		section_title = section_title_by_id.get(section_id or "")
		context_parts = [f"{node.role}: {_compact_context(node.name)}"]
		if section_title and section_title.casefold() != node.name.casefold():
			context_parts.append(f"section: {_compact_context(section_title, 120)}")
		if ancestor_names:
			context_parts.append(
				f"ancestors: {' > '.join(_compact_context(name, 100) for name in ancestor_names[-4:])}"
			)
		if child_names:
			context_parts.append(f"children: {'; '.join(child_names)}")
		# Keep the concrete control role in the descriptor.  NVDA's
		# ``_iterNodesByType`` cannot resolve an abstract ``formField`` role.
		candidates.append(NavigationTarget(
			f"nav-{node.id}", role, node.name, node.order, reason, score,
			kind="section" if node.role in {"heading", "landmark"} else "action",
			source_node_id=node.id,
			section_id=section_id,
			ancestor_names=tuple(ancestor_names),
			occurrence=occurrence,
			context_text=" | ".join(context_parts),
			parent_name=_compact_context(parent_name, 100),
			child_names=tuple(child_names),
		))
	return tuple(candidates)


def select_navigation_targets(
	candidates: tuple[NavigationTarget, ...] | list[NavigationTarget],
	*,
	max_targets: int = 8,
) -> tuple[NavigationTarget, ...]:
	"""Select bounded, display-friendly targets without destroying the index."""
	if max_targets <= 0:
		return ()
	selected: list[NavigationTarget] = []
	seen: set[tuple[str, str, str]] = set()
	for target in sorted(candidates, key=lambda item: (-item.score, item.order)):
		key = (target.kind, target.role, target.name.casefold())
		if key in seen:
			continue
		seen.add(key)
		selected.append(target)
		if len(selected) >= max_targets:
			break
	return tuple(selected)


@dataclass(frozen=True, slots=True)
class NavigationFeatures:
	"""Generic graph-derived features used by navigation ranking."""

	name_quality: float
	context_quality: float
	structural_importance: float
	interaction_value: float
	repetition_penalty: float


class NavigationIndex:
	"""Rank primary actions from a complete navigation candidate inventory."""

	def __init__(self, candidates: tuple[NavigationTarget, ...] | list[NavigationTarget]) -> None:
		self._candidates = tuple(candidates)
		self._features = self._build_features()

	def primary_actions(self, *, max_targets: int = 8) -> tuple[NavigationTarget, ...]:
		"""Return useful actions when the user did not provide a target query."""
		if max_targets <= 0:
			return ()
		ranked = sorted(
			(
				(self._primary_action_score(target), target)
				for target in self._candidates
				if target.kind == "action"
			),
			key=lambda item: (-item[0], item[1].order),
		)
		return tuple(target for _score, target in ranked[:max_targets])

	def _build_features(self) -> dict[str, NavigationFeatures]:
		counts: dict[tuple[str, str], int] = {}
		for target in self._candidates:
			key = (target.role, target.name.casefold())
			counts[key] = counts.get(key, 0) + 1
		max_order = max((target.order for target in self._candidates), default=1)
		features: dict[str, NavigationFeatures] = {}
		for target in self._candidates:
			name = target.name.strip()
			alpha = sum(character.isalpha() for character in name)
			name_quality = min(1.0, len(name) / 24.0) if name else 0.0
			if name and alpha / max(1, len(name)) < 0.35:
				name_quality *= 0.5
			if name.casefold() in {"true", "false", "yes", "no"}:
				name_quality *= 0.25
			context_length = len(target.context_text)
			context_quality = 1.0 if context_length == 0 else min(1.0, 240 / context_length)
			role_importance = {
				"heading": 1.0, "landmark": 0.9, "button": 0.85,
				"input": 0.8, "combobox": 0.8, "checkbox": 0.75,
				"radio": 0.75, "link": 0.55,
			}.get(target.role, 0.4)
			position_bonus = 1.0 - min(1.0, target.order / max_order)
			features[target.id] = NavigationFeatures(
				name_quality=name_quality,
				context_quality=context_quality,
				structural_importance=0.75 * role_importance + 0.25 * position_bonus,
				interaction_value=role_importance if target.kind == "action" else 0.0,
				repetition_penalty=min(1.0, (counts[(target.role, target.name.casefold())] - 1) / 5),
			)
		return features

	def _primary_action_score(self, target: NavigationTarget) -> float:
		features = self._features[target.id]
		return (
			features.structural_importance
			+ features.interaction_value
			+ features.name_quality * 0.35
			- features.repetition_penalty * 0.35
		)
