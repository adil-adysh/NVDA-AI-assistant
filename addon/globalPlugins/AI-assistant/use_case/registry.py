# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from ..config.settings import get_custom_use_case_definitions
from .base import UseCase
from .chat import (
	OpenChatUseCase,
	OpenChatWithPageContentUseCase,
	OpenChatWithScreenshotUseCase,
)
from .image import ImageDescriptionUseCase
from .prompt_driven import PromptDrivenUseCase
from .summary import SummaryUseCase
from .types import ContextProfileList, UseCaseSpec


def build_default_use_cases() -> tuple[UseCase, ...]:
	return (
		SummaryUseCase(),
		ImageDescriptionUseCase(),
		OpenChatUseCase(),
		OpenChatWithPageContentUseCase(),
		OpenChatWithScreenshotUseCase(),
	)


def build_default_use_case_specs() -> tuple[UseCaseSpec, ...]:
	return tuple(use_case.spec for use_case in build_default_use_cases())


def build_custom_use_cases() -> tuple[UseCase, ...]:
	return tuple(PromptDrivenUseCase(spec=spec) for spec in build_custom_use_case_specs())


def build_registered_use_cases() -> tuple[UseCase, ...]:
	default_cases = build_default_use_cases()
	custom_cases = build_custom_use_cases()
	default_ids = {use_case.spec.id for use_case in default_cases}
	for custom_case in custom_cases:
		if custom_case.spec.id in default_ids:
			raise ValueError(f"Custom use case id conflicts with built-in use case: {custom_case.spec.id}")
	return default_cases + custom_cases


def build_custom_use_case_specs() -> tuple[UseCaseSpec, ...]:
	custom_definitions = get_custom_use_case_definitions()
	specs: list[UseCaseSpec] = []
	for use_case_id, raw_definition in custom_definitions.items():
		try:
			specs.append(_build_custom_use_case_spec(use_case_id, raw_definition))
		except ValueError:
			continue
	return tuple(specs)


def _build_custom_use_case_spec(use_case_id: str, raw_definition: Any) -> UseCaseSpec:
	if not isinstance(raw_definition, dict):
		raise ValueError("Custom use case definition must be a dict")

	prompt_key = raw_definition.get("prompt_key")
	description = raw_definition.get("description")
	context_profile = raw_definition.get("context_profile", ())
	llm_method = raw_definition.get("llm_method")
	requires_input = bool(raw_definition.get("requires_input", False))

	if not isinstance(use_case_id, str) or not use_case_id.strip():
		raise ValueError("Custom use case id must be a non-empty string")
	if not isinstance(prompt_key, str) or not prompt_key.strip():
		raise ValueError(f"Custom use case {use_case_id} requires a prompt_key")
	if not isinstance(description, str) or not description.strip():
		raise ValueError(f"Custom use case {use_case_id} requires a description")
	if not isinstance(llm_method, str) or llm_method.strip() not in ("summarize", "describe_image"):
		raise ValueError(f"Custom use case {use_case_id} requires a valid llm_method")

	return UseCaseSpec(
		id=use_case_id,
		description=description.strip(),
		context_profile=_normalize_context_profile(context_profile),
		prompt_key=prompt_key.strip(),
		llm_method=llm_method.strip(),
		tools=(),
		requires_input=requires_input,
	)


def _normalize_context_profile(raw_profile: Any) -> ContextProfileList:
	if isinstance(raw_profile, str):
		return (raw_profile.strip(),) if raw_profile.strip() else ()
	if isinstance(raw_profile, (list, tuple)):
		items: list[str] = []
		for item in raw_profile:
			if isinstance(item, str) and item.strip():
				items.append(item.strip())
		return tuple(items)
	return ()
