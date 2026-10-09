# -*- coding: utf-8 -*-
"""Managed ``llama-server`` runtime.

The application talks to llama.cpp through its OpenAI-compatible HTTP API.
This module owns process lifecycle and command construction so the rest of
the provider layer never needs to know how a GGUF model is launched.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import types
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from ..interfaces import LLMProviderError

log = logging.getLogger(__name__)

DEFAULT_LLAMA_HOST = "127.0.0.1"
DEFAULT_LLAMA_PORT = 8080
DEFAULT_LLAMA_SERVER = "llama-server"
POLL_INTERVAL = 0.25


class LlamaServerError(LLMProviderError):
	"""Raised when llama-server cannot be launched or reached."""


def _creation_flags() -> int:
	return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def build_llama_server_args(
	model: str | None = None,
	*,
	host: str = DEFAULT_LLAMA_HOST,
	port: int = DEFAULT_LLAMA_PORT,
	models_preset: str | Path | None = None,
	alias: str | None = None,
	threads: int = 0,
	context: int = 0,
) -> list[str]:
	"""Build safe, provider-owned llama-server arguments.

	A model beginning with ``hf://`` is converted to llama.cpp's ``-hf``
	argument.  A local path uses ``-m``.  No shell is involved.
	"""
	model = str(model or "").strip()
	if not model and models_preset is None:
		raise LlamaServerError("A GGUF model or Hugging Face model reference is required")
	args = ["--host", host, "--port", str(port)]
	if models_preset is not None:
		args.extend(["--models-preset", str(models_preset)])
	if models_preset is None:
		if model.startswith("hf://"):
			args.extend(["-hf", model[5:]])
		else:
			args.extend(["-m", model])
	if alias:
		args.extend(["--alias", alias])
	if threads >= 1:
		args.extend(["-t", str(threads)])
	if context >= 1:
		args.extend(["-c", str(context)])
	return args


class _LlamaTestShimSupervisor:
	"""Implements the native RuntimeSupervisor protocol for tests injecting process_factory."""

	def __init__(self, host: str, port: int, runner: Callable[..., Any]) -> None:
		self.host = host
		self.port = port
		self.base_url = (
			f"http://[{self.host}]:{self.port}"
			if ":" in str(self.host) and not str(self.host).startswith("[")
			else f"http://{self.host}:{self.port}"
		)
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
		del env, timeout_seconds
		with self._lock:
			if self._shutdown:
				raise RuntimeError("Server supervisor has been shut down.")
			if self._process is not None:
				if self._process.poll() is not None:
					self._process = None
					self._state = "stopped"
					self._startup_identity = None
					self._running_model = None
				elif self._startup_identity == startup_identity:
					return self.status()
				else:
					if hasattr(self._process, "terminate"):
						try:
							self._process.terminate()
						except Exception:
							pass
					self._process = None

			command = [executable, *args]
			try:
				proc = self._runner(
					command,
					stdout=subprocess.DEVNULL,
					stderr=subprocess.DEVNULL,
					text=True,
					creationflags=_creation_flags(),
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
					self._running_model = None
					self._generation += 1
					raise RuntimeError("llama-server exited before becoming ready")

				self._process = proc
				self._state = "ready_owned"
				self._startup_identity = startup_identity
				self._running_model = running_model
				self._generation += 1
				return self.status()
			except Exception as exc:
				self._state = "failed"
				self._startup_identity = None
				self._running_model = None
				self._generation += 1
				if isinstance(exc, RuntimeError) and "exited before becoming ready" in str(exc):
					raise
				raise RuntimeError(f"Could not start llama-server ({executable!r}): {exc}") from exc

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
		error_code=None,
		error_message=None,
		startup_identity=None,
		running_model=None,
		base_url=f"http://{url_host}:{port}",
	)


class LlamaServerSupervisor:
	"""Thread-safe lifecycle manager for one llama-server endpoint."""

	def __init__(
		self,
		*,
		executable: str | Path = DEFAULT_LLAMA_SERVER,
		host: str = DEFAULT_LLAMA_HOST,
		port: int = DEFAULT_LLAMA_PORT,
		process_factory: Callable[..., subprocess.Popen[str]] | None = None,
		native_supervisor: Any | None = None,
		worker_client: Any | None = None,
	) -> None:
		self.executable = str(executable)
		self.host = host
		self.port = port
		self._process_factory = process_factory
		self._native_supervisor = native_supervisor
		self._worker_client = worker_client
		self._test_shim: Any | None = None
		self._models_cache: tuple[dict[str, object], ...] | None = None
		self._models_cache_lock = threading.Lock()

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
		if self._process_factory is not None:
			if self._test_shim is None:
				self._test_shim = _LlamaTestShimSupervisor(self.host, self.port, self._process_factory)
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
					{"type": "llama_get_status", "command": "llama_get_status"},
					timeout=5.0,
				)
				if resp.get("status"):
					return _status_dict_to_namespace(resp["status"])
				if resp.get("success") is False or resp.get("type") == "error":
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
						base_url=self.base_url,
					)
			except Exception as exc:
				log.debug("Worker llama_get_status query failed: %s", exc)
		return _idle_runtime_status(self.host, self.port)

	@property
	def base_url(self) -> str:
		url_host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
		return f"http://{url_host}:{self.port}"

	@property
	def is_running(self) -> bool:
		return bool(self.status().is_running)

	@property
	def is_adopted(self) -> bool:
		return bool(self.status().is_adopted)

	@property
	def running_model(self) -> str | None:
		return self.status().running_model

	def matches_startup_configuration(
		self,
		model: str,
		*,
		model_id: str | None = None,
		models_preset: str | Path | None = None,
		threads: int = 0,
		context: int = 0,
	) -> bool:
		"""Whether the owned live process was created from these inputs."""
		startup_identity = self._build_startup_identity(
			model,
			model_id=model_id,
			models_preset=models_preset,
			threads=threads,
			context=context,
		)
		native = self._get_native()
		if native is not None:
			try:
				return native.matches_startup_configuration(startup_identity)
			except Exception:
				return False
		status = self.status()
		alive = bool(status.is_running)
		return alive and getattr(status, "startup_identity", None) == startup_identity

	def ensure_ready(
		self,
		model: str,
		*,
		model_id: str | None = None,
		models_preset: str | Path | None = None,
		threads: int = 0,
		context: int = 0,
		on_progress: Callable[[str], None] | None = None,
		timeout: float = 60.0,
	) -> Any:
		"""Ensure the llama-server is running and ready.

		Atomic startup and health check serialized in Rust with in-flight deduplication.
		"""
		startup_identity = self._build_startup_identity(
			model,
			model_id=model_id,
			models_preset=models_preset,
			threads=threads,
			context=context,
		)
		args = build_llama_server_args(
			model,
			host=self.host,
			port=self.port,
			models_preset=models_preset,
			alias=model_id if models_preset is None else None,
			threads=threads,
			context=context,
		)
		if on_progress:
			on_progress(f"Starting llama-server for {model_id or model}...")

		native = self._get_native()
		if native is not None:
			env = dict(os.environ)
			try:
				status = native.ensure_ready(
					self.executable,
					args,
					env,
					startup_identity,
					running_model=model_id or model,
					timeout_seconds=timeout,
				)
				with self._models_cache_lock:
					self._models_cache = None
				return status
			except RuntimeError as exc:
				if "exited before becoming ready" in str(exc) or "exited unexpectedly" in str(exc):
					raise LlamaServerError("llama-server exited before becoming ready") from exc
				raise LlamaServerError(
					f"Could not start llama-server ({self.executable!r}). "
					"Install llama.cpp and ensure llama-server is on PATH."
				) from exc

		client = self._get_worker_client()
		if client is None:
			raise LlamaServerError("Worker process is not available")

		cmd = {
			"type": "llama_ensure_ready",
			"command": "llama_ensure_ready",
			"model": model,
			"model_id": model_id,
			"models_preset": str(models_preset) if models_preset is not None else None,
			"threads": threads,
			"context": context,
			"timeout_seconds": timeout,
			"host": self.host,
			"port": self.port,
			"executable": self.executable,
			"startup_identity": startup_identity,
		}
		resp = client.send_command(cmd, timeout=timeout + 5.0)
		if not resp.get("success", False) or resp.get("type") == "error":
			err_msg = resp.get("error_message") or "Failed to start llama-server"
			if "exited before becoming ready" in err_msg or "exited unexpectedly" in err_msg:
				raise LlamaServerError("llama-server exited before becoming ready")
			raise LlamaServerError(err_msg)

		with self._models_cache_lock:
			self._models_cache = None
		return _status_dict_to_namespace(resp.get("status", {}))

	def restart(
		self,
		model: str,
		*,
		model_id: str | None = None,
		models_preset: str | Path | None = None,
		threads: int = 0,
		context: int = 0,
		on_progress: Callable[[str], None] | None = None,
		timeout: float = 60.0,
	) -> Any:
		"""Restart the llama-server with fresh configuration."""
		startup_identity = self._build_startup_identity(
			model,
			model_id=model_id,
			models_preset=models_preset,
			threads=threads,
			context=context,
		)
		args = build_llama_server_args(
			model,
			host=self.host,
			port=self.port,
			models_preset=models_preset,
			alias=model_id if models_preset is None else None,
			threads=threads,
			context=context,
		)
		if on_progress:
			on_progress(f"Restarting llama-server for {model_id or model}...")

		native = self._get_native()
		if native is not None:
			env = dict(os.environ)
			try:
				status = native.restart(
					self.executable,
					args,
					env,
					startup_identity,
					running_model=model_id or model,
					timeout_seconds=timeout,
				)
				with self._models_cache_lock:
					self._models_cache = None
				return status
			except RuntimeError as exc:
				raise LlamaServerError(str(exc)) from exc

		client = self._get_worker_client()
		if client is None:
			raise LlamaServerError("Worker process is not available")

		cmd = {
			"type": "llama_restart",
			"command": "llama_restart",
			"model": model,
			"model_id": model_id,
			"models_preset": str(models_preset) if models_preset is not None else None,
			"threads": threads,
			"context": context,
			"timeout_seconds": timeout,
			"host": self.host,
			"port": self.port,
			"executable": self.executable,
			"startup_identity": startup_identity,
		}
		resp = client.send_command(cmd, timeout=timeout + 5.0)
		if not resp.get("success", False) or resp.get("type") == "error":
			err_msg = resp.get("error_message") or "Failed to restart llama-server"
			raise LlamaServerError(err_msg)

		with self._models_cache_lock:
			self._models_cache = None
		return _status_dict_to_namespace(resp.get("status", {}))

	def start(
		self,
		model: str,
		*,
		model_id: str | None = None,
		models_preset: str | Path | None = None,
		threads: int = 0,
		context: int = 0,
		on_progress: Callable[[str], None] | None = None,
	) -> None:
		self.ensure_ready(
			model,
			model_id=model_id,
			models_preset=models_preset,
			threads=threads,
			context=context,
			on_progress=on_progress,
		)

	def adopt(self, model_id: str | None = None) -> Any:
		native = self._get_native()
		if native is not None:
			try:
				status = native.adopt(model_id)
				with self._models_cache_lock:
					self._models_cache = None
				return status
			except RuntimeError as exc:
				raise LlamaServerError(str(exc)) from exc

		client = self._get_worker_client()
		if client is None:
			raise LlamaServerError("Worker process is not available")

		cmd = {
			"type": "llama_adopt",
			"command": "llama_adopt",
			"model_id": model_id,
		}
		resp = client.send_command(cmd, timeout=5.0)
		if not resp.get("success", False) or resp.get("type") == "error":
			raise LlamaServerError(resp.get("error_message") or "Failed to adopt llama-server")

		with self._models_cache_lock:
			self._models_cache = None
		return _status_dict_to_namespace(resp.get("status", {}))

	def is_healthy(self, timeout: float = 2.0) -> bool:
		try:
			request = urllib.request.Request(f"{self.base_url}/v1/models", method="GET")
			with urllib.request.urlopen(request, timeout=timeout) as response:
				return response.status == 200
		except (OSError, urllib.error.URLError):
			return False

	def wait_until_ready(
		self,
		timeout: float = 60.0,
		on_progress: Callable[[str], None] | None = None,
	) -> bool:
		del on_progress
		status = self.status()
		if not status.is_running and not status.is_adopted:
			raise LlamaServerError("llama-server exited before becoming ready")
		if not self.is_healthy():
			deadline = time.time() + timeout
			while time.time() < deadline:
				time.sleep(POLL_INTERVAL)
				status = self.status()
				if not status.is_running and not status.is_adopted:
					raise LlamaServerError("llama-server exited before becoming ready")
				if self.is_healthy():
					return True
			self.stop()
			return False
		return True

	def list_models(
		self,
		timeout: float = 1.5,
		*,
		refresh: bool = False,
	) -> tuple[dict[str, object], ...]:
		with self._models_cache_lock:
			if self._models_cache is not None and not refresh:
				return self._models_cache
		for path in ("/v1/models", "/models"):
			try:
				request = urllib.request.Request(f"{self.base_url}{path}", method="GET")
				with urllib.request.urlopen(request, timeout=timeout) as response:
					payload = json.loads(response.read().decode("utf-8"))
			except urllib.error.HTTPError as exc:
				if exc.code == 404:
					continue
				break
			except (OSError, urllib.error.URLError, json.JSONDecodeError):
				break
			items = payload.get("data") if isinstance(payload, dict) else None
			if isinstance(items, list):
				models = tuple(item for item in items if isinstance(item, dict))
				with self._models_cache_lock:
					self._models_cache = models
				return models
		return ()

	def stop(self) -> None:
		native = self._get_native()
		if native is not None:
			try:
				native.stop()
			except Exception:
				pass
		else:
			client = self._get_worker_client()
			if client is not None:
				try:
					client.send_command(
						{"type": "llama_stop", "command": "llama_stop", "timeout_seconds": 10.0},
						timeout=15.0,
					)
				except Exception:
					pass
		with self._models_cache_lock:
			self._models_cache = None

	def close(self) -> None:
		self.stop()

	def shutdown(self) -> None:
		try:
			self.stop()
		except Exception:
			pass
		with self._models_cache_lock:
			self._models_cache = None

	def _build_startup_identity(
		self,
		model: str,
		*,
		model_id: str | None,
		models_preset: str | Path | None,
		threads: int,
		context: int,
	) -> str:
		"""Snapshot every value that binds when ``llama-server`` starts."""
		preset_identity: tuple[str, str] | None = None
		if models_preset is not None:
			path = Path(models_preset).resolve()
			try:
				digest = hashlib.sha256(path.read_bytes()).hexdigest()
			except OSError:
				digest = ""
			preset_identity = (os.path.normcase(str(path)), digest)
		identity_data = {
			"model": None if preset_identity is not None else (model_id or model),
			"preset": preset_identity,
			"threads": max(0, int(threads)),
			"context": max(0, int(context)),
		}
		return json.dumps(identity_data, sort_keys=True)


def default_llama_server_executable() -> str:
	"""Resolve the executable without baking a machine-specific path in config."""
	return shutil.which(DEFAULT_LLAMA_SERVER) or DEFAULT_LLAMA_SERVER


_supervisors: dict[tuple[str, str, int], LlamaServerSupervisor] = {}
_supervisors_lock = threading.RLock()


def get_llama_supervisor(
	executable: str | Path = DEFAULT_LLAMA_SERVER,
	host: str = DEFAULT_LLAMA_HOST,
	port: int = DEFAULT_LLAMA_PORT,
	worker_client: Any | None = None,
) -> LlamaServerSupervisor:
	"""Return the application-owned supervisor for an endpoint."""
	if worker_client is not None:
		return LlamaServerSupervisor(
			executable=executable,
			host=host,
			port=port,
			worker_client=worker_client,
		)
	executable_text = str(executable)
	resolved_executable = shutil.which(executable_text) or executable_text
	key = (
		os.path.normcase(os.path.abspath(os.path.normpath(resolved_executable))),
		host.casefold(),
		port,
	)
	with _supervisors_lock:
		if key not in _supervisors:
			_supervisors[key] = LlamaServerSupervisor(
				executable=executable,
				host=host,
				port=port,
			)
		return _supervisors[key]


def shutdown_llama_servers() -> None:
	with _supervisors_lock:
		for supervisor in _supervisors.values():
			supervisor.shutdown()
		_supervisors.clear()
