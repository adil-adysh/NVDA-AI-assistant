# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUntypedBaseClass=false
import logging
from typing import Any

import globalPluginHandler

from .browser_extractor import BrowserAwarePageExtractor
from .ollama_client import OllamaClient
from .page_summary import PageSummaryCoordinator

logger = logging.getLogger(__name__)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = "Smart Browser Tools"

    def __init__(self):
        super().__init__()
        logger.debug("Browser Assistant plugin initializing")
        self._pageSummary = PageSummaryCoordinator(
            extractor=BrowserAwarePageExtractor(),
            client=OllamaClient(),
        )
        logger.debug("Browser Assistant plugin initialized")

    # ------------------------------------------------------------------
    # Scripts (keybinds)
    # ------------------------------------------------------------------

    def script_summarizeCurrentPage(self, gesture: Any):
        logger.debug("Script summarizeCurrentPage invoked gesture=%s", gesture)
        self._pageSummary.summarizeCurrentPage()

    __gestures = {
        "kb:NVDA+Shift+S": "summarizeCurrentPage",
    }
