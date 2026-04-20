# -*- coding: utf-8 -*-
from __future__ import annotations

from .collectors import ImageContextCollector, ExtractionStructureCollector, ExtractionTextCollector
from .extractors import (
	BrowserAwarePageExtractor,
	BrowserCandidateProvider,
	CandidateProvider,
	CandidateExtractionContext,
	GenericCandidateProvider,
	PageExtractionError,
	TerminalCandidateProvider,
	TextEditorCandidateProvider,
	TextAppCandidateProvider,
	buildDefaultCandidateProviders,
)
from .pipeline import ContextPipeline
from .protocols import ContextCollector, ContextFragment
from .prompts import (
	build_chat_messages,
	build_image_description_prompt,
	build_extraction_summary_prompt,
	build_system_prompt_for_nvda_assistant,
)
from .types import (
	ImageContext,
	ExtractionFacts,
	ExtractionResult,
	ExtractionStructure,
	PromptContext,
	ExtractionSnapshot,
	PromptSource,
)

__all__ = [
	"ContextCollector",
	"ContextFragment",
	"ContextPipeline",
	"BrowserAwarePageExtractor",
	"BrowserCandidateProvider",
	"build_chat_messages",
	"build_image_description_prompt",
	"build_extraction_summary_prompt",
	"build_system_prompt_for_nvda_assistant",
	"CandidateProvider",
	"CandidateExtractionContext",
	"GenericCandidateProvider",
	"ImageContext",
	"ImageContextCollector",
	"ExtractionFacts",
	"ExtractionResult",
	"ExtractionStructure",
	"ExtractionSnapshot",
	"PromptContext",
	"PromptSource",
	"ExtractionStructureCollector",
	"ExtractionTextCollector",
	"PageExtractionError",
	"TerminalCandidateProvider",
	"TextEditorCandidateProvider",
	"TextAppCandidateProvider",
	"buildDefaultCandidateProviders",
]
