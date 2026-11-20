"""Composable filters for enabled state and model availability."""
from __future__ import annotations

from ..providers.model_manager import ModelState


_AVAILABLE_STATES = frozenset({ModelState.READY, ModelState.DOWNLOADED, ModelState.REGISTERED})
_AVAILABILITY_STATES = {
	"available": _AVAILABLE_STATES,
	"not_downloaded": frozenset({ModelState.NOT_DOWNLOADED}),
	"downloading": frozenset({ModelState.DOWNLOADING}),
	"failed": frozenset({ModelState.FAILED}),
}


def matches_model_filters(
	state: ModelState,
	enabled: bool,
	enabled_filter: str,
	availability_filter: str,
) -> bool:
	"""Return whether a model state matches both selected filters."""
	if enabled_filter not in {"all", "enabled", "disabled"}:
		return False
	if enabled_filter == "enabled" and not enabled:
		return False
	if enabled_filter == "disabled" and enabled:
		return False

	if availability_filter == "all":
		return True
	return state in _AVAILABILITY_STATES.get(availability_filter, ())
