# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
from collections.abc import Callable, Sequence
from typing import Any, cast

from logHandler import log

from ..ui import nvda_ui


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
		self._active = False
		self._layered_script_to_run: Callable[[Any], None] | None = None
		self._digit_handler: Callable[[int], None] | None = None

	@property
	def active(self) -> bool:
		return self._active

	def activate(self) -> None:
		if self._active:
			raise RuntimeError("Assistant layer is already active")
		self._layered_script_to_run = None
		self._digit_handler = None
		for gesture_key, handler in self._bindings:
			self._bind_gesture(f"kb:{gesture_key}", handler.__name__[7:])
		self._active = True
		nvda_ui.message(
			# TRANSLATORS: Message spoken when the AI assistant command layer is activated, listing available key shortcuts.
			_(
				"AI assistant layer active. Press S for summary, O for structure, I for window image, F for focus describe, C for chat, P for page, X for screenshot, Z for attach focus image, V for attach selection, B for attach clipboard, T for provider select, M for model select, H for help."
			)
		)

	def resolve_script(self, gesture: Any):
		if not self._active:
			return None

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

	def finish(self) -> None:
		self._active = False
		self._layered_script_to_run = None
		self._digit_handler = None
		self._clear_gesture_bindings()
		self._restore_default_gestures()

	def script_error(self, _gesture: Any):
		# TRANSLATORS: Message spoken when an invalid key is pressed in the AI assistant command layer.
		nvda_ui.message(_("Can't find this assistant layer script."))
		self.finish()
