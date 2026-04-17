# -*- coding: utf-8 -*-
from __future__ import annotations

from ..types import PromptContext
from .defaults import get_default_prompt
from .renderer import render_prompt_template
from ...config.settings import get_prompt_template_override

_USER_PROMPT_OVERRIDES: dict[str, str] = {}


def register_user_prompt_override(prompt_key: str, template_text: str) -> None:
    _USER_PROMPT_OVERRIDES[prompt_key] = template_text


def _resolve_user_override(prompt_key: str, provider_name: str | None = None) -> str | None:
    if provider_name is not None:
        provider_key = f"{prompt_key}:{provider_name}"
        provider_override = _USER_PROMPT_OVERRIDES.get(provider_key)
        if provider_override:
            return provider_override
        provider_override = get_prompt_template_override(provider_key)
        if provider_override:
            return provider_override

    override = _USER_PROMPT_OVERRIDES.get(prompt_key)
    if override:
        return override
    return get_prompt_template_override(prompt_key)


def get_prompt_template(prompt_key: str, provider_name: str | None = None) -> str:
    user_override = _resolve_user_override(prompt_key, provider_name=provider_name)
    if user_override:
        return user_override

    default_prompt = get_default_prompt(prompt_key, provider_name=provider_name)
    if default_prompt is not None:
        return default_prompt

    raise ValueError(f"No prompt template found for prompt_key={prompt_key}")


def prompt_template_exists(prompt_key: str, provider_name: str | None = None) -> bool:
    try:
        _ = get_prompt_template(prompt_key, provider_name=provider_name)
        return True
    except ValueError:
        return False


def render_prompt(prompt_key: str, prompt_context: PromptContext, provider_name: str | None = None) -> str:
    template = get_prompt_template(prompt_key, provider_name=provider_name)
    return render_prompt_template(template, prompt_context)
