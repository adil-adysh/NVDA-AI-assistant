"""Behavior tests for model enabled-state and availability filters."""
from __future__ import annotations

import pytest

from tests.support import load_addon_module


namespace = "provider_model_filter_tests"
model_types = load_addon_module("providers.model_manager", namespace=namespace)
model_filters = load_addon_module("ui.model_filters", namespace=namespace)


@pytest.mark.parametrize(
	("state", "availability_filter", "expected"),
	[
		(model_types.ModelState.READY, "available", True),
		(model_types.ModelState.DOWNLOADED, "available", True),
		(model_types.ModelState.REGISTERED, "available", True),
		(model_types.ModelState.NOT_DOWNLOADED, "not_downloaded", True),
		(model_types.ModelState.DOWNLOADING, "downloading", True),
		(model_types.ModelState.FAILED, "failed", True),
		(model_types.ModelState.READY, "not_downloaded", False),
		(model_types.ModelState.DOWNLOADED, "downloading", False),
		(model_types.ModelState.REGISTERED, "failed", False),
		(model_types.ModelState.NOT_DOWNLOADED, "available", False),
		(model_types.ModelState.DOWNLOADING, "failed", False),
		(model_types.ModelState.FAILED, "available", False),
	],
)
def test_availability_filter_groups_model_states_correctly(state, availability_filter, expected):
	assert model_filters.matches_model_filters(state, True, "all", availability_filter) is expected


@pytest.mark.parametrize(
	("enabled", "enabled_filter", "expected"),
	[
		(True, "all", True),
		(False, "all", True),
		(True, "enabled", True),
		(False, "enabled", False),
		(True, "disabled", False),
		(False, "disabled", True),
	],
)
def test_enabled_filter_matches_the_user_enabled_state(enabled, enabled_filter, expected):
	assert model_filters.matches_model_filters(
		model_types.ModelState.READY,
		enabled,
		enabled_filter,
		"all",
	) is expected


@pytest.mark.parametrize(
	("state", "enabled", "enabled_filter", "availability_filter", "expected"),
	[
		(model_types.ModelState.READY, False, "disabled", "available", True),
		(model_types.ModelState.NOT_DOWNLOADED, True, "enabled", "not_downloaded", True),
		(model_types.ModelState.DOWNLOADING, False, "disabled", "downloading", True),
		(model_types.ModelState.FAILED, True, "enabled", "available", False),
		(model_types.ModelState.DOWNLOADED, False, "enabled", "available", False),
	],
)
def test_enabled_and_availability_filters_intersect(state, enabled, enabled_filter, availability_filter, expected):
	assert model_filters.matches_model_filters(
		state,
		enabled,
		enabled_filter,
		availability_filter,
	) is expected
