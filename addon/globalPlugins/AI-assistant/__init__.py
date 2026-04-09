# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUntypedBaseClass=false
import logging
import threading
from typing import Any

import globalPluginHandler
import ui

from .browser_extractor import BrowserAwarePageExtractor
from .ollama_client import OllamaClient, OllamaClientError
from .page_summary import PageSummaryCoordinator

logger = logging.getLogger(__name__)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = "Smart Browser Tools"

    def __init__(self):
        super().__init__()
        logger.debug("Browser Assistant plugin initializing")
        self._client = OllamaClient()
        self._pageSummary = PageSummaryCoordinator(
            extractor=BrowserAwarePageExtractor(),
            client=self._client,
        )
        self._startModelPreload()
        logger.debug("Browser Assistant plugin initialized")

    def _startModelPreload(self):
        def worker():
            ui.message("Checking Ollama model availability.")

            def announce_progress(event: dict[str, Any]) -> None:
                status = str(event.get("status", "")).strip()
                if not status:
                    return
                total = event.get("total")
                completed = event.get("completed")
                if isinstance(total, int) and isinstance(completed, int) and total > 0:
                    ui.message(f"{status} ({completed}/{total})")
                else:
                    ui.message(status)

            try:
                model = self._client.ensureModelInstalled(onProgress=announce_progress)
            except OllamaClientError as error:
                ui.message(str(error))
            else:
                ui.message(f"Ollama model {model} is ready.")

        thread = threading.Thread(
            target=worker,
            name="BrowserAssistantModelPreload",
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------
    # Scripts (keybinds)
    # ------------------------------------------------------------------

    def script_summarizeCurrentPage(self, gesture: Any):
        logger.debug("Script summarizeCurrentPage invoked gesture=%s", gesture)
        self._pageSummary.summarizeCurrentPage()

    __gestures = {
        "kb:NVDA+Shift+S": "summarizeCurrentPage",
    }
