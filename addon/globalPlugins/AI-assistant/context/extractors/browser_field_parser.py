# -*- coding: utf-8 -*-
from __future__ import annotations

import controlTypes
from textInfos import POSITION_ALL


class BrowserFieldParser:
	def extract_structured_info(self, obj: object) -> tuple[tuple[tuple[int | None, str], ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
		textInfo = self._make_text_info(obj)
		if textInfo is None:
			return (), (), (), (), (), (), (), ()

		fields = self._make_text_with_fields(textInfo)
		if not fields:
			return (), (), (), (), (), (), (), ()

		headings, links, buttons, landmarks, inputs, comboboxes, checkboxes, radios = self._parse_text_fields(fields)
		return (
			tuple(headings),
			tuple(links),
			tuple(buttons),
			tuple(landmarks),
			tuple(inputs),
			tuple(comboboxes),
			tuple(checkboxes),
			tuple(radios),
		)

	def _make_text_info(self, obj: object):
		if not hasattr(obj, "makeTextInfo"):
			return None
		try:
			return obj.makeTextInfo(POSITION_ALL)
		except Exception:
			return None

	def _make_text_with_fields(self, textInfo: object):
		if textInfo is None:
			return ()
		try:
			fields = getattr(textInfo, "getTextWithFields", None)
			if callable(fields):
				return fields() or ()
			return ()
		except Exception:
			return ()

	def _parse_text_fields(self, fields: object):
		headings = []
		links = []
		buttons = []
		landmarks = []
		inputs = []
		comboboxes = []
		checkboxes = []
		radios = []
		stack: list[dict[str, object]] = []

		for item in fields:
			if isinstance(item, str):
				if stack:
					stack[-1]["text"].append(item)
				continue

			command = getattr(item, "command", None)
			field = getattr(item, "field", None)
			if command == "controlStart" and field is not None:
				if self._is_hidden_field(field):
					continue
				stack.append({"field": field, "text": []})
			elif command == "controlEnd" and stack:
				frame = stack.pop()
				label = self._normalize_candidate_text(" ".join(frame["text"]))
				if not label:
					label = self._explicit_field_name(frame["field"])
				if label:
					if self._is_heading_field(frame["field"]):
						headings.append((self._heading_level(frame["field"]), label))
					elif self._is_button_field(frame["field"]):
						buttons.append(label)
					elif self._is_combobox_field(frame["field"]):
						comboboxes.append(label)
					elif self._is_checkbox_field(frame["field"]):
						checkboxes.append(label)
					elif self._is_radio_field(frame["field"]):
						radios.append(label)
					elif self._is_input_field(frame["field"]):
						inputs.append(label)
					elif self._is_link_field(frame["field"]):
						links.append(label)
					elif self._is_landmark_field(frame["field"]):
						landmarks.append(label)
				if stack and label:
					stack[-1]["text"].append(label)

		return (
			headings,
			self._dedupe_strings(links),
			self._dedupe_strings(buttons),
			self._dedupe_strings(landmarks),
			self._dedupe_strings(inputs),
			self._dedupe_strings(comboboxes),
			self._dedupe_strings(checkboxes),
			self._dedupe_strings(radios),
		)

	def _normalize_candidate_text(self, text: str) -> str:
		return " ".join(text.split()).strip()

	def _explicit_field_name(self, field: object) -> str:
		for key in ("IAccessible2::attribute_explicit-name", "name", "IAccessible2::attribute_name-from"):
			value = self._field_value(field, key)
			if value:
				return self._normalize_candidate_text(str(value))
		return ""

	def _field_value(self, field: object, key: str) -> object | None:
		try:
			return field.get(key)
		except Exception:
			return None

	def _heading_level(self, field: object) -> int | None:
		tag = self._field_value(field, "IAccessible2::attribute_tag")
		if isinstance(tag, str):
			tag = tag.strip().lower()
			if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
				return int(tag[1])
		return None

	def _numeric_field_role(self, field: object) -> int | None:
		role = self._field_value(field, "role")
		if isinstance(role, controlTypes.Role):
			return role.value
		if isinstance(role, int):
			return role
		if isinstance(role, str) and role.isdigit():
			return int(role)
		return None

	def _is_heading_field(self, field: object) -> bool:
		role = self._numeric_field_role(field)
		tag = self._field_value(field, "IAccessible2::attribute_tag")
		xml_role = self._field_value(field, "IAccessible2::attribute_xml-roles")
		return (
			role == controlTypes.Role.HEADING.value
			or isinstance(tag, str) and tag.strip().lower() in {"h1", "h2", "h3", "h4", "h5", "h6"}
			or isinstance(xml_role, str) and "heading" in xml_role.strip().lower()
		)

	def _is_button_field(self, field: object) -> bool:
		role = self._numeric_field_role(field)
		tag = self._field_value(field, "IAccessible2::attribute_tag")
		xml_role = self._field_value(field, "IAccessible2::attribute_xml-roles")
		return (
			role in {
				controlTypes.Role.BUTTON.value,
				controlTypes.Role.MENUBUTTON.value,
				controlTypes.Role.TOGGLEBUTTON.value,
			}
			or isinstance(xml_role, str) and "button" in xml_role.strip().lower()
			or isinstance(tag, str) and tag.strip().lower() == "button"
		)

	def _is_link_field(self, field: object) -> bool:
		role = self._numeric_field_role(field)
		tag = self._field_value(field, "IAccessible2::attribute_tag")
		xml_role = self._field_value(field, "IAccessible2::attribute_xml-roles")
		return (
			role == controlTypes.Role.LINK.value
			or isinstance(xml_role, str) and "link" in xml_role.strip().lower()
			or isinstance(tag, str) and tag.strip().lower() == "a"
		)

	def _is_combobox_field(self, field: object) -> bool:
		role = self._numeric_field_role(field)
		tag = self._field_value(field, "IAccessible2::attribute_tag")
		xml_role = self._field_value(field, "IAccessible2::attribute_xml-roles")
		return (
			role == controlTypes.Role.COMBOBOX.value if hasattr(controlTypes.Role, "COMBOBOX") else False
			or isinstance(xml_role, str) and "combobox" in xml_role.strip().lower()
			or isinstance(tag, str) and tag.strip().lower() in {"select", "combobox"}
		)

	def _is_checkbox_field(self, field: object) -> bool:
		role = self._numeric_field_role(field)
		tag = self._field_value(field, "IAccessible2::attribute_tag")
		xml_role = self._field_value(field, "IAccessible2::attribute_xml-roles")
		return (
			role == controlTypes.Role.CHECKBOX.value if hasattr(controlTypes.Role, "CHECKBOX") else False
			or isinstance(xml_role, str) and "checkbox" in xml_role.strip().lower()
			or isinstance(tag, str) and tag.strip().lower() == "checkbox"
		)

	def _is_radio_field(self, field: object) -> bool:
		role = self._numeric_field_role(field)
		tag = self._field_value(field, "IAccessible2::attribute_tag")
		xml_role = self._field_value(field, "IAccessible2::attribute_xml-roles")
		return (
			role == controlTypes.Role.RADIO.value if hasattr(controlTypes.Role, "RADIO") else False
			or isinstance(xml_role, str) and "radio" in xml_role.strip().lower()
			or isinstance(tag, str) and tag.strip().lower() == "radio"
		)

	def _is_input_field(self, field: object) -> bool:
		role = self._numeric_field_role(field)
		tag = self._field_value(field, "IAccessible2::attribute_tag")
		xml_role = self._field_value(field, "IAccessible2::attribute_xml-roles")
		return (
			role == controlTypes.Role.TEXT.value if hasattr(controlTypes.Role, "TEXT") else False
			or isinstance(xml_role, str) and any(token in xml_role.strip().lower() for token in ("textbox", "searchbox", "text"))
			or isinstance(tag, str) and tag.strip().lower() in {"input", "textarea", "textbox", "search"}
		)

	def _is_landmark_field(self, field: object) -> bool:
		tag = self._field_value(field, "IAccessible2::attribute_tag")
		xml_role = self._field_value(field, "IAccessible2::attribute_xml-roles")
		landmark = self._field_value(field, "landmark")
		if isinstance(xml_role, str) and xml_role.strip().lower() in {
			"banner",
			"complementary",
			"contentinfo",
			"form",
			"main",
			"navigation",
			"search",
		}:
			return True
		if isinstance(tag, str) and tag.strip().lower() in {
			"main",
			"nav",
			"banner",
			"complementary",
			"contentinfo",
			"search",
		}:
			return True
		if landmark is not None:
			return True
		return False

	def _is_hidden_field(self, field: object) -> bool:
		hidden = self._field_value(field, "isHidden")
		if hidden is True:
			return True
		if isinstance(hidden, str) and hidden.strip().lower() in {"1", "true", "yes"}:
			return True
		return False

	def _dedupe_strings(self, items: list[str]) -> tuple[str, ...]:
		seen: set[str] = set()
		unique: list[str] = []
		for item in items:
			if item and item not in seen:
				seen.add(item)
				unique.append(item)
		return tuple(unique)
