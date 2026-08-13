# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Iterable

import controlTypes
from textInfos import POSITION_ALL


class BrowserFieldParser:
	"""Convert NVDA browser text fields into stable semantic page facts.

	The field stream is not guaranteed to be perfectly balanced: browser
	virtual buffers can omit an end command for hidden or dynamic controls.
	Parsing therefore uses explicit frames and flushes incomplete frames safely.
	"""

	def extract_structured_info(self, obj: object) -> tuple[
		tuple[tuple[int | None, str], ...],
		tuple[str, ...],
		tuple[str, ...],
		tuple[str, ...],
		tuple[str, ...],
		tuple[str, ...],
		tuple[str, ...],
		tuple[str, ...],
	]:
		text_info = self._make_text_info(obj)
		if text_info is None:
			return self._empty_result()
		fields = self._make_text_with_fields(text_info)
		if not fields:
			return self._empty_result()
		return self._parse_text_fields(fields)

	@staticmethod
	def _empty_result() -> tuple[tuple[tuple[int | None, str], ...], ...]:
		return (), (), (), (), (), (), (), ()

	def _make_text_info(self, obj: object) -> object | None:
		make_text_info = getattr(obj, "makeTextInfo", None)
		if not callable(make_text_info):
			return None
		try:
			return make_text_info(POSITION_ALL)
		except Exception:
			return None

	def _make_text_with_fields(self, text_info: object) -> Iterable[object]:
		try:
			get_text_with_fields = getattr(text_info, "getTextWithFields", None)
			if not callable(get_text_with_fields):
				return ()
			return get_text_with_fields() or ()
		except Exception:
			return ()

	def _parse_text_fields(self, fields: Iterable[object]):
		headings: list[tuple[int | None, str]] = []
		links: list[str] = []
		buttons: list[str] = []
		landmarks: list[str] = []
		inputs: list[str] = []
		comboboxes: list[str] = []
		checkboxes: list[str] = []
		radios: list[str] = []
		stack: list[dict[str, object]] = []

		for item in fields:
			if isinstance(item, str):
				if stack and self._stack_is_visible(stack):
					text = stack[-1]["text"]
					assert isinstance(text, list)
					text.append(item)
				continue

			command = self._command_name(getattr(item, "command", None))
			field = getattr(item, "field", None)
			if command == "controlstart" and field is not None:
				stack.append({
					"field": field,
					"text": [],
					"hidden": self._is_hidden_field(field),
				})
			elif command == "controlend" and stack:
				self._close_frame(stack.pop(), stack, headings, links, buttons, landmarks, inputs, comboboxes, checkboxes, radios)

		# Recover useful labels when a dynamic browser omitted controlEnd.
		while stack:
			self._close_frame(stack.pop(), stack, headings, links, buttons, landmarks, inputs, comboboxes, checkboxes, radios)

		return (
			tuple(headings),
			self._dedupe_strings(links),
			self._dedupe_strings(buttons),
			self._dedupe_strings(landmarks),
			self._dedupe_strings(inputs),
			self._dedupe_strings(comboboxes),
			self._dedupe_strings(checkboxes),
			self._dedupe_strings(radios),
		)

	def _close_frame(
		self,
		frame: dict[str, object],
		parents: list[dict[str, object]],
		headings: list[tuple[int | None, str]],
		links: list[str],
		buttons: list[str],
		landmarks: list[str],
		inputs: list[str],
		comboboxes: list[str],
		checkboxes: list[str],
		radios: list[str],
	) -> None:
		if bool(frame.get("hidden")) or any(bool(parent.get("hidden")) for parent in parents):
			return
		field = frame.get("field")
		text_parts = frame.get("text", [])
		label = self._normalize_candidate_text(" ".join(text_parts) if isinstance(text_parts, list) else "")
		if not label and field is not None:
			label = self._explicit_field_name(field)
		if not label or field is None:
			return

		if self._is_heading_field(field):
			headings.append((self._heading_level(field), label))
		elif self._is_button_field(field):
			buttons.append(label)
		elif self._is_combobox_field(field):
			comboboxes.append(label)
		elif self._is_checkbox_field(field):
			checkboxes.append(label)
		elif self._is_radio_field(field):
			radios.append(label)
		elif self._is_input_field(field):
			inputs.append(label)
		elif self._is_link_field(field):
			links.append(label)
		elif self._is_landmark_field(field):
			landmark_type = self._landmark_type(field)
			landmarks.append(f"{landmark_type}: {label}" if landmark_type else label)

		if parents and self._stack_is_visible(parents):
			parent_text = parents[-1]["text"]
			if isinstance(parent_text, list):
				parent_text.append(label)

	@staticmethod
	def _command_name(command: object) -> str:
		return str(command or "").replace("_", "").lower()

	@staticmethod
	def _stack_is_visible(stack: list[dict[str, object]]) -> bool:
		return not any(bool(frame.get("hidden")) for frame in stack)

	def _normalize_candidate_text(self, text: str) -> str:
		return " ".join(text.split()).strip()

	def _explicit_field_name(self, field: object) -> str:
		for key in (
			"IAccessible2::attribute_explicit-name",
			"IAccessible2::attribute_name-from",
			"name",
			"value",
			"description",
			"placeholder",
		):
			value = self._field_value(field, key)
			if value is not None:
				label = self._normalize_candidate_text(str(value))
				if label:
					return label
		return ""

	@staticmethod
	def _field_value(field: object, key: str) -> object | None:
		try:
			getter = getattr(field, "get", None)
			return getter(key) if callable(getter) else None
		except Exception:
			return None

	def _heading_level(self, field: object) -> int | None:
		tag = self._tag(field)
		return int(tag[1]) if len(tag) == 2 and tag[0] == "h" and tag[1].isdigit() else None

	def _numeric_field_role(self, field: object) -> int | None:
		role = self._field_value(field, "role")
		if isinstance(role, controlTypes.Role):
			return role.value
		if isinstance(role, int):
			return role
		if isinstance(role, str):
			try:
				return controlTypes.Role[role.strip().upper()].value
			except (KeyError, AttributeError):
				return int(role) if role.strip().isdigit() else None
		return None

	def _role_matches(self, field: object, *names: str) -> bool:
		role = self._numeric_field_role(field)
		for name in names:
			role_value = getattr(getattr(controlTypes, "Role", object), name, None)
			if role_value is not None and role == getattr(role_value, "value", role_value):
				return True
		return False

	def _tag(self, field: object) -> str:
		value = self._field_value(field, "IAccessible2::attribute_tag")
		return str(value or "").strip().lower().split(":")[-1]

	def _xml_roles(self, field: object) -> set[str]:
		value = self._field_value(field, "IAccessible2::attribute_xml-roles")
		return {token for token in str(value or "").strip().lower().replace(",", " ").split() if token}

	def _is_heading_field(self, field: object) -> bool:
		return self._role_matches(field, "HEADING") or self._tag(field) in {f"h{i}" for i in range(1, 7)} or "heading" in self._xml_roles(field)

	def _is_button_field(self, field: object) -> bool:
		return self._role_matches(field, "BUTTON", "MENUBUTTON", "TOGGLEBUTTON") or self._tag(field) == "button" or bool({"button", "menubutton"} & self._xml_roles(field))

	def _is_link_field(self, field: object) -> bool:
		return self._role_matches(field, "LINK") or self._tag(field) == "a" or "link" in self._xml_roles(field)

	def _is_combobox_field(self, field: object) -> bool:
		return self._role_matches(field, "COMBOBOX") or self._tag(field) in {"select", "combobox"} or "combobox" in self._xml_roles(field)

	def _is_checkbox_field(self, field: object) -> bool:
		return self._role_matches(field, "CHECKBOX") or self._tag(field) == "checkbox" or "checkbox" in self._xml_roles(field)

	def _is_radio_field(self, field: object) -> bool:
		return self._role_matches(field, "RADIOBUTTON") or self._tag(field) == "radio" or "radio" in self._xml_roles(field)

	def _is_input_field(self, field: object) -> bool:
		return self._role_matches(field, "EDITABLETEXT", "TEXT") or self._tag(field) in {"input", "textarea", "textbox", "search"} or bool({"textbox", "searchbox"} & self._xml_roles(field))

	def _is_landmark_field(self, field: object) -> bool:
		landmark = self._field_value(field, "landmark")
		return self._role_matches(field, "LANDMARK", "ARTICLE", "REGION", "FORM") or bool(landmark) or self._tag(field) in {"main", "nav", "banner", "complementary", "contentinfo", "search", "aside", "footer", "header", "form", "article", "section"} or bool(self._xml_roles(field) & {"article", "banner", "complementary", "contentinfo", "form", "main", "navigation", "region", "search"})

	def _landmark_type(self, field: object) -> str:
		value = self._field_value(field, "landmark")
		if value:
			return self._normalize_candidate_text(str(value)).lower()
		roles = self._xml_roles(field)
		for role in ("banner", "complementary", "contentinfo", "form", "main", "navigation", "region", "search", "article"):
			if role in roles:
				return role
		tag_to_landmark = {
			"aside": "complementary",
			"article": "article",
			"footer": "contentinfo",
			"header": "banner",
			"main": "main",
			"nav": "navigation",
			"section": "region",
		}
		return tag_to_landmark.get(self._tag(field), "")

	def _is_hidden_field(self, field: object) -> bool:
		hidden = self._field_value(field, "isHidden")
		return hidden is True or str(hidden or "").strip().lower() in {"1", "true", "yes"}

	@staticmethod
	def _dedupe_strings(items: list[str]) -> tuple[str, ...]:
		seen: set[str] = set()
		unique: list[str] = []
		for item in items:
			key = item.casefold()
			if item and key not in seen:
				seen.add(key)
				unique.append(item)
		return tuple(unique)
