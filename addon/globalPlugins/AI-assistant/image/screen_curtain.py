# -*- coding: utf-8 -*-
from __future__ import annotations


class ScreenCurtainError(RuntimeError):
	"""Raised when a screen-based feature is requested while the screen curtain is active.

	Follows the official NVDA pattern of a dedicated error type carrying a
	user-facing message (cf. ``_magnifier.MagnifierStartError``), so presenters
	can surface the actionable message instead of a generic internal error.
	"""


def is_screen_curtain_active() -> bool:
	"""Return whether NVDA's screen curtain is currently enabled.

	Uses the official NVDA API: the module-level ``screenCurtain.screenCurtain``
	singleton (``source/screenCurtain/_screenCurtain.py``).  Falls back to the
	legacy ``api.isScreenCurtainRunning()`` for older NVDA versions and returns
	``False`` if no API is available.
	"""
	try:
		import screenCurtain

		singleton = screenCurtain.screenCurtain
		if singleton is not None:
			return bool(singleton.enabled)
	except Exception:
		pass
	try:
		import api

		if hasattr(api, "isScreenCurtainRunning"):
			return bool(api.isScreenCurtainRunning())
	except Exception:
		pass
	return False


def check_screen_curtain() -> None:
	"""Raise :class:`ScreenCurtainError` if the NVDA screen curtain is active.

	Capturing images while the screen curtain is enabled produces a black
	screen, so this check prevents wasted capture attempts.
	"""
	if is_screen_curtain_active():
		raise ScreenCurtainError(
			"Screen capture is not available while the screen curtain is active. "
			"Please disable the screen curtain before using image features."
		)
