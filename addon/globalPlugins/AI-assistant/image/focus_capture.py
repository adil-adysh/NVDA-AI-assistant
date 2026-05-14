# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import dataclasses
from io import BytesIO
from typing import Any

import api
from PIL import ImageGrab

from ..config.settings import get_image_format, get_image_max_side, get_image_quality
from .services import ImageEncoder, ImagePreprocessor


@dataclasses.dataclass(frozen=True, slots=True)
class FocusCaptureResult:
	"""Result of capturing the focused NVDA object as an image."""
	image_base64: str
	object_name: str | None
	object_role: str | None
	app_name: str | None
	window_title: str | None
	left: int
	top: int
	width: int
	height: int


def _get_focus_object_safe() -> Any | None:
	"""Get the current focus NVDA object, returning None on failure."""
	try:
		return api.getFocusObject()
	except Exception:
		return None


def _coerce_location_tuple(location: Any) -> tuple[int, int, int, int] | None:
	"""Coerce a location-like value to (left, top, width, height)."""
	try:
		if hasattr(location, "left"):
			left = int(location.left)
			top = int(location.top)
			width = int(location.width)
			height = int(location.height)
		else:
			left, top, width, height = (int(v) for v in location)
	except (TypeError, ValueError, AttributeError):
		return None

	if width <= 0 or height <= 0:
		return None

	return left, top, width, height


def _get_object_location(obj: Any) -> tuple[int, int, int, int] | None:
	"""Get the screen location (left, top, width, height) of an NVDA object."""
	try:
		location = obj.location
	except Exception:
		return None

	if location is None:
		return None

	return _coerce_location_tuple(location)


def _resolve_capture_location(focus_obj: Any) -> tuple[int, int, int, int] | None:
	"""Resolve capture bounds from focused object location only."""
	return _get_object_location(focus_obj)


def _resolve_capture_location_with_retry(max_attempts: int = 4) -> tuple[Any, tuple[int, int, int, int]] | None:
	"""Retry focus-bound resolution to tolerate transient focus/object location failures."""
	for _ in range(max_attempts):
		focus_obj = _get_focus_object_safe()
		if focus_obj is None:
			continue
		location = _resolve_capture_location(focus_obj)
		if location is None:
			continue
		return focus_obj, location
	return None


def _get_object_name(obj: Any) -> str | None:
	"""Get a human-readable name from an NVDA object."""
	try:
		name = obj.name
		return str(name).strip() if isinstance(name, str) and name.strip() else None
	except Exception:
		return None


def _get_object_role(obj: Any) -> str | None:
	"""Get a human-readable role from an NVDA object."""
	try:
		role = obj.role
		role_text = str(role).strip() if role else None
		return role_text if role_text else None
	except Exception:
		return None


def _get_app_name(obj: Any) -> str | None:
	"""Get the application name from an NVDA object's appModule."""
	try:
		app_module = obj.appModule
		if app_module is not None:
			app_name = getattr(app_module, "appName", None)
			return str(app_name).strip() if isinstance(app_name, str) and app_name.strip() else None
	except Exception:
		pass
	return None


def _get_window_title(obj: Any) -> str | None:
	"""Get the window title from an NVDA object."""
	try:
		window_text = obj.windowText
		return str(window_text).strip() if isinstance(window_text, str) and window_text.strip() else None
	except Exception:
		return None


def capture_focused_object(
	preprocessor: ImagePreprocessor | None = None,
	encoder: ImageEncoder | None = None,
) -> FocusCaptureResult:
	"""Capture the currently focused NVDA object as a base64-encoded image.

	Returns a FocusCaptureResult with the image data and metadata about the
	focused object.

	Raises:
		RuntimeError: If no focus object is available or its location cannot be determined.
	"""
	resolved = _resolve_capture_location_with_retry()
	if resolved is None:
		raise RuntimeError("Unable to resolve usable bounds for the current focused object.")
	focus_obj, location = resolved

	left, top, width, height = location

	# Capture the region
	try:
		bbox = (left, top, left + width, top + height)
		image = ImageGrab.grab(bbox=bbox)
	except Exception as e:
		raise RuntimeError(f"Failed to capture the focused object region: {e}")

	# Convert to bytes
	buffer = BytesIO()
	image.save(buffer, format="PNG")
	raw_bytes = buffer.getvalue()

	# Preprocess
	if preprocessor is None:
		preprocessor = ImagePreprocessor()
	processed_bytes = preprocessor.preprocess(
		image_bytes=raw_bytes,
		max_side=get_image_max_side(),
		image_format=get_image_format(),  # type: ignore[arg-type]
		quality=get_image_quality(),
	)

	# Encode
	if encoder is None:
		encoder = ImageEncoder()
	image_base64 = encoder.encode(processed_bytes)

	# Metadata
	object_name = _get_object_name(focus_obj)
	object_role = _get_object_role(focus_obj)
	app_name = _get_app_name(focus_obj)
	window_title = _get_window_title(focus_obj)

	return FocusCaptureResult(
		image_base64=image_base64,
		object_name=object_name,
		object_role=object_role,
		app_name=app_name,
		window_title=window_title,
		left=left,
		top=top,
		width=width,
		height=height,
	)
