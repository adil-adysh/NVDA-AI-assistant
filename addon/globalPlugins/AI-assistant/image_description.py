# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
import api
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import queueHandler
import ui

from .ollama_client import OllamaClient, OllamaClientError
from .prompt_builders import build_image_description_prompt
from .screenshot import capture_foreground_window_base64
from .models import SummaryResponse

logger = logging.getLogger(__name__)


class ImageDescriptionCoordinator:
	def __init__(self, client: OllamaClient):
		super().__init__()
		self._client = client
		self._lock = threading.Lock()
		self._activeWorker = None

	def describeCurrentWindow(self):
		with self._lock:
			if self._activeWorker is not None and self._activeWorker.is_alive():
				ui.message("Image description already in progress")
				return

		ui.message("Describing current window image")
		worker = threading.Thread(
			target=self._runInBackground,
			name="BrowserAssistantImageDescription",
			daemon=True,
		)
		with self._lock:
			self._activeWorker = worker
		worker.start()

	def _runInBackground(self):
		lastAnnouncedChars = 0

		def onPartial(partialText: str, generatedChars: int):
			nonlocal lastAnnouncedChars
			logger.debug("Image description partial progress chars=%d", generatedChars)
			if generatedChars < 80:
				return
			if generatedChars - lastAnnouncedChars < 180:
				return
			lastAnnouncedChars = generatedChars

			preview = " ".join(partialText.strip().split())[-120:]
			logger.debug("Queueing image progress announcement chars=%d preview=%s", generatedChars, preview)
			self._queueToNVDA(self._announceProgress, generatedChars, preview)

		try:
			imageBase64 = capture_foreground_window_base64()
		except Exception as error:
			logger.exception("Failed to capture foreground window")
			self._queueToNVDA(self._announceError, str(error))
			with self._lock:
				self._activeWorker = None
			return

		prompt = self._buildImageDescriptionPrompt()
		start = time.monotonic()
		try:
			response: SummaryResponse = self._client.describeImage(imageBase64, prompt=prompt, onPartial=onPartial)
		except OllamaClientError as error:
			logger.exception("Image description failed with OllamaClientError")
			self._queueToNVDA(self._announceError, str(error))
		except Exception as error:
			logger.exception("Image description failed with unexpected exception")
			self._queueToNVDA(self._announceError, f"Image description failed: {error}")
		else:
			duration = time.monotonic() - start
			logger.debug("Image description succeeded model=%s chars=%d duration=%.2fs", response.model, len(response.text), duration)
			self._queueToNVDA(self._presentDescription, response.text, response.model)
		finally:
			with self._lock:
				self._activeWorker = None

	def _queueToNVDA(self, callback: Callable[..., None], *args: Any):
		queueHandler.queueFunction(queueHandler.eventQueue, callback, *args)

	def _buildImageDescriptionPrompt(self) -> str:
		foreground = self._getForegroundObjectSafe()
		app_title = None
		window_title = None

		if foreground is not None:
			try:
				window_title = getattr(foreground, "windowText", None)
			except Exception:
				window_title = None

			if not isinstance(window_title, str) or not window_title.strip():
				try:
					window_title = getattr(foreground, "name", None)
				except Exception:
					window_title = None

			if isinstance(window_title, str):
				window_title = window_title.strip()

			app_module = getattr(foreground, "appModule", None)
			if app_module is not None:
				try:
					app_name = getattr(app_module, "appName", None)
				except Exception:
					app_name = None
				if isinstance(app_name, str) and app_name.strip():
					app_title = app_name.strip()

		return build_image_description_prompt(app_title=app_title, window_title=window_title)

	def _getForegroundObjectSafe(self):
		try:
			return api.getForegroundObject()
		except Exception:
			return None

	def _announceError(self, message: str):
		ui.message(message)

	def _announceProgress(self, generatedChars: int, preview: str):
		if preview:
			ui.message(f"Image description progress: {generatedChars} characters. {preview}")
			return
		ui.message(f"Image description progress: {generatedChars} characters generated")

	def _presentDescription(self, descriptionText: str, modelName: str):
		ui.message("Image description ready")
		dialogTitle = f"Image description ({modelName})"
		ui.browseableMessage(descriptionText, title=dialogTitle)
