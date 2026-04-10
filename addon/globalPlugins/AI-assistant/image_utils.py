# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
from io import BytesIO
from typing import Literal

from PIL import Image

ImageFormat = Literal["PNG", "JPEG"]


def prepare_image_bytes(
    image_bytes: bytes,
    max_side: int = 1024,
    image_format: ImageFormat = "PNG",
    quality: int | None = None,
) -> bytes:
    """Resize and re-encode an image for model provider upload."""
    return resize_image_bytes(
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


def encode_image_base64(image_bytes: bytes) -> str:
    """Encode image bytes as base64 for provider upload."""
    return base64.b64encode(image_bytes).decode("ascii")
