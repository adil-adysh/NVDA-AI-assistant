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
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import RuntimeConfig
from .download import DownloadCancelledError, RuntimeDownloadService
from .paths import get_runtime_path
from ..interfaces import LLMProviderError

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


def get_litert_supervisor() -> LiteRTServerSupervisor:
	"""Return the module-level singleton :class:`LiteRTServerSupervisor`.

	Creates the instance on first call with defaults that match the
	add-on configuration.
	"""
	global _supervisor  # pylint: disable=global-statement
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
	) -> None:
		self._port = port
		self._host = host
		self._version = version
		# Runtime code depends on these ports rather than importing the
		# application settings module. The composition root wires them in.
		self._config_provider = config_provider
		self._endpoint_provider = endpoint_provider
		self._process: subprocess.Popen[str] | None = None
		self._adopted = False
		self._lifecycle_lock = threading.RLock()
		self._download_service = RuntimeDownloadService(
			url_builder=self._build_download_url,
		)

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
		with self._lifecycle_lock:
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
		return f"http://{host}:{port}"

	@property
	def is_installed(self) -> bool:
		"""True when the self-contained runtime has been downloaded and extracted."""
		return self._server_python().exists()

	@property
	def is_running(self) -> bool:
		"""True when the server process is alive."""
		return self._process is not None and self._process.poll() is None

	@property
	def is_adopted(self) -> bool:
		"""True when a healthy server was adopted without a process handle.

		After an NVDA restart the process handle is lost but the server may
		still be reachable.  ``adopt()`` records that fact so readiness
		evaluation can treat the server as available without issuing a
		blocking socket request on the main thread.
		"""
		return self._adopted

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

	def start(
		self,
		*,
		on_progress: Callable[[str], None] | None = None,
	) -> None:
		"""Start the ``litert-lm serve`` process.

		The server starts without a pre-loaded model — the model is loaded
		lazily when the first ``/v1/chat/completions`` request references it.

		Args:
		    on_progress: Optional status callback.

		Raises:
		    LiteRTServerError: If the runtime is not installed or
		        the process fails to start.
		"""
		with self._lifecycle_lock:
			if self.is_running:
				log.debug("LiteRT server is already running")
				return

		python_exe = _resolve_litert_python(self._server_python())

		self._report(on_progress, f"Starting LiteRT-LM server on port {self._port}...")

		with self._lifecycle_lock:
			if self.is_running:
				return
			try:
				self._litert_dir().mkdir(parents=True, exist_ok=True)
				self._write_server_config()
				host, port = self._effective_host_port()
				serve_args = _build_serve_args(host, port)
				self._process = _run_litert_cli(
					python_exe,
					serve_args,
					env=self._process_environment(),
				)
				self._adopted = False
			except Exception as exc:
				raise LiteRTServerError(f"Failed to start LiteRT-LM server: {exc}") from exc

		log.info(
			"LiteRT server started (pid=%d) on %s",
			self._process.pid,
			self.base_url,
		)

	def restart(
		self,
		on_progress: Callable[[str], None] | None = None,
	) -> None:
		"""Stop the server (if running) and start it again with fresh engine config.

		Engine-level settings (``backend``, ``cache``, ``cpu_thread_count``,
		``max_num_tokens``) bind when litert-lm's engine initializes and
		cannot be changed on a running process.  ``start()`` regenerates
		``config.json`` from the current settings, so a restart is how a
		settings change takes effect.  Callers (e.g. the config-change event
		handler) are responsible for waiting until the server is ready.

		Args:
		    on_progress: Optional status callback forwarded to ``start()``.
		"""
		with self._lifecycle_lock:
			self.stop()
			self.start(on_progress=on_progress)

	def stop(self) -> None:
		"""Stop the server process gracefully, then forcefully if needed.

		Always clears any adopted state so a stopped or handleless server is
		never reported as available afterwards.  All state mutations happen
		under the lifecycle lock to avoid racing a concurrent ``start()``.
		"""
		with self._lifecycle_lock:
			process = self._process
			if process is not None and process.poll() is None:
				log.debug("Stopping LiteRT server (pid=%d)...", process.pid)
				process.terminate()
				try:
					process.wait(timeout=10)
				except subprocess.TimeoutExpired:
					log.warning("LiteRT server did not stop; killing")
					process.kill()
					process.wait(timeout=5)

			self._process = None
			self._adopted = False
		log.info("LiteRT server stopped")

	def adopt(self) -> None:
		"""Acknowledge a server running on our host:port without a process handle.

		After an NVDA restart the process handle is lost but the server may
		still be alive.  Call this when ``is_healthy()`` returns True even
		though ``is_running`` is False so the supervisor treats the server
		as available without trying to start a new one.
		"""
		with self._lifecycle_lock:
			if self.is_running:
				# A live process handle already exists; nothing to adopt.
				return
			self._adopted = True
		log.info("LiteRT server adopted (no process handle) at %s", self.base_url)

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
		if not model_id or ".." in model_id or "\\" in model_id or "\x00" in model_id:
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
				healthy = resp.status == 200
		except Exception:
			healthy = False

		# A failed liveness probe invalidates any previously recorded
		# "adopted" state (a handleless server that has since died) so a
		# later readiness evaluation does not keep reporting it as ready.
		# is_healthy() performs socket I/O and is only ever invoked from
		# worker threads, never the NVDA main thread.
		if not healthy:
			with self._lifecycle_lock:
				self._adopted = False

		return healthy

	def list_server_models(self) -> set[str]:
		"""Return the set of model IDs currently registered with the server.

		Queries ``/v1/models`` and extracts the ``id`` field from each entry.
		Returns an empty set if the server is not reachable.
		"""
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
		"""Import a local ``.litertlm`` file into the server's model catalog.

		Runs ``litert-lm import <model_path> <model_id>`` via the bundled
		Python runtime.  LiteRT-LM copies the file into the registry selected
		by ``LITERT_LM_DIR``; the original download remains in the add-on's
		model cache.

		Args:
		    model_path: Path to the ``.litertlm`` file on disk.
		    model_id: The model identifier to register (e.g.
		        ``"litert-community/gemma-4-E2B-it-litert-lm"``).
		    on_progress: Optional status callback.

		Raises:
		    LiteRTServerError: If the import fails.
		"""
		python_exe = _resolve_litert_python(self._server_python())

		self._report(
			on_progress,
			f"Registering model {model_id} with LiteRT-LM...",
		)

		model_path = Path(model_path)
		if not model_path.is_file():
			raise LiteRTServerError(f"Model file does not exist: {model_path}")
		if not model_id or "\\" in model_id or ".." in model_id or "\x00" in model_id:
			raise LiteRTServerError(f"Invalid LiteRT-LM model ID: {model_id!r}")

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

		# Managed downloads can be removed after registration, but a local
		# user-owned source must never be deleted by an import operation.
		catalog_dir = self.catalog_model_dir(model_id)
		catalog_file = catalog_dir / "model.litertlm" if catalog_dir is not None else None
		if delete_source and catalog_file is not None and catalog_file.is_file():
			try:
				model_path.unlink(missing_ok=True)
				log.debug("Deleted source model file %s after import", model_path)
			except OSError:
				log.debug("Could not delete source model file %s", model_path, exc_info=True)

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
		"""Import a repository using LiteRT-LM's native resolver.

		The artifact is mandatory because LiteRT repositories may contain more
		than one runtime/build variant.  The provider never guesses which one
		should be installed.
		"""
		python_exe = _resolve_litert_python(self._server_python())
		if not repository or "/" not in repository or not artifact:
			raise LiteRTServerError("A repository and explicit LiteRT-LM artifact are required")
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

	def delete_model(self, model_id: str) -> None:
		"""Unregister *model_id* from the LiteRT-LM catalog via CLI.

		Runs ``litert-lm delete <model_id>`` via the bundled Python
		runtime against the same ``LITERT_LM_DIR`` used by serve and
		import.  The LiteRT-LM CLI is idempotent — deleting an
		already-absent model succeeds silently.

		Args:
		    model_id: The canonical model identifier (e.g.
		        ``"litert-community/gemma-4-E2B-it-litert-lm"``).

		Raises:
		    LiteRTServerError: If the runtime is not installed, the
		        model ID is invalid, or the CLI exits non-zero.
		"""
		python_exe = _resolve_litert_python(self._server_python())

		if not model_id or "\\" in model_id or ".." in model_id or "\x00" in model_id:
			raise LiteRTServerError(f"Invalid LiteRT-LM model ID: {model_id!r}")

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

	def rename_model(self, old_id: str, new_id: str) -> None:
		"""Rename a registered model via ``litert-lm rename`` CLI.

		Args:
		    old_id: Current model identifier in the catalog.
		    new_id: New model identifier.

		Raises:
		    LiteRTServerError: If the rename fails.
		"""
		python_exe = _resolve_litert_python(self._server_python())

		for model_id in (old_id, new_id):
			if not model_id or "\\" in model_id or ".." in model_id or "\x00" in model_id:
				raise LiteRTServerError(f"Invalid LiteRT-LM model ID: {model_id!r}")

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

	def wait_until_ready(
		self,
		timeout: float = 60.0,
		on_progress: Callable[[str], None] | None = None,
	) -> bool:
		"""Poll the server health endpoint until it responds or *timeout* elapses.

		Returns:
		    ``True`` if the server became ready, ``False`` on timeout.
		"""
		deadline = time.monotonic() + timeout
		while time.monotonic() < deadline:
			if not self.is_running and not self.is_adopted:
				raise LiteRTServerError(
					"LiteRT server process exited unexpectedly. Check the server logs for details."
				)
			if self.is_healthy(timeout=2.0):
				log.info("LiteRT server is ready at %s", self.base_url)
				return True

			self._report(on_progress, "Waiting for LiteRT-LM server to be ready...")
			time.sleep(SERVER_READY_POLL_INTERVAL)

		log.warning("LiteRT server did not become ready within %.0fs", timeout)
		# Do not leave an owned but unhealthy process behind after a failed
		# readiness contract. The next request can then start cleanly.
		if self.is_running and not self.is_adopted:
			self.stop()
		return False

	def shutdown(self) -> None:
		"""Stop the server and clean up. Safe to call multiple times."""
		self.stop()

	# ------------------------------------------------------------------
	# internal helpers
	# ------------------------------------------------------------------

	def _effective_host_port(self) -> tuple[str, int]:
		"""Resolve the server bind address from the configured ``litertServerUrl``.

		The client adapter connects to the user-configurable server URL
		(``litertServerUrl``), so the ``serve`` process must bind the same
		host/port or the client and server drift apart.  The settings module
		is imported lazily and the parse is defensive so this stays usable in
		isolated environments without NVDA's config stack; on any failure the
		constructor-provided host/port are kept.
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

	def _write_server_config(self) -> None:
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
		config = (
			dict(self._config_provider())
			if self._config_provider is not None
			else _current_server_config()
		)
		config_path = self._litert_dir() / "config.json"
		if not config:
			try:
				config_path.unlink(missing_ok=True)
			except OSError:
				log.debug("Could not remove stale LiteRT config.json", exc_info=True)
			return
		config_path.parent.mkdir(parents=True, exist_ok=True)
		config_path.write_text(
			json.dumps(config, indent=2) + "\n",
			encoding="utf-8",
		)

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
