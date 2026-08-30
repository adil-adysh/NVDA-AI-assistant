"""Static contract tests for NVDA thread-affinity ownership."""

from __future__ import annotations

import ast

from tests.support import ADDON_ROOT


def _calls_in(function_name: str) -> set[str]:
	tree = ast.parse((ADDON_ROOT / "ui" / "nvda_ui.py").read_text(encoding="utf-8"))
	function = next(
		node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
		and node.name == function_name
	)
	return {
		ast.unparse(node.func)
		for node in ast.walk(function)
		if isinstance(node, ast.Call)
	}


def test_synchronous_nvda_calls_marshal_through_event_queue() -> None:
	assert "queueHandler.queueFunction" in _calls_in("call")


def test_asynchronous_nvda_calls_marshal_through_event_queue() -> None:
	assert "queueHandler.queueFunction" in _calls_in("queue")


def test_composition_root_routes_context_snapshots_through_nvda_ui_call() -> None:
	tree = ast.parse((ADDON_ROOT / "plugin" / "factory.py").read_text(encoding="utf-8"))
	context_pipeline_call = next(
		node
		for node in ast.walk(tree)
		if isinstance(node, ast.Call) and ast.unparse(node.func) == "ContextPipeline"
	)
	keyword_values = {keyword.arg: ast.unparse(keyword.value) for keyword in context_pipeline_call.keywords}
	assert keyword_values["main_thread_executor"] == "nvda_ui.call"


def test_provider_state_network_work_is_delegated_off_event_thread() -> None:
	tree = ast.parse((ADDON_ROOT / "plugin" / "application.py").read_text(encoding="utf-8"))
	application = next(
		node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AIAssistantApplication"
	)
	method = next(
		node
		for node in application.body
		if isinstance(node, ast.FunctionDef) and node.name == "_on_provider_state_change"
	)
	thread_call = next(
		node
		for node in ast.walk(method)
		if isinstance(node, ast.Call) and ast.unparse(node.func) == "threading.Thread"
	)
	keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in thread_call.keywords}
	assert keywords["target"] == "self._handle_provider_state_change"
	assert keywords["daemon"] == "True"
	assert any(
		isinstance(node, ast.Call) and ast.unparse(node.func).endswith(".start")
		for node in ast.walk(method)
	)
