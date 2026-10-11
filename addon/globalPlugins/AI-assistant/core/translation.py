"""Use NVDA's active gettext translator without importing NVDA in the worker."""
from __future__ import annotations

import builtins


def _(message: str) -> str:
	translator = getattr(builtins, "_", None)
	return translator(message) if callable(translator) else message
