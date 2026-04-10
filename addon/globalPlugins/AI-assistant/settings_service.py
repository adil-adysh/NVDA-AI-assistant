# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import NamedTuple

from . import settings


class ImageSettings(NamedTuple):
    max_side: int
    image_format: str
    image_quality: int


class MetricsSettings(NamedTuple):
    enabled: bool
    log_path: str


class SettingsService:
    def get_provider(self) -> str:
        return settings.get_provider()

    def get_image_settings(self) -> ImageSettings:
        return ImageSettings(
            max_side=settings.get_image_max_side(),
            image_format=settings.get_image_format(),
            image_quality=settings.get_image_quality(),
        )

    def get_metrics_settings(self) -> MetricsSettings:
        return MetricsSettings(
            enabled=settings.get_request_metrics_logging_enabled(),
            log_path=settings.get_request_metrics_log_path(),
        )
