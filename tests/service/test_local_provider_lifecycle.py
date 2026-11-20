from threading import Event, Thread
from importlib import import_module

import pytest

from tests.support import load_addon_module


module = load_addon_module("service.local_provider_lifecycle", namespace="local_lifecycle_testpkg")
selection = import_module("local_lifecycle_testpkg.core.runtime_selection")


def test_switch_stops_only_inactive_runtime_before_presentation():
	calls = []
	lifecycle = module.LocalProviderLifecycle(
		get_provider=lambda: "llama-cpp-server",
		stop_servers={"litert-lm": lambda: calls.append("stop litert"), "llama-cpp-server": lambda: calls.append("stop llama")},
	)
	lifecycle.run_selected("llama-cpp-server", lambda: calls.append("present"))
	assert calls == ["stop litert", "present"]


def test_stale_selection_and_shutdown_cannot_launch():
	calls = []
	lifecycle = module.LocalProviderLifecycle(get_provider=lambda: "openai", stop_servers={"litert-lm": lambda: calls.append("stop")})
	lifecycle.run_selected("litert-lm", lambda: calls.append("launch"))
	assert calls == []
	lifecycle.close()
	lifecycle.run_selected("openai", lambda: calls.append("present"))
	assert calls == []


@pytest.mark.parametrize("runtime,class_name", [("server", "LiteRTServerSupervisor"), ("llama_server", "LlamaServerSupervisor")])
@pytest.mark.parametrize("entrypoint", ["start", "restart", "ensure_ready", "adopt"])
def test_all_supervisor_launch_paths_reject_inactive_provider(monkeypatch, runtime, class_name, entrypoint):
	runtime_module = load_addon_module(f"providers.runtime.{runtime}", namespace="local_lifecycle_testpkg")
	supervisor = object.__new__(getattr(runtime_module, class_name))
	monkeypatch.setattr(selection, "_gate", module.RuntimeSelectionGate(lambda: "openai"))
	with pytest.raises(selection.RequestCancelled):
		getattr(supervisor, entrypoint)()


def test_runtime_launch_and_switch_share_the_same_fence(monkeypatch):
	current = "litert-lm"
	calls = []
	lifecycle = module.LocalProviderLifecycle(get_provider=lambda: current, stop_servers={"litert-lm": lambda: calls.append("stop")})
	monkeypatch.setattr(selection, "_gate", lifecycle.gate)
	@selection.runtime_launch("litert-lm")
	def late_request():
		calls.append("started")
	current = "openai"
	lifecycle.run_selected("openai", lambda: calls.append("present"))
	with pytest.raises(selection.RequestCancelled):
		late_request()
	assert calls == ["stop", "present"]
	lifecycle.close()
	lifecycle.run_selected("openai", lambda: calls.append("present"))
	assert calls == ["stop", "present"]


def test_switch_waits_for_startup_then_stops_outgoing_runtime():
	current = "litert-lm"
	started, release = Event(), Event()
	calls = []
	lifecycle = module.LocalProviderLifecycle(get_provider=lambda: current, stop_servers={"litert-lm": lambda: calls.append("stop")})
	def launch():
		started.set()
		assert release.wait(2)
		calls.append("started")
	first = Thread(target=lambda: lifecycle.run_selected("litert-lm", launch))
	first.start()
	assert started.wait(2)
	current = "openai"
	second = Thread(target=lambda: lifecycle.run_selected("openai", lambda: calls.append("present")))
	second.start()
	release.set()
	first.join(2)
	second.join(2)
	assert not first.is_alive() and not second.is_alive()
	assert calls == ["started", "stop", "present"]
