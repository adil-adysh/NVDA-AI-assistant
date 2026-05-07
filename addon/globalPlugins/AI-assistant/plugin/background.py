# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
import threading
from collections.abc import Callable
from typing import Any, cast

from logHandler import log

from ..providers.interfaces import LLMProviderError, ProviderConfigurationError
from ..service.error_presentation import present_error
from ..service.llm import LLMService
from ..service.provider_readiness import ProviderReadinessService, get_provider_display_name
from ..ui import nvda_ui
from ..ui.session_state import build_provider_status_message
from ..use_case.engine import UseCaseEngine
from ..use_case.types import UseCaseId


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


class BackgroundTaskRunner:
	def __init__(
		self,
		llm_service: LLMService,
		use_case_engine: UseCaseEngine,
		progress_handler: Callable[[Any], None],
		readiness_service: ProviderReadinessService | None = None,
	) -> None:
		self._llm_service = llm_service
		self._use_case_engine = use_case_engine
		self._progress_handler = progress_handler
		self._readiness_service = readiness_service or ProviderReadinessService()

	def start_model_preload(self) -> None:
		def worker() -> None:
			try:
				readiness = self._readiness_service.evaluate_active()
				if not readiness.can_infer:
					log.debug("Skipping model preload for %s; provider is not ready", readiness.provider)
					return
				provider_name = get_provider_display_name(readiness.provider)
				nvda_ui.queue(nvda_ui.message, f"Checking {provider_name} model availability.")
				model = self._llm_service.ensure_model_available(on_progress=lambda text: nvda_ui.queue(nvda_ui.message, text))
			except LLMProviderError as error:
				nvda_ui.queue(nvda_ui.message, present_error(error, _).message)
			except Exception as error:
				log.exception("Unexpected error during model preload")
				nvda_ui.queue(nvda_ui.message, present_error(error, _).message)
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
			log.debug("BackgroundTaskRunner worker starting use_case_id=%s title=%s", use_case_id, title)
			try:
				result = self._use_case_engine.execute(use_case_id, progress=self._progress_handler)
			except ProviderConfigurationError:
				log.exception("BackgroundTaskRunner blocked by provider configuration for use case %s", use_case_id)
				readiness = self._readiness_service.evaluate_active()
				message = build_provider_status_message(_, readiness) or _("The selected provider is not fully configured.")
				nvda_ui.queue(nvda_ui.message, message)
				return
			except Exception as error:
				log.exception("BackgroundTaskRunner failed executing use case %s", use_case_id)
				nvda_ui.queue(nvda_ui.message, present_error(error, _).message)
				return

			nvda_ui.queue(render_result, result)

		thread = threading.Thread(
			target=worker,
			name=f"AIassistant{title.replace(' ', '')}Worker",
			daemon=True,
		)
		thread.start()
		log.debug("BackgroundTaskRunner started thread for use_case_id=%s title=%s", use_case_id, title)
