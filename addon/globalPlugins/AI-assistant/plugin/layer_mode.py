# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
from collections.abc import Callable, Sequence
from typing import Any, cast

from logHandler import log

from ..ui import nvda_ui
from ..core.command_session import Choice, CommandSession, Phase


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))

# Keys that trigger a sub-mode (stay active, rebind to digits).
_SUB_MODE_KEYS: frozenset[str] = frozenset({"t", "m"})

# Digit keys mapped to their integer values.
_DIGIT_MAP: dict[str, int] = {
	"0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
	"5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
}


class AssistantLayerController:
	def __init__(
		self,
		bindings: Sequence[tuple[str, Callable[[Any], None]]],
		bind_gesture: Callable[[str, str], None],
		clear_gesture_bindings: Callable[[], None],
		restore_default_gestures: Callable[[], None],
	) -> None:
		self._bindings = tuple(bindings)
		self._bind_gesture = bind_gesture
		self._clear_gesture_bindings = clear_gesture_bindings
		self._restore_default_gestures = restore_default_gestures
		self.session = CommandSession()
		self._layered_script_to_run: Callable[[Any], None] | None = None
		self._digit_handler: Callable[[int], None] | None = None

	@property
	def active(self) -> bool:
		return self.session.phase is not Phase.IDLE

	def activate(self) -> None:
		if self.session.closed:
			return
		if self.active:
			raise RuntimeError("Assistant layer is already active")
		self._layered_script_to_run = None
		self._digit_handler = None
		for gesture_key, _handler in self._bindings:
			self._bind_gesture(f"kb:{gesture_key}", "layerDispatch")
		self.session.activate()
		self._bind_gesture("kb:escape", "layerDispatch")
		nvda_ui.message(
			# TRANSLATORS: Message spoken when the AI assistant command layer is activated, listing available key shortcuts.
			_(
				"AI assistant layer active. Press S for summary, O for structure, G for spelling and grammar, I for window image, F for focus describe, C for chat, P for page, X for screenshot, Z for attach focus image, V for attach selection, B for attach clipboard, T for provider select, M for model select, R for current provider and model, L for last result, Q to stop active requests, H for help."
			)
		)

	def resolve_script(self, gesture: Any):
		if not self.active:
			return None

		if gesture.mainKeyName == "escape":
			return lambda _gesture: self.finish()
		if self.session.phase is Phase.LOADING_CHOICES:
			return lambda _gesture: None
		if self.session.phase is Phase.CHOOSING and gesture.mainKeyName in {"leftArrow", "rightArrow"}:
			return lambda _gesture: self._move_page(-1 if gesture.mainKeyName == "leftArrow" else 1)

		# Digit mode active: only digit keys are accepted.
		if self._digit_handler is not None:
			digit = _DIGIT_MAP.get(gesture.mainKeyName)
			if digit is not None:
				handler = self._digit_handler
				self._layered_script_to_run = lambda g: handler(digit)
				return self.run_and_finish
			# Non-digit in digit mode — error and exit.
			self._layered_script_to_run = None
			return self.script_error

		self._layered_script_to_run = next(
			(handler for key, handler in self._bindings if key == gesture.mainKeyName),
			None,
		)
		if self._layered_script_to_run is None:
			return self.script_error

		# Sub-mode entry keys stay active after running (rebind happens in handler).
		if gesture.mainKeyName in _SUB_MODE_KEYS:
			return self.run_without_finish

		return self.run_and_finish

	def run_and_finish(self, gesture: Any):
		try:
			if self._layered_script_to_run is not None:
				self._layered_script_to_run(gesture)
			else:
				# TRANSLATORS: Message spoken when the assistant layer cannot find the matching script for a key press.
				nvda_ui.message(_("Can't find this assistant layer script."))
		finally:
			self.finish()

	def run_without_finish(self, gesture: Any):
		"""Run the matched handler but do NOT exit the layer.

		Used for sub-mode entry keys (t, m) that rebind the layer
		to digit selection without leaving.
		"""
		try:
			if self._layered_script_to_run is not None:
				self._layered_script_to_run(gesture)
			else:
				nvda_ui.message(_("Can't find this assistant layer script."))
		except Exception:
			log.exception("Error in assistant layer sub-mode handler")
			self.finish()

	def enter_digit_selection(self, handler: Callable[[int], None]) -> None:
		"""Rebind the layer to accept only digit keys 1-9 and 0.

		*handler* receives the selected digit (0-9).  Non-digit keys
		trigger an error and exit the layer.

		All 10 digit keys are bound to ``digitSelect`` on the
		controller.  NVDA's ``_getObjScript`` resolves bound gestures
		directly via ``getattr(obj, 'script_%s')``, so
		``controller.script_digitSelect`` must actively call back
		into ``resolve_script`` for ``_digit_handler`` dispatch.
		"""
		self._digit_handler = handler
		self._clear_gesture_bindings()
		for d in range(10):
			self._bind_gesture(f"kb:{d}", "digitSelect")

	def begin_choices(self, provider: str) -> int:
		token = self.session.begin_choices(provider)
		if self.session.closed:
			return token
		self._digit_handler = None
		self._clear_gesture_bindings()
		self._bind_gesture("kb:escape", "layerDispatch")
		return token

	def accepts(self, token: int, provider: str) -> bool:
		return self.session.accepts(token, provider)

	def show_choices(self, token: int, provider: str, choices: Sequence[Choice], handler: Callable[[str], None]) -> None:
		if not self.session.set_choices(token, provider, choices):
			return
		def select(digit: int) -> None:
			choice = self.session.choice(digit)
			if choice is not None:
				handler(choice.id)
		self.enter_digit_selection(select)
		for key in ("escape", "leftArrow", "rightArrow"):
			self._bind_gesture(f"kb:{key}", "layerDispatch")
		self._announce_page()

	def _move_page(self, direction: int) -> None:
		self.session.move_page(direction)
		self._announce_page()

	def _announce_page(self) -> None:
		lines = [f"{(index + 1) % 10}: {choice.label}" for index, choice in enumerate(self.session.visible_choices)]
		if len(self.session.choices) > 10:
			lines.append(_("Page {page} of {pages}. Left and right arrows change pages. Escape cancels.").format(
				page=self.session.page + 1, pages=(len(self.session.choices) + 9) // 10))
		nvda_ui.message("\n".join(lines))

	def provider_changed(self, provider: str) -> None:
		if self.session.provider is None or self.session.provider == provider:
			return
		self.session.dismiss()
		generation = self.session.generation
		def restore() -> None:
			if self.session.generation == generation:
				self.finish()
		nvda_ui.queue(restore)

	def close(self) -> None:
		self.session.close()
		self.finish()

	def finish(self) -> None:
		self.session.dismiss()
		self._layered_script_to_run = None
		self._digit_handler = None
		self._clear_gesture_bindings()
		self._restore_default_gestures()

	def script_error(self, _gesture: Any):
		# TRANSLATORS: Message spoken when an invalid key is pressed in the AI assistant command layer.
		nvda_ui.message(_("Can't find this assistant layer script."))
		self.finish()
