# -*- coding: utf-8 -*-
from __future__ import annotations

from .base import UseCase
from .chat import (
	OpenChatUseCase,
	OpenChatWithPageContentUseCase,
	OpenChatWithScreenshotUseCase,
)
from .focus_image import (
	AttachFocusedImageToChatUseCase,
	DescribeFocusedImageUseCase,
)
from .image import ImageDescriptionUseCase
from .summary import SummaryUseCase
from .structure_summary import StructureSummaryUseCase
from .types import UseCaseSpec


def build_default_use_cases() -> tuple[UseCase, ...]:
	return (
		SummaryUseCase(),
		StructureSummaryUseCase(),
		ImageDescriptionUseCase(),
		DescribeFocusedImageUseCase(),
		OpenChatUseCase(),
		OpenChatWithPageContentUseCase(),
		OpenChatWithScreenshotUseCase(),
		AttachFocusedImageToChatUseCase(),
	)


def build_default_use_case_specs() -> tuple[UseCaseSpec, ...]:
	return tuple(use_case.spec for use_case in build_default_use_cases())
