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
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import RuntimeConfig
from .download import DownloadCancelledError, RuntimeDownloadService
from .paths import get_runtime_path
from ..interfaces import LLMProviderError

if TYPE_CHECKING:
	from collections.abc import Callable

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


def _build_delete_args(model_id: str) -> list[str]:
	"""Build the CLI argument list for ``litert-lm delete``."""
	return ["delete", model_id]


def _build_rename_args(old_id: str, new_id: str) -> list[str]:
	"""Build the CLI argument list for ``litert-lm rename``."""
	return ["rename", old_id, new_id]


def build_server_config(
	model_id: str | None,
	default_num_ctx: int,
	pinned_num_ctx: int | None,
) -> dict[str, Any]:
	"""Build the ``config.json`` payload for the LiteRT-LM server engine.

	Maps the add-on's context-window setting (``num_ctx``) onto
	litert-lm's ``max_num_tokens`` — the engine's combined input+output
	KV-cache budget.  ``max_num_tokens`` is fixed when the engine is
	first initialized and has no ``serve`` CLI flag, so it belongs in
	the server config rather than the request body (litert-lm ignores
	``num_ctx`` on the wire).  The add-on's global ``num_ctx`` becomes
	``default``; a per-model pin that differs from the global value
	becomes a per-model override, mirroring ``resolve_model_sampling``.

	Args:
	    model_id: The active model's server registration ID
	        (``friendly_name``) sent on the wire, or ``None``.
	    default_num_ctx: The global context window size.
	    pinned_num_ctx: The model's pinned context window, or ``None``
	        when the model has no explicit pin.

	Returns:
	    The config dict to write to ``LITERT_LM_DIR/config.json``.
	    Empty when there is nothing meaningful to configure.
	"""
	config: dict[str, Any] = {}
	if default_num_ctx:
		config["default"] = {"max_num_tokens": default_num_ctx}
	if (
		model_id
		and pinned_num_ctx is not None
		and pinned_num_ctx != default_num_ctx
	):
		config["models"] = {model_id: {"max_num_tokens": pinned_num_ctx}}
	return config


def _current_server_config() -> dict[str, Any]:
	"""Return the server ``config.json`` payload from the add-on settings.

	The active model's pinned context window wins over the global
	``num_ctx``, exactly as the request-time ``resolve_model_sampling``
	does for the provider adapter.  The config modules are imported
	lazily so this module stays importable in isolated test environments
	that do not have NVDA's config stack available.
	"""
	from ...config.model_config import get_model_sampling
	from ...config.settings import get_litert_model_name, get_num_ctx

	model_id = get_litert_model_name()
	pinned_num_ctx = (
		get_model_sampling("litert-lm", model_id).num_ctx if model_id else None
	)
	return build_server_config(model_id, get_num_ctx(), pinned_num_ctx)


