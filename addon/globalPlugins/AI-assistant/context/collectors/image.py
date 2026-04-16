# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, cast

import api
from PIL import Image

from ...context.protocols import ContextFragment
from ...context.types import ContextProfileList, ImageContext
from ...image.services import ImageCaptureService, ImageEncoder, ImagePreprocessor
from ...image.types import ImageFormat
from ...config.settings import get_image_format, get_image_max_side, get_image_quality


@dataclass(frozen=True, slots=True)
class ImageContextCollector:
	capture_service: ImageCaptureService | None = None
	preprocessor: ImagePreprocessor | None = None
	encoder: ImageEncoder | None = None

	@property
	def profiles(self) -> ContextProfileList:
		return ("image",)

	def collect(self, use_case_id: str, **kwargs: Any) -> ContextFragment:
		if self.capture_service is None or self.preprocessor is None or self.encoder is None:
			raise ValueError("ImageContextCollector requires capture, preprocessor, and encoder services")

		raw_image_bytes = self.capture_service.capture()
		processed_bytes = self.preprocessor.preprocess(
			image_bytes=raw_image_bytes,
			max_side=get_image_max_side(),
			image_format=cast(ImageFormat, get_image_format()),
			quality=get_image_quality(),
		)
		image_base64 = self.encoder.encode(processed_bytes)

		app_title = None
		window_title = None
		foreground = self._get_foreground_object_safe()
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

		image_context = ImageContext(
			app_title=app_title,
			window_title=window_title,
			image_base64=image_base64,
		)
		with Image.open(BytesIO(processed_bytes)) as image:
			width, height = image.size

		return ContextFragment(
			facts={
				"image_context": image_context,
				"raw_image_bytes": len(raw_image_bytes),
				"processed_image_bytes": len(processed_bytes),
				"image_pixels": width * height,
			},
			image_base64=image_base64,
			metadata={
				"use_case_id": use_case_id,
				"app_title": app_title,
				"window_title": window_title,
				"raw_image_bytes": len(raw_image_bytes),
				"processed_image_bytes": len(processed_bytes),
			},
		)

	def _get_foreground_object_safe(self) -> Any:
		try:
			return api.getForegroundObject()
		except Exception:
			return None
