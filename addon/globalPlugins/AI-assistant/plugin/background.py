# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
import threading
from collections.abc import Callable
from typing import Any, cast

from logHandler import log

from ..providers.interfaces import LLMProviderError
from ..service.llm import LLMService
from ..ui import nvda_ui
from ..use_case.engine import UseCaseEngine
from ..use_case.types import UseCaseId


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


class BackgroundTaskRunner:
	def __init__(self, llm_service: LLMService, use_case_engine: UseCaseEngine, progress_handler: Callable[[Any], None]) -> None:
		self._llm_service = llm_service
		self._use_case_engine = use_case_engine
		self._progress_handler = progress_handler

	def start_model_preload(self) -> None:
		def worker() -> None:
			try:
				provider_name = self._llm_service.provider_name()
				nvda_ui.queue(nvda_ui.message, f"Checking {provider_name} model availability.")
				model = self._llm_service.ensure_model_available(on_progress=lambda text: nvda_ui.queue(nvda_ui.message, text))
			except LLMProviderError as error:
				nvda_ui.queue(nvda_ui.message, str(error))
			except Exception as error:
				log.exception("Unexpected error during model preload")
				nvda_ui.queue(nvda_ui.message, str(error))
			else:
				nvda_ui.queue(nvda_ui.message, f"{provider_name.capitalize()} model {model} is ready.")

		thread = threading.Thread(
			target=worker,
			name="BrowserAssistantModelPreload",
			daemon=True,
		)
		thread.start()

	def run_use_case_in_background(self, use_case_id: UseCaseId, title: str, render_result: Callable[[Any], None]) -> None:
		def worker() -> None:
			try:
				result = self._use_case_engine.execute(use_case_id, progress=self._progress_handler)
			except Exception as error:
				nvda_ui.queue(nvda_ui.message, _(f"Error: {error}"))
				return

			nvda_ui.queue(render_result, result)

		thread = threading.Thread(
			target=worker,
			name=f"AIassistant{title.replace(' ', '')}Worker",
			daemon=True,
		)
		thread.start()
