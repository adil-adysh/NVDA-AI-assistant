# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import dataclasses
from io import BytesIO
from typing import Any

from PIL import ImageGrab

from ..config.settings import get_image_format, get_image_max_side, get_image_quality
from .objects import (
	clip_location_to_containers,
	get_object_location,
	get_object_safe,
)
from .screen_curtain import check_screen_curtain
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
	capture_source: str = "focus"


def _resolve_capture_location(focus_obj: Any) -> tuple[int, int, int, int] | None:
	"""Resolve capture bounds from a focused/navigator object.

	Clipped to visible area via parent container intersection so that
	scroll-cropped or window-overflowing portions are excluded.
	"""
	raw = get_object_location(focus_obj)
	if raw is None:
		return None
	return clip_location_to_containers(focus_obj, raw)


def _resolve_capture_location_with_retry(
	max_attempts: int = 4,
) -> tuple[Any, tuple[int, int, int, int], str] | None:
	"""Resolve capture bounds, falling back to navigator object on failure.

	Tries the focus object first (with retries for transient failures),
	then falls back to the navigator object if focus cannot be resolved.
	Returns (obj, location, source) where source is ``"focus"`` or ``"navigator"``.
	"""
	# Phase 1: try focus object with retries
	for _ in range(max_attempts):
		focus_obj = get_object_safe("focus")
		if focus_obj is None:
			continue
		location = _resolve_capture_location(focus_obj)
		if location is None:
			continue
		return focus_obj, location, "focus"

	# Phase 2: fall back to navigator object
	nav_obj = get_object_safe("navigator")
	if nav_obj is not None:
		location = _resolve_capture_location(nav_obj)
		if location is not None:
			return nav_obj, location, "navigator"

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

	First attempts to capture from the focus object (``api.getFocusObject()``),
	then falls back to the navigator object (``api.getNavigatorObject()``) if
	the focus object's location cannot be resolved.

	Returns a FocusCaptureResult with the image data, metadata, and the
	capture source (``"focus"`` or ``"navigator"``).

	Raises:
		RuntimeError: If the screen curtain is active, or if no focus or
			navigator object is available, or if their location cannot be
			determined.
	"""
	check_screen_curtain()

	resolved = _resolve_capture_location_with_retry()
	if resolved is None:
		raise RuntimeError("Unable to resolve usable bounds for the current focused object.")
	capture_obj, location, capture_source = resolved

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
	object_name = _get_object_name(capture_obj)
	object_role = _get_object_role(capture_obj)
	app_name = _get_app_name(capture_obj)
	window_title = _get_window_title(capture_obj)

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
		capture_source=capture_source,
	)
