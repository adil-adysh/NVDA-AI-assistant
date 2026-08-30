# -*- coding: utf-8 -*-
"""Shared bootstrap for loading sibling modules in ui package tests.

The modules under test (e.g. ``host_lifecycle.py``) are standalone files that
reference NVDA-only imports at module scope, so they cannot be imported through
the normal package machinery inside the dev interpreter.  Each test file used
to duplicate this synthetic-package loader; it lives here so the tests stay in
sync.
"""

# The synthetic-package loader is intentionally duplicated inline in the
# ui package test files so each suite can run standalone (R0801).
# pylint: disable=duplicate-code

from __future__ import annotations

import sys

from tests.support import ADDON_ROOT, load_module as load_test_module, register_package

MODULE_DIR = ADDON_ROOT / "ui"
if str(MODULE_DIR) not in sys.path:
	sys.path.insert(0, str(MODULE_DIR))

PACKAGE_NAME = "ui_testpkg"
register_package(PACKAGE_NAME, MODULE_DIR)


def load_module(module_name: str, file_name: str):
	"""Load a sibling module under the synthetic ``ui_testpkg`` namespace."""
	return load_test_module(f"{PACKAGE_NAME}.{module_name}", MODULE_DIR / file_name)
