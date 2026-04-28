# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import jinja2


TEMPLATE_DIR = Path(__file__).with_name("templates")
JINJA_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


SYSTEM_PROMPT_TEMPLATE = "system_prompt.jinja2"


def render_prompt_template(template_name: str, language: str | None = None, **context: object) -> str:
    if language:
        language_template_name = f"{language}/{template_name}"
        try:
            template = JINJA_ENV.get_template(language_template_name)
        except jinja2.TemplateNotFound:
            try:
                template = JINJA_ENV.get_template(f"en/{template_name}")
            except jinja2.TemplateNotFound:
                template = JINJA_ENV.get_template(template_name)
    else:
        try:
            template = JINJA_ENV.get_template(template_name)
        except jinja2.TemplateNotFound:
            template = JINJA_ENV.get_template(f"en/{template_name}")
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
