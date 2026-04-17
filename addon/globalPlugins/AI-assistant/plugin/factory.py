# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
from typing import Callable, cast

from ..context.collectors.image import ImageContextCollector
from ..context.collectors.page import PageStructureCollector, PageTextCollector
from ..context.extractors.browser import BrowserAwarePageExtractor
from ..context.pipeline import ContextPipeline
from ..image.services import ImageCaptureService, ImageEncoder, ImagePreprocessor
from ..observability.reporter import FileMetricsReporter
from ..ui import nvda_ui
from ..providers.provider_proxy import ProviderProxy
from ..service.chat import ChatCoordinator
from ..service.llm import ProviderLLMService
from ..tools import ToolDefinition, ToolExecutor, ToolRegistry
from ..use_case.engine import UseCaseEngine
from ..use_case.registry import build_registered_use_cases
from .types import PluginServices


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


def build_plugin_services() -> PluginServices:
	provider = ProviderProxy()
	metrics_reporter = FileMetricsReporter()
	page_extractor = BrowserAwarePageExtractor()
	page_text_collector = PageTextCollector(extractor=page_extractor)
	page_structure_collector = PageStructureCollector(extractor=page_extractor)
	image_context_collector = ImageContextCollector(
		capture_service=ImageCaptureService(),
		preprocessor=ImagePreprocessor(),
		encoder=ImageEncoder(),
	)
	context_pipeline = ContextPipeline(
		collectors=(page_text_collector, page_structure_collector, image_context_collector),
		main_thread_executor=nvda_ui.call,
	)
	tool_registry = ToolRegistry()
	_register_default_tools(tool_registry)
	tool_executor = ToolExecutor(tool_registry)
	llm_service = ProviderLLMService(provider, tool_executor=tool_executor)
	chat_coordinator = ChatCoordinator(client=llm_service, metrics_reporter=metrics_reporter)
	use_case_engine = UseCaseEngine(
		llm_service=llm_service,
		context_pipeline=context_pipeline,
		use_cases=build_registered_use_cases(),
)
	return PluginServices(
		provider=provider,
		metrics_reporter=metrics_reporter,
		page_text_collector=page_text_collector,
		page_structure_collector=page_structure_collector,
		image_context_collector=image_context_collector,
		context_pipeline=context_pipeline,
		tool_registry=tool_registry,
		tool_executor=tool_executor,
		llm_service=llm_service,
		chat_coordinator=chat_coordinator,
		use_case_engine=use_case_engine,
	)


def _register_default_tools(tool_registry: ToolRegistry) -> None:
	tool_registry.register_tool(
		ToolDefinition(
			name="get_time",
			description="Get the current local date and time.",
			parameters={},
			required=[],
			executor=lambda args: __import__("datetime").datetime.now().isoformat(),
		)
	)
