# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from logHandler import log
from collections.abc import Callable
from typing import Any

from typing import Optional

from . import nvda_ui
from .base_coordinator import BaseCoordinator
from .browser_extractor import PageExtractionError
from .models import PageSnapshot, SummaryResponse
from .metrics_reporter import MetricsReporter
from .prompt_builders import build_page_summary_prompt
from .providers.base import LLMProvider
from .request_metrics import SummaryRequestMetrics, estimate_tokens


class PageSummaryCoordinator(BaseCoordinator):
    def __init__(
        self,
        extractor: Any,
        client: LLMProvider,
        metrics_reporter: MetricsReporter | None = None,
    ):
        super().__init__(metrics_reporter)
        self._extractor = extractor
        self._client = client

    def summarizeCurrentPage(self) -> None:
        try:
            snapshot = self._extractor.extract()
        except PageExtractionError as error:
            nvda_ui.message(str(error))
            return

        prompt = build_page_summary_prompt(snapshot)
        log.debug(
            "Starting page summary worker for title=%s headings=%d links=%d buttons=%d landmarks=%d",
            snapshot.title,
            len(snapshot.headings),
            len(snapshot.links),
            len(snapshot.buttons),
            len(snapshot.landmarks),
        )
        nvda_ui.message("Summarizing current page")
        self.start_task(snapshot, prompt)

    def _build_request_metrics(self, snapshot: PageSnapshot, prompt: str) -> SummaryRequestMetrics:
        return SummaryRequestMetrics(
            request_type="summary",
            provider=self._client.provider_name(),
            input_chars=len(snapshot.text or ""),
            prompt_chars=len(prompt),
            prompt_tokens_estimated=estimate_tokens(prompt),
        )

    def _run_task_logic(
        self,
        progress_callback: Optional[Callable[[str, int], None]],
        snapshot: PageSnapshot,
        prompt: str,
    ) -> tuple[SummaryResponse, str]:
        response = self._client.summarize(
            prompt,
            stream_handler=progress_callback,
        )
        if self._request_metrics is not None:
            self._request_metrics.output_chars = len(response.text or "")
            self._request_metrics.output_tokens_estimated = estimate_tokens(response.text)
            self._request_metrics.model = response.model or "unknown"
        return response, snapshot.title

    def _present_result(self, result: tuple[SummaryResponse, str]) -> None:
        response, page_title = result
        nvda_ui.message("Page summary ready")
        model_name = response.model or "unknown"
        dialogTitle = f"Page summary ({model_name}) - {page_title}"
        nvda_ui.browseable_message(response.text, title=dialogTitle)

    def _format_progress_message(self, generated_chars: int, preview: str) -> str:
        if preview:
            return f"Summary progress: {generated_chars} characters. {preview}"
        return f"Summary progress: {generated_chars} characters generated"

    def _get_task_name(self) -> str:
        return "BrowserAssistantPageSummary"

    def _get_busy_message(self) -> str:
        return "Page summary already in progress"
