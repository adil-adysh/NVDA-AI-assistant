# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUntypedBaseClass=false
import logging
import threading
from typing import Any

import addonHandler
import globalPluginHandler
import gui
import ui

from .browser_extractor import BrowserAwarePageExtractor
from .download_progress import DownloadProgressTracker
from .image_description import ImageDescriptionCoordinator
from .ollama_client import OllamaClient, OllamaClientError
from .page_summary import PageSummaryCoordinator
from .settings_panel import AIAssistantSettingsPanel

logger = logging.getLogger(__name__)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = "Smart Browser Tools"

    def __init__(self):
        super().__init__()
        addonHandler.initTranslation()
        logger.debug("Browser Assistant plugin initializing")
        self._client = OllamaClient()
        self._pageSummary = PageSummaryCoordinator(
            extractor=BrowserAwarePageExtractor(),
            client=self._client,
        )
        self._imageDescription = ImageDescriptionCoordinator(client=self._client)
        self._startModelPreload()
        gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(AIAssistantSettingsPanel)
        logger.debug("Browser Assistant plugin initialized")

    def _startModelPreload(self):
        def worker():
            ui.message("Checking Ollama model availability.")
            announcer = DownloadProgressTracker(ui.message)

            try:
                model = self._client.ensureModelInstalled(onProgress=announcer.process_event)
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

    def terminate(self):
        super().terminate()
        gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(AIAssistantSettingsPanel)

    def script_describeCurrentWindow(self, gesture: Any):
        logger.debug("Script describeCurrentWindow invoked gesture=%s", gesture)
        self._imageDescription.describeCurrentWindow()

    __gestures = {
        "kb:NVDA+Shift+S": "summarizeCurrentPage",
        "kb:NVDA+Shift+I": "describeCurrentWindow",
    }
