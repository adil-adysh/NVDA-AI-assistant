"""Smoke coverage for the real sibling NVDA API definitions."""

from __future__ import annotations

from pathlib import Path

from conftest import NVDA_ROOT, NVDA_SOURCE, PROJECT_ROOT, REAL_NVDA_MODULES


def _is_below(path: str, root: Path) -> bool:
	return Path(path).resolve().is_relative_to(root.resolve())


def test_nvda_checkout_is_discovered() -> None:
	assert NVDA_ROOT == PROJECT_ROOT.parent / "nvda"
	assert (NVDA_SOURCE / "api.py").is_file()


def test_nvda_api_definitions_come_from_sibling_checkout() -> None:
	for module in REAL_NVDA_MODULES.values():
		assert module.__file__ is not None
		assert _is_below(module.__file__, NVDA_ROOT)


def test_real_control_types_contract_is_available() -> None:
	assert REAL_NVDA_MODULES["controlTypes"].Role.BUTTON.name == "BUTTON"
	assert REAL_NVDA_MODULES["textInfos"].POSITION_ALL == "all"
