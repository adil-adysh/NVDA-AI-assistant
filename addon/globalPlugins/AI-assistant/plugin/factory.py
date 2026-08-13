# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
from typing import Callable, cast

from ..context.collectors.image import ImageContextCollector
from ..context.collectors.language import LanguageContextCollector
from ..context.collectors.page import ExtractionStructureCollector, ExtractionTextCollector
from ..context.extractors.browser import BrowserAwarePageExtractor
from ..context.extractors.generic_extractor import GenericPageExtractor
from ..context.extractors.manager import ExtractionManager
from ..context.pipeline import ContextPipeline
from ..context.reduction import ContextReducer, CurrentPageContext
from ..config.settings import get_embedding_enabled
from ..embeddings import CandleEmbeddingAdapter
from ..image.services import ImageEncoder, ImagePreprocessor
from ..observability.reporter import FileMetricsReporter
from ..ui import nvda_ui
from ..providers.provider_proxy import ProviderProxy
from ..service.chat import ChatCoordinator, ConversationService, build_default_conversation_repository
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
	browser_extractor = BrowserAwarePageExtractor()
	generic_extractor = GenericPageExtractor()
	page_extractor = ExtractionManager((browser_extractor, generic_extractor))
	page_text_collector = ExtractionTextCollector(extractor=page_extractor)
	page_structure_collector = ExtractionStructureCollector(extractor=page_extractor)
	image_context_collector = ImageContextCollector(
		preprocessor=ImagePreprocessor(),
		encoder=ImageEncoder(),
	)
	language_collector = LanguageContextCollector()
	context_pipeline = ContextPipeline(
		collectors=(page_text_collector, page_structure_collector, image_context_collector, language_collector),
		main_thread_executor=nvda_ui.call,
	)
	# The native model remains lazy.  ContextReducer has a deterministic
	# fallback when the optional extension is unavailable.
	context_reducer = ContextReducer(
		embedder=CandleEmbeddingAdapter() if get_embedding_enabled() else None
	)
	page_context_provider = CurrentPageContext(context_reducer)
	tool_registry = ToolRegistry()
	_register_default_tools(tool_registry)
	tool_executor = ToolExecutor(tool_registry)
	llm_service = ProviderLLMService(provider, tool_executor=tool_executor)
	chat_coordinator = ChatCoordinator(
		client=llm_service,
		metrics_reporter=metrics_reporter,
		repository=build_default_conversation_repository(),
		page_context_provider=page_context_provider,
	)
	conversation_service = ConversationService(chat_coordinator)
	use_case_engine = UseCaseEngine(
		llm_service=llm_service,
		context_pipeline=context_pipeline,
		context_reducer=context_reducer,
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
		conversation_service=conversation_service,
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