def _config_signature(config: dict[str, Any]) -> str:
	"""Return a canonical, order-independent signature for *config*.

	Empty configs map to ``""`` so "nothing to configure" compares equal
	to an absent (or freshly removed) ``config.json`` on disk.
	"""
	if not config:
		return ""
	return json.dumps(config, sort_keys=True, separators=(",", ":"))


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
	) -> None:
		self._port = port
		self._host = host
		self._version = version
		self._process: subprocess.Popen[str] | None = None
		# Signature of the engine config the running server was started with.
		# ``None`` means "not recorded" (e.g. server adopted after restart).
		self._applied_config_signature: str | None = None
		self._lifecycle_lock = threading.RLock()
		self._download_service = RuntimeDownloadService(
			url_builder=self._build_download_url,
		)

	# ------------------------------------------------------------------
	# public API
	# ------------------------------------------------------------------

	@property
	def base_url(self) -> str:
		"""The base URL clients should use to reach the server."""
		return f"http://{self._host}:{self._port}"

	@property
	def is_installed(self) -> bool:
		"""True when the self-contained runtime has been downloaded and extracted."""
		return self._server_python().exists()

	@property
	def is_running(self) -> bool:
		"""True when the server process is alive."""
		return self._process is not None and self._process.poll() is None

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
				self._applied_config_signature = self._write_server_config()
				serve_args = _build_serve_args(self._host, self._port)
				self._process = _run_litert_cli(
					python_exe,
					serve_args,
					env=self._process_environment(),
				)
			except Exception as exc:
				raise LiteRTServerError(f"Failed to start LiteRT-LM server: {exc}") from exc

		log.info(
			"LiteRT server started (pid=%d) on %s",
			self._process.pid,
			self.base_url,
		)

	def restart_if_config_changed(
		self,
		on_progress: Callable[[str], None] | None = None,
	) -> bool:
		"""Restart the server when the engine config no longer matches settings.

		Engine-level parameters such as ``max_num_tokens`` (the KV-cache
		budget mapped from the add-on's ``num_ctx``) bind when the engine
		initializes and cannot be changed on a running process.  This
		compares the config the running server was started with against the
		currently desired config and, on a mismatch, stops and restarts the
		server so the new values take effect.

		Call this from the readiness path whenever the server is already
		healthy — it is a cheap signature comparison in the common case and
		only restarts when the engine config actually changed.

		Args:
		    on_progress: Optional status callback forwarded to ``start()``.

		Returns:
		    ``True`` when the server was restarted, ``False`` when there was
		    nothing to do (server not running or config unchanged).
		"""
		with self._lifecycle_lock:
			if not self.is_running:
				return False

			desired = _config_signature(_current_server_config())
			applied = self._applied_config_signature
			if applied is None:
				# No recorded signature (e.g. the process handle was lost and
				# the server adopted): fall back to the config.json on disk,
				# which reflects what the running server was started with.
				applied = self._read_config_signature()

			if applied == desired:
				return False

			log.info("LiteRT server config changed; restarting to apply it")
			self.stop()
			self.start(on_progress=on_progress)
			return True

	def stop(self) -> None:
		"""Stop the server process gracefully, then forcefully if needed."""
		with self._lifecycle_lock:
			if self._process is None:
				return

			if self._process.poll() is None:
				log.debug("Stopping LiteRT server (pid=%d)...", self._process.pid)
				self._process.terminate()
				try:
					self._process.wait(timeout=10)
				except subprocess.TimeoutExpired:
					log.warning("LiteRT server did not stop; killing")
					self._process.kill()
					self._process.wait(timeout=5)

		self._process = None
		log.info("LiteRT server stopped")

	def adopt(self) -> None:
		"""Acknowledge a server running on our host:port without a process handle.

		After an NVDA restart the process handle is lost but the server may
		still be alive.  Call this when ``is_healthy()`` returns True even
		though ``is_running`` is False so the supervisor treats the server
		as available without trying to start a new one.
		"""
		# Nothing to do — the absence of a process handle is the signal.
		# Callers check is_healthy() independently to decide whether the
		# existing server is usable.

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
				return resp.status == 200
		except Exception:
			return False

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

		# Delete the source file now that litert-lm has copied it into
		# its own registry.  These files are 1-8 GB — keeping both is wasteful.
		catalog_dir = self.catalog_model_dir(model_id)
		catalog_file = catalog_dir / "model.litertlm" if catalog_dir is not None else None
		if catalog_file is not None and catalog_file.is_file():
			try:
				model_path.unlink(missing_ok=True)
				log.debug("Deleted source model file %s after import", model_path)
			except OSError:
				log.debug("Could not delete source model file %s", model_path, exc_info=True)

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
			if not self.is_running:
				raise LiteRTServerError(
					"LiteRT server process exited unexpectedly. Check the server logs for details."
				)
			if self.is_healthy(timeout=2.0):
				log.info("LiteRT server is ready at %s", self.base_url)
				return True

			self._report(on_progress, "Waiting for LiteRT-LM server to be ready...")
			time.sleep(SERVER_READY_POLL_INTERVAL)

		log.warning("LiteRT server did not become ready within %.0fs", timeout)
		return False

	def shutdown(self) -> None:
		"""Stop the server and clean up. Safe to call multiple times."""
		self.stop()

	# ------------------------------------------------------------------
	# internal helpers
	# ------------------------------------------------------------------

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

	def _write_server_config(self) -> str | None:
		"""Write ``config.json`` into ``LITERT_LM_DIR`` for the engine.

		litert-lm's ``serve`` binds ``max_num_tokens`` (the KV-cache
		budget) when the engine is first initialized, and there is no
		serve CLI flag for it — the value is read from ``config.json``.
		Writing it here, immediately before spawning the process, makes
		the add-on's context-window setting take effect.  When the
		payload is empty any stale ``config.json`` is removed so a later
		restart does not resurrect an outdated engine configuration.
		The engine caches its value for the process lifetime, so
		changing ``num_ctx`` requires a server restart to apply.

		Returns:
		    The signature of the applied config, or ``None`` when nothing
		    was written.
		"""
		config = _current_server_config()
		config_path = self._litert_dir() / "config.json"
		if not config:
			try:
				config_path.unlink(missing_ok=True)
			except OSError:
				log.debug("Could not remove stale LiteRT config.json", exc_info=True)
			return None
		config_path.parent.mkdir(parents=True, exist_ok=True)
		config_path.write_text(
			json.dumps(config, indent=2) + "\n",
			encoding="utf-8",
		)
		return _config_signature(config)

	def _read_config_signature(self) -> str:
		"""Return the signature of the ``config.json`` on disk, or ``""`` when absent."""
		config_path = self._litert_dir() / "config.json"
		try:
			data = json.loads(config_path.read_text(encoding="utf-8"))
		except (OSError, ValueError):
			return ""
		if not isinstance(data, dict):
			return ""
		return _config_signature(data)

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
