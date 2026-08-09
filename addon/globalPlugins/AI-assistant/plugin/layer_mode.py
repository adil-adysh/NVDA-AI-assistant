# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
from __future__ import annotations

import builtins
from collections.abc import Callable, Sequence
from typing import Any, cast

from ..ui import nvda_ui


def _translate(message: str) -> str:
	return message


_ = cast(Callable[[str], str], getattr(builtins, "_", _translate))


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

	@property
	def active(self) -> bool:
		return self._active

	def activate(self) -> None:
		if self._active:
			raise RuntimeError("Assistant layer is already active")
		self._layered_script_to_run = None
		for gesture_key, handler in self._bindings:
			self._bind_gesture(f"kb:{gesture_key}", handler.__name__[7:])
		self._active = True
		nvda_ui.message(
			# TRANSLATORS: Message spoken when the AI assistant command layer is activated, listing available key shortcuts.
			_(
				"AI assistant layer active. Press S for summary, O for structure, I for window image, F for focus describe, C for chat, P for page, X for screenshot, Z for attach focus image, V for attach selection, B for attach clipboard, T for toggle provider, H for help."
			)
		)

	def resolve_script(self, gesture: Any):
		if not self._active:
			return None
		self._layered_script_to_run = next(
			(handler for key, handler in self._bindings if key == gesture.mainKeyName),
			None,
		)
		if self._layered_script_to_run is None:
			return self.script_error
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

	def finish(self) -> None:
		self._active = False
		self._layered_script_to_run = None
		self._clear_gesture_bindings()
		self._restore_default_gestures()

	def script_error(self, _gesture: Any):
		# TRANSLATORS: Message spoken when an invalid key is pressed in the AI assistant command layer.
		nvda_ui.message(_("Can't find this assistant layer script."))
		self.finish()
