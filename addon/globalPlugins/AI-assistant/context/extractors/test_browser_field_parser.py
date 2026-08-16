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
	package_root = "browser_field_parser_test_package"
	context_package = f"{package_root}.context"
	extractors_package = f"{context_package}.extractors"
	for name, path in (
		(package_root, MODULE_PATH.parents[3]),
		(context_package, MODULE_PATH.parents[2]),
		(extractors_package, MODULE_PATH.parent),
	):
		package = types.ModuleType(name)
		package.__path__ = [str(path)]
		sys.modules[name] = package

	control_types = types.ModuleType("controlTypes")
	control_types.Role = Role
	text_infos = types.ModuleType("textInfos")
	text_infos.POSITION_ALL = object()
	sys.modules["controlTypes"] = control_types
	sys.modules["textInfos"] = text_infos
	types_path = MODULE_PATH.parents[1] / "types.py"
	types_spec = spec_from_file_location(f"{context_package}.types", types_path)
	assert types_spec is not None and types_spec.loader is not None
	types_module = module_from_spec(types_spec)
	sys.modules[types_spec.name] = types_module
	types_spec.loader.exec_module(types_module)
	spec = spec_from_file_location(f"{extractors_package}.browser_field_parser", MODULE_PATH)
	assert spec is not None and spec.loader is not None
	module = module_from_spec(spec)
	sys.modules[spec.name] = module
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

	def test_graph_collapses_repeated_container_wrappers(self) -> None:
		parser = _load_parser()()
		fields = [
			Command("controlStart", Field(role=Role.LANDMARK)),
			"Main",
			Command("controlStart", Field(role=Role.STATICTEXT)),
			"Main",
			Command("controlStart", Field(role=Role.BUTTON)),
			"Submit",
			Command("controlEnd"),
			Command("controlEnd"),
			Command("controlEnd"),
		]
		graph = parser.extract_graph(ObjectWithFields(fields), "Main Submit")
		self.assertEqual([node.role for node in graph.nodes], ["landmark", "button"])
		self.assertEqual(graph.nodes[1].parent_id, graph.nodes[0].id)

	def test_graph_removes_unnamed_wrapper_and_reparents_children(self) -> None:
		parser = _load_parser()()
		fields = [
			Command("controlStart", Field(role=Role.LANDMARK, landmark="main")),
			"Main",
			Command("controlStart", Field(role=Role.STATICTEXT)),
			Command("controlStart", Field(role=Role.HEADING, **{"IAccessible2::attribute_tag": "h1"})),
			"Welcome",
			Command("controlEnd"),
			Command("controlEnd"),
			Command("controlEnd"),
		]
		graph = parser.extract_graph(ObjectWithFields(fields), "Welcome")
		self.assertEqual([node.name for node in graph.nodes], ["Main Welcome", "Welcome"])
		self.assertEqual(graph.nodes[1].parent_id, graph.nodes[0].id)

	def test_graph_preserves_named_semantic_nodes_and_typed_landmarks(self) -> None:
		parser = _load_parser()()
		fields = [
			Command("controlStart", Field(role=Role.HEADING, **{"IAccessible2::attribute_tag": "h2"})),
			"Title",
			Command("controlEnd"),
			Command("controlStart", Field(role=Role.LANDMARK, landmark="navigation")),
			Command("controlStart", Field(role=Role.LINK)),
			"Details",
			Command("controlEnd"),
			Command("controlStart", Field(role=Role.BUTTON)),
			"Save",
			Command("controlEnd"),
			Command("controlStart", Field(role=Role.EDITABLETEXT)),
			"Search",
			Command("controlEnd"),
			Command("controlEnd"),
		]
		graph = parser.extract_graph(ObjectWithFields(fields))
		self.assertEqual(
			[(node.role, node.name, node.landmark, node.control_type) for node in graph.nodes],
			[
				("heading", "Title", None, None),
				("landmark", "Details Save Search", "navigation", None),
				("link", "Details", None, None),
				("button", "Save", None, None),
				("formField", "Search", None, "input"),
			],
		)

	def test_graph_sections_reference_normalized_nodes(self) -> None:
		parser = _load_parser()()
		fields = [
			Command("controlStart", Field(role=Role.HEADING, **{"IAccessible2::attribute_tag": "h2"})),
			"Overview",
			Command("controlEnd"),
			Command("controlStart", Field(role=Role.STATICTEXT)),
			"Overview",
			Command("controlStart", Field(role=Role.LINK)),
			"Details",
			Command("controlEnd"),
			Command("controlEnd"),
			Command("controlStart", Field(role=Role.HEADING, **{"IAccessible2::attribute_tag": "h2"})),
			"Contact",
			Command("controlEnd"),
		]
		graph = parser.extract_graph(ObjectWithFields(fields), "Overview\nDetails\nContact")
		node_ids = {node.id for node in graph.nodes}
		for section in graph.sections:
			self.assertIn(section.heading_node_id, node_ids)
			self.assertTrue(set(section.node_ids) <= node_ids)
		self.assertNotIn("node-1", node_ids)

	def test_graph_compacts_repeated_full_page_root_text(self) -> None:
		parser = _load_parser()()
		page_text = "Long page text " * 30
		fields = [
			Command("controlStart", Field(role=Role.STATICTEXT)),
			page_text,
			Command("controlEnd"),
		]
		graph = parser.extract_graph(ObjectWithFields(fields), page_text)
		self.assertEqual(len(graph.nodes), 1)
		self.assertEqual(graph.nodes[0].role, "container")
		self.assertEqual(graph.nodes[0].name, "")
		self.assertEqual(graph.nodes[0].text, "")


if __name__ == "__main__":
	unittest.main()
