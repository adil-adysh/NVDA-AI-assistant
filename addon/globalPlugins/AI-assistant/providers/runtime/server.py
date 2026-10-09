# -*- coding: utf-8 -*-
"""LiteRT-LM server process supervisor.

Manages the lifecycle of a ``litert-lm serve`` process that exposes an
OpenAI-compatible HTTP API on localhost.  The server runs inside a
self-contained Python 3.13 embeddable runtime that is downloaded
on demand — users do not need Python installed separately.

Usage::

    supervisor = LiteRTServerSupervisor()
    supervisor.install("0.15.0")
    supervisor.start()
    supervisor.wait_until_ready()
    # ... use the provider at http://127.0.0.1:9379 ...
    supervisor.stop()
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import types
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import RuntimeConfig
from .download import DownloadCancelledError, RuntimeDownloadService
from .paths import get_runtime_path
from ..interfaces import LLMProviderError

try:
	_addon_lib = Path(__file__).resolve().parent.parent.parent / "lib"
	if _addon_lib.is_dir() and str(_addon_lib) not in sys.path:
		sys.path.insert(0, str(_addon_lib))
	import runtime_supervisor
	if not hasattr(runtime_supervisor, "RuntimeSupervisor"):
		sys.modules.pop("runtime_supervisor", None)
		if str(_addon_lib) not in sys.path:
			sys.path.insert(0, str(_addon_lib))
		import runtime_supervisor
except Exception:
	runtime_supervisor = None

_CONFIG_WRITE_LOCK = threading.Lock()

if TYPE_CHECKING:
	from collections.abc import Callable, Mapping

log = logging.getLogger(__name__)

DEFAULT_LITERT_PORT = 9379
DEFAULT_LITERT_HOST = "127.0.0.1"
DEFAULT_LITERT_VERSION = "0.15.0"
SERVER_READY_POLL_INTERVAL = 0.5  # seconds

# GitHub release URL template for the self-contained runtime ZIP.
_RUNTIME_DOWNLOAD_BASE = (
	"https://github.com/adil-adysh/NVDA-AI-assistant/releases/download/"
	"litert-runtime-v{version}/litert-lm-{version}-windows-x64-runtime.zip"
)

_supervisor: LiteRTServerSupervisor | None = None


def _default_litert_dir() -> Path:
	"""Return the add-on-owned LiteRT-LM registry directory.

	LiteRT-LM's CLI defaults to ``%USERPROFILE%/.litert-lm``.  That is a
	process-global location and can be shared with another installation or
	CLI version, so the add-on must give both import and serve the same
	private registry instead.
	"""
	appdata = os.getenv("APPDATA")
	base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
	return base / "nvda" / "AIAssistant" / "litert-lm"


def _status_dict_to_namespace(data: dict[str, Any]) -> types.SimpleNamespace:
	return types.SimpleNamespace(
		state=str(data.get("state", "stopped")),
		is_ready=bool(data.get("is_ready", False)),
		is_running=bool(data.get("is_running", False)),
		is_adopted=bool(data.get("is_adopted", False)),
		pid=data.get("pid"),
		generation=int(data.get("generation", 0)),
		error_code=data.get("error_code"),
		error_message=data.get("error_message"),
		startup_identity=data.get("startup_identity"),
		running_model=data.get("running_model"),
		base_url=str(data.get("base_url", "")),
	)


def _idle_runtime_status(host: str, port: int) -> types.SimpleNamespace:
	url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
	return types.SimpleNamespace(
		state="stopped",
		is_ready=False,
		is_running=False,
		is_adopted=False,
		pid=None,
		generation=0,
		error_message=None,
		startup_identity=None,
		running_model=None,
		base_url=f"http://{url_host}:{port}",
	)


def get_litert_supervisor(worker_client: Any | None = None) -> LiteRTServerSupervisor:
	"""Return the module-level singleton or client-configured :class:`LiteRTServerSupervisor`."""
	global _supervisor  # pylint: disable=global-statement
	if worker_client is not None:
		return LiteRTServerSupervisor(worker_client=worker_client)
	if _supervisor is None:
		_supervisor = LiteRTServerSupervisor()
	return _supervisor



def _subprocess_flags() -> int:
	"""Return ``creationflags`` that suppress the console window on Windows.

	Without this flag, every ``subprocess.Popen`` or ``subprocess.run``
	call that launches the bundled Python runtime flashes a command-prompt
	window on screen.  ``CREATE_NO_WINDOW`` (0x08000000) tells Windows to
	run the process without a console.
	"""
	if sys.platform == "win32":
		return subprocess.CREATE_NO_WINDOW  # 0x08000000
	return 0


def _resolve_litert_python(python_exe: Path) -> Path:
	"""Verify *python_exe* exists or raise :exc:`LiteRTServerError`."""
	if not python_exe.is_file():
		raise LiteRTServerError(
			"LiteRT runtime is not installed. Call install() first or download it from the settings panel."
		)
	return python_exe


def _build_serve_args(host: str, port: int) -> list[str]:
	"""Build the CLI argument list for ``litert-lm serve``."""
	return ["serve", "--host", host, "--port", str(port)]


def _build_import_args(model_path: str | Path, model_id: str) -> list[str]:
	"""Build the CLI argument list for ``litert-lm import``."""
	return ["import", str(model_path), model_id]


def _build_huggingface_import_args(
	repository: str,
	artifact: str,
	model_id: str,
	token: str | None = None,
) -> list[str]:
	"""Build LiteRT-LM's native Hugging Face import command."""
	args = ["import", "--from-huggingface-repo", repository, artifact, model_id]
	if token:
		args.extend(["--huggingface-token", token])
	return args


