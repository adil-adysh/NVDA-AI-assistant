# -*- coding: utf-8 -*-
"""Runtime path resolution for on-demand backends.

All runtimes are stored under:
    %APPDATA%/nvda/AIAssistant/runtimes/
"""

from __future__ import annotations

import os
from pathlib import Path


def get_runtime_dir() -> Path:
	"""Return the root directory for downloaded runtimes.

	Resolves to: %APPDATA%/nvda/AIAssistant/runtimes/
	"""
	appdata = os.getenv("APPDATA")
	base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
	return base / "nvda" / "AIAssistant" / "runtimes"


def get_runtime_path(runtime_type: str, version: str) -> Path:
	"""Return the path for a specific runtime version.

	Example: %APPDATA%/nvda/AIAssistant/runtimes/litert-lm/0.15.0/
	"""
	return get_runtime_dir() / runtime_type / version
