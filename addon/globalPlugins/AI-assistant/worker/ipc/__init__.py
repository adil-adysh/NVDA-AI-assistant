# -*- coding: utf-8 -*-
"""IPC package for named pipes and Win32 security attributes."""

from __future__ import annotations

from .security import build_user_only_security_attributes
from .transport import (
	NamedPipeClient,
	NamedPipeServer,
	PipeDisconnectedError,
)

__all__ = [
	"NamedPipeClient",
	"NamedPipeServer",
	"PipeDisconnectedError",
	"build_user_only_security_attributes",
]
