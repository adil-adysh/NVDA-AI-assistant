# -*- coding: utf-8 -*-
"""Pure tests for context pipeline request and snapshot invariants."""
from __future__ import annotations

import types
import threading
import unittest

from tests.support import ADDON_ROOT, load_module, register_package

_ROOT = ADDON_ROOT / "context"
_PACKAGE = "context_pipeline_testpkg"
register_package(_PACKAGE, _ROOT)
types_module = load_module(f"{_PACKAGE}.types", _ROOT / "types.py")
load_module(f"{_PACKAGE}.protocols", _ROOT / "protocols.py")
pipeline_module = load_module(f"{_PACKAGE}.pipeline", _ROOT / "pipeline.py")


class _PageCollector:
	def handles_request(self, request):
		return isinstance(request, types_module.PageStructureRequest)

	def collect_for_request(self, _request, input_):
		return types.SimpleNamespace(
			facts={"extraction_snapshot": input_.extraction_snapshot},
			text=None,
			image_base64=None,
			metadata={},
		)


class _FocusedTextCollector:
	def handles_request(self, request):
		return isinstance(request, types_module.FocusedElementTextRequest)

	def collect_for_request(self, _request, input_):
		return types.SimpleNamespace(
			facts={"focused_text_snapshot": input_.focused_text_snapshot},
			text=input_.focused_text_snapshot.text,
			image_base64=None,
			metadata={},
		)


class ContextPipelineTests(unittest.TestCase):
	def test_only_snapshot_resolution_crosses_nvda_event_thread_boundary(self) -> None:
		snapshot = types_module.ExtractionSnapshot("Title", "Browser", "content", False)
		event_thread: list[threading.Thread] = []
		collector_thread: list[threading.Thread] = []

		class RecordingCollector(_PageCollector):
			def collect_for_request(self, request, input_):
				collector_thread.append(threading.current_thread())
				return super().collect_for_request(request, input_)

		def event_thread_executor(callable_):
			result: list[object] = []

			def run() -> None:
				event_thread.append(threading.current_thread())
				result.append(callable_())

			thread = threading.Thread(target=run, name="NVDAEventThread")
			thread.start()
			thread.join(timeout=2)
			return result[0]

		pipeline = pipeline_module.ContextPipeline(
			(RecordingCollector(),),
			event_thread_executor,
			page_extractor=lambda: snapshot,
		)
		pipeline.collect(
			"structure_summary",
			types_module.ExtractionIntent(requests=(types_module.PageStructureRequest(),)),
		)

		self.assertEqual(event_thread[0].name, "NVDAEventThread")
		self.assertIs(collector_thread[0], threading.current_thread())
		self.assertIsNot(collector_thread[0], event_thread[0])

	def test_structure_request_uses_explicit_page_extractor(self) -> None:
		snapshot = types_module.ExtractionSnapshot("Title", "Browser", "content", False)
		pipeline = pipeline_module.ContextPipeline(
			(_PageCollector(),),
			lambda callable_: callable_(),
			page_extractor=lambda: snapshot,
		)

		context = pipeline.collect(
			"structure_summary",
			types_module.ExtractionIntent(
				requests=(types_module.PageStructureRequest(),)
			),
		)

		self.assertIs(context.facts["extraction_snapshot"], snapshot)
		self.assertIsNotNone(context.extraction_result)
		self.assertEqual(context.extraction_result.text, "content")

	def test_page_request_without_extractor_fails_at_pipeline_boundary(self) -> None:
		pipeline = pipeline_module.ContextPipeline(
			(_PageCollector(),),
			lambda callable_: callable_(),
		)

		with self.assertRaises(types_module.ContextCollectionError):
			pipeline.collect(
				"structure_summary",
				types_module.ExtractionIntent(
					requests=(types_module.PageStructureRequest(),)
				),
			)

	def test_focused_text_request_uses_explicit_focused_text_extractor(self) -> None:
		snapshot = types_module.FocusedTextSnapshot("teh sentence")
		pipeline = pipeline_module.ContextPipeline(
			(_FocusedTextCollector(),),
			lambda callable_: callable_(),
			focused_text_extractor=lambda: snapshot,
		)

		context = pipeline.collect(
			"proofread",
			types_module.ExtractionIntent(
				requests=(types_module.FocusedElementTextRequest(),)
			),
		)

		self.assertIs(context.facts["focused_text_snapshot"], snapshot)
		self.assertEqual(context.text, "teh sentence")

	def test_unhandled_request_fails_instead_of_returning_empty_context(self) -> None:
		pipeline = pipeline_module.ContextPipeline((), lambda callable_: callable_())

		with self.assertRaises(types_module.ContextCollectionError):
			pipeline.collect(
				"unknown",
				types_module.ExtractionIntent(
					requests=(types_module.PageTextRequest(),)
				),
			)

	def test_unknown_request_kind_fails_before_snapshot_resolution(self) -> None:
		class UnknownRequest:
			kind = "unknown_extension_request"

		pipeline = pipeline_module.ContextPipeline((), lambda callable_: callable_())

		with self.assertRaises(types_module.ContextCollectionError):
			pipeline.collect(
				"custom",
				types_module.ExtractionIntent(requests=(UnknownRequest(),)),
			)


if __name__ == "__main__":
	unittest.main()
