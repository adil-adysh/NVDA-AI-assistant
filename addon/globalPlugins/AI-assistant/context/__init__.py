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
	build_system_prompt_for_nvda_assistant,
	get_prompt_template,
	prompt_template_exists,
	render_prompt,
	render_prompt_template,
	register_user_prompt_override,
)
from .types import (
	ContentSnapshot,
	ExcelSnapshotMetadata,
	ImageContext,
	PageContext,
	PageSnapshot,
	PromptContext,
	SnapshotType,
)

__all__ = [
	"ContextCollector",
	"ContextFragment",
	"ContextPipeline",
	"BrowserAwarePageExtractor",
	"BrowserCandidateProvider",
	"build_system_prompt_for_nvda_assistant",
	"get_prompt_template",
	"prompt_template_exists",
	"render_prompt",
	"render_prompt_template",
	"register_user_prompt_override",
	"CandidateProvider",
	"ContentSnapshot",
	"ExcelSnapshotMetadata",
	"ExtractionContext",
	"GenericCandidateProvider",
	"ImageContext",
	"ImageContextCollector",
	"PageContext",
	"PageSnapshot",
	"PromptContext",
	"SnapshotType",
	"PageStructureCollector",
	"PageTextCollector",
	"PageExtractionError",
	"TerminalCandidateProvider",
	"TextEditorCandidateProvider",
	"TextAppCandidateProvider",
	"buildDefaultCandidateProviders",
]
