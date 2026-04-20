# -*- coding: utf-8 -*-
from __future__ import annotations

import api

from .candidate_base import CandidateExtractionContext


def build_extraction_context() -> CandidateExtractionContext:
	focus = _get_focus_object_safe()
	focus_tree_interceptor = getattr(focus, "treeInterceptor", None) if focus is not None else None
	focus_ancestors = _get_focus_ancestors_safe()
	navigator = _get_navigator_object_safe()
	foreground = _get_foreground_object_safe()

	app_name = None
	app_module = getattr(focus, "appModule", None) if focus is not None else None
	maybe_name = getattr(app_module, "appName", None) if app_module is not None else None
	if isinstance(maybe_name, str) and maybe_name.strip():
		app_name = maybe_name.strip().lower()
	elif foreground is not None:
		foreground_module = getattr(foreground, "appModule", None)
		maybe_name = getattr(foreground_module, "appName", None) if foreground_module is not None else None
		if isinstance(maybe_name, str) and maybe_name.strip():
			app_name = maybe_name.strip().lower()

	return CandidateExtractionContext(
		focus=focus,
		focusTreeInterceptor=focus_tree_interceptor,
		focusAncestors=focus_ancestors,
		navigator=navigator,
		foreground=foreground,
		appName=app_name,
	)


def _get_focus_object_safe() -> object | None:
	try:
		return api.getFocusObject()
	except Exception:
		return None


def _get_focus_ancestors_safe() -> tuple[object, ...]:
	try:
		ancestors = api.getFocusAncestors()
	except Exception:
		return ()
	if ancestors is None:
		return ()
	return tuple(ancestors)


def _get_navigator_object_safe() -> object | None:
	try:
		return api.getNavigatorObject()
	except Exception:
		return None


def _get_foreground_object_safe() -> object | None:
	try:
		return api.getForegroundObject()
	except Exception:
		return None
