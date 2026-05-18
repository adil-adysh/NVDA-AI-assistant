# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import dataclasses
import time
from io import BytesIO
from typing import Any

from PIL import ImageGrab

from ..config.settings import get_image_format, get_image_max_side, get_image_quality
from logHandler import log
from .objects import (
	clip_location_to_containers,
	get_object_location_with_parent_fallback,
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

	If the leaf object has no location (common for Ia2Web elements inside
	WebViews), walks up the parent chain to find a container with a usable
	location.  The result is then clipped to parent containers so that
	scroll-cropped or window-overflowing portions are excluded.
	"""
	raw = get_object_location_with_parent_fallback(focus_obj)
	if raw is None:
		return None
	return clip_location_to_containers(focus_obj, raw)


def _get_window_rect_location(obj: Any) -> tuple[int, int, int, int] | None:
	"""Get the screen rectangle of the window that contains *obj*.

	This is the ultimate fallback when the accessibility tree provides no
	location for any object in the hierarchy (common for Ia2Web elements
	inside ``Chrome_RenderWidgetHostHWND`` WebViews).  Mirrors NVDA's own
	``WindowFromPoint`` pattern in ``IAccessible.__init__`` (line 810-815).
	"""
	try:
		window_handle = getattr(obj, "windowHandle", None)
		if window_handle is None:
			return None
		import winUser
		# getWindowRect returns (left, top, right, bottom)
		left, top, right, bottom = winUser.getWindowRect(window_handle)
		width = right - left
		height = bottom - top
		if width <= 0 or height <= 0:
			return None
		loc: tuple[int, int, int, int] = (int(left), int(top), int(width), int(height))
		log.debug(
			"Window-rect fallback resolved: hwnd=%d rect=%s",
			window_handle, loc,
		)
		return loc
	except Exception:
		return None


def _resolve_capture_location_with_retry(
	max_attempts: int = 5,
	retry_delay_seconds: float = 0.1,
) -> tuple[Any, tuple[int, int, int, int], str] | None:
	"""Resolve capture bounds, falling back through multiple sources on failure.

	Resolution order (each phase falls through to the next on failure):

	1. **Focus object** with retries — transient ``accLocation`` failures
	   are common for Ia2Web objects in WebViews ("marshalled for a
	   different thread").  A short sleep between attempts gives the COM
	   bridge time to resolve.
	2. **Navigator object** — NVDA's review-cursor object often has better
	   location fidelity for WebView content.
	3. **Foreground object** — the top-level window; usually backed by UIA
	   which provides reliable bounding rectangles.
	4. **Window rectangle** — ``winUser.getWindowRect(obj.windowHandle)``
	   as a last resort.  Matches the pattern used by NVDA's own
	   ``IAccessible.__init__`` when ``accLocation`` fails (line 810-815).

	Returns ``(obj, location, source)`` where *source* is one of
	``"focus"``, ``"navigator"``, ``"foreground"``, or ``"window_rect"``.
	Returns ``None`` if all phases are exhausted.
	"""
	# Phase 1: try focus object with retries
	for attempt in range(max_attempts):
		focus_obj = get_object_safe("focus")
		if focus_obj is None:
			log.debug("Focus capture retry %d/%d: getFocusObject returned None", attempt + 1, max_attempts)
			if attempt < max_attempts - 1:
				time.sleep(retry_delay_seconds)
			continue
		location = _resolve_capture_location(focus_obj)
		if location is not None:
			return focus_obj, location, "focus"
		_describe = _describe_object(focus_obj)
		log.debug(
			"Focus capture retry %d/%d: location resolution failed for %s",
			attempt + 1, max_attempts, _describe,
		)
		if attempt < max_attempts - 1:
			time.sleep(retry_delay_seconds)

	# Phase 2: fall back to navigator object
	nav_obj = get_object_safe("navigator")
	if nav_obj is not None:
		location = _resolve_capture_location(nav_obj)
		if location is not None:
			return nav_obj, location, "navigator"
		log.debug("Focus capture fallback: navigator location resolution failed for %s", _describe_object(nav_obj))
	else:
		log.debug("Focus capture fallback: getNavigatorObject returned None")

	# Phase 3: fall back to foreground object
	fg_obj = get_object_safe("foreground")
	if fg_obj is not None:
		location = _resolve_capture_location(fg_obj)
		if location is not None:
			return fg_obj, location, "foreground"
		log.debug("Focus capture fallback: foreground location resolution failed for %s", _describe_object(fg_obj))
	else:
		log.debug("Focus capture fallback: getForegroundObject returned None")

	# Phase 4: window-rectangle fallback (NVDA IAccessible.__init__ pattern)
	# Use the last known focus object's windowHandle if available, otherwise
	# probe the foreground object.
	probe_obj = get_object_safe("focus") or get_object_safe("foreground")
	if probe_obj is not None:
		location = _get_window_rect_location(probe_obj)
		if location is not None:
			return probe_obj, location, "window_rect"
		log.debug("Focus capture fallback: window-rect resolution failed for %s", _describe_object(probe_obj))

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


def _describe_object(obj: Any) -> str:
	"""Return a debug-level description of an NVDA object."""
	parts: list[str] = [type(obj).__name__]
	try:
		name = getattr(obj, "name", None)
		if isinstance(name, str) and name.strip():
			parts.append(f"name={name.strip()!r}")
	except Exception:
		pass
	try:
		role = getattr(obj, "role", None)
		if role is not None:
			parts.append(f"role={role}")
	except Exception:
		pass
	try:
		app_name = _get_app_name(obj)
		if app_name:
			parts.append(f"app={app_name}")
	except Exception:
		pass
	try:
		loc = getattr(obj, "location", None)
		if loc is not None:
			parts.append(f"loc=({loc.left},{loc.top},{loc.width},{loc.height})")
		else:
			parts.append("loc=None")
	except Exception:
		parts.append("loc=<error>")
	return " ".join(parts)


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
		focus_obj = get_object_safe("focus")
		nav_obj = get_object_safe("navigator")
		fg_obj = get_object_safe("foreground")
		log.debug(
			"Focus capture failed: focus=%s, navigator=%s, foreground=%s",
			_describe_object(focus_obj) if focus_obj is not None else "None",
			_describe_object(nav_obj) if nav_obj is not None else "None",
			_describe_object(fg_obj) if fg_obj is not None else "None",
		)
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
