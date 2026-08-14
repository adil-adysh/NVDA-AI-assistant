# -*- coding: utf-8 -*-
"""Managed ``llama-server`` runtime.

The application talks to llama.cpp through its OpenAI-compatible HTTP API.
This module owns process lifecycle and command construction so the rest of
the provider layer never needs to know how a GGUF model is launched.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from ..interfaces import LLMProviderError
from .lifecycle import wait_for_server_ready

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


class LlamaServerSupervisor:
	"""Thread-safe lifecycle manager for one llama-server endpoint."""

	def __init__(
		self,
		*,
		executable: str | Path = DEFAULT_LLAMA_SERVER,
		host: str = DEFAULT_LLAMA_HOST,
		port: int = DEFAULT_LLAMA_PORT,
		process_factory: Callable[..., subprocess.Popen[str]] | None = None,
	) -> None:
		self.executable = str(executable)
		self.host = host
		self.port = port
		self._process_factory = process_factory or subprocess.Popen
		self._process: subprocess.Popen[str] | None = None
		self._running_model: str | None = None
		self._adopted = False
		self._lock = threading.RLock()

	@property
	def base_url(self) -> str:
		return f"http://{self.host}:{self.port}"

	@property
	def is_running(self) -> bool:
		return self._process is not None and self._process.poll() is None

	@property
	def is_adopted(self) -> bool:
		return self._adopted

	@property
	def running_model(self) -> str | None:
		return self._running_model

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
		with self._lock:
			if self.is_running:
				if self._running_model == (model_id or model):
					return
				self.stop()
			command = [
				self.executable,
				*build_llama_server_args(
					model,
					host=self.host,
					port=self.port,
					models_preset=models_preset,
					alias=model_id if models_preset is None else None,
					threads=threads,
					context=context,
				),
			]
			if on_progress:
				on_progress(f"Starting llama-server for {model_id or model}...")
			try:
				self._process = self._process_factory(
					command,
					stdout=subprocess.DEVNULL,
					stderr=subprocess.DEVNULL,
					text=True,
					creationflags=_creation_flags(),
				)
			except OSError as exc:
				raise LlamaServerError(
					f"Could not start llama-server ({self.executable!r}). "
					"Install llama.cpp and ensure llama-server is on PATH."
				) from exc
			self._running_model = model_id or model
			self._adopted = False

	def adopt(self, model_id: str | None = None) -> None:
		with self._lock:
			if self.is_running:
				return
			self._adopted = True
			self._running_model = model_id

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
		try:
			return wait_for_server_ready(
				is_running=lambda: self.is_running,
				is_adopted=lambda: self.is_adopted,
				is_healthy=self.is_healthy,
				stop=self.stop,
				timeout=timeout,
				interval=POLL_INTERVAL,
				on_progress=on_progress,
				progress_message="Waiting for llama-server to become ready...",
				exit_message="llama-server exited before becoming ready",
			)
		except RuntimeError as exc:
			raise LlamaServerError(str(exc)) from exc

	def list_models(self, timeout: float = 5.0) -> tuple[dict[str, object], ...]:
		try:
			request = urllib.request.Request(f"{self.base_url}/v1/models", method="GET")
			with urllib.request.urlopen(request, timeout=timeout) as response:
				payload = json.loads(response.read().decode("utf-8"))
		except (OSError, urllib.error.URLError, json.JSONDecodeError):
			return ()
		items = payload.get("data") if isinstance(payload, dict) else None
		if not isinstance(items, list):
			return ()
		return tuple(item for item in items if isinstance(item, dict))

	def stop(self) -> None:
		with self._lock:
			process = self._process
			if process is not None and process.poll() is None:
				process.terminate()
				try:
					process.wait(timeout=10)
				except subprocess.TimeoutExpired:
					process.kill()
					process.wait(timeout=5)
			self._process = None
			self._running_model = None
			self._adopted = False

	def close(self) -> None:
		self.stop()

	def shutdown(self) -> None:
		self.stop()


def default_llama_server_executable() -> str:
	"""Resolve the executable without baking a machine-specific path in config."""
	return shutil.which(DEFAULT_LLAMA_SERVER) or DEFAULT_LLAMA_SERVER


_supervisors: dict[tuple[str, str, int], LlamaServerSupervisor] = {}
_supervisors_lock = threading.RLock()


def get_llama_supervisor(
	executable: str | Path = DEFAULT_LLAMA_SERVER,
	host: str = DEFAULT_LLAMA_HOST,
	port: int = DEFAULT_LLAMA_PORT,
) -> LlamaServerSupervisor:
	"""Return the application-owned supervisor for an endpoint."""
	key = (str(executable), host, port)
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
