# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from logHandler import log

from ..config.settings import get_custom_use_case_definitions
from ..context.prompt.registry import prompt_template_exists
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
	default_cases = (
		SummaryUseCase(),
		ImageDescriptionUseCase(),
		OpenChatUseCase(),
		OpenChatWithPageContentUseCase(),
		OpenChatWithScreenshotUseCase(),
	)
	log.info("Loaded built-in use cases: %s", [use_case.spec.id for use_case in default_cases])
	return default_cases


def build_default_use_case_specs() -> tuple[UseCaseSpec, ...]:
	return tuple(use_case.spec for use_case in build_default_use_cases())


def build_custom_use_cases() -> tuple[UseCase, ...]:
	return tuple(PromptDrivenUseCase(spec=spec) for spec in build_custom_use_case_specs())


def build_registered_use_cases() -> tuple[UseCase, ...]:
	default_cases = build_default_use_cases()
	custom_cases = build_custom_use_cases()
	if custom_cases:
		log.info("Loaded custom use cases: %s", [use_case.spec.id for use_case in custom_cases])
	else:
		log.info("No custom use cases loaded")
	default_ids = {use_case.spec.id for use_case in default_cases}
	for custom_case in custom_cases:
		if custom_case.spec.id in default_ids:
			raise ValueError(f"Custom use case id conflicts with built-in use case: {custom_case.spec.id}")
	return default_cases + custom_cases


def build_custom_use_case_specs() -> tuple[UseCaseSpec, ...]:
	custom_definitions = get_custom_use_case_definitions()
	if not custom_definitions:
		log.debug("No custom use case definitions found in configuration")
	else:
		log.debug("Found custom use case definitions: %s", list(custom_definitions.keys()))
	specs: list[UseCaseSpec] = []
	for use_case_id, raw_definition in custom_definitions.items():
		try:
			specs.append(_build_custom_use_case_spec(use_case_id, raw_definition))
			log.info("Registered custom use case: %s", use_case_id)
		except ValueError as error:
			log.warning("Skipping invalid custom use case '%s': %s", use_case_id, error)
	return tuple(specs)


def _build_custom_use_case_spec(use_case_id: str, raw_definition: Any) -> UseCaseSpec:
	if not isinstance(raw_definition, dict):
		raise ValueError("Custom use case definition must be a dict")

	prompt_template = raw_definition.get("prompt_template")
	if isinstance(prompt_template, str):
		prompt_template = prompt_template.strip()
	else:
		prompt_template = None

	builtin_prompt_name = raw_definition.get("builtin_prompt_name")
	if isinstance(builtin_prompt_name, str):
		builtin_prompt_name = builtin_prompt_name.strip()
	else:
		builtin_prompt_name = None

	description = raw_definition.get("description")
	context_profile = raw_definition.get("context_profile", ())
	llm_method = raw_definition.get("llm_method")
	requires_input = bool(raw_definition.get("requires_input", False))

	if not isinstance(use_case_id, str) or not use_case_id.strip():
		raise ValueError("Custom use case id must be a non-empty string")
	if not isinstance(description, str) or not description.strip():
		raise ValueError(f"Custom use case {use_case_id} requires a description")
	if not isinstance(llm_method, str) or llm_method.strip().lower() not in ("summarize", "describe_image", "generate"):
		raise ValueError(f"Custom use case {use_case_id} requires a valid llm_method")
	if prompt_template is not None and builtin_prompt_name is not None:
		raise ValueError(f"Custom use case {use_case_id} must specify only one of prompt_template or builtin_prompt_name")
	if prompt_template is None and builtin_prompt_name is None:
		raise ValueError(f"Custom use case {use_case_id} requires either prompt_template or builtin_prompt_name")

	if prompt_template is not None:
		if not prompt_template:
			raise ValueError(f"Custom use case {use_case_id} requires a non-empty prompt_template")
		prompt_template = prompt_template.strip()

	if builtin_prompt_name is not None:
		if not builtin_prompt_name:
			raise ValueError(f"Custom use case {use_case_id} requires a non-empty builtin_prompt_name")
		builtin_prompt_name = builtin_prompt_name.strip()
		if not prompt_template_exists(builtin_prompt_name):
			raise ValueError(f"Custom use case {use_case_id} uses unknown builtin_prompt_name: {builtin_prompt_name}")

	return UseCaseSpec(
		id=use_case_id,
		description=description.strip(),
		context_profile=_normalize_context_profile(context_profile),
		prompt_template=prompt_template,
		builtin_prompt_name=builtin_prompt_name,
		llm_method=llm_method.strip().lower(),
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
