"""Shared test support for importing the hyphenated NVDA add-on package."""

from .bootstrap import ADDON_ROOT, PROJECT_ROOT, load_addon_module, load_module, register_package

__all__ = ["ADDON_ROOT", "PROJECT_ROOT", "load_addon_module", "load_module", "register_package"]
