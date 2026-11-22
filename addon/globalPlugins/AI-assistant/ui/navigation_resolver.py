"""Restore browser focus and resolve navigation targets through NVDA."""

from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from ..core.translation import _


def _tree_interceptor(preferred: object | None = None) -> Any | None:
	if preferred is not None and callable(getattr(preferred, "_iterNodesByType", None)):
		return preferred
	try:
		import api
	except ImportError:
		return None
	for getter in (api.getFocusObject, api.getNavigatorObject, api.getForegroundObject):
		try:
			obj = getter()
			ti = getattr(obj, "treeInterceptor", None)
			if ti is not None and callable(getattr(ti, "_iterNodesByType", None)):
				return ti
		except Exception:
			continue
	return None


def _role_candidates(role: str) -> tuple[object, ...]:
	"""Translate stable descriptor roles to NVDA quick-nav item names."""
	names = {
		"heading": ("heading",),
		"link": ("link",),
		"button": ("button",),
		"landmark": ("landmark",),
		"input": ("edit",),
		"combobox": ("comboBox",),
		"checkbox": ("checkBox",),
		"radio": ("radioButton",),
		# Legacy structure-only descriptors do not carry a concrete type.
		"formField": ("formField",),
	}.get(role, ())
	return names


def _node_label(item: object) -> str:
	"""Return the accessible name exposed by an NVDA quick-nav node."""
	for attribute in ("name", "label", "displayText", "value", "description"):
		try:
			value = getattr(item, attribute, None)
		except Exception:
			continue
		label = " ".join(str(value or "").split())
		if label:
			return label
	return ""


def _activate_browser(ti: object) -> Callable[[], bool] | None:
	"""Request foreground activation and return a nonblocking readiness check."""
	root = getattr(ti, "rootNVDAObject", None)
	window_handle = getattr(root, "windowHandle", None)
	if not window_handle:
		return None
	try:
		import ctypes
		import winUser

		# A browser document can expose a child window rather than its owner.
		handle = int(ctypes.windll.user32.GetAncestor(int(window_handle), 2)) or int(window_handle)
		winUser.setForegroundWindow(handle)
		winUser.setFocus(handle)
		get_foreground = getattr(winUser, "getForegroundWindow", None)
		if callable(get_foreground):
			return lambda: get_foreground() == handle
	except Exception:
		pass
	return None


def navigate_to_target(
	target: dict[str, object],
	navigation_context: object | None,
	on_result: Callable[[bool, str], None],
	*,
	schedule: Callable[[int, Callable[[], None]], object] | None = None,
) -> None:
	"""Restore browser focus and resolve on the NVDA event thread."""
	ti = _tree_interceptor(navigation_context)
	if ti is None:
		on_result(False, _("The current window is not an active browser document."))
		return
	is_ready = _activate_browser(ti)
	deadline = time.monotonic() + 1.0

	def finish_when_ready() -> None:
		if schedule is not None and is_ready is not None and time.monotonic() < deadline:
			try:
				ready = is_ready()
			except Exception:
				ready = True
			if not ready:
				schedule(20, finish_when_ready)
				return
		on_result(*resolve_and_move_target(target, ti))

	finish_when_ready()


def resolve_and_move_target(
	target: dict[str, object], navigation_context: object | None = None
) -> tuple[bool, str]:
	"""Resolve a target on the live NVDA document and move to it."""
	try:
		import textInfos
	except ImportError:
		return False, _("NVDA browser navigation is unavailable.")
	ti = _tree_interceptor(navigation_context)
	if ti is None:
		return False, _("The current window is not an active browser document.")
	role = str(target.get("role") or "")
	name = " ".join(str(target.get("name") or "").split()).casefold()
	try:
		occurrence = max(0, int(target.get("occurrence", 0)))
	except (TypeError, ValueError):
		occurrence = 0
	match_names = {name} if name else set()
	if role == "landmark" and ":" in name:
		match_names.add(name.split(":", 1)[1].strip())
		match_names.discard("")
	try:
		root = getattr(ti, "rootNVDAObject", None)
		set_focus = getattr(root, "setFocus", None)
		if callable(set_focus):
			set_focus()
		position = ti.makeTextInfo(textInfos.POSITION_FIRST)
		for role_value in _role_candidates(role):
			exact_count = 0
			partial_matches = []
			for item in ti._iterNodesByType(role_value, direction="next", pos=position):
				raw_label = _node_label(item)
				label = raw_label.casefold()
				if label in match_names:
					if exact_count == occurrence:
						return _move_to_item(item, raw_label)
					exact_count += 1
				elif any(label.startswith(f"{candidate}; ") for candidate in match_names):
					partial_matches.append((item, raw_label))
			if exact_count == 0 and len(partial_matches) > occurrence:
				return _move_to_item(*partial_matches[occurrence])
	except Exception:
		pass
	return False, _("Unable to locate that page target. The page may have changed.")


def _move_to_item(item: object, label: str) -> tuple[bool, str]:
	move_to = getattr(item, "moveTo", None)
	if not callable(move_to):
		return False, _("Unable to move to that page target. The page may have changed.")
	move_to()
	return True, label