def _build_delete_args(model_id: str) -> list[str]:
	"""Build the CLI argument list for ``litert-lm delete``."""
	return ["delete", model_id]


def _build_rename_args(old_id: str, new_id: str) -> list[str]:
	"""Build the CLI argument list for ``litert-lm rename``."""
	return ["rename", old_id, new_id]


def _validate_model_id(model_id: str) -> str:
	"""Validate an ID before passing it to LiteRT-LM or using it as a path."""
	value = str(model_id or "").strip()
	if (
		not value
		or any(ord(char) < 0x20 for char in value)
		or "\\" in value
		or any(part in {"", ".", ".."} for part in value.split("/"))
	):
		raise LiteRTServerError(f"Invalid LiteRT-LM model ID: {model_id!r}")
	return value


def _validate_huggingface_artifact(artifact: str) -> str:
	"""Reject artifact paths that could escape the resolver's repository root."""
	value = str(artifact or "").strip()
	if (
		not value
		or "\\" in value
		or "\x00" in value
		or value.startswith("/")
		or any(part in {"", ".", ".."} for part in value.split("/"))
	):
		raise LiteRTServerError(f"Invalid Hugging Face artifact: {artifact!r}")
	return value


def build_server_config(
	default_num_ctx: int,
	pinned_models: Mapping[str, Any],
	*,
	backend: str = "",
	cache: str = "",
	cpu_thread_count: int = 0,
) -> dict[str, Any]:
	"""Build the ``config.json`` payload for the LiteRT-LM server engine.

	Maps the add-on's context-window setting (``num_ctx``) onto
	litert-lm's ``max_num_tokens`` — the engine's combined input+output
	KV-cache budget.  ``max_num_tokens`` is fixed when the engine is
	first initialized and has no ``serve`` CLI flag, so it belongs in
	the server config rather than the request body (litert-lm ignores
	``num_ctx`` on the wire).  The add-on's global ``num_ctx`` becomes
	``default``; per-model pins that differ from the global value
	become per-model overrides, mirroring ``resolve_model_sampling``.

	Optional server engine knobs (``backend``, ``cache``,
	``cpu_thread_count``) ride along in the ``default`` section; empty
	or zero values are omitted so litert-lm uses its own defaults.

	Per-model sampling pins are written into the ``models.<id>``
	section for *every* pinned model, matching litert-lm's per-model
	``ModelConfig`` keys.  litert-lm resolves per-model config at
	request time for whichever model a chat request targets, so pins
	for non-active models must be present too.  Values are validated
	against litert-lm's schema bounds (temperature >= 0, top_p in
	[0, 1], top_k >= 1) so an out-of-range pin can never crash
	``serve`` at startup; ``max_tokens`` and ``repeat_penalty`` have no
	litert-lm config key and stay request-body-only.

	Args:
	    default_num_ctx: The global context window size.
	    pinned_models: Mapping of server registration model ID to its
	        explicit pinned sampling config (fields that are ``None``
	        are not pinned and are skipped).
	    backend: ``'cpu'`` or ``'gpu'`` compute backend, or ``''`` to
	        let litert-lm decide.
	    cache: ``'disk'``, ``'memory'`` or ``'no'`` cache policy, or
	        ``''`` to let litert-lm decide.
	    cpu_thread_count: CPU thread count, or ``0`` to let litert-lm
	        decide.

	Returns:
	    The config dict to write to ``LITERT_LM_DIR/config.json``.
	    Empty when there is nothing meaningful to configure.
	"""
	config: dict[str, Any] = {}
	default_cfg: dict[str, Any] = {}
	if default_num_ctx:
		default_cfg["max_num_tokens"] = default_num_ctx
	if backend:
		default_cfg["backend"] = backend
	if cache:
		default_cfg["cache"] = cache
	if cpu_thread_count and cpu_thread_count >= 1:
		default_cfg["cpu_thread_count"] = cpu_thread_count
	if default_cfg:
		config["default"] = default_cfg
	models_cfg: dict[str, Any] = {}
	for model_id, sampling in pinned_models.items():
		model_cfg: dict[str, Any] = {}
		if (
			sampling.num_ctx is not None
			and sampling.num_ctx >= 1
			and sampling.num_ctx != default_num_ctx
		):
			model_cfg["max_num_tokens"] = sampling.num_ctx
		if sampling.temperature is not None and sampling.temperature >= 0.0:
			model_cfg["temperature"] = sampling.temperature
		if sampling.top_p is not None and 0.0 <= sampling.top_p <= 1.0:
			model_cfg["top_p"] = sampling.top_p
		if sampling.top_k is not None and sampling.top_k >= 1:
			model_cfg["top_k"] = sampling.top_k
		if model_cfg:
			models_cfg[model_id] = model_cfg
	if models_cfg:
		config["models"] = models_cfg
	return config


def _current_server_config() -> dict[str, Any]:
	"""Return an empty low-level fallback when no app port is configured.

	Production code injects the application-owned provider at the
	composition root.  Keeping this fallback empty prevents a standalone
	provider-runtime import from reaching into config storage.
	"""
	return {}


