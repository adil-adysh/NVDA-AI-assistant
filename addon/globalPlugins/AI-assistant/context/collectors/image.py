# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import cast

from PIL import Image

from ...context.protocols import CollectorInput, ImageContextFragment
from ...context.types import (
	ContentRequest,
	FocusedElementImageRequest,
	ForegroundImageRequest,
	ImageCaptureSource,
	ImageContext,
	NavigatorImageRequest,
)
from ...image.services import ImageEncoder, ImagePreprocessor
from ...image.types import ImageFormat
from ...config.settings import get_image_format, get_image_max_side, get_image_quality


# Map request types to snapshot sources — the pipeline captures images
# on the NVDA main thread and stores them in CollectorInput.image_snapshots.
_REQUEST_SOURCES: dict[type, ImageCaptureSource] = {
	ForegroundImageRequest: "foreground",
	FocusedElementImageRequest: "focus",
	NavigatorImageRequest: "navigator",
}


@dataclass(frozen=True, slots=True)
class ImageContextCollector:
	"""Collector that preprocesses and encodes pre-captured image snapshots.

	Image capture happens in the pipeline's snapshot resolution phase
	(on the NVDA main thread).  This collector only does thread-safe
	transforms: resize, format conversion, base64 encoding.
	"""

	preprocessor: ImagePreprocessor | None = None
	encoder: ImageEncoder | None = None

	def handles_request(self, request: ContentRequest) -> bool:
		return isinstance(request, tuple(_REQUEST_SOURCES))

	def collect_for_request(self, request: ContentRequest, input: CollectorInput) -> ImageContextFragment:
		if self.preprocessor is None or self.encoder is None:
			raise ValueError("ImageContextCollector requires preprocessor and encoder services")

		source = _REQUEST_SOURCES.get(type(request), "foreground")
		image_snapshot = input.image_snapshots.get(source)
		if image_snapshot is None:
			raise ValueError(f"No image snapshot available for source: {source}")

		processed_bytes = self.preprocessor.preprocess(
			image_bytes=image_snapshot.raw_bytes,
			max_side=get_image_max_side(),
			image_format=cast(ImageFormat, get_image_format()),
			quality=get_image_quality(),
		)
		image_base64 = self.encoder.encode(processed_bytes)

		app_title = image_snapshot.app_title
		window_title = image_snapshot.window_title

		image_context = ImageContext(
			app_title=app_title,
			window_title=window_title,
			image_base64=image_base64,
		)
		with Image.open(BytesIO(processed_bytes)) as image:
			width, height = image.size

		return ImageContextFragment(
			facts={
				"image_context": image_context,
				"raw_image_bytes": len(image_snapshot.raw_bytes),
				"processed_image_bytes": len(processed_bytes),
				"image_pixels": width * height,
			},
			image_base64=image_base64,
			metadata={
				"use_case_id": input.use_case_id,
				"app_title": app_title,
				"window_title": window_title,
				"raw_image_bytes": len(image_snapshot.raw_bytes),
				"processed_image_bytes": len(processed_bytes),
			},
		)
