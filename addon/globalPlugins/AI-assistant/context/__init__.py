# -*- coding: utf-8 -*-
from __future__ import annotations

from .collectors import ImageContextCollector, PageStructureCollector, PageTextCollector
from .extractors import (
	BrowserAwarePageExtractor,
	BrowserCandidateProvider,
	CandidateProvider,
	ExtractionContext,
	GenericCandidateProvider,
	PageExtractionError,
	TerminalCandidateProvider,
	TextEditorCandidateProvider,
	TextAppCandidateProvider,
	buildDefaultCandidateProviders,
)
from .pipeline import ContextPipeline
from .protocols import ContextCollector, ContextFragment
from .prompt import (
	build_chat_messages,
	build_image_description_prompt,
	build_page_summary_prompt,
	build_system_prompt_for_nvda_assistant,
)
from .types import ImageContext, PageContext, PageSnapshot, PromptContext

__all__ = [
	"ContextCollector",
	"ContextFragment",
	"ContextPipeline",
	"BrowserAwarePageExtractor",
	"BrowserCandidateProvider",
	"build_chat_messages",
	"build_image_description_prompt",
	"build_page_summary_prompt",
	"build_system_prompt_for_nvda_assistant",
	"CandidateProvider",
	"ExtractionContext",
	"GenericCandidateProvider",
	"ImageContext",
	"ImageContextCollector",
	"PageContext",
	"PageSnapshot",
	"PageStructureCollector",
	"PageTextCollector",
	"PageExtractionError",
	"PromptContext",
	"TerminalCandidateProvider",
	"TextEditorCandidateProvider",
	"TextAppCandidateProvider",
	"buildDefaultCandidateProviders",
]
