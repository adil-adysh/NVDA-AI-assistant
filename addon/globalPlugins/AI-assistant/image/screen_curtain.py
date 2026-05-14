# -*- coding: utf-8 -*-
from __future__ import annotations


def check_screen_curtain() -> None:
	"""Raise RuntimeError if the NVDA screen curtain is active.

	Capturing images while the screen curtain is enabled produces a black
	screen, so this check prevents wasted capture attempts.
	"""
	try:
		import api

		if api.isScreenCurtainRunning():
			raise RuntimeError(
				"Screen capture is not available while the screen curtain is active. "
				"Please disable the screen curtain before using image features."
			)
	except AttributeError:
		pass  # isScreenCurtainRunning not available in this NVDA version
