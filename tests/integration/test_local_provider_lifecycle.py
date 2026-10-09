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
from typing import Any
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


class LocalTestShimSupervisor:
	"""Test-only supervisor double implementing the native RuntimeSupervisor protocol."""

	def __init__(self, host: str, port: int, runner: Any) -> None:
		self.host = host
		self.port = port
		url_host = f"[{self.host}]" if ":" in str(self.host) and not str(self.host).startswith("[") else self.host
		self.base_url = f"http://{url_host}:{self.port}"
		self._runner = runner
		self._process: Any = None
		self._state = "stopped"
		self._generation = 0
		self._startup_identity: str | None = None
		self._running_model: str | None = None
		self._shutdown = False
		self._lock = threading.RLock()

	def status(self) -> Any:
		with self._lock:
			is_alive = False
			pid = None
			if self._process is not None:
				is_alive = self._process.poll() is None
				pid = getattr(self._process, "pid", None)
				if not is_alive:
					self._state = "stopped"
			is_adopted = self._state == "ready_adopted"
			is_ready = is_alive or is_adopted
			return types.SimpleNamespace(
				state=self._state if is_ready else "stopped",
				is_ready=is_ready,
				is_running=is_alive,
				is_adopted=is_adopted,
				pid=pid,
				generation=self._generation,
				error_code=None,
				error_message=None,
				startup_identity=self._startup_identity,
				running_model=self._running_model,
				base_url=self.base_url,
			)

	def matches_startup_configuration(self, startup_identity: str) -> bool:
		with self._lock:
			alive = self._process is not None and self._process.poll() is None
			return alive and self._startup_identity == startup_identity

	def ensure_ready(
		self,
		executable: str,
		args: list[str],
		env: dict[str, str],
		startup_identity: str,
		running_model: str | None = None,
		timeout_seconds: float | None = None,
	) -> Any:
		del timeout_seconds
		with self._lock:
			if self._shutdown:
				raise RuntimeError("Server supervisor has been shut down.")
			if self._process is not None:
				if self._process.poll() is not None:
					self._process = None
					self._state = "stopped"
					self._startup_identity = None
				elif self._startup_identity == startup_identity:
					return self.status()
				else:
					if hasattr(self._process, "terminate"):
						try:
							self._process.terminate()
						except Exception:
							pass
					self._process = None

			is_litert = len(args) > 2 and args[:2] == ["-m", "litert_lm_cli.main"]
			if is_litert:
				serve_args = args[2:]
				cmd_or_path = Path(executable)
				runner_args = (cmd_or_path, serve_args)
				exit_msg = "Server process exited unexpectedly."
			else:
				command = [executable, *args]
				runner_args = (command,)
				exit_msg = "Server process exited before becoming ready."

			try:
				proc = self._runner(*runner_args, env=env)
				if self._shutdown:
					if hasattr(proc, "terminate"):
						try:
							proc.terminate()
						except Exception:
							pass
					self._state = "stopped"
					return self.status()

				if hasattr(proc, "poll") and proc.poll() is not None:
					self._state = "failed"
					self._startup_identity = None
					self._generation += 1
					raise RuntimeError(exit_msg)

				self._process = proc
				self._state = "ready_owned"
				self._startup_identity = startup_identity
				self._running_model = running_model
				self._generation += 1
				return self.status()
			except Exception as exc:
				self._state = "failed"
				self._startup_identity = None
				self._generation += 1
				if isinstance(exc, RuntimeError) and (
					"exited unexpectedly" in str(exc) or "exited before becoming ready" in str(exc)
				):
					raise
				raise RuntimeError(f"Failed to start server: {exc}") from exc

	def restart(
		self,
		executable: str,
		args: list[str],
		env: dict[str, str],
		startup_identity: str,
		running_model: str | None = None,
		timeout_seconds: float | None = None,
	) -> Any:
		self.stop()
		return self.ensure_ready(
			executable,
			args,
			env,
			startup_identity,
			running_model=running_model,
			timeout_seconds=timeout_seconds,
		)

	def stop(self, timeout_seconds: float | None = None) -> Any:
		with self._lock:
			if self._process is not None:
				if hasattr(self._process, "terminate"):
					try:
						self._process.terminate()
						if hasattr(self._process, "wait"):
							self._process.wait(timeout=timeout_seconds)
					except Exception:
						pass
				self._process = None
			self._state = "stopped"
			self._startup_identity = None
			self._running_model = None
			self._generation += 1
			return self.status()

	def shutdown(self) -> None:
		with self._lock:
			self._shutdown = True
			self.stop()

	def adopt(self, model_id: str | None = None) -> Any:
		with self._lock:
			alive = self._process is not None and self._process.poll() is None
			if alive:
				return self.status()
			self._state = "ready_adopted"
			self._startup_identity = None
			self._running_model = model_id
			self._generation += 1
			return self.status()


