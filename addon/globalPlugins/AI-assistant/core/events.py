# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal


@dataclass(frozen=True, slots=True)
class ProgressEvent:
	stage: Literal[
		"start",
		"collecting_context",
		"building_prompt",
		"llm_request",
		"streaming",
		"tool_execution",
		"complete",
		"error",
	]
	message: str


ProgressHandler = Callable[[ProgressEvent], None]
