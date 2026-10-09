"""Shutdown behavior for plugin-owned background work."""

from __future__ import annotations

import ast
import sys
import threading
import time
from types import SimpleNamespace
import types

from tests.support import ADDON_ROOT, load_module, register_package


NAMESPACE = "background_shutdown_testpkg"
register_package(NAMESPACE, ADDON_ROOT)
register_package(f"{NAMESPACE}.plugin", ADDON_ROOT / "plugin")
for package_name in ("config", "providers", "providers.runtime", "service", "ui", "use_case"):
	register_package(f"{NAMESPACE}.{package_name}", ADDON_ROOT.joinpath(*package_name.split(".")))


def _stub(relative_name: str, **attributes: object) -> types.ModuleType:
	module = types.ModuleType(f"{NAMESPACE}.{relative_name}")
	for name, value in attributes.items():
		setattr(module, name, value)
	sys.modules[module.__name__] = module
	return module


class _ProviderConfigurationError(Exception):
	pass


class _LiteRTServerError(Exception):
	pass


_stub(
	"providers.interfaces",
	LLMProviderError=RuntimeError,
	ProviderConfigurationError=_ProviderConfigurationError,
)
_stub(
	"providers.runtime.server",
	LiteRTServerError=_LiteRTServerError,
	get_litert_supervisor=lambda: SimpleNamespace(),
)
_stub("providers.runtime.llama_server", shutdown_llama_servers=lambda: None)
_stub("providers.llama_manager", LlamaCppModelManager=object)
_stub(
	"service.error_reporter",
	ErrorContext=lambda **kwargs: kwargs,
	error_reporter=SimpleNamespace(report=lambda *_args, **_kwargs: None),
)
_stub("service.llm", LLMService=object)
_stub(
	"service.provider_readiness",
	ProviderReadinessService=lambda: SimpleNamespace(),
	get_provider_display_name=str,
)
_stub("config.settings", get_provider=lambda: "none", get_model_name=lambda: "")
_stub(
	"config.state",
	subscribe_litert_server_config_change=lambda _callback: None,
	subscribe_llama_server_config_change=lambda _callback: None,
)
nvda_ui = _stub("ui.nvda_ui", queue=lambda *_args: None, message=lambda *_args: None)
_stub("ui.session_state", build_provider_status_message=lambda *_args: "")
_stub("use_case.engine", UseCaseEngine=object)
_stub(
	"use_case.types",
	ATTACH_FOCUSED_IMAGE_TO_CHAT="attach-focused",
	OPEN_CHAT="open-chat",
	OPEN_CHAT_WITH_PAGE_CONTENT="open-page-chat",
	OPEN_CHAT_WITH_SCREENSHOT="open-screenshot-chat",
	UseCaseId=str,
)
background = load_module(
	f"{NAMESPACE}.plugin.background",
	ADDON_ROOT / "plugin" / "background.py",
)


class _BlockingEngine:
	def __init__(self) -> None:
		self.started = threading.Event()
		self.release = threading.Event()
		self.calls = 0

	def execute(self, _use_case_id, progress=None):
		self.calls += 1
		self.started.set()
		assert self.release.wait(timeout=2)
		return SimpleNamespace(message="done")


def _runner(engine: _BlockingEngine):
	return background.BackgroundTaskRunner(
		llm_service=SimpleNamespace(),
		use_case_engine=engine,
		progress_handler=lambda _event: None,
		readiness_service=SimpleNamespace(),
	)


def test_close_suppresses_late_result_delivery(monkeypatch) -> None:
	engine = _BlockingEngine()
	runner = _runner(engine)
	queued: list[tuple[object, ...]] = []
	monkeypatch.setattr(background.nvda_ui, "queue", lambda *args: queued.append(args))

	runner.run_use_case_in_background(background.OPEN_CHAT, "Chat", lambda _result: None)
	assert engine.started.wait(timeout=2)
	runner.close()
	engine.release.set()

	for _ in range(100):
		with runner._threads_lock:
			if not runner._threads:
				break
		time.sleep(0.01)
	assert queued == []


