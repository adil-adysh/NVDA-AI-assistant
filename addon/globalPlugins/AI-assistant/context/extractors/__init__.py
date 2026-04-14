# -*- coding: utf-8 -*-
from __future__ import annotations

from .browser import BrowserAwarePageExtractor, PageExtractionError
from .candidates import (
	BrowserCandidateProvider,
	CandidateProvider,
	ExtractionContext,
	GenericCandidateProvider,
	TextAppCandidateProvider,
	buildDefaultCandidateProviders,
)
from .terminal_candidates import TerminalCandidateProvider
from .text_editor_candidates import TextEditorCandidateProvider

__all__ = [
	"BrowserAwarePageExtractor",
	"PageExtractionError",
	"BrowserCandidateProvider",
	"CandidateProvider",
	"ExtractionContext",
	"GenericCandidateProvider",
	"TerminalCandidateProvider",
	"TextEditorCandidateProvider",
	"TextAppCandidateProvider",
	"buildDefaultCandidateProviders",
]
