# -*- coding: utf-8 -*-
"""Context package public API with lazy imports.

Keeping exports lazy prevents pure services such as token budgeting from
loading NVDA, image, or platform-specific modules merely by importing a
context submodule.
"""
from __future__ import annotations

from importlib import import_module


_EXPORTS = {
	"ContextPipeline": ("pipeline", "ContextPipeline"),
	"ContextRequestDefinition": ("request_registry", "ContextRequestDefinition"),
	"ContextRequestRegistry": ("request_registry", "ContextRequestRegistry"),
	"ApproximateTokenCounter": ("budget", "ApproximateTokenCounter"),
	"ContextBudgetError": ("budget", "ContextBudgetError"),
	"ContextWindowBudget": ("budget", "ContextWindowBudget"),
	"ImageContextCollector": ("collectors", "ImageContextCollector"),
	"FocusedTextCollector": ("collectors", "FocusedTextCollector"),
	"ExtractionStructureCollector": ("collectors", "ExtractionStructureCollector"),
	"ExtractionTextCollector": ("collectors", "ExtractionTextCollector"),
	"BrowserAwarePageExtractor": ("extractors", "BrowserAwarePageExtractor"),
	"BrowserCandidateProvider": ("extractors", "BrowserCandidateProvider"),
	"CandidateProvider": ("extractors", "CandidateProvider"),
	"CandidateExtractionContext": ("extractors", "CandidateExtractionContext"),
	"GenericCandidateProvider": ("extractors", "GenericCandidateProvider"),
	"PageExtractionError": ("extractors", "PageExtractionError"),
	"TerminalCandidateProvider": ("extractors", "TerminalCandidateProvider"),
	"TextEditorCandidateProvider": ("extractors", "TextEditorCandidateProvider"),
	"TextAppCandidateProvider": ("extractors", "TextAppCandidateProvider"),
	"buildDefaultCandidateProviders": ("extractors", "buildDefaultCandidateProviders"),
	"ContextCollector": ("protocols", "ContextCollector"),
	"ContextFragment": ("protocols", "ContextFragment"),
	"PageContextFragment": ("protocols", "PageContextFragment"),
	"BrowserContextFragment": ("protocols", "BrowserContextFragment"),
	"TerminalContextFragment": ("protocols", "TerminalContextFragment"),
	"ImageContextFragment": ("protocols", "ImageContextFragment"),
	"build_chat_messages": ("prompts", "build_chat_messages"),
	"build_image_description_prompt": ("prompts", "build_image_description_prompt"),
	"build_extraction_summary_prompt": ("prompts", "build_extraction_summary_prompt"),
	"build_system_prompt_for_nvda_assistant": ("prompts", "build_system_prompt_for_nvda_assistant"),
}

_TYPE_EXPORTS = (
	"AccessibilityGraph", "AccessibilityNode", "ALL_STRUCTURED_FIELDS", "ContentRequest", "ExtractionFacts", "ExtractionIntent",
	"ExtractionResult", "ExtractionSnapshot", "ExtractionStructure", "FocusedElementImageRequest",
	"FocusedElementTextRequest", "FocusedTextSnapshot", "ForegroundImageRequest",
	"ImageCaptureSource", "ImageCaptureSnapshot", "ImageContext", "NavigatorImageRequest",
	"PageStructureRequest", "PageTextRequest", "PromptContext", "PromptSource", "SemanticSection", "StructuredField",
)
for _name in _TYPE_EXPORTS:
	_EXPORTS[_name] = ("types", _name)


def __getattr__(name: str):
	try:
		module_name, attribute_name = _EXPORTS[name]
	except KeyError as error:
		raise AttributeError(name) from error
	module = import_module(f"{__name__}.{module_name}")
	value = getattr(module, attribute_name)
	globals()[name] = value
	return value


__all__ = list(_EXPORTS)
