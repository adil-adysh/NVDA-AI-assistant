"""Single-file llama model source policy shared with worker discovery."""
from pathlib import Path
import re

from .translation import _


def is_standalone_gguf(source: str) -> bool:
	name = Path(source).name.lower()
	return name.endswith(".gguf") and not name.startswith("mmproj") and not re.search(r"-\d{5}-of-\d{5}\.gguf$", name)


def validate_standalone_gguf(source: str) -> None:
	if not is_standalone_gguf(source):
		raise ValueError(_("Choose a single standalone GGUF model. Model shards and projector files cannot be imported as standalone models."))
