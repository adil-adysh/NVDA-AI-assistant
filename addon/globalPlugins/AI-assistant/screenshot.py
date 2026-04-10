# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
import base64
import ctypes
from ctypes import wintypes
from io import BytesIO

from PIL import ImageGrab


def _get_foreground_window_rect() -> tuple[int, int, int, int]:
	user32 = ctypes.windll.user32
	hwnd = user32.GetForegroundWindow()
	if not hwnd:
		raise RuntimeError("Unable to locate the current foreground window.")

	rect = wintypes.RECT()
	if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
		raise RuntimeError("Unable to read the foreground window bounds.")

	if rect.right <= rect.left or rect.bottom <= rect.top:
		raise RuntimeError("Foreground window bounds are invalid.")

	return rect.left, rect.top, rect.right, rect.bottom


def capture_foreground_window_png() -> bytes:
	"""Capture the current foreground window and return PNG bytes."""
	bbox = _get_foreground_window_rect()
	image = ImageGrab.grab(bbox=bbox)
	buffer = BytesIO()
	image.save(buffer, format="PNG")
	return buffer.getvalue()


def capture_foreground_window_bytes() -> bytes:
    """Capture the current foreground window and return raw image bytes."""
    return capture_foreground_window_png()
