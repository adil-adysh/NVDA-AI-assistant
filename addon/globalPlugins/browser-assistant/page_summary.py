# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import queueHandler
import ui

logger = logging.getLogger(__name__)

from .browser_extractor import PageExtractionError
from .models import PageSnapshot, SummaryResponse
from .ollama_client import OllamaClientError


class PageSummaryCoordinator:
    def __init__(self, extractor: Any, client: Any):
        super().__init__()
        self._extractor = extractor
        self._client = client
        self._lock = threading.Lock()
        self._activeWorker = None

    def summarizeCurrentPage(self):
        with self._lock:
            if self._activeWorker is not None and self._activeWorker.is_alive():
                ui.message("Page summary already in progress")
                return

        try:
            snapshot = self._extractor.extract()
        except PageExtractionError as error:
            ui.message(str(error))
            return

        logger.debug(
            "Starting page summary worker for title=%s headings=%d links=%d buttons=%d landmarks=%d",
            snapshot.title,
            len(snapshot.headings),
            len(snapshot.links),
            len(snapshot.buttons),
            len(snapshot.landmarks),
        )
        ui.message("Summarizing current page")
        worker = threading.Thread(
            target=self._runInBackground,
            args=(snapshot,),
            name="BrowserAssistantPageSummary",
            daemon=True,
        )
        with self._lock:
            self._activeWorker = worker
        worker.start()

    def _runInBackground(self, snapshot: PageSnapshot):
        lastAnnouncedChars = 0

        def onPartial(partialText: str, generatedChars: int):
            nonlocal lastAnnouncedChars
            logger.debug("Page summary partial progress chars=%d", generatedChars)
            if generatedChars < 80:
                return
            if generatedChars - lastAnnouncedChars < 180:
                return
            lastAnnouncedChars = generatedChars

            preview = " ".join(partialText.strip().split())[-120:]
            logger.debug("Queueing progress announcement chars=%d preview=%s", generatedChars, preview)
            self._queueToNVDA(self._announceProgress, generatedChars, preview)

        start = time.monotonic()
        try:
            response: SummaryResponse = self._client.summarize(snapshot, onPartial=onPartial)
        except OllamaClientError as error:
            logger.exception("Page summary failed with OllamaClientError")
            self._queueToNVDA(self._announceError, str(error))
        except Exception as error:
            logger.exception("Page summary failed with unexpected exception")
            self._queueToNVDA(self._announceError, f"Page summary failed: {error}")
        else:
            duration = time.monotonic() - start
            logger.debug("Page summary succeeded title=%s model=%s chars=%d duration=%.2fs", snapshot.title, response.model, len(response.text), duration)
            self._queueToNVDA(self._presentSummary, snapshot.title, response.text, response.model)
        finally:
            with self._lock:
                self._activeWorker = None

    def _queueToNVDA(self, callback: Callable[..., None], *args: Any):
        queueHandler.queueFunction(queueHandler.eventQueue, callback, *args)

    def _announceError(self, message: str):
        ui.message(message)

    def _announceProgress(self, generatedChars: int, preview: str):
        if preview:
            ui.message(f"Summary progress: {generatedChars} characters. {preview}")
            return
        ui.message(f"Summary progress: {generatedChars} characters generated")

    def _presentSummary(self, pageTitle: str, summaryText: str, modelName: str):
        ui.message("Page summary ready")
        dialogTitle = f"Page summary ({modelName}) - {pageTitle}"
        ui.browseableMessage(summaryText, title=dialogTitle)
