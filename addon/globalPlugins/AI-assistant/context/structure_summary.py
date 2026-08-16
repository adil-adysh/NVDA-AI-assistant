"""Compact, actionable projections of accessibility graphs for prompts."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re

from .navigation import NavigationTarget, build_navigation_index
from .types import AccessibilityGraph, ExtractionStructure


@dataclass(frozen=True, slots=True)
class StructurePromptTarget:
	"""Serializable target descriptor supplied to the structure-summary LLM."""

	id: str
	role: str
	control_type: str | None
	name: str
	section_id: str | None
	parent: str
	ancestors: tuple[str, ...]
	children: tuple[str, ...]
	order: int
	context: str


@dataclass(frozen=True, slots=True)
class StructurePromptSection:
	"""Serializable semantic section with bounded supporting text."""

	id: str
	title: str
	heading_level: int | None
	snippet: str
	target_ids: tuple[str, ...]
	counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class StructurePromptContext:
	"""Canonical, bounded page map used by the structure-summary prompt."""

	title: str = ""
	app_title: str = ""
	source: str = "generic"
	truncated: bool = False
	sections: tuple[StructurePromptSection, ...] = ()
	targets: tuple[StructurePromptTarget, ...] = ()
	total_counts: tuple[tuple[str, int], ...] = ()
	omitted_sections: int = 0
	omitted_targets: int = 0
	omitted_text_chars: int = 0
	marked_text: str = ""

	def to_marked_text(self) -> str:
		"""Return the compact, LLM-facing inline accessibility projection."""
		return self.marked_text

	def to_dict(self) -> dict[str, object]:
		return {
			"page": {
				"title": self.title,
				"app_title": self.app_title,
				"source": self.source,
				"truncated": self.truncated,
			},
			"sections": [
				{
					"id": section.id,
					"title": section.title,
					"heading_level": section.heading_level,
					"snippet": section.snippet,
					"target_ids": list(section.target_ids),
					"counts": dict(section.counts),
				}
				for section in self.sections
			],
			"targets": [
				{
					"id": target.id,
					"role": target.role,
					"control_type": target.control_type,
					"name": target.name,
					"section_id": target.section_id,
					"parent": target.parent,
					"ancestors": list(target.ancestors),
					"children": list(target.children),
					"order": target.order,
					"context": target.context,
				}
				for target in self.targets
			],
			"total_counts": dict(self.total_counts),
			"omissions": {
				"sections": self.omitted_sections,
				"targets": self.omitted_targets,
				"text_chars": self.omitted_text_chars,
			},
			"marked_text": self.marked_text,
		}


@dataclass(frozen=True, slots=True)
class StructureSummaryRepresentation:
	headings: tuple[tuple[int | None, str], ...] = ()
	links: tuple[str, ...] = ()
	buttons: tuple[str, ...] = ()
	landmarks: tuple[str, ...] = ()
	inputs: tuple[str, ...] = ()
	comboboxes: tuple[str, ...] = ()
	checkboxes: tuple[str, ...] = ()
	radios: tuple[str, ...] = ()
	sections: tuple[tuple[str, tuple[str, ...]], ...] = ()
	actions: tuple[NavigationTarget, ...] = ()


def _compact(value: object, limit: int) -> str:
	text = " ".join(str(value or "").split()).strip()
	if len(text) <= limit:
		return text
	return text[: limit - 1].rstrip() + "…"


def _action_label(value: str, limit: int) -> str:
	"""Remove verbose accessibility annotations from the visible summary label."""
	parts = [part.strip() for part in value.split(",") if part.strip()]
	if len(parts) > 1 and any(
		re.search(r"\b(?:shift|alt|ctrl|control|command|press|shortcut)\b", part, re.I)
		for part in parts[1:]
	):
		value = parts[0]
	return _compact(value, limit)


def _normalized(value: object) -> str:
	return " ".join(str(value or "").split()).strip()


def _bounded_snippet(value: object, limit: int) -> tuple[str, int]:
	text = _normalized(value)
	if len(text) <= limit:
		return text, 0
	return text[: max(1, limit - 1)].rsplit(" ", 1)[0].rstrip() + "…", len(text) - limit


def _marked_content(value: object, limit: int) -> str:
	"""Normalize page text and neutralize marker-looking content."""
	text, _omitted = _bounded_snippet(value, limit)
	return text.replace("[", "‹").replace("]", "›")


def _marker_role(target: NavigationTarget, node_control_type: str | None) -> str:
	if target.role == "heading":
		return "heading"
	if target.role == "landmark":
		return "region"
	if target.role == "formField":
		return node_control_type or "form-field"
	return target.role


def _render_marked_text(
		sections: tuple[StructurePromptSection, ...],
		targets: tuple[StructurePromptTarget, ...],
		*,
		max_chars: int,
		omitted_sections: int,
		omitted_targets: int,
		omitted_text_chars: int,
	) -> str:
	"""Render compact source-ordered markers without exposing graph objects."""
	by_section: dict[str, list[StructurePromptTarget]] = {}
	for target in targets:
		by_section.setdefault(target.section_id or "", []).append(target)
	lines: list[str] = []
	for section in sections:
		level = f" level={section.heading_level}" if section.heading_level is not None else ""
		lines.append(f"[section id={section.id}{level}] {_marked_content(section.title, 112)}")
		if section.snippet:
			lines.append(f"[text section={section.id}] {_marked_content(section.snippet, len(section.snippet))}")
		for target in by_section.get(section.id, ()):
			control = f" control={target.control_type}" if target.control_type else ""
			parent = f" parent={target.parent}" if target.parent else ""
			lines.append(
				f"[{_marker_role(target, target.control_type)} id={target.id} section={section.id}{control}{parent}] "
				f"{_marked_content(target.name, 112)}"
			)
	for target in by_section.get("", ()):
			control = f" control={target.control_type}" if target.control_type else ""
			lines.append(f"[{_marker_role(target, target.control_type)} id={target.id}{control}] {_marked_content(target.name, 112)}")
	if omitted_sections or omitted_targets or omitted_text_chars:
		lines.append(
			f"[omitted sections={omitted_sections} targets={omitted_targets} text_chars={omitted_text_chars}]"
		)
	result = "\n".join(lines)
	if len(result) <= max_chars:
		return result
	return result[: max(1, max_chars - 1)].rsplit("\n", 1)[0] + "\n[omitted page map details]"


def build_structure_prompt_context(
	graph: AccessibilityGraph | None,
	structure: ExtractionStructure | None = None,
	*,
	title: str = "",
	app_title: str = "",
	source: str = "generic",
	truncated: bool = False,
	max_sections: int = 12,
	max_targets: int = 256,
	max_label_chars: int = 112,
	max_snippet_chars: int = 900,
	max_context_chars: int = 16000,
) -> StructurePromptContext:
	"""Build one bounded semantic page map for the structure-summary LLM.

	The graph is authoritative when present. Legacy structure is used only as a
	compatibility fallback for sources that cannot provide graph sections.
	"""
	if graph is None or not graph.nodes:
		return _build_legacy_prompt_context(
			structure,
			title=title,
			app_title=app_title,
			source=source,
			truncated=truncated,
			max_targets=max_targets,
			max_label_chars=max_label_chars,
		)

	from .navigation import build_llm_navigation_candidates

	candidates = build_llm_navigation_candidates(graph=graph, max_candidates=max_targets)
	node_by_id = {node.id: node for node in graph.nodes}
	all_candidates = build_llm_navigation_candidates(graph=graph, max_candidates=10_000)
	sections: list[StructurePromptSection] = []
	omitted_text_chars = 0

	for section in graph.sections[:max_sections]:
		heading = node_by_id.get(section.heading_node_id or "")
		target_ids = tuple(
			target.id for target in candidates
			if target.section_id == section.id
		)
		role_counts: Counter[str] = Counter(
			target.role for target in candidates if target.section_id == section.id
		)
		section_budget = min(max_snippet_chars, max_context_chars // max(1, min(max_sections, len(graph.sections))))
		snippet, omitted = _bounded_snippet(section.text, section_budget)
		omitted_text_chars += omitted
		sections.append(
			StructurePromptSection(
				id=section.id,
				title=_compact(section.title, max_label_chars),
				heading_level=getattr(heading, "heading_level", None),
				snippet=snippet,
				target_ids=target_ids,
				counts=tuple(sorted(role_counts.items())),
			)
		)

	all_targets = tuple(
		StructurePromptTarget(
			id=target.id,
			role=target.role,
			control_type=node_by_id.get(target.source_node_id or "").control_type
				if target.source_node_id in node_by_id else None,
			name=_compact(target.name, max_label_chars),
			section_id=target.section_id,
			parent=_compact(target.parent_name, max_label_chars),
			ancestors=tuple(_compact(name, max_label_chars) for name in target.ancestor_names[-4:]),
			children=tuple(_compact(name, max_label_chars) for name in target.child_names[:6]),
			order=target.order,
			context=_compact(target.context_text, max_label_chars * 3),
		)
		for target in candidates
	)
	used_chars = sum(len(target.name) + len(target.context) + 80 for target in all_targets)
	targets = all_targets
	while targets and used_chars > max_context_chars:
		removed = targets[-1]
		targets = targets[:-1]
		used_chars -= len(removed.name) + len(removed.context) + 80
	kept_ids = {target.id for target in targets}
	sections = [
		StructurePromptSection(
			section.id,
			section.title,
			section.heading_level,
			section.snippet,
			tuple(target_id for target_id in section.target_ids if target_id in kept_ids),
			section.counts,
		)
		for section in sections
	]
	role_counts = Counter(target.role for target in targets)
	marked_text = _render_marked_text(
		tuple(sections),
		tuple(targets),
		max_chars=max_context_chars,
		omitted_sections=max(0, len(graph.sections) - len(sections)),
		omitted_targets=max(0, len(all_candidates) - len(targets)),
		omitted_text_chars=omitted_text_chars,
	)
	return StructurePromptContext(
		title=_normalized(title),
		app_title=_normalized(app_title),
		source=_normalized(source) or "generic",
		truncated=truncated,
		sections=tuple(sections),
		targets=targets,
		total_counts=tuple(sorted(role_counts.items())),
		omitted_sections=max(0, len(graph.sections) - len(sections)),
		omitted_targets=max(0, len(all_candidates) - len(targets)),
		omitted_text_chars=omitted_text_chars,
		marked_text=marked_text,
	)


def _build_legacy_prompt_context(
	structure: ExtractionStructure | None,
	*,
	title: str,
	app_title: str,
	source: str,
	truncated: bool,
	max_targets: int,
	max_label_chars: int,
) -> StructurePromptContext:
	if structure is None:
		return StructurePromptContext()
	from .navigation import build_llm_navigation_candidates

	candidates = build_llm_navigation_candidates(structure=structure, max_candidates=max_targets)
	targets = tuple(
		StructurePromptTarget(
			id=target.id,
			role=target.role,
			control_type=None,
			name=_compact(target.name, max_label_chars),
			section_id=target.section_id,
			parent=_compact(target.parent_name, max_label_chars),
			ancestors=tuple(_compact(name, max_label_chars) for name in target.ancestor_names[-4:]),
			children=tuple(_compact(name, max_label_chars) for name in target.child_names[:6]),
			order=target.order,
			context=_compact(target.context_text, max_label_chars * 3),
		)
		for target in candidates
	)
	counts = Counter(target.role for target in targets)
	marked_text = _render_marked_text(
		(), targets, max_chars=max(8000, max_label_chars * max(1, len(targets))),
		omitted_sections=0,
		omitted_targets=max(0, len(build_llm_navigation_candidates(structure=structure, max_candidates=10_000)) - len(targets)),
		omitted_text_chars=0,
	)
	return StructurePromptContext(
		title=_normalized(title),
		app_title=_normalized(app_title),
		source=_normalized(source) or "generic",
		truncated=truncated,
		targets=targets,
		total_counts=tuple(sorted(counts.items())),
		omitted_targets=max(0, len(build_llm_navigation_candidates(structure=structure, max_candidates=10_000)) - len(targets)),
		marked_text=marked_text,
	)


def _ordered_counts(values: list[str], limit: int, label_limit: int) -> tuple[str, ...]:
	counts = Counter(value.casefold() for value in values if value.strip())
	seen: set[str] = set()
	result: list[str] = []
	for value in values:
		clean = _compact(value, label_limit)
		key = clean.casefold()
		if not clean or key in seen:
			continue
		seen.add(key)
		count = counts.get(value.casefold(), 1)
		result.append(f"{clean} (×{count})" if count > 1 else clean)
		if len(result) >= limit:
			break
	if len(values) > len(seen) and len(result) == limit:
		result.append(f"[additional items omitted: {len(values) - len(seen)}]")
	return tuple(result)


def build_structure_summary_representation(
	graph: AccessibilityGraph | None,
	structure: ExtractionStructure | None = None,
	*,
	max_sections: int = 8,
	max_members_per_section: int = 5,
	max_items: dict[str, int] | int | None = None,
	max_label_chars: int = 80,
	max_actions: int = 8,
) -> StructureSummaryRepresentation:
	"""Build a concise structure map without sending raw graph noise."""
	if isinstance(max_items, int):
		limits = {
			field: max_items for field in
			("headings", "links", "buttons", "landmarks", "inputs",
			 "comboboxes", "checkboxes", "radios")
		}
	else:
		limits = max_items or {
			"headings": 24, "links": 24, "buttons": 16, "landmarks": 10,
			"inputs": 12, "comboboxes": 12, "checkboxes": 12, "radios": 12,
		}
	if graph is None or not graph.nodes:
		if structure is None:
			return StructureSummaryRepresentation()
		return StructureSummaryRepresentation(
			headings=tuple((level, _compact(name, max_label_chars)) for level, name in structure.headings[:limits["headings"]]),
			links=_ordered_counts(list(structure.links), limits["links"], max_label_chars),
			buttons=_ordered_counts(list(structure.buttons), limits["buttons"], max_label_chars),
			landmarks=_ordered_counts(list(structure.landmarks), limits["landmarks"], max_label_chars),
			inputs=_ordered_counts(list(structure.inputs), limits["inputs"], max_label_chars),
			comboboxes=_ordered_counts(list(structure.comboboxes), limits["comboboxes"], max_label_chars),
			checkboxes=_ordered_counts(list(structure.checkboxes), limits["checkboxes"], max_label_chars),
			radios=_ordered_counts(list(structure.radios), limits["radios"], max_label_chars),
		)

	nodes = tuple(sorted((node for node in graph.nodes if node.name.strip()), key=lambda node: node.order))
	by_role = {role: [node.name for node in nodes if node.role == role] for role in ("link", "button", "landmark")}
	form_nodes = [node for node in nodes if node.role == "formField"]
	section_context: list[tuple[str, tuple[str, ...]]] = []
	node_by_id = {node.id: node for node in nodes}
	section_limit = max_sections
	if max_actions > 0 and max_sections > 0:
		section_limit -= 1
	for section in graph.sections[:max(0, section_limit)]:
		members = tuple(
			f"{node.role}: {_compact(node.name, max_label_chars)}"
			for node_id in section.node_ids
			if (node := node_by_id.get(node_id)) is not None
			and node.role != "container"
			and node.name.strip()
		)[:max_members_per_section]
		section_context.append((_compact(section.title, max_label_chars), members))

	index = build_navigation_index(graph=graph)
	actions = index.primary_actions(max_targets=max_actions)
	if actions and max_sections > 0:
		section_context.append((
			"Important actions",
			tuple(
				f"{action.role}: {_action_label(action.name, max_label_chars)}"
				for action in actions
			),
		))
	return StructureSummaryRepresentation(
		headings=tuple(
			(node.heading_level, _compact(node.name, max_label_chars))
			for node in nodes if node.role == "heading"
		)[:limits["headings"]],
		links=_ordered_counts(by_role["link"], limits["links"], max_label_chars),
		buttons=_ordered_counts(by_role["button"], limits["buttons"], max_label_chars),
		landmarks=_ordered_counts(by_role["landmark"], limits["landmarks"], max_label_chars),
		inputs=_ordered_counts([node.name for node in form_nodes if node.control_type == "input"], limits["inputs"], max_label_chars),
		comboboxes=_ordered_counts([node.name for node in form_nodes if node.control_type == "combobox"], limits["comboboxes"], max_label_chars),
		checkboxes=_ordered_counts([node.name for node in form_nodes if node.control_type == "checkbox"], limits["checkboxes"], max_label_chars),
		radios=_ordered_counts([node.name for node in form_nodes if node.control_type == "radio"], limits["radios"], max_label_chars),
		sections=tuple(section_context),
		actions=actions,
	)