def test_close_rejects_new_background_work() -> None:
	engine = _BlockingEngine()
	runner = _runner(engine)
	runner.close()

	runner.run_use_case_in_background(background.OPEN_CHAT, "Chat", lambda _result: None)

	assert engine.calls == 0
	with runner._threads_lock:
		assert not runner._threads


def test_preload_readiness_failure_is_reported_without_unbound_state(monkeypatch) -> None:
	reported: list[BaseException] = []
	monkeypatch.setattr(
		background,
		"error_reporter",
		SimpleNamespace(report=lambda error, *_args, **_kwargs: reported.append(error)),
	)
	engine = _BlockingEngine()
	runner = background.BackgroundTaskRunner(
		llm_service=SimpleNamespace(),
		use_case_engine=engine,
		progress_handler=lambda _event: None,
		readiness_service=SimpleNamespace(
			evaluate_active=lambda: (_ for _ in ()).throw(RuntimeError("readiness failed"))
		),
	)

	runner.start_model_preload()
	for _ in range(100):
		with runner._threads_lock:
			if not runner._threads:
				break
		time.sleep(0.01)

	assert len(reported) == 1
	assert str(reported[0]) == "readiness failed"


def test_application_terminate_closes_background_runner_first() -> None:
	application_path = ADDON_ROOT / "plugin" / "application.py"
	tree = ast.parse(application_path.read_text(encoding="utf-8"))
	application = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AIAssistantApplication")
	terminate = next(node for node in application.body if isinstance(node, ast.FunctionDef) and node.name == "terminate")
	calls = [
		ast.unparse(node.func)
		for node in ast.walk(terminate)
		if isinstance(node, ast.Call)
	]
	assert "self.background.close" in calls
	assert calls.index("self.background.close") < calls.index("self._services.provider.close")


def test_application_terminate_has_no_runtime_shutdown_threads() -> None:
	"""Verify AIAssistantApplication.terminate does not spawn unmanaged daemon threads."""
	application_path = ADDON_ROOT / "plugin" / "application.py"
	tree = ast.parse(application_path.read_text(encoding="utf-8"))
	application = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AIAssistantApplication")
	terminate = next(node for node in application.body if isinstance(node, ast.FunctionDef) and node.name == "terminate")
	thread_names = [
		keyword.value.value
		for node in ast.walk(terminate)
		if isinstance(node, ast.Call) and ast.unparse(node.func) == "threading.Thread"
		for keyword in node.keywords
		if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)
	]
	assert "LiteRTServerShutdown" not in thread_names
	assert "LlamaServerShutdown" not in thread_names


def test_application_initialization_schedules_active_local_provider_start() -> None:
	application_path = ADDON_ROOT / "plugin" / "application.py"
	tree = ast.parse(application_path.read_text(encoding="utf-8"))
	application = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AIAssistantApplication")
	initializer = next(node for node in application.body if isinstance(node, ast.FunctionDef) and node.name == "__init__")
	calls = [
		ast.unparse(node.func)
		for node in ast.walk(initializer)
		if isinstance(node, ast.Call)
	]
	assert "self._auto_start_active_local_provider" in calls


def test_stale_healthy_litert_runtime_is_replaced_before_use(monkeypatch) -> None:
	events: list[str] = []

	class Supervisor:
		is_running = True
		is_adopted = False
		is_installed = True
		base_url = "http://127.0.0.1:9379"

		def is_healthy(self) -> bool:
			return True

		def matches_current_configuration(self) -> bool:
			return False

		def stop(self) -> None:
			events.append("stop-stale")
			self.is_running = False

		def start(self, *, on_progress=None) -> None:
			del on_progress
			events.append("start-current")
			self.is_running = True

		def wait_until_ready(self, **_kwargs) -> bool:
			events.append("ready")
			return True

	supervisor = Supervisor()
	monkeypatch.setattr(background, "get_provider", lambda: "litert-lm")
	monkeypatch.setattr(background, "get_litert_supervisor", lambda: supervisor)
	monkeypatch.setattr(
		background,
		"_ensure_model_imported",
		lambda _supervisor, on_progress=None: events.append("model"),
	)

	background.ensure_litert_server_ready()

	assert events == ["stop-stale", "start-current", "ready", "model"]
