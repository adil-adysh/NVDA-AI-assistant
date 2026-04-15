# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
from typing import Callable, cast

from ..context.collectors.image import ImageContextCollector
from ..context.collectors.page import PageContextCollector
from ..context.extractors.browser import BrowserAwarePageExtractor
from ..context.pipeline import ContextPipeline
from ..image.services import ImageCaptureService, ImageEncoder, ImagePreprocessor
from ..observability.reporter import FileMetricsReporter
from ..providers.provider_proxy import ProviderProxy
from ..service.chat import ChatCoordinator
from ..service.llm import ProviderLLMService
from ..tools import ToolDefinition, ToolExecutor, ToolRegistry
from ..use_case.engine import UseCaseEngine
from .types import PluginServices


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


def build_plugin_services() -> PluginServices:
	provider = ProviderProxy()
	metrics_reporter = FileMetricsReporter()
	page_context_collector = PageContextCollector(extractor=BrowserAwarePageExtractor())
	image_context_collector = ImageContextCollector(
		capture_service=ImageCaptureService(),
		preprocessor=ImagePreprocessor(),
		encoder=ImageEncoder(),
	)
	context_pipeline = ContextPipeline(
		collectors=(page_context_collector, image_context_collector),
	)
	tool_registry = ToolRegistry()
	_register_default_tools(tool_registry)
	tool_executor = ToolExecutor(tool_registry)
	llm_service = ProviderLLMService(provider, tool_executor=tool_executor)
	chat_coordinator = ChatCoordinator(client=llm_service, metrics_reporter=metrics_reporter)
	use_case_engine = UseCaseEngine(
		chat_coordinator=chat_coordinator,
		llm_service=llm_service,
		context_pipeline=context_pipeline,
		page_context_collector=page_context_collector,
		image_context_collector=image_context_collector,
	)
	return PluginServices(
		provider=provider,
		metrics_reporter=metrics_reporter,
		page_context_collector=page_context_collector,
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
