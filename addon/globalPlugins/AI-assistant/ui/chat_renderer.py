# -*- coding: utf-8 -*-
from __future__ import annotations

from html import escape as html_escape

import markdown

from ..core.messages import ChatMessage


class ChatHtmlRenderer:
	HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body { font-family: Arial, sans-serif; padding: 12px; line-height: 1.5; background: #ffffff; color: #111; }
#chat { margin: 0; padding: 0; }
.msg { margin-bottom: 18px; }
h4 { font-size: 1rem; font-weight: bold; margin: 0 0 8px 0; }
.bubble { background: #f7f7f7; border-radius: 10px; padding: 12px; border: 1px solid #ddd; }
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
</style>
</head>
<body>
<div id="chat" role="log" aria-live="polite"></div>
</body>
</html>
"""

	@classmethod
	def build_history_page(cls, messages: list[ChatMessage]) -> str:
		rows: list[str] = []
		for msg in messages:
			role = msg.role if msg.role in {"user", "assistant", "system", "tool"} else "assistant"
			label = "User" if role == "user" else "Assistant" if role == "assistant" else msg.role.capitalize()
			content = msg.content or ""
			if role == "tool":
				label = f"Tool/{msg.tool_name or 'tool'}"
			rows.append(
				f"<div class='msg {role}'><h4>{cls._escape_html(label)}</h4>"
				f"<div class='bubble content'>{cls._render_message_html(content)}</div></div>"
			)
		html = cls.HTML_TEMPLATE.replace(
			"<div id=\"chat\" role=\"log\" aria-live=\"polite\"></div>",
			"<div id=\"chat\" role=\"log\" aria-live=\"polite\">" + "".join(rows) + "</div>",
		)
		return html

	@classmethod
	def build_last_turn_html(
		cls,
		user_message: str,
		assistant_message: str,
		thinking_trace: str | None = None,
	) -> str:
		user_html = cls._render_message_html(user_message)
		assistant_html = cls._render_message_html(assistant_message)
		thinking_html = cls._render_message_html(thinking_trace or "") if thinking_trace else ""
		result = [
			"<!DOCTYPE html>",
			"<html><head><meta charset=\"utf-8\"><style>",
			"body{font-family:Arial,sans-serif;padding:16px;line-height:1.6;color:#111;}",
			".section{margin-bottom:18px;}",
			"h4{font-size:1rem;font-weight:bold;margin:0 0 8px 0;}",
			".bubble{background:#f7f7f7;border-radius:10px;padding:12px;border:1px solid #ddd;}",
			"</style></head><body>",
			"<div class=\"section\"><h4>User query</h4>",
			f"<div class=\"bubble\">{user_html}</div></div>",
		]
		if thinking_trace:
			result.extend([
				"<div class=\"section\"><h4>Thinking trace</h4>",
				f"<div class=\"bubble\">{thinking_html}</div></div>",
			])
		result.extend([
			"<div class=\"section\"><h4>Assistant response</h4>",
			f"<div class=\"bubble\">{assistant_html}</div></div>",
			"</body></html>",
		])
		return "".join(result)

	@classmethod
	def _render_message_html(cls, content: str) -> str:
		if not content:
			return ""
		return markdown.markdown(
			content,
			extensions=["extra", "sane_lists", "smarty"],
			output_format="html5",
		)

	@staticmethod
	def _escape_html(text: str) -> str:
		return html_escape(text)
