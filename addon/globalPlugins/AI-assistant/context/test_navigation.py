"""Tests for complete navigation candidate extraction and resolution."""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types
import unittest


MODULE_PATH = Path(__file__).with_name("navigation.py")


def _load_navigation():
	root_name = "navigation_test_package"
	context_name = f"{root_name}.context"
	for name, path in ((root_name, MODULE_PATH.parent.parent), (context_name, MODULE_PATH.parent)):
		package = types.ModuleType(name)
		package.__path__ = [str(path)]
		sys.modules[name] = package

	types_spec = spec_from_file_location(
		f"{context_name}.types", MODULE_PATH.with_name("types.py")
	)
	assert types_spec is not None and types_spec.loader is not None
	types_module = module_from_spec(types_spec)
	sys.modules[types_spec.name] = types_module
	types_spec.loader.exec_module(types_module)

	navigation_spec = spec_from_file_location(f"{context_name}.navigation", MODULE_PATH)
	assert navigation_spec is not None and navigation_spec.loader is not None
	navigation_module = module_from_spec(navigation_spec)
	sys.modules[navigation_spec.name] = navigation_module
	navigation_spec.loader.exec_module(navigation_module)
	return navigation_module, types_module


class _FakeItem:
	def __init__(self, name: str) -> None:
		self.name = name
		self.moved = False

	def moveTo(self) -> None:
		self.moved = True


class _FakeTreeInterceptor:
	def __init__(self, items: list[_FakeItem]) -> None:
		self.items = items

	def _iterNodesByType(self, _role: object, direction: str, pos: object):
		return iter(self.items)

	def makeTextInfo(self, _position: object) -> object:
		return object()


class _FakeEmbedder:
	model_key = "fake"

	@staticmethod
	def _vector(text: str) -> tuple[float, float]:
		text = text.casefold()
		return (1.0, 0.0) if "download" in text else (0.0, 1.0)

	def embed_query(self, _query: str, _instruction: str) -> tuple[float, float]:
		return self._vector(_query)

	def embed(self, texts: list[str]) -> tuple[tuple[float, float], ...]:
		return tuple(self._vector(text) for text in texts)


class NavigationTests(unittest.TestCase):
	def setUp(self) -> None:
		self.navigation, self.graph_types = _load_navigation()

	def _graph(self):
		AccessibilityGraph = self.graph_types.AccessibilityGraph
		AccessibilityNode = self.graph_types.AccessibilityNode
		SemanticSection = self.graph_types.SemanticSection
		return AccessibilityGraph(
			nodes=(
				AccessibilityNode("node-0", "heading", "Product", 0),
				AccessibilityNode("node-1", "button", "Add to cart", 1, "node-0"),
				AccessibilityNode("node-2", "heading", "Recommendations", 2),
				AccessibilityNode("node-3", "button", "Add to cart", 3, "node-2"),
			),
			sections=(
				SemanticSection("section-product", "Product", "", 0, "node-0", ("node-1",)),
				SemanticSection("section-recommendations", "Recommendations", "", 2, "node-2", ("node-3",)),
			),
		)

	def test_candidates_keep_duplicate_actions_with_context(self) -> None:
		candidates = self.navigation.build_navigation_candidates(graph=self._graph())
		buttons = [candidate for candidate in candidates if candidate.role == "button"]
		self.assertEqual(len(buttons), 2)
		self.assertEqual({candidate.section_id for candidate in buttons}, {"section-product", "section-recommendations"})
		self.assertEqual({candidate.occurrence for candidate in buttons}, {0, 1})
		self.assertIn("section: Product", buttons[0].context_text)
		self.assertIn("ancestors: Product", buttons[0].context_text)
		self.assertEqual(buttons[0].parent_name, "Product")
		product_heading = next(candidate for candidate in candidates if candidate.name == "Product")
		self.assertEqual(product_heading.child_names, ("Add to cart",))
		self.assertIn("children: Add to cart", product_heading.context_text)

	def test_bounded_selection_does_not_change_complete_candidates(self) -> None:
		candidates = self.navigation.build_navigation_candidates(graph=self._graph())
		selected = self.navigation.build_navigation_targets(graph=self._graph(), max_targets=2)
		self.assertEqual(len(candidates), 4)
		self.assertEqual(len(selected), 2)
		self.assertEqual(len(self.navigation.build_navigation_candidates(graph=self._graph())), 4)

	def test_llm_inventory_is_bounded_without_becoming_importance_ranking(self) -> None:
		candidates = self.navigation.build_navigation_candidates(graph=self._graph())
		inventory = self.navigation.build_llm_navigation_candidates(
			graph=self._graph(), max_candidates=2
		)
		self.assertEqual(len(candidates), 4)
		self.assertEqual(len(inventory), 2)
		self.assertTrue(any(target.kind == "section" for target in inventory))

	def test_resolution_uses_duplicate_occurrence(self) -> None:
		sys.modules["textInfos"] = types.SimpleNamespace(POSITION_FIRST=object())
		items = [_FakeItem("Add to cart"), _FakeItem("Add to cart")]
		target = next(
			candidate for candidate in self.navigation.build_navigation_candidates(graph=self._graph())
			if candidate.role == "button" and candidate.occurrence == 1
		)
		succeeded, label = self.navigation.resolve_and_move_target(
			target.to_dict(), _FakeTreeInterceptor(items)
		)
		self.assertTrue(succeeded)
		self.assertEqual(label, "Add to cart")
		self.assertFalse(items[0].moved)
		self.assertTrue(items[1].moved)

	def test_index_searches_sections_and_actions(self) -> None:
		candidates = self.navigation.build_navigation_candidates(graph=self._graph())
		index = self.navigation.NavigationIndex(candidates)
		section_result = index.search("go to the product section", max_targets=1)
		action_result = index.search("find the add to cart button", max_targets=1)
		self.assertEqual(section_result[0].name, "Product")
		self.assertEqual(action_result[0].role, "button")
		self.assertEqual(action_result[0].name, "Add to cart")

	def test_index_ranks_primary_actions_without_query(self) -> None:
		candidates = self.navigation.build_navigation_candidates(graph=self._graph())
		index = self.navigation.NavigationIndex(candidates)
		actions = index.primary_actions(max_targets=2)
		self.assertEqual([target.name for target in actions], ["Add to cart", "Add to cart"])

	def test_index_embedding_can_recover_from_weak_lexical_overlap(self) -> None:
		NavigationTarget = self.navigation.NavigationTarget
		candidates = (
			NavigationTarget("download", "link", "Download", 0, "", 70, kind="action", context_text="link: Download"),
			NavigationTarget("cart", "button", "Add to cart", 1, "", 84, kind="action", context_text="button: Add to cart"),
		)
		index = self.navigation.NavigationIndex(candidates, embedder=_FakeEmbedder())
		result = index.search("download an add-on", max_targets=1)
		self.assertEqual(result[0].name, "Download")


if __name__ == "__main__":
	unittest.main()
