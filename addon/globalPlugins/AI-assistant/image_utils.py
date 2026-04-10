# -*- coding: utf-8 -*-
from __future__ import annotations

from .image_services import ImageEncoder, ImagePreprocessor
from .image_services import ImageFormat


def prepare_image_bytes(
    image_bytes: bytes,
    max_side: int = 1024,
    image_format: ImageFormat = "PNG",
    quality: int | None = None,
) -> bytes:
    """Resize and re-encode an image for model provider upload."""
    return ImagePreprocessor().preprocess(
        image_bytes=image_bytes,
        max_side=max_side,
        image_format=image_format,
        quality=quality,
    )


def resize_image_bytes(
    image_bytes: bytes,
    max_side: int = 1024,
    image_format: ImageFormat = "PNG",
    quality: int | None = None,
) -> bytes:
    """Resize an image to fit within a max side and encode it into the desired format."""
    return prepare_image_bytes(
        image_bytes=image_bytes,
        max_side=max_side,
        image_format=image_format,
        quality=quality,
    )


def encode_image_base64(image_bytes: bytes) -> str:
    """Encode image bytes as base64 for provider upload."""
    return ImageEncoder().encode(image_bytes)
