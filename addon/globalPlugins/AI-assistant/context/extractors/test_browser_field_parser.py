"""Shape-based tests for the NVDA ``getTextWithFields`` contract."""
from __future__ import annotations

from enum import IntEnum
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types
import unittest


MODULE_PATH = Path(__file__).with_name("browser_field_parser.py")


class Role(IntEnum):
	STATICTEXT = 1
	CHECKBOX = 5
	RADIOBUTTON = 6
	EDITABLETEXT = 7
	HEADING = 10
	LINK = 11
	COMBOBOX = 13
	BUTTON = 15
	LANDMARK = 78


def _load_parser():
	control_types = types.ModuleType("controlTypes")
	control_types.Role = Role
	text_infos = types.ModuleType("textInfos")
	text_infos.POSITION_ALL = object()
	sys.modules["controlTypes"] = control_types
	sys.modules["textInfos"] = text_infos
	spec = spec_from_file_location("browser_field_parser_test_module", MODULE_PATH)
	assert spec is not None and spec.loader is not None
	module = module_from_spec(spec)
	spec.loader.exec_module(module)
	return module.BrowserFieldParser


class Field:
	def __init__(self, **values: object) -> None:
		self.values = values

	def get(self, key: str):
		return self.values.get(key)


class Command:
	def __init__(self, command: str, field: Field | None = None) -> None:
		self.command = command
		self.field = field


class Info:
	def __init__(self, fields: list[object]) -> None:
		self.fields = fields

	def getTextWithFields(self):
		return self.fields


class ObjectWithFields:
	def __init__(self, fields: list[object]) -> None:
		self.info = Info(fields)

	def makeTextInfo(self, _position):
		return self.info


class BrowserFieldParserTests(unittest.TestCase):
	def test_uses_nvda_roles_and_html_aria_fallbacks(self) -> None:
		parser = _load_parser()()
		fields = [
			Command("controlStart", Field(role=Role.HEADING, **{"IAccessible2::attribute_tag": "h2"})),
			"Introduction",
			Command("controlEnd"),
			Command("controlStart", Field(role=Role.STATICTEXT, **{"IAccessible2::attribute_tag": "a"})),
			"Read more",
			Command("controlEnd"),
			Command("controlStart", Field(role=Role.STATICTEXT, **{"IAccessible2::attribute_tag": "select"})),
			"Category",
			Command("controlEnd"),
			Command("controlStart", Field(role=Role.LANDMARK, landmark="main")),
			"Article body",
			Command("controlEnd"),
			Command("controlStart", Field(role=Role.RADIOBUTTON)),
			"Monthly",
			Command("controlEnd"),
		]
		headings, links, _buttons, landmarks, _inputs, comboboxes, _checkboxes, radios = parser.extract_structured_info(ObjectWithFields(fields))
		self.assertEqual(headings, ((2, "Introduction"),))
		self.assertEqual(links, ("Read more",))
		self.assertEqual(comboboxes, ("Category",))
		self.assertEqual(landmarks, ("main: Article body",))
		self.assertEqual(radios, ("Monthly",))

	def test_hidden_and_unbalanced_controls_do_not_corrupt_neighbors(self) -> None:
		parser = _load_parser()()
		fields = [
			Command("controlStart", Field(role=Role.BUTTON, isHidden=True)),
			"Hidden",
			Command("controlStart", Field(role=Role.LINK)),
			"Also hidden",
			Command("controlEnd"),
			Command("controlEnd"),
			Command("controlStart", Field(role=Role.BUTTON)),
			"Visible action",
			# No controlEnd: dynamic browser content can end this way.
		]
		_result = parser.extract_structured_info(ObjectWithFields(fields))
		self.assertEqual(_result[2], ("Visible action",))
		self.assertEqual(_result[1], ())


if __name__ == "__main__":
	unittest.main()
