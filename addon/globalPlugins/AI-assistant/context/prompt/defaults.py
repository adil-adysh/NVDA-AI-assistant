# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

@dataclass(frozen=True, slots=True)
class PromptTemplate:
    key: str
    description: str
    template: str
    provider_name: str | None = None

_DEFAULT_PROMPTS: dict[tuple[str, str | None], PromptTemplate] = {}

SYSTEM_PROMPT = (
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

PAGE_SUMMARY_TEMPLATE = (
    "${system_prompt}\n"
    "Output EXACTLY:\n"
    "\n"
    "Overview:\n"
    "(1–2 sentences about page purpose)\n\n"
    "Key points:\n"
    "\n"
    "* (3 to 5 short points that matter to the user)\n\n"
    "Page structure summary:\n"
    "(Short description of layout/navigation)\n\n"
    "Actions (optional):\n"
    "\n"
    "* (Up to 3 useful next steps)\n\n"
    "Context:\n"
    "App: ${app_title}\n"
    "Title: ${page_title}\n"
    "Trimmed: ${truncated_notice}\n\n"
    "Counts:\n"
    "Headings: ${heading_count}\n"
    "Links: ${link_count}\n"
    "Buttons: ${button_count}\n"
    "Landmarks: ${landmark_count}\n\n"
    "Headings:\n"
    "${headings}\n\n"
    "Landmarks:\n"
    "${landmarks}\n\n"
    "Links:\n"
    "${links}\n\n"
    "Buttons:\n"
    "${buttons}\n\n"
    "Content:\n"
    "${text}"
)

IMAGE_DESCRIPTION_TEMPLATE = (
    "${system_prompt}\n"
    "Goal: Describe the visible window screenshot for someone using a screen reader.\n"
    "\n"
    "Rules:\n"
    "* Use ONLY the visible image contents. Do NOT guess or invent missing details.\n"
    "* Describe the layout, visible text, labels, buttons, controls, and any prominent sections.\n"
    "* Mention what is likely interactive, what appears disabled, and what is the main focus.\n"
    "* Include enough context so a blind user can understand the purpose of the screen and next steps.\n"
    "* If you cannot read a visual element clearly, say that it is uncertain or partially visible.\n"
    "* Do not repeat information or use vague language.\n"
    "\n"
    "Output EXACTLY:\n"
    "\n"
    "Overview:\n"
    "(1–2 sentences summarizing the visible window and its main purpose)\n\n"
    "Key points:\n"
    "\n"
    "* (3 to 5 short points describing important visible elements, text, and structure)\n\n"
    "Actions (optional):\n"
    "\n"
    "* (Up to 3 useful next steps or what the user can do next)\n\n"
    "Context:\n"
    "${image_context}"
)

CHAT_TEMPLATE = (
    "${system_prompt}\n"
    "You are an accessibility assistant. Use the available context and answer the user's question clearly and directly.\n"
    "\n"
    "User input:\n"
    "${text}\n"
)

CHAT_WITH_PAGE_CONTEXT_TEMPLATE = (
    "${system_prompt}\n"
    "Use the page context below to answer the user's question.\n"
    "\n"
    "Page context:\n"
    "App: ${app_title}\n"
    "Title: ${page_title}\n"
    "${text}\n"
)

CHAT_WITH_IMAGE_CONTEXT_TEMPLATE = (
    "${system_prompt}\n"
    "Use the screenshot context below to answer the user's question.\n"
    "\n"
    "Screenshot context:\n"
    "${image_context}\n"
    "${text}\n"
)

PAGE_SUMMARY_KEY = "page_summary"
IMAGE_DESCRIPTION_KEY = "image_description"
CHAT_KEY = "chat"
CHAT_WITH_PAGE_CONTEXT_KEY = "chat_with_page_context"
CHAT_WITH_IMAGE_CONTEXT_KEY = "chat_with_image_context"


def register_default_prompt(template: PromptTemplate) -> None:
    _DEFAULT_PROMPTS[(template.key, template.provider_name)] = template


def get_default_prompt(prompt_key: str, provider_name: str | None = None) -> str | None:
    template = _DEFAULT_PROMPTS.get((prompt_key, provider_name))
    if template is not None:
        return template.template
    template = _DEFAULT_PROMPTS.get((prompt_key, None))
    return template.template if template is not None else None


def build_system_prompt_for_nvda_assistant() -> str:
    return SYSTEM_PROMPT


register_default_prompt(
    PromptTemplate(
        key=PAGE_SUMMARY_KEY,
        description="Default page summary prompt template.",
        template=PAGE_SUMMARY_TEMPLATE,
    )
)
register_default_prompt(
    PromptTemplate(
        key=IMAGE_DESCRIPTION_KEY,
        description="Default image description prompt template.",
        template=IMAGE_DESCRIPTION_TEMPLATE,
    )
)
register_default_prompt(
    PromptTemplate(
        key=CHAT_KEY,
        description="Default blank chat prompt template.",
        template=CHAT_TEMPLATE,
    )
)
register_default_prompt(
    PromptTemplate(
        key=CHAT_WITH_PAGE_CONTEXT_KEY,
        description="Default chat prompt template with page context.",
        template=CHAT_WITH_PAGE_CONTEXT_TEMPLATE,
    )
)
register_default_prompt(
    PromptTemplate(
        key=CHAT_WITH_IMAGE_CONTEXT_KEY,
        description="Default chat prompt template with image context.",
        template=CHAT_WITH_IMAGE_CONTEXT_TEMPLATE,
    )
)
