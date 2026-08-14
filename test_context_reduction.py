# -*- coding: utf-8 -*-
"""Pure tests for context reduction; no NVDA or native extension required."""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


_ROOT = Path(__file__).parent / "addon" / "globalPlugins" / "AI-assistant" / "context"
_PACKAGE = "context_reduction_testpkg"
package = types.ModuleType(_PACKAGE)
package.__path__ = [str(_ROOT)]
sys.modules[_PACKAGE] = package


def _load(name: str, path: Path) -> types.ModuleType:
	spec = importlib.util.spec_from_file_location(name, path)
	assert spec is not None and spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	sys.modules[name] = module
	spec.loader.exec_module(module)
	return module


types_module = _load(f"{_PACKAGE}.types", _ROOT / "types.py")
_load(f"{_PACKAGE}.formatting", _ROOT / "formatting.py")
reduction = _load(f"{_PACKAGE}.reduction", _ROOT / "reduction.py")


class _FakeEmbedder:
	model_key = "fake:v1"

	def embed(self, texts):
		return [(1.0, 0.0) if "target" in text else (0.0, 1.0) for text in texts]


class ContextReductionTests(unittest.TestCase):
	def _context(self, text: str):
		result = types_module.ExtractionResult("Title", "Browser", text, False)
		return types_module.PromptContext(
			use_case_id="summary",
			extraction_result=result,
			text=text,
		)

	def test_none_policy_preserves_context(self) -> None:
		context = self._context("one\n\ntwo")
		reducer = reduction.ContextReducer()
		self.assertIs(reducer.reduce(context, reduction.ContextReductionPolicy()), context)

	def test_coverage_selection_preserves_first_and_last_chunks(self) -> None:
		text = "\n\n".join(f"section {index} " + ("word " * 30) for index in range(8))
		context = self._context(text)
		result = reduction.ContextReducer().reduce(
			context,
				reduction.ContextReductionPolicy(mode="page_summary", max_tokens=160, max_chunks=4),
		)
		self.assertIn("section 0", result.text)
		self.assertIn("section 7", result.text)
		self.assertLessEqual(result.metadata["context_selected_tokens"], 160)

	def test_query_selection_uses_injected_embedder(self) -> None:
		context = self._context("background\n\ntarget information\n\nother")
		result = reduction.ContextReducer(embedder=_FakeEmbedder()).reduce(
			context,
			reduction.ContextReductionPolicy(
				mode="query_retrieval",
				max_tokens=5,
				max_chunks=1,
				allow_query_retrieval=True,
			),
			query="target question",
		)
		self.assertIn("target information", result.text)

	def test_prompt_aware_reduction_accounts_for_prompt_envelope(self) -> None:
		context = self._context("first " + ("word " * 30) + "\n\nsecond " + ("word " * 30))
		reducer = reduction.ContextReducer()
		result = reducer.reduce(
			context,
			reduction.ContextReductionPolicy(mode="page_summary", max_chunks=4),
			prompt_builder=lambda candidate: f"System instructions\n\n{candidate.text}\n\nReturn an answer.",
			prompt_budget=reduction.ContextWindowBudget(
				context_window_tokens=40,
				reserved_output_tokens=5,
				safety_margin_tokens=2,
			),
		)

		prompt = f"System instructions\n\n{result.text}\n\nReturn an answer."
		self.assertLessEqual(reduction.ApproximateTokenEstimator().count(prompt), 33)
		self.assertLess(result.metadata["context_selected_tokens"], result.metadata["context_original_tokens"])

	def test_budget_reserves_tokens_for_fixed_conversation_input(self) -> None:
		budget = reduction.ContextWindowBudget(
			context_window_tokens=100,
			reserved_output_tokens=10,
			safety_margin_tokens=5,
			reserved_input_tokens=20,
		)
		self.assertEqual(budget.input_token_limit, 65)

	def test_current_page_context_is_conversation_scoped(self) -> None:
		context = self._context("target information")
		page = reduction.CurrentPageContext(reduction.ContextReducer(embedder=_FakeEmbedder()))
		page.set(context, "conversation-1")
		self.assertIn("target information", page.retrieve("target", "conversation-1"))
		self.assertIsNone(page.retrieve("target", "conversation-2"))

	def test_current_page_context_preserves_structure_with_retrieved_content(self) -> None:
		structure = types_module.ExtractionStructure(
			headings=((2, "Software Solutions"), (3, "Software Releases")),
			landmarks=("main: Product information",),
			links=("JAWS 2026", "Downloads"),
		)
		result = types_module.ExtractionResult(
			"Title", "Browser", "target information", False, structure=structure
		)
		context = types_module.PromptContext(
			use_case_id="summary", extraction_result=result, text=result.text
		)
		page = reduction.CurrentPageContext(reduction.ContextReducer(embedder=_FakeEmbedder()))
		page.set(context, "conversation-1")

		retrieved = page.retrieve("target", "conversation-1")

		self.assertIn("Page structure:", retrieved)
		self.assertIn("H2: Software Solutions", retrieved)
		self.assertIn("H3: Software Releases", retrieved)
		self.assertIn("main: Product information", retrieved)
		self.assertIn("Relevant page content:\ntarget information", retrieved)

	def test_current_page_context_retrieves_graph_sections_with_embeddings(self) -> None:
		graph = types_module.AccessibilityGraph(
			sections=(
				types_module.SemanticSection("section-a", "Overview", "general introduction", 0),
				types_module.SemanticSection("section-b", "Downloads", "target download information", 1),
			)
		)
		result = types_module.ExtractionResult(
			"Title", "Browser", "general introduction\n\ntarget download information", False, graph=graph
		)
		page = reduction.CurrentPageContext(reduction.ContextReducer(embedder=_FakeEmbedder()))
		page.set(types_module.PromptContext(use_case_id="summary", extraction_result=result), "conversation-1")

		retrieved = page.retrieve("where is the target download", "conversation-1")

		self.assertIn("target download information", retrieved)


if __name__ == "__main__":
	unittest.main()
