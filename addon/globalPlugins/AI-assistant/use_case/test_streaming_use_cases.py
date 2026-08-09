# -*- coding: utf-8 -*-
# Pylint cannot infer attributes assigned to types.ModuleType() fakes used
# to stub NVDA-internal modules (E1101 ``__name__`` false positives).
# Test files deliberately duplicate the self-contained synthetic-package
# bootstrap so each suite can run standalone (R0801).
# pylint: disable=no-member,duplicate-code
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "use_case_streaming_testpkg"


def _register_package(name: str, path: Path | None = None) -> types.ModuleType:
	module = types.ModuleType(name)
	if path is not None:
		module.__path__ = [str(path)]
	sys.modules[name] = module
	return module


def _load_module(module_name: str, file_path: Path):
	spec = importlib.util.spec_from_file_location(module_name, file_path)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[module_name] = module
	spec.loader.exec_module(module)
	return module


_register_package(PACKAGE_NAME, ROOT_DIR)
_register_package(f"{PACKAGE_NAME}.context", ROOT_DIR / "context")
_register_package(f"{PACKAGE_NAME}.service", ROOT_DIR / "service")
_register_package(f"{PACKAGE_NAME}.use_case", ROOT_DIR / "use_case")
_register_package(f"{PACKAGE_NAME}.utils", ROOT_DIR / "utils")

context_pipeline_module = types.ModuleType(f"{PACKAGE_NAME}.context.pipeline")
context_pipeline_module.ContextPipeline = object
sys.modules[context_pipeline_module.__name__] = context_pipeline_module


@dataclass(frozen=True)
class ExtractionStructure:
	headings: tuple[tuple[int | None, str], ...] = ()
	links: tuple[str, ...] = ()
	buttons: tuple[str, ...] = ()
	landmarks: tuple[str, ...] = ()
	inputs: tuple[str, ...] = ()
	comboboxes: tuple[str, ...] = ()
	checkboxes: tuple[str, ...] = ()
	radios: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtractionResult:
	text: str
	title: str | None = None
	app_title: str | None = None
	structure: ExtractionStructure | None = None


@dataclass(frozen=True)
class ImageContext:
	image_base64: str | None = None


@dataclass(frozen=True)
class PromptContext:
	use_case_id: str
	facts: dict[str, object] = field(default_factory=dict)
	language: str = "en"
	extraction_result: ExtractionResult | None = None
	text: str | None = None
	image_base64: str | None = None
	metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PageTextRequest:
	"""Minimal stand-in for context.types.PageTextRequest."""


@dataclass(frozen=True)
class PageStructureRequest:
	"""Minimal stand-in for context.types.PageStructureRequest."""

	fields: tuple[object, ...] = ()


@dataclass(frozen=True)
class ForegroundImageRequest:
	"""Minimal stand-in for context.types.ForegroundImageRequest."""


@dataclass(frozen=True)
class ExtractionIntent:
	"""Minimal stand-in for context.types.ExtractionIntent."""

	requests: tuple[object, ...] = ()


context_types_module = types.ModuleType(f"{PACKAGE_NAME}.context.types")
context_types_module.APP = "app"
context_types_module.PAGE = "page"
context_types_module.IMAGE = "image"
context_types_module.ContextProfileList = tuple[str, ...]
context_types_module.ExtractionResult = ExtractionResult
context_types_module.ExtractionStructure = ExtractionStructure
context_types_module.ImageContext = ImageContext
context_types_module.PromptContext = PromptContext
context_types_module.PageTextRequest = PageTextRequest
context_types_module.PageStructureRequest = PageStructureRequest
context_types_module.ForegroundImageRequest = ForegroundImageRequest
context_types_module.ExtractionIntent = ExtractionIntent
sys.modules[context_types_module.__name__] = context_types_module

providers_interfaces_module = types.ModuleType(f"{PACKAGE_NAME}.providers.interfaces")
providers_interfaces_module.PartialCallback = object
sys.modules[providers_interfaces_module.__name__] = providers_interfaces_module

service_llm_module = types.ModuleType(f"{PACKAGE_NAME}.service.llm")
service_llm_module.LLMService = object
sys.modules[service_llm_module.__name__] = service_llm_module

utils_markdown_module = types.ModuleType(f"{PACKAGE_NAME}.utils.markdown")
utils_markdown_module.render_markdown_to_html = lambda text: f"<p>{text}</p>"
sys.modules[utils_markdown_module.__name__] = utils_markdown_module

prompts_module = types.ModuleType(f"{PACKAGE_NAME}.prompts")
prompts_module.build_extraction_summary_prompt = lambda extraction_result, language: (
	f"summary:{extraction_result.text}:{language}"
)
prompts_module.build_extraction_structure_summary_prompt = lambda extraction_result, language: (
	f"structure:{extraction_result.text}:{language}"
)
prompts_module.build_image_description_prompt = lambda image_context, language: (
	f"image:{image_context.image_base64}:{language}"
)
sys.modules[prompts_module.__name__] = prompts_module

