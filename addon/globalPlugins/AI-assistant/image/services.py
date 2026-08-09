# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
from io import BytesIO
from typing import Literal

from PIL import Image, ImageGrab

from .objects import clip_location_to_containers, get_object_location, get_object_safe
from .screen_curtain import check_screen_curtain
from .types import ImageFormat

CaptureSource = Literal["foreground", "focus", "navigator", "desktop"]


class ImageCaptureService:
	"""Screen capture through NVDA's object model.

	Supports the same 4 capture sources as the Screenshots Wizard add-on:
	- ``"desktop"`` — full virtual desktop
	- ``"foreground"`` — foreground window (default)
	- ``"focus"`` — keyboard focus object
	- ``"navigator"`` — NVDA navigator object

	Object-based sources (foreground, focus, navigator) use container-clipped
	bounding boxes so scroll-cropped or window-overflowing portions are excluded.
	"""

	def capture(self, source: CaptureSource = "foreground") -> bytes:
		check_screen_curtain()

		if source == "desktop":
			return self._capture_full_screen()

		obj = get_object_safe(source)
		if obj is None:
			raise RuntimeError(f"Unable to locate the {source} object for capture.")

		location = get_object_location(obj)
		if location is None:
			raise RuntimeError(f"The {source} object has no usable screen location.")

		# Clip to visible area like the Screenshots Wizard add-on does
		location = clip_location_to_containers(obj, location)
		left, top, width, height = location
		bbox = (left, top, left + width, top + height)
		image = ImageGrab.grab(bbox=bbox)
		buffer = BytesIO()
		image.save(buffer, format="PNG")
		return buffer.getvalue()

	def _capture_full_screen(self) -> bytes:
		image = ImageGrab.grab()
		buffer = BytesIO()
		image.save(buffer, format="PNG")
		return buffer.getvalue()


class ImagePreprocessor:
	def preprocess(
		self,
		image_bytes: bytes,
		max_side: int,
		image_format: ImageFormat,
		quality: int | None = None,
	) -> bytes:
		if max_side <= 0:
			raise ValueError("max_side must be a positive integer")

		image = Image.open(BytesIO(image_bytes))
		image.load()

		width, height = image.size
		longest_side = max(width, height)
		if longest_side > max_side:
			scale = max_side / float(longest_side)
			new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
			image = image.resize(new_size, Image.LANCZOS)

		normalized_format = str(image_format).upper()
		save_kwargs: dict[str, int | bool] = {}
		if normalized_format == "JPEG":
			image = image.convert("RGB")
			save_kwargs["quality"] = quality or 80
			save_kwargs["optimize"] = True
		elif normalized_format != "PNG":
			raise ValueError(f"Unsupported image format: {image_format}")

		buffer = BytesIO()
		image.save(buffer, format=normalized_format, **save_kwargs)
		return buffer.getvalue()


class ImageEncoder:
	def encode(self, image_bytes: bytes) -> str:
		return base64.b64encode(image_bytes).decode("ascii")
