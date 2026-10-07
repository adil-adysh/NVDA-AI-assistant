# -*- coding: utf-8 -*-
"""Tier 1 Pure-Python Unit Tests for Job Domain and IPC Protocol."""

from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
	sys.path.insert(0, str(_PROJECT_ROOT))
