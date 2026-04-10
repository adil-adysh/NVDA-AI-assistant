# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from io import BytesIO
from typing import Literal

from PIL import Image, ImageGrab

ImageFormat = Literal["PNG", "JPEG"]


class ImageCaptureService:
    def capture(self) -> bytes:
        return self._capture_foreground_window_bytes()

    def _get_foreground_window_rect(self) -> tuple[int, int, int, int]:
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

    def _capture_foreground_window_png(self) -> bytes:
        bbox = self._get_foreground_window_rect()
        image = ImageGrab.grab(bbox=bbox)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def _capture_foreground_window_bytes(self) -> bytes:
        return self._capture_foreground_window_png()


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
            raise ValueError("Unsupported image format: %s" % image_format)

        buffer = BytesIO()
        image.save(buffer, format=normalized_format, **save_kwargs)
        return buffer.getvalue()


class ImageEncoder:
    def encode(self, image_bytes: bytes) -> str:
        return base64.b64encode(image_bytes).decode("ascii")
