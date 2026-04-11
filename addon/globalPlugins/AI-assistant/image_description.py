# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
import api
from logHandler import log
from collections.abc import Callable
from io import BytesIO
from typing import Any, Optional

from . import nvda_ui
from PIL import Image

from .base_coordinator import BaseCoordinator
from .image_services import ImageCaptureService, ImageEncoder, ImagePreprocessor
from .metrics_reporter import MetricsReporter
from .prompt_builders import build_image_description_prompt
from .providers.base import LLMProvider
from .request_metrics import ImageRequestMetrics, estimate_tokens
from .models import LLMRequest, LLMResponse, TaskType
from .settings import get_image_format, get_image_max_side, get_image_quality


class ImageDescriptionCoordinator(BaseCoordinator):
    def __init__(
        self,
        client: LLMProvider,
        metrics_reporter: MetricsReporter | None = None,
        capture_service: ImageCaptureService | None = None,
        preprocessor: ImagePreprocessor | None = None,
        encoder: ImageEncoder | None = None,
    ):
        super().__init__(metrics_reporter)
        self._client = client
        self._capture_service = capture_service or ImageCaptureService()
        self._preprocessor = preprocessor or ImagePreprocessor()
        self._encoder = encoder or ImageEncoder()

    def describeCurrentWindow(self) -> None:
        nvda_ui.message("Describing current window image")
        self.start_task()

    def _build_request_metrics(self) -> ImageRequestMetrics:
        return ImageRequestMetrics(
            request_type="image_description",
            provider=self._client.provider_name(),
        )

    def _run_task_logic(
        self,
        progress_callback: Optional[Callable[[str, int], None]],
        *args: Any,
        **kwargs: Any,
    ) -> LLMResponse:
        raw_image_bytes = self._capture_service.capture()
        processed_bytes = self._preprocessor.preprocess(
            image_bytes=raw_image_bytes,
            max_side=get_image_max_side(),
            image_format=get_image_format(),
            quality=get_image_quality(),
        )
        image_base64 = self._encoder.encode(processed_bytes)
        prompt = self._build_image_description_prompt()

        if self._request_metrics is not None:
            self._request_metrics.raw_image_bytes = len(raw_image_bytes)
            self._request_metrics.processed_image_bytes = len(processed_bytes)
            self._request_metrics.prompt_chars = len(prompt)
            self._request_metrics.prompt_tokens_estimated = estimate_tokens(prompt)
            if len(raw_image_bytes) > 0:
                self._request_metrics.resize_ratio = len(processed_bytes) / len(raw_image_bytes)
            with Image.open(BytesIO(processed_bytes)) as image:
                width, height = image.size
                self._request_metrics.image_pixels = width * height

        response = self._client.generate(
            LLMRequest(
                task_type=TaskType.IMAGE_DESCRIPTION,
                input_text=prompt,
                image_base64=image_base64,
                stream=progress_callback is not None,
                stream_handler=progress_callback,
                metadata=None,
            )
        )

        if self._request_metrics is not None:
            self._request_metrics.base64_size = len(image_base64)
            self._request_metrics.output_chars = len(response.text or "")
            self._request_metrics.output_tokens_estimated = estimate_tokens(response.text)
            self._request_metrics.model = response.model or "unknown"

        return response

    def _get_task_name(self) -> str:
        return "BrowserAssistantImageDescription"

    def _get_busy_message(self) -> str:
        return "Image description already in progress"

    def _format_progress_message(self, generated_chars: int, preview: str) -> str:
        if preview:
            return f"Image description progress: {generated_chars} characters. {preview}"
        return f"Image description progress: {generated_chars} characters generated"

    def _present_result(self, result: LLMResponse) -> None:
        nvda_ui.message("Image description ready")
        model_name = result.model or "unknown"
        dialog_title = f"Image description ({model_name})"
        nvda_ui.browseable_message(result.text, title=dialog_title)

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
