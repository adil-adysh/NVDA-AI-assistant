# -*- coding: utf-8 -*-
from __future__ import annotations

import collections.abc
import functools
import threading
import time
from typing import Any, Callable

import queueHandler
import ui

from ..config.state import ProviderState
from ..config.settings import is_streaming_tone_enabled


_streaming_tone_lock = threading.Lock()
_last_streaming_tone_time = 0.0
_streaming_tone_interval = 1.0
_STREAMING_TONE_MIN_INTERVAL = 1.0
_STREAMING_TONE_MAX_INTERVAL = 4.0


def play_streaming_tone() -> None:
	"""Play a short tone when streamed response progress is received."""
	if not is_streaming_tone_enabled():
		return

	now = time.monotonic()
	global _last_streaming_tone_time, _streaming_tone_interval  # pylint: disable=global-statement
	with _streaming_tone_lock:
		elapsed = now - _last_streaming_tone_time
		if elapsed < _streaming_tone_interval:
			_streaming_tone_interval = min(_streaming_tone_interval * 1.5, _STREAMING_TONE_MAX_INTERVAL)
			return

		if elapsed > 2.0:
			_streaming_tone_interval = _STREAMING_TONE_MIN_INTERVAL

		_last_streaming_tone_time = now

	try:
		import tones
	except Exception:
		return

	try:
		queue(tones.beep, 520.0, 50)
	except Exception:
		from logHandler import log

		log.exception("Error playing streaming tone")


def message(text: str) -> None:
	ui.message(text)


def queue_speech_then(
	text: str,
	on_complete: Callable[[], None],
) -> None:
	"""Speak *text* and invoke ``on_complete`` after NVDA finishes it.

	The callback is deliberately attached to the speech sequence rather than
	queued as a separate event.  NVDA cancels speech when focus moves into a
	new browse-mode document, so a UI operation that must take focus belongs
	after the response's final speech callback.

	When speech is disabled, beeps-only, or on-demand, there is no guaranteed
	speech completion callback.  In those modes the caller must still be able
	to present its result, so complete immediately.
	"""
	try:
		import speech
		from speech.commands import CallbackCommand
		from speech.extensions import pre_speechCanceled

		state = speech.getState()
		if state is None or state.speechMode != speech.SpeechMode.talk:
			on_complete()
			return

		completed = False

		def complete_once() -> None:
			nonlocal completed
			if completed:
				return
			completed = True
			pre_speechCanceled.unregister(complete_once)
			on_complete()

		# If the user cancels speech, NVDA removes CallbackCommand instances
		# from the pending sequence. Complete the UI transition anyway; the
		# result must not disappear merely because speech was stopped.
		pre_speechCanceled.register(complete_once)

		speech.speak(
			[
				text,
				CallbackCommand(complete_once, name="AI Assistant: render one-shot result"),
			]
		)
	except Exception:
		from logHandler import log

		log.exception("Unable to attach one-shot result completion to NVDA speech")
		on_complete()


def format_browseable_title(title: str, provider_state: ProviderState | None = None) -> str:
	"""Return a title string that includes the current provider and model name."""
	if provider_state is None:
		return title

	provider = provider_state.provider.strip()
	model_name = provider_state.model_name.strip()
	if not provider:
		return title

	provider_label = provider.capitalize()
	if model_name:
		return f"{title} — {provider_label} ({model_name})"
	return f"{title} — {provider_label}"


def browseable_message(
	text: str,
	title: str | None = None,
	is_html: bool = False,
	close_button: bool = False,
	copy_button: bool = False,
	sanitize_html_func: collections.abc.Callable[[str], str] = ui.nh3.clean,
) -> None:
	if is_html and sanitize_html_func is ui.nh3.clean:

		def _passthrough(html: str) -> str:
			return html

		sanitize_html_func = _passthrough

	ui.browseableMessage(
		text,
		title=title,
		isHtml=is_html,
		closeButton=close_button,
		copyButton=copy_button,
		sanitizeHtmlFunc=sanitize_html_func,
	)


def queue(callback: Callable[..., None], *args: Any, **kwargs: Any) -> None:
	if kwargs:
		callback = functools.partial(callback, **kwargs)
	queueHandler.queueFunction(queueHandler.eventQueue, callback, *args)


def call(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
	if threading.current_thread() is threading.main_thread():
		return callback(*args, **kwargs)

	done = threading.Event()
	result: dict[str, Any] = {}

	def runner() -> None:
		try:
			result["value"] = callback(*args, **kwargs)
		except Exception as error:
			result["error"] = error
		finally:
			done.set()

	queueHandler.queueFunction(queueHandler.eventQueue, runner)
	done.wait()
	if "error" in result:
		raise result["error"]
	return result.get("value")
