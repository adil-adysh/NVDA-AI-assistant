"""Cancellable, local-only cache discovery. No NVDA or inference imports."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import struct
import threading
import time
import uuid

try:
	from ...core.model_assets import ModelAssetSnapshot, ModelDiscoverySnapshot
	from ...core.job.execution import check_job_cancelled
	from ...core.translation import _
	from ...core.llama_model_source import is_standalone_gguf
except ImportError:
	from core.model_assets import ModelAssetSnapshot, ModelDiscoverySnapshot
	from core.job.execution import check_job_cancelled
	from core.translation import _
	from core.llama_model_source import is_standalone_gguf


def default_cache_roots():
	roots = []
	if os.getenv("LLAMA_CACHE"):
		roots.append({"path": os.environ["LLAMA_CACHE"], "source": "llama_cache"})
	elif os.name == "nt" and os.getenv("LOCALAPPDATA"):
		# Upstream fs_get_cache_directory; verified against supported Windows builds.
		cache = Path(os.environ["LOCALAPPDATA"]) / "llama.cpp"
		if cache.is_dir():
			roots.append({"path": str(cache), "source": "llama_cache"})
	# HF's documented environment configuration; discover only existing roots.
	hf_home = Path(os.getenv("HF_HOME") or (Path(os.getenv("XDG_CACHE_HOME") or (Path.home() / ".cache")) / "huggingface"))
	hub = Path(os.getenv("HF_HUB_CACHE") or os.getenv("HUGGINGFACE_HUB_CACHE") or hf_home / "hub")
	if hub.is_dir():
		roots.append({"path": str(hub), "source": "hf_hub"})
	return roots


def file_identity(path):
	stat = path.stat()
	return f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"


class ModelAssetExecutor:
	def __init__(self):
		self._tokens = {}
		self._lock = threading.Lock()

	def discover_model_assets(self, roots, generation):
		assets, errors, seen = [], {}, set()
		deadline = time.monotonic() + 20
		for item in roots:
			check_job_cancelled()
			root = Path(item["path"]).expanduser().resolve()
			source = item.get("source", "user_folder")
			if source not in {"user_folder", "hf_hub", "llama_cache"}:
				raise ValueError(_("Unknown model cache source."))
			try:
				if not root.is_dir():
					raise ValueError(_("Cache folder is missing or inaccessible."))
				def failed(error):
					errors[str(root)] = str(error)
				for directory, folders, files in os.walk(root, followlinks=False, onerror=failed):
					check_job_cancelled()
					if time.monotonic() > deadline:
						errors[str(root)] = _("Scan timed out. Choose a smaller cache folder.")
						break
					folders[:] = sorted(folder for folder in folders if not Path(directory, folder).is_symlink())
					for name in sorted(files):
						check_job_cancelled()
						if time.monotonic() > deadline or len(assets) >= 10000:
							errors[str(root)] = _("Scan limit reached. Choose a smaller cache folder.")
							break
						if not name.lower().endswith(".gguf"):
							continue
						path = Path(directory, name)
						target = path.resolve()
						if str(target) in seen:
							continue
						seen.add(str(target))
						try:
							identity = file_identity(target)
							with target.open("rb") as stream:
								header = stream.read(24)
							valid = len(header) == 24 and header[:4] == b"GGUF" and struct.unpack("<I", header[4:8])[0] in {2, 3}
							availability = "present" if valid and target.is_relative_to(root) else "incomplete"
							if not is_standalone_gguf(name):
								availability = "unknown"
							asset_id = hashlib.sha256(os.path.normcase(str(target)).encode()).hexdigest()
							repo = revision = artifact = None
							parts = path.relative_to(root).parts
							if source == "hf_hub" and len(parts) >= 4 and parts[0].startswith("models--") and parts[1] == "snapshots":
								repo = parts[0].removeprefix("models--").replace("--", "/", 1)
								revision, artifact = parts[2], "/".join(parts[3:])
							token = uuid.uuid4().hex
							asset = ModelAssetSnapshot(asset_id, token, str(path), source, availability, target.stat().st_size,
								repository=repo, revision=revision, artifact=artifact, file_identity=identity)
							with self._lock:
								now = time.monotonic()
								self._tokens = {key: value for key, value in self._tokens.items() if now - value[2] < 3600}
								self._tokens[token] = (asset, root, now)
							assets.append(asset)
						except (OSError, ValueError) as error:
							errors[str(root)] = str(error)
			except (OSError, ValueError) as error:
				errors[str(root)] = str(error)
		return ModelDiscoverySnapshot(int(generation), tuple(assets), errors, time.time())

	def verify_model_asset(self, token, role="primary"):
		check_job_cancelled()
		with self._lock:
			entry = self._tokens.get(token)
		if entry is None or time.monotonic() - entry[2] >= 3600:
			raise ValueError(_("This model discovery has expired. Refresh downloaded models."))
		asset, root, unused = entry
		path = Path(asset.path).resolve()
		try:
			if not path.is_relative_to(root) or file_identity(path) != asset.file_identity:
				raise ValueError()
		except (ValueError, OSError) as error:
			raise ValueError(_("The downloaded model changed or is missing. Refresh before creating a configuration.")) from error
		from .llama_hf import verify_gguf
		verify_gguf(path, role)
		return replace(asset, path=str(path), availability="present")
