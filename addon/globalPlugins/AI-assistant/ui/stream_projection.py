# -*- coding: utf-8 -*-
"""Streaming LLM response projection to the host UI via protocol commands.

See ``docs/specs/stream-projection.md`` for the behavioral contract.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from logHandler import log

from . import nvda_ui
from .host_renderer import HostRenderer


def normalize_stream_fragment(
	known_text: str,
	partial_text: str,
	generated_chars: int,
) -> tuple[str, str]:
	"""Normalize partial LLM output into a consistent running text and delta."""
	partial_text = partial_text or ""
	if not partial_text:
		return known_text, ""

	known_length = len(known_text)
	if generated_chars <= known_length:
		return known_text, ""

	if len(partial_text) == generated_chars:
		normalized_text = partial_text
	elif known_length + len(partial_text) == generated_chars:
		normalized_text = f"{known_text}{partial_text}"
	elif partial_text.startswith(known_text):
		normalized_text = partial_text[:generated_chars]
	else:
		normalized_text = f"{known_text}{partial_text}"
		if len(normalized_text) > generated_chars:
			normalized_text = normalized_text[:generated_chars]

	if not normalized_text.startswith(known_text):
		return normalized_text, partial_text

	delta_text = normalized_text[known_length:]
	return normalized_text, delta_text


@dataclass(slots=True)
class StreamProjection:
	"""Bridges LLM streaming callbacks to host protocol commands.

	Normalizes partial text, buffers deltas, and sends ``chat_stream_begin``,
	``chat_stream_delta``, ``chat_stream_end`` (or ``chat_append`` fallback)
	to the host renderer.
	"""

	renderer: HostRenderer
	use_case_id: str | None
	conversation_id: str
	message_id: str
	stream_id: str
	final_metadata_factory: Callable[[], dict[str, object]]
	stream_update_interval: int = 1200
	streaming_started: bool = False
	host_stream_updates_enabled: bool = True
	normalized_stream_text: str = ""
	pending_stream_delta_chunks: list[str] = field(default_factory=list)
	pending_stream_delta_char_count: int = 0
	stream_sequence: int = 0

	def update(self, partial_text: str, generated_chars: int) -> None:
		if not self.host_stream_updates_enabled:
			return
		self.normalized_stream_text, delta_text = normalize_stream_fragment(
			self.normalized_stream_text,
			partial_text,
			generated_chars,
		)
		if delta_text:
			self.pending_stream_delta_chunks.append(delta_text)
			self.pending_stream_delta_char_count += len(delta_text)
		should_flush = not self.streaming_started or self.pending_stream_delta_char_count >= self.stream_update_interval
		if should_flush:
			self.flush()

	def flush(self) -> bool:
		if not self.host_stream_updates_enabled:
			self._clear_pending_delta()
			return False
		delta_text = "".join(self.pending_stream_delta_chunks)
		if not delta_text:
			return self.streaming_started
		try:
			if not self.streaming_started:
				self.renderer.chat_stream_begin(
					self.use_case_id,
					self.conversation_id,
					self.message_id,
					self.stream_id,
				)
				self.streaming_started = True
			self.renderer.chat_stream_delta(
				self.use_case_id,
				self.conversation_id,
				self.message_id,
				self.stream_id,
				delta_text,
				self.stream_sequence,
			)
		except Exception:
			self.host_stream_updates_enabled = False
			log.exception("Streaming host update failed; continuing without UI refreshes")
			self._clear_pending_delta()
			return False
		self.stream_sequence += 1
		self._clear_pending_delta()
		nvda_ui.play_streaming_tone()
		return True

	def finish(self, assistant_content: list[dict[str, Any]]) -> None:
		if self.streaming_started:
			self.flush()
		if not self.host_stream_updates_enabled:
			return
		try:
			if self.streaming_started:
				self.renderer.chat_stream_end(
					self.use_case_id,
					self.conversation_id,
					self.message_id,
					self.stream_id,
					self.stream_sequence - 1,
					assistant_content,
					metadata=self.final_metadata_factory(),
				)
			else:
				self.renderer.chat_append(
					self.use_case_id,
					self.conversation_id,
					{
						"id": self.message_id,
						"role": "assistant",
						"content": assistant_content,
					},
					metadata=self.final_metadata_factory(),
				)
		except Exception:
			if self.streaming_started:
				try:
					self.renderer.chat_stream_abort(
						self.use_case_id,
						self.conversation_id,
						self.message_id,
						self.stream_id,
						self.stream_sequence - 1,
						reason="final_commit_failed",
					)
				except Exception:
					pass
			log.exception("Final host chat update failed after streaming; preserving backend response")

	def abort(self, reason: str | None = None) -> None:
		"""Abort an in-flight stream and clean up UI state.

		If streaming had started, sends ``chat_stream_abort`` to tear down
		the streaming message in the UI.  If streaming had not yet started,
		this is a no-op (no UI state to clean up).

		Safe to call regardless of whether streaming started — the method
		no-ops cleanly if ``streaming_started`` is False.
		"""
		if not self.streaming_started:
			return
		try:
			self.renderer.chat_stream_abort(
				self.use_case_id,
				self.conversation_id,
				self.message_id,
				self.stream_id,
				self.stream_sequence - 1,
				reason=reason,
			)
		except Exception:
			log.exception("Stream abort delivery failed; streaming state may be dangling in the UI")
		self.host_stream_updates_enabled = False

	def _clear_pending_delta(self) -> None:
		self.pending_stream_delta_chunks = []
		self.pending_stream_delta_char_count = 0