types_module = _load_module(
	f"{PACKAGE_NAME}.use_case.types",
	ROOT_DIR / "use_case" / "types.py",
)
_load_module(
	f"{PACKAGE_NAME}.use_case.base",
	ROOT_DIR / "use_case" / "base.py",
)
summary_module = _load_module(
	f"{PACKAGE_NAME}.use_case.summary",
	ROOT_DIR / "use_case" / "summary.py",
)
structure_summary_module = _load_module(
	f"{PACKAGE_NAME}.use_case.structure_summary",
	ROOT_DIR / "use_case" / "structure_summary.py",
)
image_module = _load_module(
	f"{PACKAGE_NAME}.use_case.image",
	ROOT_DIR / "use_case" / "image.py",
)

SummaryUseCase = summary_module.SummaryUseCase
StructureSummaryUseCase = structure_summary_module.StructureSummaryUseCase
ImageDescriptionUseCase = image_module.ImageDescriptionUseCase
ResultContextItem = types_module.ResultContextItem
ResultOutputItem = types_module.ResultOutputItem


class _Pipeline:
	def __init__(self, prompt_context: PromptContext) -> None:
		self._prompt_context = prompt_context

	def collect(self, **_kwargs):
		return self._prompt_context


class _StreamingLLMService:
	def __init__(self) -> None:
		self.summary_stream_handler = None
		self.image_stream_handler = None

	def supports_image_description(self) -> bool:
		return True

	def provider_name(self) -> str:
		return "test"

	def summarize(self, _prompt: str, stream_handler=None):
		self.summary_stream_handler = stream_handler
		if stream_handler is not None:
			stream_handler("partial summary", len("partial summary"))
		return types.SimpleNamespace(text="final summary", model="test-model", provider="test")

	def describe_image(  # pylint: disable=unused-argument
		self, image_base64: str, prompt: str, stream_handler=None
	):
		self.image_stream_handler = stream_handler
		if stream_handler is not None:
			stream_handler("partial image", len("partial image"))
		return types.SimpleNamespace(text="final image", model="test-model", provider="test")


class StreamingUseCaseTests(unittest.TestCase):
	def test_summary_use_case_passes_stream_handler_and_emits_streaming(self) -> None:
		service = _StreamingLLMService()
		events: list[tuple[str, str]] = []

		def emit(stage: str, message: str) -> None:
			events.append((stage, message))

		pipeline = _Pipeline(
			PromptContext(
				use_case_id="summary",
				extraction_result=ExtractionResult(text="example page"),
			)
		)

		result = SummaryUseCase().execute(pipeline, service, emit=emit)

		self.assertEqual(result.output_text, "final summary")
		self.assertTrue(callable(service.summary_stream_handler))
		self.assertIn(("streaming", "partial summary"), events)
		self.assertEqual(
			[(item.id, item.content) for item in result.context_items],
			[("page_content", "Page content:\nexample page")],
		)
		self.assertEqual(
			[(item.id, item.content) for item in result.output_items],
			[("summary", "final summary")],
		)

	def test_summary_use_case_includes_structure_context_item_when_present(self) -> None:
		service = _StreamingLLMService()
		pipeline = _Pipeline(
			PromptContext(
				use_case_id="summary",
				extraction_result=ExtractionResult(
					text="example page",
					title="My Page",
					app_title="Browser",
					structure=ExtractionStructure(headings=((1, "Intro"),)),
				),
			)
		)

		result = SummaryUseCase().execute(pipeline, service)

		self.assertEqual(
			[item.id for item in result.context_items],
			["page_content", "page_structure"],
		)
		self.assertIn("Headings:\n- H1: Intro", result.context_items[1].content)
		self.assertIn("Title: My Page", result.context_items[0].content)
		self.assertIn("App: Browser", result.context_items[0].content)

	def test_structure_summary_use_case_passes_stream_handler_and_emits_streaming(self) -> None:
		service = _StreamingLLMService()
		events: list[tuple[str, str]] = []

		def emit(stage: str, message: str) -> None:
			events.append((stage, message))

		pipeline = _Pipeline(
			PromptContext(
				use_case_id="structure_summary",
				extraction_result=ExtractionResult(text="example page"),
			)
		)

		result = StructureSummaryUseCase().execute(pipeline, service, emit=emit)

		self.assertEqual(result.output_text, "final summary")
		self.assertTrue(callable(service.summary_stream_handler))
		self.assertIn(("streaming", "partial summary"), events)
		self.assertEqual(
			[(item.id, item.content) for item in result.output_items],
			[("structure_summary", "final summary")],
		)
		self.assertEqual(
			[item.id for item in result.context_items],
			["page_content"],
		)

	def test_image_description_use_case_passes_stream_handler_and_emits_streaming(self) -> None:
		service = _StreamingLLMService()
		events: list[tuple[str, str]] = []

		def emit(stage: str, message: str) -> None:
			events.append((stage, message))

		pipeline = _Pipeline(
			PromptContext(
				use_case_id="describe_image",
				facts={"image_context": ImageContext(image_base64="abc123")},
			)
		)

		result = ImageDescriptionUseCase().execute(pipeline, service, emit=emit)

		self.assertEqual(result.output_text, "final image")
		self.assertTrue(callable(service.image_stream_handler))
		self.assertIn(("streaming", "partial image"), events)
		self.assertEqual(
			[(item.id, item.image_base64) for item in result.context_items],
			[("screenshot", "abc123")],
		)
		self.assertEqual(
			[(item.id, item.content) for item in result.output_items],
			[("image_description", "final image")],
		)


if __name__ == "__main__":
	unittest.main()
