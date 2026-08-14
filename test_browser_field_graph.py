# -*- coding: utf-8 -*-
"""Pure graph extraction tests without an NVDA runtime."""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).parent / "addon" / "globalPlugins" / "AI-assistant" / "context"
PACKAGE = "browser_graph_testpkg"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
extractors_package = types.ModuleType(f"{PACKAGE}.extractors")
extractors_package.__path__ = [str(ROOT / "extractors")]
sys.modules[extractors_package.__name__] = extractors_package

control_types = types.ModuleType("controlTypes")
control_types.Role = type("Role", (), {})
sys.modules.setdefault("controlTypes", control_types)
text_infos = types.ModuleType("textInfos")
text_infos.POSITION_ALL = "all"
sys.modules.setdefault("textInfos", text_infos)


def load(name: str, path: Path) -> types.ModuleType:
	spec = importlib.util.spec_from_file_location(name, path)
	assert spec is not None and spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)
	return module


load(f"{PACKAGE}.types", ROOT / "types.py")
parser_module = load(f"{PACKAGE}.extractors.browser_field_parser", ROOT / "extractors" / "browser_field_parser.py")
BrowserFieldParser = parser_module.BrowserFieldParser
navigation_module = load(f"{PACKAGE}.navigation", ROOT / "navigation.py")
types_module = sys.modules[f"{PACKAGE}.types"]


class FieldCommand:
	def __init__(self, command: str, field: dict[str, object] | None = None) -> None:
		self.command = command
		self.field = field


class FakeTextInfo:
	def __init__(self, fields: list[object]) -> None:
		self._fields = fields

	def getTextWithFields(self):
		return self._fields


class FakeDocument:
	def __init__(self, fields: list[object]) -> None:
		self._fields = fields

	def makeTextInfo(self, _position: object) -> FakeTextInfo:
		return FakeTextInfo(self._fields)


class BrowserFieldGraphTests(unittest.TestCase):
	def test_graph_preserves_containment_and_sections(self) -> None:
		fields = [
			FieldCommand("controlStart", {"IAccessible2::attribute_tag": "main"}),
			FieldCommand("controlStart", {"IAccessible2::attribute_tag": "h2"}),
			"Getting Started",
			FieldCommand("controlEnd"),
			FieldCommand("controlStart", {"IAccessible2::attribute_tag": "a"}),
			"GitHub releases page",
			FieldCommand("controlEnd"),
			FieldCommand("controlEnd"),
		]
		parser = BrowserFieldParser()
		graph = parser.extract_graph(FakeDocument(fields), "Getting Started\nInstall from the release page")

		self.assertEqual([node.role for node in graph.nodes], ["landmark", "heading", "link"])
		self.assertEqual(graph.nodes[1].parent_id, graph.nodes[0].id)
		self.assertEqual(graph.nodes[2].parent_id, graph.nodes[0].id)
		self.assertEqual(graph.sections[0].title, "Getting Started")
		self.assertIn("Install from the release page", graph.sections[0].text)
		self.assertEqual(
			parser.structured_info_from_graph(graph)[1], ("GitHub releases page",)
		)

	def test_navigation_target_limit_is_hard_bound(self) -> None:
		graph = navigation_module.AccessibilityGraph(
			nodes=(types_module.AccessibilityNode("node-0", "heading", "Home", 0),)
		)
		self.assertEqual(navigation_module.build_navigation_targets(None, graph=graph, max_targets=0), ())

	def test_navigation_reads_nvda_accessible_name_before_legacy_label(self) -> None:
		self.assertEqual(
			navigation_module._node_label(types.SimpleNamespace(name="Search Results", label="")),
			"Search Results",
		)

	def test_navigation_uses_nvda_quick_nav_names(self) -> None:
		self.assertEqual(navigation_module._role_candidates("landmark"), ("landmark",))
		self.assertEqual(navigation_module._role_candidates("button"), ("button",))


if __name__ == "__main__":
	unittest.main()
