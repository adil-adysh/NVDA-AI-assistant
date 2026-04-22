# -*- coding: utf-8 -*-
from __future__ import annotations

import pathlib
import sys

# Ensure the parent scripts directory is importable when running this file directly.
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from build_host import main  # noqa: E402

if __name__ == "__main__":
	raise SystemExit(main())
