from types import SimpleNamespace

from tests.support.bootstrap import load_addon_module

progress = load_addon_module("core.readiness_progress", namespace="readiness_progress_tests")


def test_ready_checks_are_silent_and_startup_is_announced_once():
	messages = []
	policy = progress.ReadinessProgress(messages.append)
	policy.update(SimpleNamespace(state="ready_owned"), 0)
	assert messages == []
	policy.update(SimpleNamespace(state="starting"), 1)
	policy.update(SimpleNamespace(state="starting"), 2)
	assert messages == ["Starting local AI server…"]


def test_long_wait_reports_once_without_claiming_model_loading():
	messages = []
	policy = progress.ReadinessProgress(messages.append)
	policy.update(None, 9)
	assert messages == []
	policy.update(None, 10)
	policy.update(None, 30)
	assert messages == ["Still preparing local AI. Please wait."]


def test_observer_stops_after_operation_and_preserves_errors():
	import pytest

	messages = []
	with pytest.raises(ValueError, match="startup failed"):
		progress.run_with_readiness_progress(lambda: (_ for _ in ()).throw(ValueError("startup failed")), messages.append)
	assert messages == []


def test_observer_reports_actual_transition_while_operation_is_in_flight():
	import threading

	announced = threading.Event()
	messages = []
	def report(message):
		messages.append(message)
		announced.set()
	def operation():
		assert announced.wait(2), "startup was not observed"
		return "ready"
	assert progress.run_with_readiness_progress(operation, report, lambda: SimpleNamespace(state="starting")) == "ready"
	assert messages == ["Starting local AI server…"]
