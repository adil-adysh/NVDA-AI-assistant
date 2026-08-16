# -*- coding: utf-8 -*-
"""Actionable navigation targets for browser structure results.

Targets are deliberately small, serializable descriptors.  NVDA objects and
TextInfo instances are thread-affine and short-lived, so they must be
resolved again when the user invokes a result action.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import re
import time
from typing import Any

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


_ACTION_TERMS = re.compile(
	r"\b(click|press|button|action|buy|submit|download|apply|login|sign in|select|change|write|open)\b",
	re.IGNORECASE,
)
_SECTION_TERMS = re.compile(
	r"\b(go|jump|section|where|about|reviews?|description|details|information|payment|shipping)\b",
	re.IGNORECASE,
)


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

	return tuple(target for _score, target in candidates)


def build_navigation_index(
	structure: ExtractionStructure | None = None,
	*,
	graph: AccessibilityGraph | None = None,
	embedder: object | None = None,
) -> "NavigationIndex":
	"""Build a searchable index without discarding any navigation candidates."""
	return NavigationIndex(
		build_navigation_candidates(structure, graph=graph),
		embedder=embedder,
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
			reason = "Important page section"
		elif node.role == "formField":
			score, reason = 88, "Useful form field"
		elif node.role == "button":
			score, reason = 84, "Useful page action"
		elif node.role == "landmark":
			score, reason = 78, "Useful page region"
		else:
			score, reason = 70, "Useful page link"
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
	"""Rank a complete navigation candidate inventory.

	This first ranking layer is deliberately deterministic. Embedding-based
	semantic scoring can be added behind this interface once target extraction
	and live resolution are validated.
	"""

	def __init__(
		self,
		candidates: tuple[NavigationTarget, ...] | list[NavigationTarget],
		embedder: object | None = None,
	) -> None:
		self._candidates = tuple(candidates)
		self._embedder = embedder
		self._embedding_cache: dict[str, tuple[float, ...]] = {}
		self._features = self._build_features()

	@property
	def candidates(self) -> tuple[NavigationTarget, ...]:
		return self._candidates

	def search(self, query: str, *, max_targets: int = 8) -> tuple[NavigationTarget, ...]:
		"""Return the best section/action targets for a natural-language query."""
		if max_targets <= 0 or not query.strip():
			return ()
		query_text = " ".join(query.split()).casefold()
		query_terms = self._terms(query_text)
		if not query_terms:
			return ()
		section_intent = bool(_SECTION_TERMS.search(query_text))
		action_intent = bool(_ACTION_TERMS.search(query_text))
		lexical = {
			target.id: self._query_score(target, query_text, query_terms, section_intent, action_intent)
			for target in self._candidates
		}
		semantic = self._semantic_scores(query_text)
		if self._embedder is None:
			eligible = [target for target in self._candidates if lexical[target.id] >= 0]
		else:
			eligible = list(self._candidates)
		# With embeddings enabled, retain the full candidate set. A weak lexical
		# overlap such as "add" in "download an add-on" must not prevent the
		# semantic ranker from finding the correct target. Without embeddings,
		# lexical intent can safely narrow the deterministic fallback.
		if self._embedder is None:
			matched = [target for target in eligible if lexical[target.id] >= 0]
			if section_intent and any(target.kind == "section" for target in matched):
				eligible = [target for target in matched if target.kind == "section"]
			elif action_intent and any(target.kind == "action" for target in matched):
				eligible = [target for target in matched if target.kind == "action"]
		if not eligible:
			return ()
		ranks = [
			self._rank_ids(eligible, lexical, descending=True, minimum=0),
			self._rank_ids(eligible, self._structural_scores(), descending=True),
		]
		if semantic:
			ranks.append(self._rank_ids(eligible, semantic, descending=True))
		fused = self._fuse_ranks(eligible, ranks)
		return tuple(target for _score, target in fused[:max_targets])

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

	def _structural_scores(self) -> dict[str, float]:
		return {
			target_id: (
				features.structural_importance
				+ features.interaction_value
				+ features.name_quality * 0.25
				- features.repetition_penalty * 0.25
			)
			for target_id, features in self._features.items()
		}

	def _semantic_scores(self, query: str) -> dict[str, float]:
		if self._embedder is None:
			return {}
		try:
			query_embedder = getattr(self._embedder, "embed_query", None)
			if callable(query_embedder):
				query_vector = tuple(float(value) for value in query_embedder(query, "Find the most useful page navigation target"))
			else:
				query_vector = self._embed_texts((query,))[0]
			target_vectors = self._embed_texts(tuple(self._embedding_text(target) for target in self._candidates))
			return {
				target.id: self._cosine(query_vector, vector)
				for target, vector in zip(self._candidates, target_vectors)
			}
		except Exception:
			return {}

	@staticmethod
	def _embedding_text(target: NavigationTarget) -> str:
		return _compact_context(
			f"role: {target.role}; kind: {target.kind}; name: {target.name}; {target.context_text}",
			480,
		)

	def _embed_texts(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
		assert self._embedder is not None
		model_key = str(getattr(self._embedder, "model_key", "embedder"))
		missing = [text for text in texts if f"{model_key}:{text}" not in self._embedding_cache]
		if missing:
			vectors = self._embedder.embed(missing)
			for text, vector in zip(missing, vectors):
				self._embedding_cache[f"{model_key}:{text}"] = tuple(float(value) for value in vector)
		return tuple(self._embedding_cache[f"{model_key}:{text}"] for text in texts)

	@staticmethod
	def _rank_ids(
		candidates: list[NavigationTarget], scores: dict[str, float],
		*, descending: bool, minimum: float | None = None,
	) -> dict[str, int]:
		ordered = [
			target for target in candidates
			if minimum is None or scores.get(target.id, -1.0) >= minimum
		]
		ordered.sort(key=lambda target: (scores.get(target.id, -1.0), -target.order), reverse=descending)
		return {target.id: rank for rank, target in enumerate(ordered)}

	@staticmethod
	def _fuse_ranks(
		candidates: list[NavigationTarget], ranks: list[dict[str, int]],
	) -> list[tuple[float, NavigationTarget]]:
		return sorted(
			(
				(sum(1.0 / (60 + rank.get(target.id, len(candidates))) for rank in ranks), target)
				for target in candidates
			),
			key=lambda item: (-item[0], item[1].order),
		)

	@staticmethod
	def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
		if not left or len(left) != len(right):
			return -1.0
		left_norm = math.sqrt(sum(value * value for value in left))
		right_norm = math.sqrt(sum(value * value for value in right))
		if left_norm == 0 or right_norm == 0:
			return -1.0
		return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)

	@staticmethod
	def _terms(text: str) -> set[str]:
		return {term for term in re.findall(r"[\w']+", text) if len(term) > 2}

	@classmethod
	def _query_score(
		cls,
		target: NavigationTarget,
		query: str,
		query_terms: set[str],
		section_intent: bool,
		action_intent: bool,
	) -> int:
		name = target.name.casefold()
		context = target.context_text.casefold()
		name_terms = cls._terms(name)
		context_terms = cls._terms(context)
		name_matches = len(query_terms & name_terms)
		context_matches = len((query_terms - name_terms) & context_terms)
		if name_matches == 0 and context_matches == 0 and name not in query and query not in name:
			return -1
		score = name_matches * 30 + context_matches * 8
		if name and name in query:
			score += 45
		if query in name:
			score += 55
		if section_intent and target.kind == "section":
			score += 28
		if action_intent and target.kind == "action":
			score += 28
		if target.role in {"heading", "landmark"} and section_intent:
			score += 10
		if target.role in {"button", "input", "combobox", "checkbox", "radio"} and action_intent:
			score += 10
		return score + target.score // 4

	def _primary_action_score(self, target: NavigationTarget) -> float:
		features = self._features[target.id]
		return (
			features.structural_importance
			+ features.interaction_value
			+ features.name_quality * 0.35
			- features.repetition_penalty * 0.35
		)


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
	try:
		target_occurrence = max(0, int(target.get("occurrence", 0)))
	except (TypeError, ValueError):
		target_occurrence = 0
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
			matching_occurrence = 0
			for item in items:
				raw_label = _node_label(item)
				label = raw_label.casefold()
				if any(candidate == label or (candidate and candidate in label) for candidate in match_names):
					if matching_occurrence != target_occurrence:
						matching_occurrence += 1
						continue
					move_to = getattr(item, "moveTo", None)
					if not callable(move_to):
						return False, "Unable to move to that page target. The page may have changed."
					move_to()
					return True, raw_label or str(target.get("name") or "")
	except Exception:
		return False, "Unable to locate that page target. The page may have changed."
	return False, "Unable to locate that page target. The page may have changed."
