# -*- coding: utf-8 -*-
from __future__ import annotations

from ..context.types import ExtractionResult
from ..prompts import build_extraction_summary_prompt


def build_prompt_for_summary(extraction_result: ExtractionResult) -> str:
	"""Select the summary prompt builder based on extraction source."""
	return build_extraction_summary_prompt(extraction_result)
