# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from dataclasses import dataclass
from math import ceil
from typing import Any


def estimate_tokens(text: str) -> int:
	"""Estimate token count for a text string using a simple heuristic."""
	if not text:
		return 0
	return max(1, ceil(len(text) / 4))


@dataclass
class RequestMetrics:
	request_type: str
	provider: str
	model: str = "unknown"
	start_time: float = 0.0
	end_time: float = 0.0
	duration_seconds: float = 0.0
	success: bool = False
	error: str | None = None

	def finalize(self, end_time: float, success: bool, error: str | None = None) -> None:
		self.end_time = end_time
		self.duration_seconds = end_time - self.start_time
		self.success = success
		self.error = error

	def to_dict(self) -> dict[str, Any]:
		return {
			"request_type": self.request_type,
			"provider": self.provider,
			"model": self.model,
			"duration_seconds": self.duration_seconds,
			"success": self.success,
			"error": self.error,
		}

	def to_log_record(self) -> dict[str, Any]:
		record = {
			"timestamp": time.time(),
		}
		record.update(self.to_dict())
		return record


@dataclass
class SummaryRequestMetrics(RequestMetrics):
	input_chars: int = 0
	prompt_chars: int = 0
	prompt_tokens_estimated: int = 0
	output_chars: int = 0
	output_tokens_estimated: int = 0

	def to_dict(self) -> dict[str, Any]:
		base = super().to_dict()
		base.update(
			{
				"input_chars": self.input_chars,
				"prompt_chars": self.prompt_chars,
				"prompt_tokens_estimated": self.prompt_tokens_estimated,
				"output_chars": self.output_chars,
				"output_tokens_estimated": self.output_tokens_estimated,
			}
		)
		return base


@dataclass
class ImageRequestMetrics(RequestMetrics):
	raw_image_bytes: int = 0
	processed_image_bytes: int = 0
	image_pixels: int = 0
	resize_ratio: float = 1.0
	base64_size: int = 0
	prompt_chars: int = 0
	prompt_tokens_estimated: int = 0
	output_chars: int = 0
	output_tokens_estimated: int = 0

	def to_dict(self) -> dict[str, Any]:
		base = super().to_dict()
		base.update(
			{
				"raw_image_bytes": self.raw_image_bytes,
				"processed_image_bytes": self.processed_image_bytes,
				"image_pixels": self.image_pixels,
				"resize_ratio": self.resize_ratio,
				"base64_size": self.base64_size,
				"prompt_chars": self.prompt_chars,
				"prompt_tokens_estimated": self.prompt_tokens_estimated,
				"output_chars": self.output_chars,
				"output_tokens_estimated": self.output_tokens_estimated,
			}
		)
		return base
