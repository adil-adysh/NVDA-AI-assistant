"""Deterministic integration tests for managed local-provider lifecycles.

These tests keep the real supervisor, startup identity, locking, and cleanup
code in the loop.  Only the OS process and network-health boundaries are
controlled, so no model download or arbitrary sleep is required.
"""
from __future__ import annotations

import sys
import threading
import types
from pathlib import Path
from unittest import mock

import pytest

from tests.support import ADDON_ROOT, load_module, register_package


PACKAGE = "local_provider_lifecycle_testpkg"
PROVIDERS = ADDON_ROOT / "providers"
RUNTIME = PROVIDERS / "runtime"


def _load_runtime_modules():
	register_package(PACKAGE, ADDON_ROOT)
	register_package(f"{PACKAGE}.providers", PROVIDERS)
	register_package(f"{PACKAGE}.providers.runtime", RUNTIME)

	interfaces = types.ModuleType(f"{PACKAGE}.providers.interfaces")
	interfaces.LLMProviderError = RuntimeError
	sys.modules[interfaces.__name__] = interfaces

	runtime_config = types.ModuleType(f"{PACKAGE}.providers.runtime.config")
	runtime_config.RuntimeConfig = object
	sys.modules[runtime_config.__name__] = runtime_config

	runtime_download = types.ModuleType(f"{PACKAGE}.providers.runtime.download")
	runtime_download.DownloadCancelledError = type("DownloadCancelledError", (Exception,), {})
	runtime_download.RuntimeDownloadService = mock.MagicMock
	sys.modules[runtime_download.__name__] = runtime_download

	runtime_paths = types.ModuleType(f"{PACKAGE}.providers.runtime.paths")
	runtime_paths.get_runtime_path = lambda *_args: Path("C:/fake/runtime")
	sys.modules[runtime_paths.__name__] = runtime_paths

	llama = load_module(
		f"{PACKAGE}.providers.runtime.llama_server",
		RUNTIME / "llama_server.py",
	)
	litert = load_module(
		f"{PACKAGE}.providers.runtime.server",
		RUNTIME / "server.py",
	)
	return llama, litert


LLAMA, LITERT = _load_runtime_modules()


class ControlledProcess:
	"""Small Popen boundary double with explicit alive/dead state."""

	_next_pid = 1000

	def __init__(self) -> None:
		type(self)._next_pid += 1
		self.pid = type(self)._next_pid
		self.alive = True
		self.terminated = False
		self.killed = False

	def poll(self) -> int | None:
		return None if self.alive else 1

	def terminate(self) -> None:
		self.terminated = True
		self.alive = False

	def kill(self) -> None:
		self.killed = True
		self.alive = False

	def wait(self, timeout: float | None = None) -> int:
		del timeout
		self.alive = False
		return 0

	def crash(self) -> None:
		self.alive = False


class ProcessFactoryRecorder:
	def __init__(self, *, block_first: bool = False, fail_first: bool = False) -> None:
		self.calls: list[list[str]] = []
		self.processes: list[ControlledProcess] = []
		self.entered = threading.Event()
		self.release = threading.Event()
		self.block_first = block_first
		self.fail_first = fail_first

	def __call__(self, command, *args, **_kwargs) -> ControlledProcess:
		# ``Popen`` receives one command list; the LiteRT CLI seam receives
		# ``python_exe, serve_args``. Record the meaningful argument vector.
		argument_vector = args[0] if args else command
		self.calls.append(list(argument_vector))
		call_number = len(self.calls)
		if call_number == 1:
			self.entered.set()
			if self.block_first:
				assert self.release.wait(2), "test did not release controlled startup"
			if self.fail_first:
				raise OSError("controlled spawn failure")
		process = ControlledProcess()
		self.processes.append(process)
		return process


def test_llama_concurrent_requests_share_single_startup() -> None:
	factory = ProcessFactoryRecorder(block_first=True)
	supervisor = LLAMA.LlamaServerSupervisor(process_factory=factory)
	errors: list[BaseException] = []

	def start() -> None:
		try:
			supervisor.start("C:/models/a.gguf", model_id="a", context=4096)
		except BaseException as error:  # pragma: no cover - assertion reports worker failures
			errors.append(error)

	threads = [threading.Thread(target=start) for _ in range(2)]
	for thread in threads:
		thread.start()
	assert factory.entered.wait(1)
	factory.release.set()
	for thread in threads:
		thread.join(2)

	assert not errors
	assert len(factory.calls) == 1
	assert supervisor.is_running


