# -*- coding: utf-8 -*-
"""llama-server Worker Host Executor.

Authoritative out-of-process executor hosting and managing the native PyO3
``runtime_supervisor.RuntimeSupervisor("llama-server")`` extension and
coordinating router preset generation within the worker process.

Enforces:
- Invariant A1: Zero heavy compute or long subprocess execution on NVDA threads.
- Invariant A7: Exactly one authoritative owner of runtime lifecycle (worker process).
- Invariant A8: Rust supervisor receives immutable runtime specifications via json startup identity.
- Invariant A16: Pure-Python process isolation, zero NVDA imports.
- Invariant A19: Fault isolation (process death trapped by supervisor, generations monotonic).
- Invariant A26: Windows Job Object child containment.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
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

try:
	from ...core.job.execution import check_job_cancelled
	from ...core.translation import _
	from ...core.llama_options import canonical_key, OPTION_BY_KEY
except ImportError:
	from core.job.execution import check_job_cancelled
	from core.translation import _
	from core.llama_options import canonical_key, OPTION_BY_KEY

logger = logging.getLogger(__name__)

DEFAULT_LLAMA_HOST = "127.0.0.1"
DEFAULT_LLAMA_PORT = 8080
DEFAULT_LLAMA_SERVER = "llama-server"

_SECTION_RE = re.compile(r"^\[([^\]\r\n]+)\]\s*$")


def default_preset_dir() -> Path:
	"""Return the add-on-owned llama-cpp models directory."""
	appdata = os.getenv("APPDATA")
	base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
	return base / "nvda" / "AIAssistant" / "models" / "llama-cpp"


def default_preset_file() -> Path:
	"""Keep generated output separate from legacy migration input."""
	return default_preset_dir() / "runtime-models.ini"


def subprocess_flags() -> int:
	"""Return creationflags that suppress console window creation on Windows."""
	if sys.platform == "win32":
		return subprocess.CREATE_NO_WINDOW  # 0x08000000
	return 0


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
	"""Build safe, provider-owned llama-server arguments without a shell."""
	model_str = str(model or "").strip()
	if not model_str and models_preset is None:
		raise ValueError("A GGUF model or models_preset is required")
	args = ["--host", host, "--port", str(port)]
	if models_preset is not None:
		args.extend(["--models-preset", str(models_preset)])
	if models_preset is None:
		if model_str.startswith("hf://"):
			args.extend(["-hf", model_str[5:]])
		else:
			args.extend(["-m", model_str])
	if alias:
		args.extend(["--alias", str(alias)])
	if threads >= 1:
		args.extend(["-t", str(threads)])
	if context >= 1:
		args.extend(["-c", str(context)])
	return args


def build_startup_identity(
	model: str | None = None,
	*,
	model_id: str | None = None,
	models_preset: str | Path | None = None,
	threads: int = 0,
	context: int = 0,
) -> str:
	"""Snapshot every value that binds when llama-server starts."""
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


try:
	from ...core.llama_preset import LlamaPresetCodec, build_models_preset as build_models_preset, merge_models_preset as merge_models_preset
except ImportError:
	from core.llama_preset import LlamaPresetCodec, build_models_preset as build_models_preset, merge_models_preset as merge_models_preset


class LlamaWorkerExecutor:
	"""Out-of-process executor for llama-server runtime supervisor and router preset generation."""

	def __init__(
		self,
		host: str = DEFAULT_LLAMA_HOST,
		port: int = DEFAULT_LLAMA_PORT,
		supervisor: Any | None = None,
		owned_cache_root: Path | None = None,
	) -> None:
		self.host = host
		self.port = port
		self._supervisor = supervisor
		self._preset_lock = threading.Lock()
		self._option_cache = {}
		self._spec_modes = None
		self._preparation_lock = threading.Lock()
		self._preparations = {}
		self._owned_cache_root = (owned_cache_root or (default_preset_dir() / "cache")).resolve()

		if self._supervisor is None and runtime_supervisor is not None and hasattr(runtime_supervisor, "RuntimeSupervisor"):
			try:
				self._supervisor = runtime_supervisor.RuntimeSupervisor(
					"llama-server", host=self.host, port=self.port
				)
			except Exception as exc:
				logger.warning("Could not initialize native RuntimeSupervisor('llama-server'): %s", exc)

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
					try:
						self._supervisor.stop()
					except Exception:
						pass
					self._supervisor = runtime_supervisor.RuntimeSupervisor(
						"llama-server", host=self.host, port=self.port
					)
			return self._supervisor
		if runtime_supervisor is not None and hasattr(runtime_supervisor, "RuntimeSupervisor"):
			self._supervisor = runtime_supervisor.RuntimeSupervisor(
				"llama-server", host=self.host, port=self.port
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
		model_id: str | None = None,
		timeout_seconds: float = 60.0,
		host: str | None = None,
		port: int | None = None,
		executable: str | Path | None = None,
		model: str | None = None,
		models_preset: str | Path | None = None,
		threads: int = 0,
		context: int = 0,
		alias: str | None = None,
		startup_identity: str | None = None,
	) -> dict[str, Any]:
		"""Atomically ensure the llama-server is running and healthy."""
		# A new use/startup supersedes cleanup from any abandoned preparation.
		with self._preparation_lock:
			self._preparations.clear()
		if host is not None:
			self.host = str(host)
		if port is not None:
			self.port = int(port)

		cfg = config or {}
		model = model or cfg.get("model") or cfg.get("server_model")
		model_id = model_id or cfg.get("model_id")
		models_preset = models_preset or cfg.get("models_preset") or cfg.get("preset_path")
		if not model and model_id and not models_preset:
			model = model_id

		threads = threads or int(cfg.get("threads", 0))
		context = context or int(cfg.get("context", 0) or cfg.get("num_ctx", 0))
		executable = executable or cfg.get("executable") or cfg.get("server_executable")
		alias = alias or cfg.get("alias") or (model_id if models_preset is None else None)

		exe_str = str(executable) if executable else (shutil.which(DEFAULT_LLAMA_SERVER) or DEFAULT_LLAMA_SERVER)

		args = build_llama_server_args(
			model=model,
			host=self.host,
			port=self.port,
			models_preset=models_preset,
			alias=alias,
			threads=threads,
			context=context,
		)

		identity = startup_identity or build_startup_identity(
			model=model,
			model_id=model_id,
			models_preset=models_preset,
			threads=threads,
			context=context,
		)

		env = dict(os.environ)
		sup = self._get_supervisor()

		check_job_cancelled()
		status = sup.ensure_ready(
			exe_str,
			args,
			env,
			identity,
			running_model=model_id or model,
			timeout_seconds=timeout_seconds,
		)
		return serialize_runtime_status(status)

	def restart(
		self,
		config: dict[str, Any] | None = None,
		timeout_seconds: float = 60.0,
		host: str | None = None,
		port: int | None = None,
		executable: str | Path | None = None,
		model: str | None = None,
		model_id: str | None = None,
		models_preset: str | Path | None = None,
		threads: int = 0,
		context: int = 0,
		alias: str | None = None,
		startup_identity: str | None = None,
	) -> dict[str, Any]:
		"""Restart the llama-server with fresh configuration."""
		if host is not None:
			self.host = str(host)
		if port is not None:
			self.port = int(port)

		cfg = config or {}
		model = model or cfg.get("model") or cfg.get("server_model")
		model_id = model_id or cfg.get("model_id")
		models_preset = models_preset or cfg.get("models_preset") or cfg.get("preset_path")
		if not model and model_id and not models_preset:
			model = model_id

		threads = threads or int(cfg.get("threads", 0))
		context = context or int(cfg.get("context", 0) or cfg.get("num_ctx", 0))
		executable = executable or cfg.get("executable") or cfg.get("server_executable")
		alias = alias or cfg.get("alias") or (model_id if models_preset is None else None)

		exe_str = str(executable) if executable else (shutil.which(DEFAULT_LLAMA_SERVER) or DEFAULT_LLAMA_SERVER)

		args = build_llama_server_args(
			model=model,
			host=self.host,
			port=self.port,
			models_preset=models_preset,
			alias=alias,
			threads=threads,
			context=context,
		)

		identity = startup_identity or build_startup_identity(
			model=model,
			model_id=model_id,
			models_preset=models_preset,
			threads=threads,
			context=context,
		)

		env = dict(os.environ)
		sup = self._get_supervisor()

		check_job_cancelled()
		status = sup.restart(
			exe_str,
			args,
			env,
			identity,
			running_model=model_id or model,
			timeout_seconds=timeout_seconds,
		)
		return serialize_runtime_status(status)

	def stop(self, timeout_seconds: float = 10.0) -> dict[str, Any]:
		"""Stop the server process gracefully, then forcefully if needed."""
		if self._supervisor is None:
			return self.get_status()
		status = self._supervisor.stop(timeout_seconds=timeout_seconds)
		return serialize_runtime_status(status)

	def adopt(self, model_id: str | None = None) -> dict[str, Any]:
		"""Acknowledge a healthy server running on host:port without owned child process."""
		sup = self._get_supervisor()
		status = sup.adopt(model_id=model_id)
		return serialize_runtime_status(status)

	def delete_cache(self, cache_root: str, path: str, model_id: str | None = None) -> dict[str, Any]:
		"""Delete only a recorded owned GGUF under the worker's authoritative root."""
		root = self._owned_cache_root
		target = Path(path).resolve()
		if Path(cache_root).resolve() != root or not target.is_relative_to(root) or target == root or target.suffix.lower() != ".gguf":
			raise ValueError(_("Model cache deletion target is outside the owned cache directory"))
		owned = False
		for manifest in root.parent.glob("models*.json"):
			try:
				payload = json.loads(manifest.read_text(encoding="utf-8"))
			except (OSError, ValueError) as error:
				raise ValueError(_("Unable to verify model catalog dependencies before deletion.")) from error
			if not isinstance(payload, dict) or payload.get("version") != 1:
				continue
			for record in payload.get("models", []):
				if not isinstance(record, dict):
					continue
				if record.get("model_id") == model_id and record.get("ownership") == "addon" and record.get("cached_path"):
					owned = owned or Path(record["cached_path"]).resolve() == target
				if record.get("model_id") == model_id:
					continue
				references = [record.get(key) for key in ("source", "local_path", "cached_path")]
				options = record.get("preset_options") or {}
				if isinstance(options, dict):
					references.extend(options.get(key) for key in ("mmproj", "spec-draft-model", "model-draft"))
				for companion in record.get("companions") or ():
					if isinstance(companion, dict):
						references.extend(companion.get(key) for key in ("source", "local_path"))
				for reference in references:
					if isinstance(reference, str) and reference and Path(reference).resolve() == target:
						raise ValueError(_("This file is referenced by another model configuration."))
		if not owned:
			raise ValueError(_("The cached model file has no add-on ownership record"))
		check_job_cancelled()
		target.unlink(missing_ok=True)
		return {"success": True}

	def _model_request(self, operation: str, model_id: str, timeout_seconds: float):
		url_host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
		request = urllib.request.Request(f"http://{url_host}:{self.port}/models/{operation}",
			data=json.dumps({"model": model_id}).encode(), headers={"Content-Type": "application/json"}, method="POST")
		with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
			return json.load(response)

	def prepare_model(self, model_id: str, timeout_seconds: float = 300, on_stage=None):
		"""Load explicitly, without claiming router health means model readiness."""
		before = self.get_status()
		if not before.get("is_running") or before.get("is_adopted"):
			raise ValueError(_("Model preparation is available only for an add-on-owned server."))
		check_job_cancelled()
		finished, stopped = threading.Event(), threading.Event()
		token = object()
		with self._preparation_lock:
			self._preparations[model_id] = token
		initial = next((item for item in self.list_models(timeout_seconds=0.5) if str(item.get("id", "")) == model_id), None)
		initial_status = initial.get("status") if initial else None
		if isinstance(initial_status, dict) and initial_status.get("value") == "loaded":
			check_job_cancelled()
			return {"success": True, "state": "loaded"}
		errors = []
		def unload():
			with self._preparation_lock:
				if self._preparations.get(model_id) is not token:
					return
				try:
					current = self.get_status()
					if current.get("generation") == before.get("generation") and current.get("pid") == before.get("pid") and not current.get("is_adopted"):
						self._model_request("unload", model_id, 2)
				except Exception:
					logger.debug("Unable to unload stopped preparation", exc_info=True)
		def load():
			try:
				self._model_request("load", model_id, timeout_seconds)
			except Exception as error:
				errors.append(error)
			finally:
				finished.set()
				if stopped.is_set():
					unload()
		if on_stage:
			on_stage("loading_model")
		threading.Thread(target=load, daemon=True, name="llama-prepare-request").start()
		deadline = time.monotonic() + timeout_seconds
		try:
			while time.monotonic() < deadline:
				check_job_cancelled()
				if errors:
					raise ValueError(_("Model preparation failed: {error}").format(error=errors[0]))
				items = self.list_models(timeout_seconds=0.5)
				item = next((item for item in items if str(item.get("id", "")) == model_id), None)
				status = item.get("status") if item else None
				status = status if isinstance(status, dict) else {}
				if status.get("failed"):
					raise ValueError(_("Model loading failed. Edit runtime settings or choose another model."))
				if status.get("value") == "loaded":
					return {"success": True, "state": "loaded"}
				stopped.wait(0.1)
			raise ValueError(_("Timed out waiting for the model to load."))
		except BaseException:
			stopped.set()
			unload()
			raise

	def resolve_hf(self, repo, revision="main", role="primary"):
		from .llama_hf import resolve_hf
		return resolve_hf(repo, revision, role)

	def resolve_companions(self, companions, on_stage=None):
		from .llama_hf import resolve_companions
		return resolve_companions(companions, on_stage=on_stage)

	def unload_model(self, model_id: str, timeout_seconds: float = 30, on_stage=None):
		"""Confirm the owned router has unloaded this exact model, with a bound."""
		if not str(model_id).strip():
			raise ValueError(_("A model ID is required for unload."))
		before = self.get_status()
		if not before.get("is_running") or before.get("is_adopted"):
			raise ValueError(_("Model unload is available only for an add-on-owned server."))
		with self._preparation_lock:
			self._preparations.pop(model_id, None)
		timeout = min(30.0, max(0.01, float(timeout_seconds)))
		deadline = time.monotonic() + timeout
		check_job_cancelled()
		if on_stage:
			on_stage("unloading_model")
		response = self._model_request("unload", model_id, min(2.0, timeout))
		if isinstance(response, dict) and response.get("success") is False:
			raise ValueError(_("The server rejected the model unload request."))
		while time.monotonic() < deadline:
			check_job_cancelled()
			current = self.get_status()
			if current.get("generation") != before.get("generation") or current.get("pid") != before.get("pid") or current.get("is_adopted"):
				raise ValueError(_("The owned server changed while unloading the model."))
			items = self.list_models(timeout_seconds=min(0.5, max(0.001, (deadline-time.monotonic())/2)))
			item = next((item for item in items if str(item.get("id", "")) == model_id), None)
			status = item.get("status") if item else None
			if isinstance(status, dict) and status.get("value") == "unloaded":
				return {"success": True, "state": "unloaded", "model_id": model_id}
			time.sleep(min(0.1, max(0, deadline-time.monotonic())))
		raise ValueError(_("Unable to observe the model unloaded before the timeout."))

	def inspect_options(self, executable: str) -> set[str]:
		"""Inspect the installed binary in the worker; cache by file identity."""
		path = Path(shutil.which(executable) or executable).resolve()
		shim = path.with_suffix(".shim")
		if shim.is_file():
			for line in shim.read_text(encoding="utf-8").splitlines():
				if line.startswith("path = "):
					candidate = Path(line.split("=", 1)[1].strip().strip('"'))
					if candidate.is_file():
						path = candidate.resolve()
					break
		stat = path.stat()
		identity = (str(path), stat.st_mtime_ns, stat.st_size)
		if identity in self._option_cache:
			return set(self._option_cache[identity])
		check_job_cancelled()
		process = subprocess.Popen([str(path), "--help"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess_flags())
		deadline = time.monotonic() + 5.0
		try:
			while True:
				check_job_cancelled()
				if time.monotonic() >= deadline:
					raise ValueError(_("Timed out checking supported llama.cpp runtime options."))
				try:
					output, unused = process.communicate(timeout=0.1)
					break
				except subprocess.TimeoutExpired:
					continue
		finally:
			if process.poll() is None:
				process.kill()
				process.communicate()
		if process.returncode != 0:
			raise ValueError(_("Unable to check supported llama.cpp runtime options. Check the server executable."))
		help_text = output.decode("utf-8", errors="replace")
		mode_match = re.search(r"--spec-type\s+([a-z0-9,-]+)", help_text)
		self._spec_modes = frozenset(mode_match.group(1).split(",")) if mode_match else frozenset()
		keys = {canonical_key(key) for key in re.findall(r"(?<!\w)--([a-z][a-z0-9-]+)", output.decode("utf-8", errors="replace"))}
		# These are documented router preset options, absent from CLI help.
		keys.update({"load-on-startup", "stop-timeout", "dedup-cache-models"})
		supported = keys & OPTION_BY_KEY.keys()
		self._option_cache = {identity: frozenset(supported)}
		return supported

	def configure_preset(
		self,
		models: list[dict[str, Any]] | list[Any],
		default_model: str | None = None,
		preset_path: str | Path | None = None,
		executable: str | None = None,
	) -> dict[str, Any]:
		"""Generate and write a llama-server router preset models.ini atomically."""
		target_path = Path(preset_path) if preset_path else default_preset_file()
		with self._preset_lock:
			target_path.parent.mkdir(parents=True, exist_ok=True)

			ordered_models = list(models)
			if default_model:
				def_id = str(default_model).strip()
				def_match = None
				remaining = []
				for m in ordered_models:
					m_id = m.get("model_id") if isinstance(m, dict) else getattr(m, "model_id", "")
					if str(m_id).strip() == def_id and def_match is None:
						def_match = m
					else:
						remaining.append(m)
				if def_match is not None:
					ordered_models = [def_match, *remaining]

			# The catalog is authoritative. Never merge stale generated files.
			content = LlamaPresetCodec().encode(ordered_models)
			if executable:
				supported = self.inspect_options(executable)
				requested_modes = {line.split("=", 1)[1].strip() for line in content.splitlines() if line.startswith("spec-type =")}
				if self._spec_modes is not None and requested_modes - self._spec_modes:
					raise ValueError(_("The installed llama.cpp runtime does not support speculative modes: {modes}.").format(modes=", ".join(sorted(requested_modes - self._spec_modes))))
				used = {line.split("=", 1)[0].strip() for line in content.splitlines() if "=" in line}
				unsupported = sorted((used & OPTION_BY_KEY.keys()) - supported)
				if unsupported:
					raise ValueError(_("The installed llama.cpp runtime does not support: {options}. Update the runtime or reset these model settings.").format(options=", ".join(unsupported)))

			fd, temp_file = tempfile.mkstemp(prefix="models-", suffix=".ini", dir=target_path.parent)
			try:
				with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
					handle.write(content)
				Path(temp_file).replace(target_path)
			except Exception:
				try:
					Path(temp_file).unlink(missing_ok=True)
				except OSError:
					pass
				raise

			content_bytes = target_path.read_bytes()
			sha256_hash = hashlib.sha256(content_bytes).hexdigest()

		return {
			"success": True,
			"preset_path": str(target_path),
			"sha256": sha256_hash,
		}

	def list_models(
		self,
		timeout_seconds: float = 2.0,
		preset_path: str | Path | None = None,
	) -> list[dict[str, Any]]:
		"""List models exposed by the running server."""
		url_host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
		for path in ("/models", "/v1/models"):
			try:
				url = f"http://{url_host}:{self.port}{path}"
				req = urllib.request.Request(url, method="GET")
				with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
					if resp.status == 200:
						data = json.loads(resp.read().decode("utf-8"))
						if isinstance(data, dict) and isinstance(data.get("data"), list):
							return [item for item in data["data"] if isinstance(item, dict)]
			except Exception:
				pass
		return []
