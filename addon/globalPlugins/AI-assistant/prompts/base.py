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


def render_prompt_template(template_name: str, **context: object) -> str:
    template = JINJA_ENV.get_template(template_name)
    return template.render(**context)


def build_system_prompt_for_nvda_assistant() -> str:
    """Build the shared system prompt for the NVDA assistant."""
    return (
        "Role: NVDA accessibility assistant.\n"
        "\n"
        "Goal: Give a quick, useful understanding of the task or content.\n"
        "\n"
        "Rules:\n"
        "* Use ONLY given content. Do NOT guess.\n"
        "* Be concise and practical.\n"
        "* Do not repeat information.\n"
        "\n"
        "Process:\n"
        "1. Read the instructions carefully.\n"
        "2. Use the available content to answer clearly.\n"
        "3. Keep language simple and direct.\n"
    )


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