def test_llama_startup_failure_does_not_poison_next_startup() -> None:
	factory = ProcessFactoryRecorder(fail_first=True)
	supervisor = LLAMA.LlamaServerSupervisor(process_factory=factory)

	with pytest.raises(LLAMA.LlamaServerError):
		supervisor.start("C:/models/a.gguf", model_id="a")
	supervisor.start("C:/models/a.gguf", model_id="a")

	assert len(factory.calls) == 2
	assert supervisor.is_running


def test_llama_dead_cached_process_is_not_reused() -> None:
	factory = ProcessFactoryRecorder()
	supervisor = LLAMA.LlamaServerSupervisor(process_factory=factory)
	supervisor.start("C:/models/a.gguf", model_id="a")
	factory.processes[0].crash()

	supervisor.start("C:/models/a.gguf", model_id="a")

	assert len(factory.calls) == 2
	assert supervisor.is_running


def test_llama_process_exit_before_ready_allows_retry() -> None:
	factory = ProcessFactoryRecorder()
	supervisor = LLAMA.LlamaServerSupervisor(process_factory=factory)
	supervisor.start("C:/models/a.gguf", model_id="a")
	factory.processes[0].crash()

	with pytest.raises(LLAMA.LlamaServerError, match="exited before becoming ready"):
		supervisor.wait_until_ready(timeout=0.01)
	supervisor.start("C:/models/a.gguf", model_id="a")

	assert len(factory.calls) == 2
	assert supervisor.is_running


def test_llama_readiness_timeout_stops_process_and_allows_retry(monkeypatch) -> None:
	factory = ProcessFactoryRecorder()
	supervisor = LLAMA.LlamaServerSupervisor(process_factory=factory)
	monkeypatch.setattr(supervisor, "is_healthy", lambda _timeout=2.0: False)
	monkeypatch.setattr(LLAMA, "POLL_INTERVAL", 0.0)
	supervisor.start("C:/models/a.gguf", model_id="a")

	assert not supervisor.wait_until_ready(timeout=0.001)
	assert factory.processes[0].terminated
	supervisor.start("C:/models/a.gguf", model_id="a")
	assert len(factory.calls) == 2


def test_llama_startup_configuration_change_replaces_running_server() -> None:
	factory = ProcessFactoryRecorder()
	supervisor = LLAMA.LlamaServerSupervisor(process_factory=factory)
	supervisor.start("C:/models/a.gguf", model_id="a", context=4096, threads=4)
	first = factory.processes[0]

	supervisor.start("C:/models/a.gguf", model_id="a", context=8192, threads=4)

	assert len(factory.calls) == 2
	assert first.terminated
	assert "8192" in factory.calls[1]


def test_llama_router_model_change_reuses_server_but_preset_change_restarts(tmp_path: Path) -> None:
	preset = tmp_path / "models.ini"
	preset.write_text("version = 1\n[a]\nmodel = a.gguf\n[b]\nmodel = b.gguf\n", encoding="utf-8")
	factory = ProcessFactoryRecorder()
	supervisor = LLAMA.LlamaServerSupervisor(process_factory=factory)
	supervisor.start("a.gguf", model_id="a", models_preset=preset, context=4096)

	supervisor.start("b.gguf", model_id="b", models_preset=preset, context=4096)
	assert len(factory.calls) == 1

	preset.write_text("version = 1\n[a]\nmodel = changed.gguf\n", encoding="utf-8")
	supervisor.start("a.gguf", model_id="a", models_preset=preset, context=4096)
	assert len(factory.calls) == 2
	assert factory.processes[0].terminated


def test_llama_request_only_sampling_change_does_not_restart_server() -> None:
	request_options = {"temperature": 0.2, "top_p": 0.8}
	factory = ProcessFactoryRecorder()
	supervisor = LLAMA.LlamaServerSupervisor(process_factory=factory)
	supervisor.start("C:/models/a.gguf", model_id="a", context=4096)

	request_options.update(temperature=1.1, top_p=0.95)
	supervisor.start("C:/models/a.gguf", model_id="a", context=4096)

	assert request_options["temperature"] == 1.1
	assert len(factory.calls) == 1


def test_llama_shutdown_during_startup_cannot_leave_ready_runtime() -> None:
	factory = ProcessFactoryRecorder(block_first=True)
	supervisor = LLAMA.LlamaServerSupervisor(process_factory=factory)
	starter = threading.Thread(target=lambda: supervisor.start("a.gguf", model_id="a"))
	shutdown = threading.Thread(target=supervisor.shutdown)
	starter.start()
	assert factory.entered.wait(1)
	shutdown.start()
	factory.release.set()
	starter.join(2)
	shutdown.join(2)

	assert not supervisor.is_running
	assert factory.processes[0].terminated


