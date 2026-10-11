"""LiteRT version and single-container import policy shared with the worker."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
import re

from .translation import _

DEFAULT_LITERT_VERSION = "0.18.0"
_SHARD = re.compile(r"(?:-\d+-of-\d+|[._-]part\d+)", re.IGNORECASE)


def validate_litert_artifact(value: str | Path, *, local: bool = False) -> str:
	"""Accept one .litertlm container, never directories, shards or raw components."""
	name = str(value).strip()
	if not local and (
		"\\" in name or "\x00" in name or name.startswith("/")
		or any(part in {"", ".", ".."} for part in name.split("/"))
	):
		raise ValueError(_("Invalid Hugging Face artifact: {artifact}").format(artifact=name))
	if PurePosixPath(name.replace("\\", "/")).suffix.lower() != ".litertlm" or _SHARD.search(Path(name).name):
		raise ValueError(_("LiteRT-LM supports a single .litertlm model file. Models requiring multiple files are not supported."))
	if local and not Path(name).is_file():
		if Path(name).is_dir():
			raise ValueError(_("Select a single .litertlm model file; directories are not supported."))
		raise ValueError(_("Model file does not exist: {path}").format(path=name))
	return name