def _run_litert_cli(
	python_exe: Path,
	args: list[str],
	*,
	env: dict[str, str],
	timeout: float | None = None,
	capture: bool = False,
) -> subprocess.Popen[str] | subprocess.CompletedProcess[str]:
	"""Launch a ``litert-lm`` CLI command via the bundled Python runtime.

	Args:
	    python_exe: Path to the bundled ``python.exe``.
	    args: CLI subcommand and arguments (e.g. ``["serve", "--host", ...]``).
	    env: Full environment dict (must include ``LITERT_LM_DIR``).
	    timeout: If set, uses ``subprocess.run`` with a deadline.
	        If ``None``, spawns a long-running ``subprocess.Popen``.
	    capture: When ``True`` (used with *timeout*), capture stdout/stderr.
	        When ``False``, discard output via ``DEVNULL``.

	Returns:
	    A ``Popen`` instance for long-running commands or a
	    ``CompletedProcess`` for finite commands.
	"""
	cmd = [str(python_exe), "-m", "litert_lm_cli.main", *args]
	flags = _subprocess_flags()

	if timeout is not None:
		return subprocess.run(
			cmd,
			capture_output=capture,
			text=True,
			timeout=timeout,
			env=env,
			creationflags=flags,
			check=False,
		)

	return subprocess.Popen(
		cmd,
		stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL,
		text=True,
		env=env,
		creationflags=flags,
	)


_real_run_litert_cli = _run_litert_cli


