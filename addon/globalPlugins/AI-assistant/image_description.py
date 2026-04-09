# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
import api
import logging
from collections.abc import Callable
from typing import Any, Optional

import ui

from .base_coordinator import BaseCoordinator
from .ollama_client import OllamaClient
from .prompt_builders import build_image_description_prompt
from .screenshot import capture_foreground_window_base64
from .models import SummaryResponse

logger = logging.getLogger(__name__)


class ImageDescriptionCoordinator(BaseCoordinator):
	def __init__(self, client: OllamaClient):
		super().__init__()
		self._client = client

	def describeCurrentWindow(self) -> None:
		ui.message("Describing current window image")
		self.start_task()

	def _run_task_logic(
		self,
		progress_callback: Optional[Callable[[str, int], None]],
		*args: Any,
		**kwargs: Any,
	) -> SummaryResponse:
		imageBase64 = capture_foreground_window_base64()
		prompt = self._build_image_description_prompt()
		return self._client.describeImage(imageBase64, prompt=prompt, onPartial=progress_callback)

	def _present_result(self, result: SummaryResponse) -> None:
		ui.message("Image description ready")
		dialogTitle = f"Image description ({result.model})"
		ui.browseableMessage(result.text, title=dialogTitle)

	def _format_progress_message(self, generated_chars: int, preview: str) -> str:
		if preview:
			return f"Image description progress: {generated_chars} characters. {preview}"
		return f"Image description progress: {generated_chars} characters generated"

	def _get_task_name(self) -> str:
		return "BrowserAssistantImageDescription"

	def _get_busy_message(self) -> str:
		return "Image description already in progress"

	def _build_image_description_prompt(self) -> str:
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

	def _getForegroundObjectSafe(self) -> Any:
		try:
			return api.getForegroundObject()
		except Exception:
			return None
