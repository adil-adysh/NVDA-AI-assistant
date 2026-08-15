# Pylint cannot infer attributes from the synthetic package bootstrap.
# pylint: disable=no-member
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "prompts_summary_testpkg"


def _register_package(name: str, path: Path) -> None:
	module = types.ModuleType(name)
	module.__path__ = [str(path)]
	sys.modules[name] = module


def _load(module_name: str, path: Path):
	spec = importlib.util.spec_from_file_location(module_name, path)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[module_name] = module
	spec.loader.exec_module(module)
	return module


_register_package(PACKAGE_NAME, ROOT_DIR)
_register_package(f"{PACKAGE_NAME}.context", ROOT_DIR / "context")
_register_package(f"{PACKAGE_NAME}.prompts", MODULE_DIR)
types_module = _load(f"{PACKAGE_NAME}.context.types", ROOT_DIR / "context" / "types.py")
_load(f"{PACKAGE_NAME}.prompts.base", MODULE_DIR / "base.py")
summary_module = _load(f"{PACKAGE_NAME}.prompts.summary", MODULE_DIR / "summary.py")


class GraphFirstPromptTests(unittest.TestCase):
	def test_graph_is_authoritative_over_legacy_structure(self) -> None:
		graph = types_module.AccessibilityGraph(
			nodes=(
				types_module.AccessibilityNode("h1", "heading", "Graph heading", 0, heading_level=1),
				types_module.AccessibilityNode("b1", "button", "Graph action", 1),
			),
		)
		legacy = types_module.ExtractionStructure(
			headings=((1, "Stale heading"),),
			buttons=("Stale action",),
		)
		context = types_module.ExtractionResult(
			title="Page",
			app_title="Browser",
			text="",
			truncated=False,
			structure=legacy,
			graph=graph,
		)

		prompt = summary_module.build_structure_summary_prompt(context)

		self.assertIn("Graph heading", prompt)
		self.assertIn("Graph action", prompt)
		self.assertNotIn("Stale heading", prompt)
		self.assertNotIn("Stale action", prompt)

	def test_structure_fallback_remains_available_without_graph(self) -> None:
		context = types_module.ExtractionResult(
			title="Page",
			app_title="Browser",
			text="",
			truncated=False,
			structure=types_module.ExtractionStructure(buttons=("Legacy action",)),
		)

		prompt = summary_module.build_structure_summary_prompt(context)

		self.assertIn("Legacy action", prompt)


if __name__ == "__main__":
	unittest.main()