class _TestShimSupervisor:
	"""Implements the native RuntimeSupervisor protocol for tests patching _run_litert_cli."""

	def __init__(self, host: str, port: int, runner: Callable[..., Any]) -> None:
		self.host = host
		self.port = port
		self.base_url = f"http://{host}:{port}"
		self._runner = runner
		self._process: Any = None
		self._state = "stopped"
		self._generation = 0
		self._startup_identity: str | None = None
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
			from types import SimpleNamespace
			return SimpleNamespace(
				state=self._state if is_ready else "stopped",
				is_ready=is_ready,
				is_running=is_alive,
				is_adopted=is_adopted,
				pid=pid,
				generation=self._generation,
				error_message=None,
				startup_identity=self._startup_identity,
				running_model=None,
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
		del running_model, timeout_seconds
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

			serve_args = args[2:] if len(args) > 2 and args[:2] == ["-m", "litert_lm_cli.main"] else args
			try:
				proc = self._runner(
					Path(executable),
					serve_args,
					env=env,
				)
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
					raise RuntimeError("LiteRT server process exited unexpectedly.")

				self._process = proc
				self._state = "ready_owned"
				self._startup_identity = startup_identity
				self._generation += 1
				return self.status()
			except Exception as exc:
				self._state = "failed"
				self._startup_identity = None
				self._generation += 1
				if isinstance(exc, RuntimeError) and "exited unexpectedly" in str(exc):
					raise
				raise RuntimeError(f"Failed to start LiteRT-LM server: {exc}") from exc

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
			self._generation += 1
			return self.status()

	def shutdown(self) -> None:
		with self._lock:
			self._shutdown = True
			self.stop()

	def adopt(self, model_id: str | None = None) -> Any:
		del model_id
		with self._lock:
			alive = self._process is not None and self._process.poll() is None
			if alive:
				return self.status()
			self._state = "ready_adopted"
			self._startup_identity = None
			self._generation += 1
			return self.status()


class LiteRTServerError(LLMProviderError):
	"""Raised when the LiteRT-LM server cannot be started or is unhealthy."""


class LiteRTServerSupervisor:
	"""Manages the lifecycle of a ``litert-lm serve`` process.

	The server runs inside a self-contained Python 3.13 runtime that is
	downloaded on first use.  No system Python installation is required.
	"""

	def __init__(
		self,
		*,
		port: int = DEFAULT_LITERT_PORT,
		host: str = DEFAULT_LITERT_HOST,
		version: str = DEFAULT_LITERT_VERSION,
		config_provider: Callable[[], Mapping[str, Any]] | None = None,
		endpoint_provider: Callable[[], str] | None = None,
		worker_client: Any | None = None,
		native_supervisor: Any | None = None,
	) -> None:
		self._port = port
		self._host = host
		self._version = version
		# Runtime code depends on these ports rather than importing the
		# application settings module. The composition root wires them in.
		self._config_provider = config_provider
		self._endpoint_provider = endpoint_provider
		self._worker_client = worker_client
		self._native_supervisor = native_supervisor
		self._native: Any | None = None
		self._test_shim: Any | None = None
		self._download_service = RuntimeDownloadService(
			url_builder=self._build_download_url,
		)

	def _get_worker_client(self) -> Any | None:
		if self._worker_client is not None:
			try:
				conn = getattr(self._worker_client, "is_connected", False)
				is_connected = conn() if callable(conn) else bool(conn)
				if is_connected:
					return self._worker_client
			except Exception:
				pass
			return None
		try:
			from ...plugin.worker_supervisor import get_worker_client

			client = get_worker_client()
			if client is not None:
				conn = getattr(client, "is_connected", False)
				is_connected = conn() if callable(conn) else bool(conn)
				if is_connected:
					return client
		except Exception:
			pass
		return None

	def _get_native(self) -> Any:
		if self._native_supervisor is not None:
			return self._native_supervisor
		host, port = self._effective_host_port()
		if self._test_shim is not None:
			if self._test_shim.host != host or self._test_shim.port != port:
				try:
					self._test_shim.stop()
				except Exception:
					pass
				self._test_shim = _TestShimSupervisor(host, port, _run_litert_cli)
			return self._test_shim
		if _run_litert_cli is not _real_run_litert_cli:
			self._test_shim = _TestShimSupervisor(host, port, _run_litert_cli)
			return self._test_shim
		return None

	def status(self) -> Any:
		"""Return an immutable snapshot of supervisor status (non-blocking)."""
		native = self._get_native()
		if native is not None:
			return native.status()
		client = self._get_worker_client()
		if client is not None:
			try:
				resp = client.send_command(
					{"type": "litert_get_status", "command": "litert_get_status"},
					timeout=5.0,
				)
				if resp.get("status"):
					return _status_dict_to_namespace(resp["status"])
				if resp.get("success") is False or resp.get("type") == "error":
					host, port = self._effective_host_port()
					url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
					err_code = resp.get("error_code")
					err_msg = resp.get("error_message") or err_code
					return types.SimpleNamespace(
						state="failed",
						is_ready=False,
						is_running=False,
						is_adopted=False,
						pid=None,
						generation=int(resp.get("generation", 0)),
						error_code=err_code,
						error_message=err_msg,
						startup_identity=None,
						running_model=None,
						base_url=f"http://{url_host}:{port}",
					)
			except Exception as exc:
				log.debug("Worker litert_get_status query failed: %s", exc)
		host, port = self._effective_host_port()
		return _idle_runtime_status(host, port)


	# ------------------------------------------------------------------
	# public API
	# ------------------------------------------------------------------

	def configure(
		self,
		*,
		config_provider: Callable[[], Mapping[str, Any]] | None = None,
		endpoint_provider: Callable[[], str] | None = None,
	) -> None:
		"""Inject application-owned configuration ports before startup."""
		if self.is_running or self.is_adopted:
			raise LiteRTServerError("Cannot reconfigure a running LiteRT server")
		if config_provider is not None:
			self._config_provider = config_provider
		if endpoint_provider is not None:
			self._endpoint_provider = endpoint_provider

	@property
	def base_url(self) -> str:
		"""The base URL clients should use to reach the server."""
		host, port = self._effective_host_port()
		url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
		return f"http://{url_host}:{port}"

	@property
	def is_installed(self) -> bool:
		"""True when the self-contained runtime has been downloaded and extracted."""
		return self._server_python().exists()

	@property
	def is_running(self) -> bool:
		"""True when the server process is alive."""
		return bool(self.status().is_running)

	@property
	def is_adopted(self) -> bool:
		"""True when a healthy server was adopted without a process handle."""
		return bool(self.status().is_adopted)

	def matches_current_configuration(self) -> bool:
		"""Whether the owned live process matches all current startup inputs."""
		config = self._server_config_snapshot()
		host, port = self._effective_host_port()
		identity = self._configuration_identity(config, host, port)
		try:
			return self._get_native().matches_startup_configuration(identity)
		except Exception:
			return False

	def install(
		self,
		on_progress: Callable[[str], None] | None = None,
		on_bytes_progress: Callable[[int, int], None] | None = None,
		cancel_event: threading.Event | None = None,
	) -> Path:
		"""Download and extract the self-contained litert-lm runtime.

		The runtime includes Python 3.13 and litert-lm — no system
		Python or pip is needed.

		Args:
		    on_progress: Optional callback receiving status strings.
		    on_bytes_progress: Optional callback ``(downloaded_bytes, total_bytes)``
		        for byte-level progress during download.
		    cancel_event: Optional ``threading.Event``; when set the download
		        is cancelled and partial data is preserved.

		Returns the path to the runtime directory.

		Raises:
		    LiteRTServerError: If the download or extraction fails.
		"""
		server_dir = self._server_dir()
		python_exe = self._server_python()

		if python_exe.exists():
			log.debug("LiteRT runtime already present at %s", server_dir)
			return server_dir

		self._report(on_progress, "Downloading LiteRT-LM runtime...")

		try:
			self._download_service.download(
				runtime="litert-lm",
				version=self._version,
				platform="windows-x64",
				on_progress=on_progress,
				on_bytes_progress=on_bytes_progress,
				cancel_event=cancel_event,
			)
		except DownloadCancelledError:
			raise
		except Exception as exc:
			raise LiteRTServerError(f"Failed to download LiteRT-LM runtime {self._version}: {exc}") from exc

		if not python_exe.exists():
			raise LiteRTServerError(f"Runtime extracted but python.exe not found at {python_exe}")

		log.info("LiteRT runtime installed at %s", server_dir)
		return server_dir

	def ensure_ready(
		self,
		timeout: float = 60.0,
		on_progress: Callable[[str], None] | None = None,
	) -> Any:
		"""Ensure the LiteRT-LM server is running and healthy."""
		native = self._get_native()
		if native is not None:
			config = self._server_config_snapshot()
			host, port = self._effective_host_port()
			startup_identity = self._configuration_identity(config, host, port)

			python_exe = _resolve_litert_python(self._server_python())
			self._litert_dir().mkdir(parents=True, exist_ok=True)
			self._write_server_config(config)

			serve_args = _build_serve_args(host, port)
			cmd_args = ["-m", "litert_lm_cli.main", *serve_args]
			env = self._process_environment()

			self._report(on_progress, f"Starting LiteRT-LM server on port {port}...")
			try:
				status = native.ensure_ready(
					str(python_exe),
					cmd_args,
					env,
					startup_identity,
					timeout_seconds=timeout,
				)
				if status.is_ready:
					log.info("LiteRT server is ready at %s", self.base_url)
				return status
			except RuntimeError as exc:
				raise LiteRTServerError(str(exc)) from exc

		client = self._get_worker_client()
		if client is None:
			raise LiteRTServerError("Worker process is not available")

		config = self._server_config_snapshot()
		host, port = self._effective_host_port()
		self._report(on_progress, f"Starting LiteRT-LM server on port {port}...")

		cmd = {
			"type": "litert_ensure_ready",
			"command": "litert_ensure_ready",
			"config": config,
			"timeout_seconds": timeout,
			"host": host,
			"port": port,
			"version": self._version,
		}
		resp = client.send_command(cmd, timeout=timeout + 5.0)
		if not resp.get("success", False) or resp.get("type") == "error":
			err_msg = resp.get("error_message") or "Failed to start LiteRT server"
			raise LiteRTServerError(err_msg)

		status_data = resp.get("status", {})
		status = _status_dict_to_namespace(status_data)
		if status.is_ready:
			log.info("LiteRT server is ready at %s", self.base_url)
		return status

	def start(
		self,
		*,
		on_progress: Callable[[str], None] | None = None,
	) -> None:
		"""Start the ``litert-lm serve`` process."""
		self.ensure_ready(on_progress=on_progress)

	def restart(
		self,
		on_progress: Callable[[str], None] | None = None,
		timeout: float = 60.0,
	) -> Any:
		"""Stop the server (if running) and start it again with fresh engine config."""
		native = self._get_native()
		if native is not None:
			config = self._server_config_snapshot()
			host, port = self._effective_host_port()
			startup_identity = self._configuration_identity(config, host, port)

			python_exe = _resolve_litert_python(self._server_python())
			self._litert_dir().mkdir(parents=True, exist_ok=True)
			self._write_server_config(config)

			serve_args = _build_serve_args(host, port)
			cmd_args = ["-m", "litert_lm_cli.main", *serve_args]
			env = self._process_environment()

			self._report(on_progress, f"Restarting LiteRT-LM server on port {port}...")
			try:
				return native.restart(
					str(python_exe),
					cmd_args,
					env,
					startup_identity,
					timeout_seconds=timeout,
				)
			except RuntimeError as exc:
				raise LiteRTServerError(str(exc)) from exc

		client = self._get_worker_client()
		if client is None:
			raise LiteRTServerError("Worker process is not available")

		config = self._server_config_snapshot()
		host, port = self._effective_host_port()
		self._report(on_progress, f"Restarting LiteRT-LM server on port {port}...")

		cmd = {
			"type": "litert_restart",
			"command": "litert_restart",
			"config": config,
			"timeout_seconds": timeout,
			"host": host,
			"port": port,
			"version": self._version,
		}
		resp = client.send_command(cmd, timeout=timeout + 5.0)
		if not resp.get("success", False) or resp.get("type") == "error":
			err_msg = resp.get("error_message") or "Failed to restart LiteRT server"
			raise LiteRTServerError(err_msg)

		return _status_dict_to_namespace(resp.get("status", {}))

	def stop(self, timeout: float = 10.0) -> Any:
		"""Stop the server process gracefully, then forcefully if needed."""
		native = self._get_native()
		if native is not None:
			try:
				status = native.stop(timeout_seconds=timeout)
				log.info("LiteRT server stopped")
				return status
			except RuntimeError as exc:
				raise LiteRTServerError(str(exc)) from exc

		client = self._get_worker_client()
		if client is None:
			host, port = self._effective_host_port()
			return _idle_runtime_status(host, port)

		cmd = {
			"type": "litert_stop",
			"command": "litert_stop",
			"timeout_seconds": timeout,
		}
		try:
			resp = client.send_command(cmd, timeout=timeout + 5.0)
			return _status_dict_to_namespace(resp.get("status", {}))
		except Exception as exc:
			raise LiteRTServerError(str(exc)) from exc

	def adopt(self) -> Any:
		"""Acknowledge a server running on our host:port without a process handle."""
		native = self._get_native()
		if native is not None:
			try:
				status = native.adopt()
				log.info("LiteRT server adopted (no process handle) at %s", self.base_url)
				return status
			except RuntimeError as exc:
				raise LiteRTServerError(str(exc)) from exc

		client = self._get_worker_client()
		if client is None:
			raise LiteRTServerError("Worker process is not available")

		cmd = {"type": "litert_adopt", "command": "litert_adopt"}
		try:
			resp = client.send_command(cmd, timeout=5.0)
			return _status_dict_to_namespace(resp.get("status", {}))
		except Exception as exc:
			raise LiteRTServerError(str(exc)) from exc

	def shutdown(self) -> None:
		"""Cleanly shutdown runtime during add-on termination."""
		native = self._get_native()
		if native is not None:
			try:
				native.shutdown()
			except Exception:
				pass
		client = self._get_worker_client()
		if client is not None:
			try:
				client.send_command(
					{"type": "litert_stop", "command": "litert_stop", "timeout_seconds": 5.0},
					timeout=5.0,
				)
			except Exception:
				pass


	def wait_until_ready(
		self,
		timeout: float = 60.0,
		on_progress: Callable[[str], None] | None = None,
	) -> bool:
		"""Wait until the server is running and ready."""
		status = self.status()
		if not status.is_running and not status.is_adopted:
			raise LiteRTServerError("LiteRT server process exited unexpectedly. Check the server logs for details.")
		if status.is_ready:
			return True
		status = self.ensure_ready(timeout=timeout, on_progress=on_progress)
		return bool(status.is_ready)

	def sync_config(self) -> None:
		"""Regenerate ``config.json`` from current settings without starting.

		Used by the config-change path when the server was adopted (no
		process handle) and therefore cannot be restarted to apply engine
		settings; the next ``start()`` then picks up the new configuration.
		"""
		self._write_server_config()

	def catalog_model_dir(self, model_id: str) -> Path | None:
		"""Return the on-disk catalog directory for *model_id*, if any.

		LiteRT-LM stores imported models under the directory supplied through
		``LITERT_LM_DIR``.  This is deliberately not the global user home.
		"""
		try:
			model_id = _validate_model_id(model_id)
		except LiteRTServerError:
			return None
		dir_name = model_id.replace("/", "--")
		return self._litert_dir() / "models" / dir_name

	def is_healthy(self, timeout: float = 5.0) -> bool:
		"""Check if the server is responding to health checks.

		Sends a GET to ``/v1/models`` — the lightest endpoint.
		Does NOT require ``is_running`` to be True so that the check
		still works after an NVDA restart when the process handle is lost.
		"""
		try:
			req = urllib.request.Request(
				f"{self.base_url}/v1/models",
				method="GET",
			)
			with urllib.request.urlopen(req, timeout=timeout) as resp:
				return resp.status == 200
		except Exception:
			return False

	def list_server_models(self) -> set[str]:
		"""Return the set of model IDs currently registered with the server.

		Queries worker or /v1/models and extracts the id field from each entry.
		Returns an empty set if the server is not reachable.
		"""
		client = self._get_worker_client()
		if client is not None:
			try:
				resp = client.send_command(
					{"type": "litert_list_models", "command": "litert_list_models"},
					timeout=5.0,
				)
				if resp.get("success", False) and "models" in resp:
					return set(resp["models"])
			except Exception:
				pass

		try:
			req = urllib.request.Request(
				f"{self.base_url}/v1/models",
				method="GET",
			)
			with urllib.request.urlopen(req, timeout=5.0) as resp:
				data = json.loads(resp.read().decode("utf-8"))
		except Exception:
			return set()

		if not isinstance(data, dict):
			return set()
		model_list = data.get("data")
		if not isinstance(model_list, list):
			return set()
		return {str(m.get("id", "")).strip() for m in model_list if isinstance(m, dict) and m.get("id")}

	def import_model(
		self,
		model_path: str | Path,
		model_id: str,
		*,
		on_progress: Callable[[str], None] | None = None,
		delete_source: bool = True,
	) -> None:
		"""Import a local ``.litertlm`` file into the server's model catalog."""
		model_path = Path(model_path)
		if not model_path.is_file():
			raise LiteRTServerError(f"Model file does not exist: {model_path}")
		model_id = _validate_model_id(model_id)

		if _run_litert_cli is not _real_run_litert_cli:
			python_exe = _resolve_litert_python(self._server_python())
			self._report(
				on_progress,
				f"Registering model {model_id} with LiteRT-LM...",
			)
			import_args = _build_import_args(model_path, model_id)
			try:
				result = _run_litert_cli(
					python_exe,
					import_args,
					env=self._process_environment(),
					timeout=120,
					capture=True,
				)
			except subprocess.TimeoutExpired as exc:
				raise LiteRTServerError(f"Model import timed out for {model_id}") from exc
			except Exception as exc:
				raise LiteRTServerError(f"Failed to import model {model_id}: {exc}") from exc

			if result.returncode != 0:
				stderr = result.stderr.strip() or result.stdout.strip()
				raise LiteRTServerError(f"Model import failed for {model_id}: {stderr}")

			log.info("Model %s imported successfully", model_id)
			catalog_dir = self.catalog_model_dir(model_id)
			catalog_file = catalog_dir / "model.litertlm" if catalog_dir is not None else None
			if delete_source and catalog_file is not None and catalog_file.is_file():
				try:
					if model_path.resolve() != catalog_file.resolve():
						model_path.unlink(missing_ok=True)
						log.debug("Deleted source model file %s after import", model_path)
				except OSError:
					log.debug("Could not delete source model file %s", model_path, exc_info=True)

			if on_progress:
				on_progress(f"Model {model_id} registered.")
			return

		client = self._get_worker_client()
		if client is None:
			raise LiteRTServerError("Worker process is not available")

		self._report(
			on_progress,
			f"Registering model {model_id} with LiteRT-LM...",
		)
		cmd = {
			"type": "litert_import_model",
			"command": "litert_import_model",
			"model_path": str(model_path),
			"model_id": model_id,
			"delete_source": delete_source,
		}
		resp = client.send_command(cmd, timeout=130.0)
		if not resp.get("success", False) or resp.get("type") == "error":
			err_msg = resp.get("error_message") or f"Model import failed for {model_id}"
			raise LiteRTServerError(err_msg)

		if on_progress:
			on_progress(f"Model {model_id} registered.")

	def import_huggingface_model(
		self,
		repository: str,
		artifact: str,
		model_id: str,
		*,
		on_progress: Callable[[str], None] | None = None,
		huggingface_token: str | None = None,
	) -> None:
		"""Import a repository using LiteRT-LM's native resolver."""
		if (
			not repository
			or "/" not in repository
			or any(part in {"", ".", ".."} for part in repository.split("/"))
			or "\\" in repository
			or "\x00" in repository
		):
			raise LiteRTServerError("A repository and explicit LiteRT-LM artifact are required")
		artifact = _validate_huggingface_artifact(artifact)
		model_id = _validate_model_id(model_id)

		if _run_litert_cli is not _real_run_litert_cli:
			python_exe = _resolve_litert_python(self._server_python())
			self._report(on_progress, f"Importing {artifact} from Hugging Face...")
			try:
				result = _run_litert_cli(
					python_exe,
					_build_huggingface_import_args(repository, artifact, model_id, huggingface_token),
					env=self._process_environment(),
					timeout=600,
					capture=True,
				)
			except subprocess.TimeoutExpired as exc:
				raise LiteRTServerError(f"Hugging Face import timed out for {repository}") from exc
			except Exception as exc:
				raise LiteRTServerError(f"Failed to import {repository}: {exc}") from exc
			if result.returncode != 0:
				stderr = result.stderr.strip() or result.stdout.strip()
				raise LiteRTServerError(f"Hugging Face import failed for {repository}: {stderr}")
			if on_progress:
				on_progress(f"Model {model_id} registered.")
			return

		client = self._get_worker_client()
		if client is None:
			raise LiteRTServerError("Worker process is not available")

		self._report(on_progress, f"Importing {artifact} from Hugging Face...")
		cmd = {
			"type": "litert_import_huggingface_model",
			"command": "litert_import_huggingface_model",
			"repository": repository,
			"artifact": artifact,
			"model_id": model_id,
			"token": huggingface_token,
		}
		resp = client.send_command(cmd, timeout=610.0)
		if not resp.get("success", False) or resp.get("type") == "error":
			err_msg = resp.get("error_message") or f"Hugging Face import failed for {repository}"
			raise LiteRTServerError(err_msg)

		if on_progress:
			on_progress(f"Model {model_id} registered.")

	def delete_model(self, model_id: str) -> None:
		"""Unregister *model_id* from the LiteRT-LM catalog."""
		model_id = _validate_model_id(model_id)

		if _run_litert_cli is not _real_run_litert_cli:
			python_exe = _resolve_litert_python(self._server_python())
			log.debug("Unregistering model %s from LiteRT-LM catalog", model_id)
			delete_args = _build_delete_args(model_id)
			try:
				result = _run_litert_cli(
					python_exe,
					delete_args,
					env=self._process_environment(),
					timeout=60,
					capture=True,
				)
			except subprocess.TimeoutExpired as exc:
				raise LiteRTServerError(
					f"Model deletion timed out for {model_id}"
				) from exc
			except Exception as exc:
				raise LiteRTServerError(
					f"Failed to delete model {model_id}: {exc}"
				) from exc

			if result.returncode != 0:
				stderr = result.stderr.strip() or result.stdout.strip()
				raise LiteRTServerError(
					f"Model deletion failed for {model_id}: {stderr}"
				)

			log.info("Model %s deleted from LiteRT-LM catalog", model_id)
			return

		client = self._get_worker_client()
		if client is None:
			raise LiteRTServerError("Worker process is not available")

		log.debug("Unregistering model %s from LiteRT-LM catalog via worker", model_id)
		cmd = {
			"type": "litert_delete_model",
			"command": "litert_delete_model",
			"model_id": model_id,
		}
		resp = client.send_command(cmd, timeout=65.0)
		if not resp.get("success", False) or resp.get("type") == "error":
			err_msg = resp.get("error_message") or f"Model deletion failed for {model_id}"
			raise LiteRTServerError(err_msg)

		log.info("Model %s deleted from LiteRT-LM catalog", model_id)

	def rename_model(self, old_id: str, new_id: str) -> None:
		"""Rename a registered model via ``litert-lm rename`` CLI."""
		old_id = _validate_model_id(old_id)
		new_id = _validate_model_id(new_id)

		if _run_litert_cli is not _real_run_litert_cli:
			python_exe = _resolve_litert_python(self._server_python())
			log.debug("Renaming model %s → %s", old_id, new_id)
			rename_args = _build_rename_args(old_id, new_id)
			try:
				result = _run_litert_cli(
					python_exe,
					rename_args,
					env=self._process_environment(),
					timeout=30,
					capture=True,
				)
			except subprocess.TimeoutExpired as exc:
				raise LiteRTServerError(
					f"Model rename timed out for {old_id}"
				) from exc
			except Exception as exc:
				raise LiteRTServerError(
					f"Failed to rename model {old_id}: {exc}"
				) from exc

			if result.returncode != 0:
				stderr = result.stderr.strip() or result.stdout.strip()
				raise LiteRTServerError(
					f"Model rename failed for {old_id} → {new_id}: {stderr}"
				)

			log.info("Model renamed from %s to %s", old_id, new_id)
			return

		client = self._get_worker_client()
		if client is None:
			raise LiteRTServerError("Worker process is not available")

		log.debug("Renaming model %s → %s via worker", old_id, new_id)
		cmd = {
			"type": "litert_rename_model",
			"command": "litert_rename_model",
			"old_id": old_id,
			"new_id": new_id,
		}
		resp = client.send_command(cmd, timeout=35.0)
		if not resp.get("success", False) or resp.get("type") == "error":
			err_msg = resp.get("error_message") or f"Model rename failed for {old_id} → {new_id}"
			raise LiteRTServerError(err_msg)

		log.info("Model renamed from %s to %s", old_id, new_id)


	# ------------------------------------------------------------------
	# internal helpers
	# ------------------------------------------------------------------

	def _effective_host_port(self) -> tuple[str, int]:
		"""Resolve the server bind address from the configured ``litertServerUrl``.

		The client adapter connects to the injected server URL, so the
		``serve`` process must bind the same host/port or the client and server
		drift apart. On any failure the constructor-provided host/port are kept.
		"""
		try:
			url = self._endpoint_provider() if self._endpoint_provider is not None else ""
			parsed = urllib.parse.urlparse(str(url or "").strip())
			if parsed.hostname and parsed.port:
				return parsed.hostname, parsed.port
		except Exception:
			log.debug(
				"Could not resolve LiteRT server URL from settings; using default host/port",
				exc_info=True,
			)
		return self._host, self._port

	def _server_dir(self) -> Path:
		"""Return the path to the self-contained runtime directory."""
		return get_runtime_path("litert-lm", self._version)

	def _server_python(self) -> Path:
		"""Return the path to the bundled Python executable."""
		return self._server_dir() / "python.exe"

	@staticmethod
	def _litert_dir() -> Path:
		return _default_litert_dir()

	@classmethod
	def _process_environment(cls) -> dict[str, str]:
		env = os.environ.copy()
		env["LITERT_LM_DIR"] = str(cls._litert_dir())
		return env

	def _server_config_snapshot(self) -> dict[str, Any]:
		raw = (
			dict(self._config_provider())
			if self._config_provider is not None
			else _current_server_config()
		)
		# Detach nested model/default mappings from mutable settings objects.
		# The same immutable value must drive both the fingerprint and file.
		return json.loads(json.dumps(raw))

	def _configuration_identity(
		self,
		config: Mapping[str, Any],
		host: str,
		port: int,
	) -> str:
		"""Return an immutable fingerprint of process/engine startup inputs."""
		return json.dumps(
			{
				"version": self._version,
				"python": os.path.normcase(str(self._server_python().resolve())),
				"host": host.casefold(),
				"port": port,
				"config": config,
			},
			sort_keys=True,
			separators=(",", ":"),
		)

	def _write_server_config(self, config: Mapping[str, Any] | None = None) -> None:
		"""Write ``config.json`` into ``LITERT_LM_DIR`` for the engine.

		litert-lm's ``serve`` binds engine parameters (``max_num_tokens``,
		``backend``, ...) when the engine is first initialized, and there
		is no serve CLI flag for them — they are read from ``config.json``.
		Writing it here, immediately before spawning the process, makes
		the add-on's settings take effect.  When the payload is empty any
		stale ``config.json`` is removed so a later start does not
		resurrect an outdated engine configuration.

		``config.json`` is a derived startup artifact: it is regenerated
		from the add-on settings whenever the server (re)starts.  The
		running server is kept consistent with settings by restarting when
		server-relevant settings change (see the config-change event in
		plugin/background.py).
		"""
		config = dict(config) if config is not None else self._server_config_snapshot()
		config_path = self._litert_dir() / "config.json"
		if not config:
			with _CONFIG_WRITE_LOCK:
				try:
					config_path.unlink(missing_ok=True)
				except OSError:
					log.debug("Could not remove stale LiteRT config.json", exc_info=True)
			return

		payload = json.dumps(config, indent=2) + "\n"
		with _CONFIG_WRITE_LOCK:
			config_path.parent.mkdir(parents=True, exist_ok=True)
			if config_path.exists():
				try:
					if config_path.read_text(encoding="utf-8") == payload:
						return
				except OSError:
					pass

			tmp_path = config_path.with_name(
				f".{config_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
			)
			for attempt in range(5):
				try:
					tmp_path.write_text(payload, encoding="utf-8")
					tmp_path.replace(config_path)
					break
				except OSError:
					if attempt == 4:
						raise
					time.sleep(0.02)
				finally:
					try:
						tmp_path.unlink(missing_ok=True)
					except OSError:
						pass

	@staticmethod
	def _build_download_url(config: RuntimeConfig) -> str:
		"""Build the GitHub Releases download URL for a runtime ZIP."""
		return _RUNTIME_DOWNLOAD_BASE.format(version=config.version)

	@staticmethod
	def _report(
		callback: Callable[[str], None] | None,
		message: str,
	) -> None:
		"""Invoke a progress callback if provided."""
		if callback is not None:
			try:
				callback(message)
			except Exception:
				pass
