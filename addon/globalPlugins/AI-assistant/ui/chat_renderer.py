# -*- coding: utf-8 -*-
from __future__ import annotations

from html import escape as html_escape

from ..core.messages import ChatMessage
from ..utils.markdown import render_markdown_to_html


class ChatHtmlRenderer:
	COMMON_CSS = """body { font-family: Arial, sans-serif; padding: 12px; line-height: 1.5; background: #ffffff; color: #111; }
h6.section-heading { font-size: 1rem; font-weight: bold; margin: 0 0 8px 0; }
.bubble { background: #f7f7f7; border-radius: 10px; padding: 12px; border: 1px solid #ddd; }
"""

	HISTORY_CSS = """#chat { margin: 0; padding: 0; }
.msg { margin-bottom: 18px; }
.msg.user .bubble { border-left: 4px solid #0078d7; }
.msg.assistant .bubble { border-left: 4px solid #333; }
.content { white-space: pre-wrap; word-wrap: break-word; }
pre { background: #eee; padding: 10px; border-radius: 4px; overflow-x: auto; }
code { background: #f2f2f2; padding: 2px 4px; border-radius: 4px; }
blockquote { border-left: 4px solid #ccc; margin: 12px 0; padding-left: 12px; color: #555; }
table { border-collapse: collapse; width: 100%; margin-top: 10px; }
td, th { border: 1px solid #999; padding: 6px 10px; }
a { color: #0066cc; text-decoration: none; }
a:hover { text-decoration: underline; }
"""

	LAST_TURN_CSS = """.section { margin-bottom: 18px; }
"""

	@classmethod
	def build_history_page(cls, messages: list[ChatMessage]) -> str:
		rows = [cls._build_history_entry(msg) for msg in messages]
		body = f"<div id=\"chat\" role=\"log\" aria-live=\"polite\">{"".join(rows)}</div>"
		return cls._wrap_html(body, cls.HISTORY_CSS)

	@classmethod
	def build_last_turn_html(
		cls,
		user_message: str,
		assistant_message: str,
		thinking_trace: str | None = None,
	) -> str:
		user_html = cls._render_message_html(user_message)
		assistant_html = cls._render_message_html(assistant_message)
		results = [
			"<div class=\"section\"><h6 class=\"section-heading\">User query</h6>",
			f"<div class=\"bubble\">{user_html}</div></div>",
		]
		if thinking_trace:
			thinking_html = cls._render_message_html(thinking_trace)
			results.extend([
				"<div class=\"section\"><h6 class=\"section-heading\">Thinking trace</h6>",
				f"<div class=\"bubble\">{thinking_html}</div></div>",
			])
		results.extend([
			"<div class=\"section\"><h6 class=\"section-heading\">Assistant response</h6>",
			f"<div class=\"bubble\">{assistant_html}</div></div>",
		])
		return cls._wrap_html("".join(results), cls.LAST_TURN_CSS)

	@classmethod
	def _build_history_entry(cls, msg: ChatMessage) -> str:
		role = msg.role if msg.role in {"user", "assistant", "system", "tool"} else "assistant"
		label = "User" if role == "user" else "Assistant" if role == "assistant" else msg.role.capitalize()
		if role == "tool":
			label = f"Tool/{msg.tool_name or 'tool'}"
		content = msg.content or ""
		return (
			f"<div class='msg {role}'><h6 class='section-heading'>{cls._escape_html(label)}</h6>"
			f"<div class='bubble content'>{cls._render_message_html(content)}</div></div>"
		)

	@classmethod
	def _wrap_html(cls, body: str, extra_css: str = "") -> str:
		return (
			f"<!DOCTYPE html><html><head><meta charset=\"utf-8\"><style>"
			f"{cls.COMMON_CSS}{extra_css}</style></head><body>{body}</body></html>"
		)

	@classmethod
	def _render_message_html(cls, content: str) -> str:
		if not content:
			return ""

		return render_markdown_to_html(content)

	@staticmethod
	def _escape_html(text: str) -> str:
		return html_escape(text)