def _llama_supervisor(
	factory: ProcessFactoryRecorder | None = None,
	*,
	host: str = "127.0.0.1",
	port: int = 8080,
	**kwargs: Any,
) -> Any:
	native = LocalTestShimSupervisor(host, port, factory) if factory is not None else None
	return LLAMA.LlamaServerSupervisor(
		host=host,
		port=port,
		native_supervisor=native,
		**kwargs,
	)


def test_llama_concurrent_requests_share_single_startup() -> None:
	factory = ProcessFactoryRecorder(block_first=True)
	supervisor = _llama_supervisor(factory)
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
	supervisor = _llama_supervisor(factory)

	with pytest.raises(LLAMA.LlamaServerError):
		supervisor.start("C:/models/a.gguf", model_id="a")
	supervisor.start("C:/models/a.gguf", model_id="a")

	assert len(factory.calls) == 2
	assert supervisor.is_running


def test_llama_dead_cached_process_is_not_reused() -> None:
	factory = ProcessFactoryRecorder()
	supervisor = _llama_supervisor(factory)
	supervisor.start("C:/models/a.gguf", model_id="a")
	factory.processes[0].crash()

	supervisor.start("C:/models/a.gguf", model_id="a")

	assert len(factory.calls) == 2
	assert supervisor.is_running


def test_llama_process_exit_before_ready_allows_retry() -> None:
	factory = ProcessFactoryRecorder()
	supervisor = _llama_supervisor(factory)
	supervisor.start("C:/models/a.gguf", model_id="a")
	factory.processes[0].crash()

	with pytest.raises(LLAMA.LlamaServerError, match="exited before becoming ready"):
		supervisor.wait_until_ready(timeout=0.01)
	supervisor.start("C:/models/a.gguf", model_id="a")

	assert len(factory.calls) == 2
	assert supervisor.is_running


def test_llama_readiness_timeout_stops_process_and_allows_retry(monkeypatch) -> None:
	factory = ProcessFactoryRecorder()
	supervisor = _llama_supervisor(factory)
	monkeypatch.setattr(supervisor, "is_healthy", lambda _timeout=2.0: False)
	monkeypatch.setattr(LLAMA, "POLL_INTERVAL", 0.0)
	supervisor.start("C:/models/a.gguf", model_id="a")

	assert not supervisor.wait_until_ready(timeout=0.001)
	assert factory.processes[0].terminated
	supervisor.start("C:/models/a.gguf", model_id="a")
	assert len(factory.calls) == 2


def test_llama_startup_configuration_change_replaces_running_server() -> None:
	factory = ProcessFactoryRecorder()
	supervisor = _llama_supervisor(factory)
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
	supervisor = _llama_supervisor(factory)
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
	supervisor = _llama_supervisor(factory)
	supervisor.start("C:/models/a.gguf", model_id="a", context=4096)

	request_options.update(temperature=1.1, top_p=0.95)
	supervisor.start("C:/models/a.gguf", model_id="a", context=4096)

	assert request_options["temperature"] == 1.1
	assert len(factory.calls) == 1


def test_llama_shutdown_during_startup_cannot_leave_ready_runtime() -> None:
	factory = ProcessFactoryRecorder(block_first=True)
	supervisor = _llama_supervisor(factory)
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
	supervisor = _llama_supervisor(factory)
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


def _litert_supervisor(
	tmp_path: Path,
	config: dict[str, object],
	factory: ProcessFactoryRecorder | None = None,
	*,
	endpoint_provider: Any = None,
):
	native = LocalTestShimSupervisor("127.0.0.1", 9379, factory) if factory is not None else None
	kwargs: dict[str, Any] = {
		"config_provider": lambda: config,
		"native_supervisor": native,
	}
	if endpoint_provider is not None:
		kwargs["endpoint_provider"] = endpoint_provider
	supervisor = LITERT.LiteRTServerSupervisor(**kwargs)
	supervisor._server_dir = lambda: Path("C:/fake/runtime")  # noqa: SLF001
	supervisor._server_python = lambda: Path("C:/fake/runtime/python.exe")  # noqa: SLF001
	supervisor._litert_dir = lambda: tmp_path  # noqa: SLF001
	return supervisor


