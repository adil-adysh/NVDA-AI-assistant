# -*- coding: utf-8 -*-
"""Pure tests for context reduction; no NVDA or native extension required."""
from __future__ import annotations

import unittest

from tests.support import load_addon_module

types_module = load_addon_module("context.types", namespace="context_reduction_testpkg")
reduction = load_addon_module("context.reduction", namespace="context_reduction_testpkg")


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


	def test_large_cache_lookup_keeps_every_vector_for_current_request(self) -> None:
		reducer = reduction.ContextReducer(_FakeEmbedder())
		vectors = reducer._embed_cached([f"chunk {index}" for index in range(513)])
		self.assertEqual(len(vectors), 513)

	def test_page_retrieval_falls_back_within_budget(self) -> None:
		class UnavailableEmbedder(_FakeEmbedder):
			def embed(self, texts):
				raise RuntimeError("Worker unavailable")

		page = reduction.CurrentPageContext(reduction.ContextReducer(UnavailableEmbedder()))
		context = self._context("first " * 50 + "\n\n" + "second " * 50)
		page.set(context, "conversation")
		budget = reduction.ContextWindowBudget(120, 10, 2)
		result = page.retrieve("question", "conversation", budget)
		self.assertIn("first", result)
		self.assertLessEqual(reduction.ApproximateTokenEstimator().count(result), 108)

	def test_graph_retrieval_bounds_oversized_sections(self) -> None:
		text = "word " * 200
		graph = types_module.AccessibilityGraph(
			sections=(types_module.SemanticSection("section", "Section", text, 0),)
		)
		context = types_module.PromptContext(
			use_case_id="chat",
			extraction_result=types_module.ExtractionResult("Title", "Browser", text, False, graph=graph),
		)
		page = reduction.CurrentPageContext(reduction.ContextReducer(_FakeEmbedder()))
		page.set(context, "conversation")
		result = page.retrieve("word", "conversation", reduction.ContextWindowBudget(120, 10, 2))
		self.assertIn("word", result)
		self.assertLessEqual(reduction.ApproximateTokenEstimator().count(result), 108)


	def test_page_retrieval_reads_embedding_switch_each_turn(self) -> None:
		class CountingEmbedder(_FakeEmbedder):
			calls = 0

			def embed(self, texts):
				self.calls += 1
				return super().embed(texts)

		embedder = CountingEmbedder()
		enabled = False
		page = reduction.CurrentPageContext(
			reduction.ContextReducer(embedder), max_tokens=100, embeddings_enabled=lambda: enabled,
		)
		page.set(self._context("target " * 50 + "\n\n" + "other " * 50), "conversation")
		self.assertIn("target", page.retrieve("target", "conversation"))
		self.assertEqual(embedder.calls, 0)
		enabled = True
		page.retrieve("target", "conversation")
		self.assertEqual(embedder.calls, 1)

	def test_page_retrieval_propagates_cancellation(self) -> None:
		class CancelledEmbedder(_FakeEmbedder):
			def embed(self, texts):
				raise reduction.RequestCancelled()

		page = reduction.CurrentPageContext(reduction.ContextReducer(CancelledEmbedder()), max_tokens=100)
		page.set(self._context("target " * 100), "conversation")
		with self.assertRaises(reduction.RequestCancelled):
			page.retrieve("target", "conversation")

	def test_malformed_vectors_are_rejected_before_caching(self) -> None:
		class MalformedEmbedder(_FakeEmbedder):
			def embed(self, texts):
				return [(1.0, 2.0), (float("nan"), 0.0)]

		reducer = reduction.ContextReducer(MalformedEmbedder())
		with self.assertRaises(ValueError):
			reducer._embed_cached(["first", "second"])
		self.assertFalse(reducer._embedding_cache)


	def test_graph_retrieval_keeps_heading_path_on_split_passages(self) -> None:
		parent = types_module.AccessibilityNode("parent", "heading", "Setup", 0, heading_level=1)
		child = types_module.AccessibilityNode("child", "heading", "Offline installation", 1, heading_level=2)
		section = types_module.SemanticSection(
			"section", child.name, "generic " * 185 + "\n\n" + "Use installer E-201.", 1, child.id,
		)
		graph = types_module.AccessibilityGraph((parent, child), (section,))
		result = types_module.ExtractionResult("Title", "Browser", section.text, False, graph=graph)
		page = reduction.CurrentPageContext(reduction.ContextReducer(), max_tokens=100)
		page.set(types_module.PromptContext(use_case_id="chat", extraction_result=result), "chat")
		retrieved = page.retrieve("E-201", "chat")
		self.assertIn("Setup > Offline installation", retrieved)
		self.assertIn("Use installer E-201.", retrieved)

	def test_exact_identifier_survives_semantic_ranking(self) -> None:
		reducer = reduction.ContextReducer(_FakeEmbedder())
		chunks = reducer._segmenter.segment(
			"target information about E-120\n\nFix for E-12\n\n" +
			"\n\n".join(f"target reference E-120 ({i})" for i in range(50))
		)
		ranked = reducer._rank_for_retrieval(chunks, "target E-12", None, True)
		self.assertEqual(ranked[0].text, "Fix for E-12")

	def test_graph_retrieval_uses_budget_for_distinct_evidence(self) -> None:
		paragraphs = ["Plan A costs $10.", "Plan B costs $20."] + [
			f"Distinct evidence number {index}." for index in range(6)
		]
		sections = tuple(
			types_module.SemanticSection(str(i), "Plans", text, i)
			for i, text in enumerate(["Plan A costs $10."] * 5 + paragraphs)
		)
		graph = types_module.AccessibilityGraph(sections=sections)
		result = types_module.ExtractionResult("Title", "Browser", "Plans", False, graph=graph)
		page = reduction.CurrentPageContext(reduction.ContextReducer())
		page.set(types_module.PromptContext(use_case_id="chat", extraction_result=result), "chat")
		retrieved = page.retrieve("Compare Plan A and Plan B", "chat")
		self.assertEqual(retrieved.count("Plan A costs $10."), 1)
		self.assertIn("Plan B costs $20.", retrieved)
		self.assertIn("Distinct evidence number 5.", retrieved)


	def test_comparison_keeps_both_sides_when_embeddings_favor_one(self) -> None:
		reducer = reduction.ContextReducer(_FakeEmbedder())
		chunks = reducer._segmenter.segment(
			"Compare Plan A and Plan B here.\n\n"
			"Plan A has target data at $10.\n\nPlan A has target support.\n\nPlan B costs $20."
		)
		ranked = reducer._rank_for_retrieval(chunks, "Compare Plan A and Plan B", None, True)
		self.assertEqual([chunk.text for chunk in ranked[:2]], [
			"Plan A has target data at $10.", "Plan B costs $20.",
		])

	def test_exact_match_keeps_adjacent_section_context_before_unrelated_passages(self) -> None:
		sections = (
			types_module.SemanticSection("other", "Questions", "target details", 0),
			types_module.SemanticSection("plan", "Pricing", "Plan | Monthly | Annual\nE-12 | $10 | $100", 1),
		)
		reducer = reduction.ContextReducer(_FakeEmbedder())
		chunks = reducer._graph_passages(types_module.AccessibilityGraph(sections=sections))
		ranked = reducer._rank_for_retrieval(chunks, "What does E-12 cost?", None, True)
		self.assertIn("E-12 | $10 | $100", ranked[0].text)
		self.assertIn("Plan | Monthly | Annual", ranked[1].text)


if __name__ == "__main__":
	unittest.main()
