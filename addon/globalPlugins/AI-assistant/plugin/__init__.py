# -*- coding: utf-8 -*-
from __future__ import annotations

import addonHandler

addonHandler.initTranslation()

from .application import AIAssistantApplication
from .controller import GlobalPlugin
from .types import PluginServices

__all__ = [
	"AIAssistantApplication",
	"GlobalPlugin",
	"PluginServices",
]
