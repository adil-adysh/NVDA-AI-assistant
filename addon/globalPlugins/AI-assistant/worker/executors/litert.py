# -*- coding: utf-8 -*-
"""LiteRT-LM Worker Host Executor.

Authoritative out-of-process executor hosting and managing the native PyO3
``runtime_supervisor.RuntimeSupervisor("litert-lm")`` extension and running
all LiteRT-LM CLI commands out-of-process within the worker process.

Enforces:
- Invariant A1: Zero heavy compute or long subprocess execution on NVDA threads.
- Invariant A7: Exactly one authoritative owner of runtime lifecycle (worker process).
- Invariant A8: Rust supervisor receives immutable runtime specifications.
- Invariant A16: Pure-Python process isolation, zero NVDA imports.
- Invariant A19: Fault isolation (process death trapped by supervisor, generations monotonic).
- Invariant A26: Windows Job Object child containment.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any
import urllib.error
import urllib.request

try:
	_addon_lib = Path(__file__).resolve().parent.parent.parent / "lib"
	if _addon_lib.is_dir() and str(_addon_lib) not in sys.path:
		sys.path.insert(0, str(_addon_lib))
	import runtime_supervisor
except Exception:
	runtime_supervisor = None

logger = logging.getLogger(__name__)

DEFAULT_LITERT_PORT = 9379
DEFAULT_LITERT_HOST = "127.0.0.1"
DEFAULT_LITERT_VERSION = "0.15.0"


def default_litert_dir() -> Path:
	"""Return the add-on-owned LiteRT-LM registry directory."""
	appdata = os.getenv("APPDATA")
	base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
	return base / "nvda" / "AIAssistant" / "litert-lm"


def default_runtime_dir(version: str = DEFAULT_LITERT_VERSION) -> Path:
	"""Return the path to the self-contained embeddable runtime directory."""
	appdata = os.getenv("APPDATA")
	base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
	return base / "nvda" / "AIAssistant" / "runtimes" / f"litert-lm-{version}"


def default_python_exe(version: str = DEFAULT_LITERT_VERSION) -> Path:
	"""Return the path to the python.exe inside the embeddable runtime."""
	return default_runtime_dir(version) / "python.exe"


def subprocess_flags() -> int:
	"""Return creationflags that suppress console window creation on Windows."""
	if sys.platform == "win32":
		return subprocess.CREATE_NO_WINDOW  # 0x08000000
	return 0


def validate_model_id(model_id: str) -> str:
	"""Validate a model ID to prevent path traversal or invalid characters."""
	value = str(model_id or "").strip()
	if (
		not value
		or any(ord(char) < 0x20 for char in value)
		or "\\" in value
		or any(part in {"", ".", ".."} for part in value.split("/"))
	):
		raise ValueError(f"Invalid model ID: {model_id!r}")
	return value


def serialize_runtime_status(status: Any) -> dict[str, Any]:
	"""Convert a Rust PyO3 RuntimeStatus or duck-typed object into a JSON-safe dict."""
	if isinstance(status, dict):
		return status
	return {
		"state": str(getattr(status, "state", "stopped")),
		"is_ready": bool(getattr(status, "is_ready", False)),
		"is_running": bool(getattr(status, "is_running", False)),
		"is_adopted": bool(getattr(status, "is_adopted", False)),
		"pid": getattr(status, "pid", None),
		"generation": int(getattr(status, "generation", 0)),
		"error_message": getattr(status, "error_message", None),
		"startup_identity": getattr(status, "startup_identity", None),
		"running_model": getattr(status, "running_model", None),
		"base_url": str(getattr(status, "base_url", "")),
	}


class LiteRTWorkerExecutor:
	"""Out-of-process executor for LiteRT-LM runtime supervisor and CLI commands."""

	def __init__(
		self,
		host: str = DEFAULT_LITERT_HOST,
		port: int = DEFAULT_LITERT_PORT,
		supervisor: Any | None = None,
	) -> None:
		self.host = host
		self.port = port
		self._config_lock = threading.Lock()
		self._supervisor = supervisor

		if self._supervisor is None and runtime_supervisor is not None and hasattr(runtime_supervisor, "RuntimeSupervisor"):
			try:
				self._supervisor = runtime_supervisor.RuntimeSupervisor(
					"litert-lm", host=self.host, port=self.port
				)
			except Exception as exc:
				logger.warning("Could not initialize native RuntimeSupervisor('litert-lm'): %s", exc)

	def _get_supervisor(self) -> Any:
		if self._supervisor is not None:
			if (
				runtime_supervisor is not None
				and hasattr(runtime_supervisor, "RuntimeSupervisor")
				and isinstance(self._supervisor, runtime_supervisor.RuntimeSupervisor)
			):
				cur_host = getattr(self._supervisor, "host", None)
				cur_port = getattr(self._supervisor, "port", None)
				if cur_host != self.host or cur_port != self.port:
					self._supervisor = runtime_supervisor.RuntimeSupervisor(
						"litert-lm", host=self.host, port=self.port
					)
			return self._supervisor
		if runtime_supervisor is not None and hasattr(runtime_supervisor, "RuntimeSupervisor"):
			self._supervisor = runtime_supervisor.RuntimeSupervisor(
				"litert-lm", host=self.host, port=self.port
			)
			return self._supervisor
		raise RuntimeError("Native PyO3 runtime_supervisor is not available")

	def get_status(self) -> dict[str, Any]:
		"""Return snapshot of runtime status."""
		if self._supervisor is not None:
			return serialize_runtime_status(self._supervisor.status())
		url_host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
		return {
			"state": "stopped",
			"is_ready": False,
			"is_running": False,
			"is_adopted": False,
			"pid": None,
			"generation": 0,
			"error_message": None,
			"startup_identity": None,
			"running_model": None,
			"base_url": f"http://{url_host}:{self.port}",
		}

	def ensure_ready(
		self,
		config: dict[str, Any] | None = None,
		timeout_seconds: float = 60.0,
		python_exe: Path | str | None = None,
		litert_dir: Path | str | None = None,
		version: str = DEFAULT_LITERT_VERSION,
		host: str | None = None,
		port: int | None = None,
	) -> dict[str, Any]:
		"""Atomically ensure the LiteRT server is running and healthy."""
		if host is not None:
			self.host = str(host)
		if port is not None:
			self.port = int(port)

		sup = self._get_supervisor()

		py_path = Path(python_exe) if python_exe else default_python_exe(version)
		lt_dir = Path(litert_dir) if litert_dir else default_litert_dir()

		# Write config.json
		with self._config_lock:
			lt_dir.mkdir(parents=True, exist_ok=True)
			cfg_path = lt_dir / "config.json"
			if config:
				cfg_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
			elif cfg_path.is_file():
				try:
					cfg_path.unlink()
				except OSError:
					pass

		identity_payload = {
			"config": config or {},
			"host": self.host,
			"port": self.port,
			"python": str(py_path).lower(),
			"version": version,
		}
		startup_identity = json.dumps(identity_payload, sort_keys=True)

		cmd_args = ["-m", "litert_lm_cli.main", "serve", "--host", self.host, "--port", str(self.port)]
		env = {**os.environ, "LITERT_LM_DIR": str(lt_dir)}

		status = sup.ensure_ready(
			str(py_path),
			cmd_args,
			env,
			startup_identity,
			timeout_seconds=timeout_seconds,
		)
		return serialize_runtime_status(status)

	def restart(
		self,
		config: dict[str, Any] | None = None,
		timeout_seconds: float = 60.0,
		python_exe: Path | str | None = None,
		litert_dir: Path | str | None = None,
		version: str = DEFAULT_LITERT_VERSION,
		host: str | None = None,
		port: int | None = None,
	) -> dict[str, Any]:
		"""Restart the LiteRT server with updated configuration."""
		if host is not None:
			self.host = str(host)
		if port is not None:
			self.port = int(port)

		sup = self._get_supervisor()

		py_path = Path(python_exe) if python_exe else default_python_exe(version)
		lt_dir = Path(litert_dir) if litert_dir else default_litert_dir()

		with self._config_lock:
			lt_dir.mkdir(parents=True, exist_ok=True)
			cfg_path = lt_dir / "config.json"
			if config:
				cfg_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
			elif cfg_path.is_file():
				try:
					cfg_path.unlink()
				except OSError:
					pass

		identity_payload = {
			"config": config or {},
			"host": self.host,
			"port": self.port,
			"python": str(py_path).lower(),
			"version": version,
		}
		startup_identity = json.dumps(identity_payload, sort_keys=True)

		cmd_args = ["-m", "litert_lm_cli.main", "serve", "--host", self.host, "--port", str(self.port)]
		env = {**os.environ, "LITERT_LM_DIR": str(lt_dir)}

		status = sup.restart(
			str(py_path),
			cmd_args,
			env,
			startup_identity,
			timeout_seconds=timeout_seconds,
		)
		return serialize_runtime_status(status)

	def stop(self, timeout_seconds: float = 10.0) -> dict[str, Any]:
		"""Stop the server process gracefully, then forcefully if needed."""
		if self._supervisor is None:
			return self.get_status()
		status = self._supervisor.stop(timeout_seconds=timeout_seconds)
		return serialize_runtime_status(status)

	def adopt(self) -> dict[str, Any]:
		"""Acknowledge a healthy server running on host:port without owned child process."""
		sup = self._get_supervisor()
		status = sup.adopt()
		return serialize_runtime_status(status)

	def _run_cli(
		self,
		args: list[str],
		python_exe: Path | str | None = None,
		litert_dir: Path | str | None = None,
		version: str = DEFAULT_LITERT_VERSION,
		timeout_seconds: float = 120.0,
	) -> subprocess.CompletedProcess[str]:
		"""Execute a LiteRT CLI command via the bundled Python executable."""
		py_path = Path(python_exe) if python_exe else default_python_exe(version)
		lt_dir = Path(litert_dir) if litert_dir else default_litert_dir()

		lt_dir.mkdir(parents=True, exist_ok=True)
		env = {**os.environ, "LITERT_LM_DIR": str(lt_dir)}

		cmd = [str(py_path), "-m", "litert_lm_cli.main", *args]
		logger.debug("Executing LiteRT CLI command: %s", cmd)

		return subprocess.run(
			cmd,
			env=env,
			capture_output=True,
			text=True,
			timeout=timeout_seconds,
			creationflags=subprocess_flags(),
			check=False,
		)

	def import_model(
		self,
		model_path: str | Path,
		model_id: str,
		delete_source: bool = False,
		timeout_seconds: float = 120.0,
		python_exe: Path | str | None = None,
		litert_dir: Path | str | None = None,
		version: str = DEFAULT_LITERT_VERSION,
	) -> dict[str, Any]:
		"""Import a local model file into the LiteRT model registry."""
		src_path = Path(model_path)
		if not src_path.is_file():
			raise FileNotFoundError(f"Source model file does not exist: {src_path}")

		clean_id = validate_model_id(model_id)
		lt_dir = Path(litert_dir) if litert_dir else default_litert_dir()

		result = self._run_cli(
			["import", str(src_path), clean_id],
			python_exe=python_exe,
			litert_dir=lt_dir,
			version=version,
			timeout_seconds=timeout_seconds,
		)

		if result.returncode != 0:
			stderr = (result.stderr or "").strip()
			stdout = (result.stdout or "").strip()
			err = stderr or stdout or f"Exit code {result.returncode}"
			raise RuntimeError(f"Model import failed for {clean_id}: {err}")

		# Optionally delete source cache file after successful import
		dest_file = lt_dir / "models" / clean_id.replace("/", "--") / "model.litertlm"
		if delete_source and dest_file.is_file():
			try:
				if src_path.resolve() != dest_file.resolve():
					src_path.unlink(missing_ok=True)
			except OSError as exc:
				logger.debug("Could not delete source file %s: %s", src_path, exc)

		return {
			"success": True,
			"model_id": clean_id,
			"imported_path": str(dest_file) if dest_file.exists() else str(src_path),
		}

	def import_huggingface_model(
		self,
		repository: str,
		artifact: str,
		model_id: str,
		token: str | None = None,
		timeout_seconds: float = 600.0,
		python_exe: Path | str | None = None,
		litert_dir: Path | str | None = None,
		version: str = DEFAULT_LITERT_VERSION,
	) -> dict[str, Any]:
		"""Import a Hugging Face model repository artifact."""
		clean_id = validate_model_id(model_id)
		if not repository or not artifact:
			raise ValueError("Repository and artifact are required for Hugging Face import")

		cli_args = ["import", "--from-huggingface-repo", repository, artifact, clean_id]
		if token:
			cli_args.extend(["--huggingface-token", token])

		result = self._run_cli(
			cli_args,
			python_exe=python_exe,
			litert_dir=litert_dir,
			version=version,
			timeout_seconds=timeout_seconds,
		)

		if result.returncode != 0:
			stderr = (result.stderr or "").strip()
			stdout = (result.stdout or "").strip()
			err = stderr or stdout or f"Exit code {result.returncode}"
			raise RuntimeError(f"Hugging Face import failed for {repository}: {err}")

		return {"success": True, "model_id": clean_id}

	def delete_model(
		self,
		model_id: str,
		timeout_seconds: float = 60.0,
		python_exe: Path | str | None = None,
		litert_dir: Path | str | None = None,
		version: str = DEFAULT_LITERT_VERSION,
	) -> dict[str, Any]:
		"""Unregister a model from the LiteRT catalog."""
		clean_id = validate_model_id(model_id)
		result = self._run_cli(
			["delete", clean_id],
			python_exe=python_exe,
			litert_dir=litert_dir,
			version=version,
			timeout_seconds=timeout_seconds,
		)

		if result.returncode != 0:
			stderr = (result.stderr or "").strip()
			stdout = (result.stdout or "").strip()
			err = stderr or stdout or f"Exit code {result.returncode}"
			raise RuntimeError(f"Model deletion failed for {clean_id}: {err}")

		return {"success": True, "model_id": clean_id}

	def rename_model(
		self,
		old_id: str,
		new_id: str,
		timeout_seconds: float = 30.0,
		python_exe: Path | str | None = None,
		litert_dir: Path | str | None = None,
		version: str = DEFAULT_LITERT_VERSION,
	) -> dict[str, Any]:
		"""Rename a registered model in the LiteRT catalog."""
		clean_old = validate_model_id(old_id)
		clean_new = validate_model_id(new_id)

		result = self._run_cli(
			["rename", clean_old, clean_new],
			python_exe=python_exe,
			litert_dir=litert_dir,
			version=version,
			timeout_seconds=timeout_seconds,
		)

		if result.returncode != 0:
			stderr = (result.stderr or "").strip()
			stdout = (result.stdout or "").strip()
			err = stderr or stdout or f"Exit code {result.returncode}"
			raise RuntimeError(f"Model rename failed for {clean_old} -> {clean_new}: {err}")

		return {"success": True, "old_id": clean_old, "new_id": clean_new}

	def list_models(
		self,
		timeout_seconds: float = 5.0,
		litert_dir: Path | str | None = None,
	) -> list[str]:
		"""List all registered models on the server or on disk."""
		url_host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
		# 1. Try querying /v1/models if server is reachable
		try:
			url = f"http://{url_host}:{self.port}/v1/models"
			req = urllib.request.Request(url, method="GET")
			with urllib.request.urlopen(req, timeout=min(2.0, timeout_seconds)) as resp:
				if resp.status == 200:
					data = json.loads(resp.read().decode("utf-8"))
					if isinstance(data, dict) and isinstance(data.get("data"), list):
						return [
							str(m["id"])
							for m in data["data"]
							if isinstance(m, dict) and "id" in m
						]
		except Exception:
			pass

		# 2. Fallback to on-disk model directories
		lt_dir = Path(litert_dir) if litert_dir else default_litert_dir()
		models_dir = lt_dir / "models"
		if not models_dir.is_dir():
			return []

		found: list[str] = []
		for entry in models_dir.iterdir():
			if entry.is_dir() and (entry / "model.litertlm").is_file():
				found.append(entry.name.replace("--", "/"))
		return sorted(found)
