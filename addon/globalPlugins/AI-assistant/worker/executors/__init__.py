# -*- coding: utf-8 -*-
"""Worker task executors.

Contains out-of-process executors for heavy compute and network operations,
including streaming model and runtime downloads, streaming checksum validation,
and atomic file unpacking.
"""

from __future__ import annotations
