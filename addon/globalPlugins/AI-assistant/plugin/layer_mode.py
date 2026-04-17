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
		self._keep_active = False

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
			_(
				"AI assistant layer active. Press S for summary, I for image describe, C for chat, P for page content, X for screenshot, U for custom use cases, T for provider toggle, or H for help."
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
				nvda_ui.message(_("Can't find this assistant layer script."))
		finally:
			if self._keep_active:
				self._keep_active = False
				self._layered_script_to_run = None
				return
			self.finish()

	def finish(self) -> None:
		self._active = False
		self._layered_script_to_run = None
		self._clear_gesture_bindings()
		self._restore_default_gestures()

	def sustain(self) -> None:
		self._keep_active = True

	def script_error(self, gesture: Any):
		nvda_ui.message(_("Can't find this assistant layer script."))
		self.finish()
