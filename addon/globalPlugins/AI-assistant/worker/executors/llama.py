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
	"""Return the path to the router preset models.ini file."""
	return default_preset_dir() / "models.ini"


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


def _record_source_lines(model: dict[str, Any] | Any) -> list[str]:
	if isinstance(model, dict):
		kind = model.get("kind", "")
		source = str(model.get("source", "")).strip()
		variant = model.get("variant")
		local_path = model.get("local_path")
		hf_repo = model.get("hf_repo") or model.get("hf-repo")
	else:
		kind = getattr(model, "kind", "")
		source = str(getattr(model, "source", "")).strip()
		variant = getattr(model, "variant", None)
		local_path = getattr(model, "local_path", None)
		hf_repo = getattr(model, "hf_repo", None)

	if hf_repo:
		clean_hf_repo = re.sub(r"[\r\n]+", "", str(hf_repo)).strip()
		if clean_hf_repo:
			return [f"hf-repo = {clean_hf_repo}"]
	if kind == "hugging_face" or source.startswith("hf://"):
		clean_source = re.sub(r"[\r\n]+", "", source).strip()
		repo = clean_source.removeprefix("hf://").strip()
		if variant:
			clean_variant = re.sub(r"[\r\n]+", "", str(variant)).strip()
			if clean_variant:
				repo = f"{repo}:{clean_variant}"
		if repo:
			return [f"hf-repo = {repo}"]
	raw_target = str(local_path or source)
	clean_target = re.sub(r"[\r\n]+", "", raw_target).strip()
	if not clean_target:
		return []
	try:
		path = str(Path(clean_target).resolve())
	except Exception:
		path = clean_target
	return [f"model = {path}"]


def build_models_preset(models: list[Any]) -> str:
	"""Build a llama-server router preset from model records."""
	lines = ["version = 1", ""]
	for m in models:
		m_id = m.get("model_id") if isinstance(m, dict) else getattr(m, "model_id", "")
		m_id = str(m_id or "").strip()
		if not m_id or any(char in m_id for char in "[]\r\n"):
			continue
		lines.append(f"[{m_id}]")
		lines.extend(_record_source_lines(m))
		lines.append("")
	return "\n".join(lines)


def merge_models_preset(text: str, models: list[Any]) -> str:
	"""Reconcile model sources while preserving preset comments and options."""
	if not text.strip():
		return build_models_preset(models)
	lines = text.splitlines()
	sections: list[tuple[str, int, int]] = []
	for index, line in enumerate(lines):
		match = _SECTION_RE.match(line.strip())
		if match:
			if sections:
				sections[-1] = (sections[-1][0], sections[-1][1], index)
			sections.append((match.group(1).strip(), index, len(lines)))

	managed: dict[str, Any] = {}
	for m in models:
		m_id = m.get("model_id") if isinstance(m, dict) else getattr(m, "model_id", "")
		m_id_str = str(m_id or "").strip()
		if m_id_str and not any(char in m_id_str for char in "[]\r\n"):
			managed[m_id_str] = m

	output = list(lines)
	for section, start, end in reversed(sections):
		m = managed.get(section)
		if m is None or section == "*":
			continue
		body = output[start + 1 : end]
		body = [line for line in body if not re.match(r"^\s*(?:model|hf-repo)\s*=", line, re.I)]
		body = _record_source_lines(m) + body
		output[start + 1 : end] = body

	existing = {section for section, _, _ in sections}
	for m in models:
		m_id = m.get("model_id") if isinstance(m, dict) else getattr(m, "model_id", "")
		m_id_str = str(m_id or "").strip()
		if not m_id_str or any(char in m_id_str for char in "[]\r\n") or m_id_str in existing:
			continue
		while output and not output[-1].strip():
			output.pop()
		output.extend(["", f"[{m_id_str}]", *_record_source_lines(m)])
	return "\n".join(output).rstrip() + "\n"


class LlamaWorkerExecutor:
	"""Out-of-process executor for llama-server runtime supervisor and router preset generation."""

	def __init__(
		self,
		host: str = DEFAULT_LLAMA_HOST,
		port: int = DEFAULT_LLAMA_PORT,
		supervisor: Any | None = None,
	) -> None:
		self.host = host
		self.port = port
		self._supervisor = supervisor
		self._preset_lock = threading.Lock()

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

	def configure_preset(
		self,
		models: list[dict[str, Any]] | list[Any],
		default_model: str | None = None,
		preset_path: str | Path | None = None,
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

			existing_content = ""
			if target_path.is_file():
				try:
					existing_content = target_path.read_text(encoding="utf-8")
				except OSError:
					existing_content = ""

			content = merge_models_preset(existing_content, ordered_models)

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
		for path in ("/v1/models", "/models"):
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
