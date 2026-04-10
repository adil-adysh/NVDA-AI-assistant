# -*- coding: utf-8 -*-
from __future__ import annotations

from .image_services import ImageCaptureService


def capture_foreground_window_png() -> bytes:
    """Capture the current foreground window and return PNG bytes."""
    return ImageCaptureService().capture()


def capture_foreground_window_bytes() -> bytes:
    """Capture the current foreground window and return raw image bytes."""
    return capture_foreground_window_png()