def test_llama_late_startup_for_old_configuration_cannot_replace_new_runtime() -> None:
	factory = ProcessFactoryRecorder(block_first=True)
	supervisor = LLAMA.LlamaServerSupervisor(process_factory=factory)
	old_start = threading.Thread(
		target=lambda: supervisor.start("a.gguf", model_id="a", context=4096),
	)
	new_start = threading.Thread(
		target=lambda: supervisor.start("a.gguf", model_id="a", context=8192),
	)
	old_start.start()
	assert factory.entered.wait(1)
	new_start.start()
	factory.release.set()
	old_start.join(2)
	new_start.join(2)

	assert len(factory.calls) == 2
	assert factory.processes[0].terminated
	assert "8192" in factory.calls[1]
	assert supervisor.is_running


def test_llama_equivalent_executable_paths_share_cache_and_shutdown_evicts(tmp_path: Path) -> None:
	executable = tmp_path / "bin" / "llama-server.exe"
	executable.parent.mkdir()
	executable.touch()
	equivalent = executable.parent / ".." / "bin" / executable.name

	first = LLAMA.get_llama_supervisor(executable, "LOCALHOST", 8123)
	second = LLAMA.get_llama_supervisor(equivalent, "localhost", 8123)
	assert first is second

	LLAMA.shutdown_llama_servers()
	assert LLAMA.get_llama_supervisor(executable, "localhost", 8123) is not first


def _litert_supervisor(tmp_path: Path, config: dict[str, object]):
	supervisor = LITERT.LiteRTServerSupervisor(config_provider=lambda: config)
	supervisor._server_dir = lambda: Path("C:/fake/runtime")  # noqa: SLF001
	supervisor._server_python = lambda: Path("C:/fake/runtime/python.exe")  # noqa: SLF001
	supervisor._litert_dir = lambda: tmp_path  # noqa: SLF001
	return supervisor


def test_litert_concurrent_requests_share_single_initialization(tmp_path: Path) -> None:
	config = {"default": {"max_num_tokens": 4096}}
	supervisor = _litert_supervisor(tmp_path, config)
	factory = ProcessFactoryRecorder(block_first=True)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path), mock.patch.object(
		LITERT, "_run_litert_cli", side_effect=factory,
	):
		threads = [threading.Thread(target=supervisor.start) for _ in range(2)]
		for thread in threads:
			thread.start()
		assert factory.entered.wait(1)
		factory.release.set()
		for thread in threads:
			thread.join(2)

	assert len(factory.calls) == 1
	assert supervisor.is_running


def test_litert_initialization_failure_allows_retry(tmp_path: Path) -> None:
	supervisor = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}})
	factory = ProcessFactoryRecorder(fail_first=True)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path), mock.patch.object(
		LITERT, "_run_litert_cli", side_effect=factory,
	):
		with pytest.raises(LITERT.LiteRTServerError):
			supervisor.start()
		supervisor.start()

	assert len(factory.calls) == 2
	assert supervisor.is_running


def test_litert_dead_cached_process_is_not_reused(tmp_path: Path) -> None:
	supervisor = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}})
	factory = ProcessFactoryRecorder()

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path), mock.patch.object(
		LITERT, "_run_litert_cli", side_effect=factory,
	):
		supervisor.start()
		factory.processes[0].crash()
		supervisor.start()

	assert len(factory.calls) == 2
	assert supervisor.is_running


def test_litert_process_exit_before_ready_allows_retry(tmp_path: Path) -> None:
	supervisor = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}})
	factory = ProcessFactoryRecorder()

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path), mock.patch.object(
		LITERT, "_run_litert_cli", side_effect=factory,
	):
		supervisor.start()
		factory.processes[0].crash()
		with pytest.raises(LITERT.LiteRTServerError, match="exited unexpectedly"):
			supervisor.wait_until_ready(timeout=0.01)
		supervisor.start()

	assert len(factory.calls) == 2
	assert supervisor.is_running


def test_litert_startup_configuration_change_replaces_running_runtime(tmp_path: Path) -> None:
	config = {"default": {"backend": "cpu", "max_num_tokens": 4096}}
	supervisor = _litert_supervisor(tmp_path, config)
	factory = ProcessFactoryRecorder()

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path), mock.patch.object(
		LITERT, "_run_litert_cli", side_effect=factory,
	):
		supervisor.start()
		first = factory.processes[0]
		config["default"] = {"backend": "gpu", "max_num_tokens": 8192}
		supervisor.start()

	assert len(factory.calls) == 2
	assert first.terminated