def test_litert_concurrent_requests_share_single_initialization(tmp_path: Path) -> None:
	config = {"default": {"max_num_tokens": 4096}}
	factory = ProcessFactoryRecorder(block_first=True)
	supervisor = _litert_supervisor(tmp_path, config, factory)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path):
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
	factory = ProcessFactoryRecorder(fail_first=True)
	supervisor = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}}, factory)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path):
		with pytest.raises(LITERT.LiteRTServerError):
			supervisor.start()
		supervisor.start()

	assert len(factory.calls) == 2
	assert supervisor.is_running


def test_litert_dead_cached_process_is_not_reused(tmp_path: Path) -> None:
	factory = ProcessFactoryRecorder()
	supervisor = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}}, factory)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path):
		supervisor.start()
		factory.processes[0].crash()
		supervisor.start()

	assert len(factory.calls) == 2
	assert supervisor.is_running


def test_litert_process_exit_before_ready_allows_retry(tmp_path: Path) -> None:
	factory = ProcessFactoryRecorder()
	supervisor = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}}, factory)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path):
		supervisor.start()
		factory.processes[0].crash()
		with pytest.raises(LITERT.LiteRTServerError, match="exited unexpectedly"):
			supervisor.wait_until_ready(timeout=0.01)
		supervisor.start()

	assert len(factory.calls) == 2
	assert supervisor.is_running


def test_litert_startup_configuration_change_replaces_running_runtime(tmp_path: Path) -> None:
	config = {"default": {"backend": "cpu", "max_num_tokens": 4096}}
	factory = ProcessFactoryRecorder()
	supervisor = _litert_supervisor(tmp_path, config, factory)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path):
		supervisor.start()
		first = factory.processes[0]
		config["default"] = {"backend": "gpu", "max_num_tokens": 8192}
		supervisor.start()

	assert len(factory.calls) == 2
	assert first.terminated


def test_litert_endpoint_change_replaces_running_runtime(tmp_path: Path) -> None:
	endpoint = ["http://127.0.0.1:9379"]
	factory = ProcessFactoryRecorder()
	supervisor = _litert_supervisor(
		tmp_path,
		{"default": {"backend": "cpu"}},
		factory,
		endpoint_provider=lambda: endpoint[0],
	)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path):
		supervisor.start()
		endpoint[0] = "http://127.0.0.1:9555"
		supervisor.start()

	assert len(factory.calls) == 2
	assert factory.processes[0].terminated
	assert factory.calls[1][-1] == "9555"


def test_litert_request_model_change_reuses_shared_server(tmp_path: Path) -> None:
	active_model = ["model-a"]
	factory = ProcessFactoryRecorder()
	supervisor = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}}, factory)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path):
		supervisor.start()
		active_model[0] = "model-b"
		supervisor.start()

	assert active_model[0] == "model-b"
	assert len(factory.calls) == 1


def test_litert_late_initialization_cannot_overwrite_new_configuration(tmp_path: Path) -> None:
	config = {"default": {"backend": "cpu"}}
	factory = ProcessFactoryRecorder(block_first=True)
	supervisor = _litert_supervisor(tmp_path, config, factory)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path):
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
	factory = ProcessFactoryRecorder(block_first=True)
	supervisor = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}}, factory)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path):
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
			supervisor = _litert_supervisor(tmp_path, config, factory)
			assert not supervisor.is_running
			supervisor.start()

	assert [len(factory.calls) for factory in factories] == [1, 1]


def test_provider_runtime_caches_are_isolated(tmp_path: Path) -> None:
	llama_factory = ProcessFactoryRecorder()
	llama = _llama_supervisor(llama_factory)
	litert_factory = ProcessFactoryRecorder()
	litert = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}}, litert_factory)

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path):
		llama.start("C:/models/a.gguf", model_id="a")
		litert.start()
		llama.start("C:/models/a.gguf", model_id="a")

	assert len(llama_factory.calls) == 1
	assert len(litert_factory.calls) == 1
	assert llama.is_running and litert.is_running


def test_switching_from_llama_to_litert_during_startup_keeps_state_isolated(tmp_path: Path) -> None:
	llama_factory = ProcessFactoryRecorder(block_first=True)
	llama = _llama_supervisor(llama_factory)
	litert_factory = ProcessFactoryRecorder()
	litert = _litert_supervisor(tmp_path, {"default": {"backend": "cpu"}}, litert_factory)
	llama_thread = threading.Thread(target=lambda: llama.start("a.gguf", model_id="a"))

	with mock.patch.object(LITERT, "_resolve_litert_python", side_effect=lambda path: path):
		llama_thread.start()
		assert llama_factory.entered.wait(1)
		litert.start()
		assert litert.is_running
		llama_factory.release.set()
		llama_thread.join(2)

	assert llama.is_running
	assert len(llama_factory.calls) == len(litert_factory.calls) == 1
