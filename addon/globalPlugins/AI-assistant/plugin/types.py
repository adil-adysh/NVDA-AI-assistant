# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

from dataclasses import dataclass

from ..context.collectors.image import ImageContextCollector
from ..context.collectors.page import ExtractionStructureCollector, ExtractionTextCollector
from ..context.pipeline import ContextPipeline
from ..observability.reporter import FileMetricsReporter
from ..providers.provider_proxy import ProviderProxy
from ..service.chat import ChatCoordinator, ConversationService
from ..service.llm import ProviderLLMService
from ..tools import ToolExecutor, ToolRegistry
from ..use_case.engine import UseCaseEngine


@dataclass(frozen=True, slots=True)
class PluginServices:
	provider: ProviderProxy
	metrics_reporter: FileMetricsReporter
	page_text_collector: ExtractionTextCollector
	page_structure_collector: ExtractionStructureCollector
	image_context_collector: ImageContextCollector
	context_pipeline: ContextPipeline
	tool_registry: ToolRegistry
	tool_executor: ToolExecutor
	llm_service: ProviderLLMService
	chat_coordinator: ChatCoordinator
	conversation_service: ConversationService
	use_case_engine: UseCaseEngine
