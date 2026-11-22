"""Tests for complete navigation candidate extraction and resolution."""
from __future__ import annotations

import unittest

import pytest

from tests.support import ADDON_ROOT, load_module, register_package
from tests.support.bootstrap import load_addon_module


MODULE_PATH = ADDON_ROOT / "context" / "navigation.py"


def _load_navigation():
	root_name = "navigation_test_package"
	context_name = f"{root_name}.context"
	register_package(root_name, MODULE_PATH.parent.parent)
	register_package(context_name, MODULE_PATH.parent)
	types_module = load_module(f"{context_name}.types", MODULE_PATH.with_name("types.py"))
	navigation_module = load_module(f"{context_name}.navigation", MODULE_PATH)
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

	@pytest.mark.nvda_integration
	def test_resolution_uses_duplicate_occurrence(self) -> None:
		items = [_FakeItem("Add to cart settings"), _FakeItem("Add to cart"), _FakeItem("Add to cart")]
		target = next(
			candidate for candidate in self.navigation.build_navigation_candidates(graph=self._graph())
			if candidate.role == "button" and candidate.occurrence == 1
		)
		# The real textInfos.POSITION_FIRST constant is used. Only live object
		# movement state remains represented by the fake tree interceptor.
		succeeded, label = load_addon_module("ui.navigation_resolver").resolve_and_move_target(
			target.to_dict(), _FakeTreeInterceptor(items)
		)
		self.assertTrue(succeeded)
		self.assertEqual(label, "Add to cart")
		self.assertFalse(items[0].moved)
		self.assertFalse(items[1].moved)
		self.assertTrue(items[2].moved)

	def test_index_ranks_primary_actions_without_query(self) -> None:
		candidates = self.navigation.build_navigation_candidates(graph=self._graph())
		index = self.navigation.NavigationIndex(candidates)
		actions = index.primary_actions(max_targets=2)
		self.assertEqual([target.name for target in actions], ["Add to cart", "Add to cart"])

def test_navigation_waits_for_foreground_without_blocking(monkeypatch):
	resolver = load_addon_module("ui.navigation_resolver")
	interceptor = _FakeTreeInterceptor([])
	ready = False
	scheduled = []
	results = []
	monkeypatch.setattr(resolver, "_activate_browser", lambda _ti: lambda: ready)
	monkeypatch.setattr(resolver, "resolve_and_move_target", lambda _target, _ti: (True, "Account"))

	resolver.navigate_to_target(
		{"name": "Account"}, interceptor, lambda *result: results.append(result),
		schedule=lambda delay, callback: scheduled.append((delay, callback)),
	)

	assert results == []
	delay, retry = scheduled.pop()
	assert delay == 20
	ready = True
	retry()
	assert results == [(True, "Account")]
	assert scheduled == []
