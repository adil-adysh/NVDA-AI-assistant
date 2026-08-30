"""Shared pytest bootstrap for the sibling NVDA source checkout."""

from __future__ import annotations

import builtins
import gettext
import os
import subprocess
import sys
import tempfile
import tomllib
import warnings
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent
NVDA_ROOT = PROJECT_ROOT.parent / "nvda"
NVDA_SOURCE = NVDA_ROOT / "source"
NVDA_MISC_DEPS = NVDA_ROOT / "miscDeps" / "python"
NVDA_VENV_SITE_PACKAGES = NVDA_ROOT / ".venv" / "Lib" / "site-packages"

with (PROJECT_ROOT / "nvda-source.toml").open("rb") as pin_file:
	NVDA_REVISION = tomllib.load(pin_file)["nvda"]["revision"]

if not (NVDA_SOURCE / "api.py").is_file():
	raise pytest.UsageError(
		"NVDA source checkout was not found at ../nvda. "
		"Clone https://github.com/nvaccess/nvda.git beside NVDA-AI-assistant.",
	)

revision = subprocess.run(
	["git", "rev-parse", "HEAD"],
	cwd=NVDA_ROOT,
	check=True,
	capture_output=True,
	text=True,
).stdout.strip()
if revision != NVDA_REVISION:
	message = (
		f"Sibling NVDA checkout is at {revision}, but this project is tested against "
		f"{NVDA_REVISION}. Run: git -C ../nvda checkout {NVDA_REVISION}"
	)
	if os.environ.get("CI"):
		raise pytest.UsageError(message)
	warnings.warn(message, stacklevel=1)

for path in reversed((NVDA_SOURCE, NVDA_MISC_DEPS)):
	path_string = str(path)
	if path_string not in sys.path:
		sys.path.insert(0, path_string)

# The built-NVDA tier uses the sibling checkout's locked runtime environment
# for NVDA-only dependencies (for example nh3).  Append rather than prepend so
# the add-on's own locked dependencies remain authoritative for its code.
if NVDA_VENV_SITE_PACKAGES.is_dir():
	sys.path.append(str(NVDA_VENV_SITE_PACKAGES))

# A running NVDA process installs these translation functions in builtins.
# Standalone pytest has no initialized NVDA language/config runtime, so use
# gettext's identity-compatible functions while retaining the real modules.
builtins._ = gettext.gettext
builtins.ngettext = gettext.ngettext
builtins.pgettext = gettext.pgettext
builtins.npgettext = gettext.npgettext

# NVDA sets this during process startup; API-definition imports consult it for
# resource paths even though the standalone suite does not launch NVDA.
import globalVars  # noqa: E402

globalVars.appDir = str(NVDA_SOURCE)
globalVars.appArgs.disableAddons = True
nvda_test_config = Path(tempfile.gettempdir()) / "nvda-ai-assistant-tests"
nvda_test_config.mkdir(parents=True, exist_ok=True)
globalVars.appArgs.configPath = str(nvda_test_config)

# Import these shared API-definition modules before pytest prepends individual
# add-on package directories.  Both NVDA and the add-on contain a top-level
# ``utils`` package; establishing NVDA's imports here prevents that name from
# being resolved to the add-on package during collection.
import controlTypes  # noqa: E402, F401
import logHandler  # noqa: E402, F401
import textInfos  # noqa: E402, F401

REAL_NVDA_MODULES = {
	"controlTypes": controlTypes,
	"logHandler": logHandler,
	"textInfos": textInfos,
}
