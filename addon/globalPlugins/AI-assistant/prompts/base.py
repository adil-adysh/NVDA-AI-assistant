# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

try:
    from logHandler import log
except Exception:
    import logging

    log = logging.getLogger(__name__)

import jinja2


TEMPLATE_DIR = Path(__file__).with_name("templates")
JINJA_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


SYSTEM_PROMPT_TEMPLATE = "system_prompt.jinja2"


def _iter_template_names(template_name: str, language: str | None = None) -> tuple[str, ...]:
    candidates: list[str] = []
    if language:
        normalized_language = language.strip()
        language_variants: list[str] = []
        for variant in (
            normalized_language,
            normalized_language.replace("-", "_"),
            normalized_language.replace("_", "-"),
        ):
            if variant and variant not in language_variants:
                language_variants.append(variant)

        base_variants: list[str] = []
        for variant in language_variants:
            base_language = variant.split("_", 1)[0].split("-", 1)[0]
            if base_language and base_language not in language_variants and base_language not in base_variants:
                base_variants.append(base_language)

        for variant in language_variants + base_variants:
            candidate = f"{variant}/{template_name}"
            if candidate not in candidates:
                candidates.append(candidate)

    english_template = f"en/{template_name}"
    if english_template not in candidates:
        candidates.append(english_template)
    if template_name not in candidates:
        candidates.append(template_name)
    return tuple(candidates)


def render_prompt_template(template_name: str, language: str | None = None, **context: object) -> str:
    candidates = _iter_template_names(template_name, language=language)
    log.debug(
        "Prompt template candidates=%s template_name=%r language=%r",
        candidates,
        template_name,
        language,
    )
    for candidate in candidates:
        try:
            template = JINJA_ENV.get_template(candidate)
            log.debug(
                "Prompt template selected=%r language=%r candidate=%r",
                template_name,
                language,
                candidate,
            )
            break
        except jinja2.TemplateNotFound:
            log.debug("Prompt template candidate not found=%r", candidate)
            continue
    else:
        template = JINJA_ENV.get_template(template_name)
        log.debug(
            "Prompt template fallback to default=%r language=%r",
            template_name,
            language,
        )
    return template.render(**context)


def build_system_prompt_for_nvda_assistant(language: str | None = None) -> str:
    """Build the shared system prompt for the NVDA assistant."""
    return render_prompt_template(SYSTEM_PROMPT_TEMPLATE, language=language)


def build_chat_messages(
    system_prompt: str,
    user_messages: list[str],
    assistant_messages: list[str] | None = None,
) -> list[dict[str, str]]:
    """Build a structured message list for interactive chat."""
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    assistant_messages = assistant_messages or []
    for content in assistant_messages:
        messages.append({"role": "assistant", "content": content})

    for content in user_messages:
        messages.append({"role": "user", "content": content})

    return messages
