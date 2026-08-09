# -*- coding: utf-8 -*-
"""Shared bootstrap for loading sibling modules in ui package tests.

The modules under test (e.g. ``host_lifecycle.py``) are standalone files that
reference NVDA-only imports at module scope, so they cannot be imported through
the normal package machinery inside the dev interpreter.  Each test file used
to duplicate this synthetic-package loader; it lives here so the tests stay in
sync.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
	sys.path.insert(0, str(MODULE_DIR))

PACKAGE_NAME = "ui_testpkg"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(MODULE_DIR)]
sys.modules.setdefault(PACKAGE_NAME, package)


def load_module(module_name: str, file_name: str):
	"""Load a sibling module under the synthetic ``ui_testpkg`` namespace."""
	spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.{module_name}", MODULE_DIR / file_name)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = module
	spec.loader.exec_module(module)
	return module