def test_litert_endpoint_change_replaces_running_runtime(tmp_path: Path) -> None:
	endpoint = ["http://127.0.0.1:9379"]
	supervisor = LITERT.LiteRTServerSupervisor(
		config_provider=lambda: {"default": {"backend": "cpu"}},
		endpoint_provider=lambda: endpoint[0],
	)
	supervisor._server_python = lambda: Path("C:/fake/runtime/python.exe")  # noqa: SLF001
	supervisor._litert_dir = lambda: tmp_path  # noqa: SLF001
	factory = ProcessFactoryRecorder()

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path), mock.patch.object(
		LITERT, "_run_litert_cli", side_effect=factory,
	):
		supervisor.start()
		endpoint[0] = "http://127.0.0.1:9555"
		supervisor.start()

	assert len(factory.calls) == 2
	assert factory.processes[0].terminated
	assert factory.calls[1][-1] == "9555"


def test_litert_request_model_change_reuses_shared_server(tmp_path: Path) -> None:
	active_model = ["model-a"]
	supervisor = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}})
	factory = ProcessFactoryRecorder()

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path), mock.patch.object(
		LITERT, "_run_litert_cli", side_effect=factory,
	):
		supervisor.start()
		active_model[0] = "model-b"
		supervisor.start()

	assert active_model[0] == "model-b"
	assert len(factory.calls) == 1


def test_litert_late_initialization_cannot_overwrite_new_configuration(tmp_path: Path) -> None:
	config = {"default": {"backend": "cpu"}}
	supervisor = _litert_supervisor(tmp_path, config)
	factory = ProcessFactoryRecorder(block_first=True)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path), mock.patch.object(
		LITERT, "_run_litert_cli", side_effect=factory,
	):
		old_start = threading.Thread(target=supervisor.start)
		old_start.start()
		assert factory.entered.wait(1)
		config["default"] = {"backend": "gpu"}
		new_start = threading.Thread(target=supervisor.start)
		new_start.start()
		factory.release.set()
		old_start.join(2)
		new_start.join(2)

	assert len(factory.calls) == 2
	assert factory.processes[0].terminated
	assert supervisor.is_running


def test_litert_shutdown_during_initialization_cannot_publish_ready_runtime(tmp_path: Path) -> None:
	supervisor = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}})
	factory = ProcessFactoryRecorder(block_first=True)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path), mock.patch.object(
		LITERT, "_run_litert_cli", side_effect=factory,
	):
		starter = threading.Thread(target=supervisor.start)
		shutdown = threading.Thread(target=supervisor.shutdown)
		starter.start()
		assert factory.entered.wait(1)
		shutdown.start()
		factory.release.set()
		starter.join(2)
		shutdown.join(2)

	assert not supervisor.is_running
	assert factory.processes[0].terminated


def test_provider_configuration_roundtrip_does_not_restore_runtime_ready_state(tmp_path: Path) -> None:
	config = {"default": {"backend": "cpu", "max_num_tokens": 4096}}
	factories = [ProcessFactoryRecorder(), ProcessFactoryRecorder()]

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path):
		for factory in factories:
			supervisor = _litert_supervisor(tmp_path, config)
			assert not supervisor.is_running
			with mock.patch.object(LITERT, "_run_litert_cli", side_effect=factory):
				supervisor.start()

	assert [len(factory.calls) for factory in factories] == [1, 1]


def test_provider_runtime_caches_are_isolated(tmp_path: Path) -> None:
	llama_factory = ProcessFactoryRecorder()
	llama = LLAMA.LlamaServerSupervisor(process_factory=llama_factory)
	litert = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}})
	litert_factory = ProcessFactoryRecorder()

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path), mock.patch.object(
		LITERT, "_run_litert_cli", side_effect=litert_factory,
	):
		llama.start("C:/models/a.gguf", model_id="a")
		litert.start()
		llama.start("C:/models/a.gguf", model_id="a")

	assert len(llama_factory.calls) == 1
	assert len(litert_factory.calls) == 1
	assert llama.is_running and litert.is_running


def test_switching_from_llama_to_litert_during_startup_keeps_state_isolated(tmp_path: Path) -> None:
	llama_factory = ProcessFactoryRecorder(block_first=True)
	llama = LLAMA.LlamaServerSupervisor(process_factory=llama_factory)
	litert_factory = ProcessFactoryRecorder()
	litert = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}})
	llama_thread = threading.Thread(target=lambda: llama.start("a.gguf", model_id="a"))

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path), mock.patch.object(
		LITERT, "_run_litert_cli", side_effect=litert_factory,
	):
		llama_thread.start()
		assert llama_factory.entered.wait(1)
		litert.start()
		assert litert.is_running
		llama_factory.release.set()
		llama_thread.join(2)

	assert llama.is_running
	assert len(llama_factory.calls) == len(litert_factory.calls) == 1
