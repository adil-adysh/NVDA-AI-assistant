"""Supported llama.cpp preset options and Hugging Face source validation.

Only per-model options are represented here. Server/router settings, secrets
and local file paths are intentionally absent: a preset describes one
Hugging Face model section and its runtime flags.
"""
from dataclasses import dataclass
import math
import re

from .translation import _


@dataclass(frozen=True)
class PresetOption:
	key: str
	label: str
	choices: tuple[str, ...] = ()
	minimum: float | None = None
	maximum: float | None = None
	kind: str = "text"


CACHE_TYPES = ("f16", "bf16", "f8_e4m3", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1", "f32")
BOOLEAN = ("true", "false")
SPEC_TYPES = (
	"none", "draft-simple", "draft-eagle3", "draft-mtp", "draft-dflash",
	"draft-dspark", "draft-dflash2", "draft-lilicorr", "ngram-simple",
	"ngram-map-k", "ngram-map-k4v", "ngram-mod", "ngram-cache",
)
OPTIONS = (
	# Context, memory and batching.
	PresetOption("ctx-size", _("Context length (tokens)"), minimum=0, kind="int"),
	PresetOption("gpu-layers", _("GPU layers (auto, all, or a number)")),
	PresetOption("flash-attn", _("Flash Attention"), ("auto", "on", "off")),
	PresetOption("cache-type-k", _("Key cache precision"), CACHE_TYPES),
	PresetOption("cache-type-v", _("Value cache precision"), CACHE_TYPES),
	PresetOption("kv-offload", _("Offload KV cache to GPU"), ("true",)),
	PresetOption("no-kv-offload", _("Keep KV cache on CPU"), ("true",)),
	PresetOption("kv-unified", _("Use one unified KV cache"), BOOLEAN),
	PresetOption("cache-prompt", _("Reuse the prompt cache"), BOOLEAN),
	PresetOption("cache-reuse", _("Minimum chunk size for cache reuse (tokens)"), minimum=0, kind="int"),
	PresetOption("ctx-checkpoints", _("Maximum context checkpoints"), minimum=0, kind="int"),
	PresetOption("cpu-moe", _("Keep all MoE experts on CPU"), ("true",)),
	PresetOption("n-cpu-moe", _("MoE layers with experts on CPU"), minimum=0, kind="int"),
	PresetOption("n-cpu-ffn", _("Dense FFN layers on CPU"), minimum=0, kind="int"),
	PresetOption("moe-cache-mib", _("MoE GPU cache (MiB)"), minimum=0, kind="int"),
	PresetOption("moe-cache-cpu-share", _("MoE cache CPU share"), minimum=0, maximum=1, kind="float"),
	PresetOption("threads", _("Generation CPU threads"), minimum=1, kind="int"),
	PresetOption("threads-batch", _("Prompt CPU threads"), minimum=1, kind="int"),
	PresetOption("batch-size", _("Logical batch size"), minimum=1, kind="int"),
	PresetOption("ubatch-size", _("Physical batch size"), minimum=1, kind="int"),
	PresetOption("load-mode", _("Model loading mode"), ("auto", "none", "mmap", "mlock", "mmap+mlock", "dio")),
	# Prompt and reasoning.
	PresetOption("reasoning", _("Reasoning"), ("on", "off", "auto")),
	PresetOption("reasoning-format", _("Reasoning format"), ("none", "deepseek", "deepseek-legacy", "auto")),
	PresetOption("reasoning-budget", _("Reasoning token budget (-1 = unlimited)"), minimum=-1, kind="int"),
	PresetOption("jinja", _("Enable Jinja templates"), ("true",)),
	PresetOption("chat-template", _("Chat template")),
	# Multimodal projector.
	PresetOption("mmproj-auto", _("Use the repository projector automatically"), BOOLEAN),
	PresetOption("mmproj-offload", _("Offload the projector to GPU"), BOOLEAN),
	PresetOption("mmproj-device", _("Projector device")),
	PresetOption("image-min-tokens", _("Minimum image tokens"), minimum=0, kind="int"),
	PresetOption("image-max-tokens", _("Maximum image tokens"), minimum=0, kind="int"),
	# Speculative decoding.
	PresetOption("spec-type", _("Speculative decoding modes (comma-separated)")),
	PresetOption("spec-draft-n-max", _("Maximum speculative draft tokens"), minimum=0, kind="int"),
	PresetOption("spec-draft-n-min", _("Minimum speculative draft tokens"), minimum=0, kind="int"),
	PresetOption("spec-draft-p-min", _("Minimum speculative draft probability"), minimum=0, maximum=1, kind="float"),
	PresetOption("spec-draft-ngl", _("Draft model GPU layers")),
	PresetOption("spec-draft-cpu-moe", _("Keep draft MoE experts on CPU"), ("true",)),
	PresetOption("spec-draft-n-cpu-moe", _("Draft MoE layers on CPU"), minimum=0, kind="int"),
	# Sampling defaults.
	PresetOption("n-predict", _("Maximum output tokens (-1 = unlimited)"), minimum=-1, kind="int"),
	PresetOption("temperature", _("Temperature"), minimum=0, kind="float"),
	PresetOption("dynatemp-range", _("Dynamic temperature range"), minimum=0, kind="float"),
	PresetOption("dynatemp-exp", _("Dynamic temperature exponent"), minimum=0, kind="float"),
	PresetOption("top-k", _("Top K"), minimum=0, kind="int"),
	PresetOption("top-p", _("Top P"), minimum=0, maximum=1, kind="float"),
	PresetOption("min-p", _("Min P"), minimum=0, maximum=1, kind="float"),
	PresetOption("xtc-probability", _("XTC probability"), minimum=0, maximum=1, kind="float"),
	PresetOption("xtc-threshold", _("XTC threshold"), minimum=0, maximum=1, kind="float"),
	PresetOption("typical-p", _("Typical P"), minimum=0, maximum=1, kind="float"),
	PresetOption("top-n-sigma", _("Top N sigma"), minimum=-1, kind="float"),
	PresetOption("repeat-last-n", _("Repeat penalty window"), minimum=0, kind="int"),
	PresetOption("repeat-penalty", _("Repeat penalty"), minimum=0, kind="float"),
	PresetOption("presence-penalty", _("Presence penalty"), minimum=0, kind="float"),
	PresetOption("frequency-penalty", _("Frequency penalty"), minimum=0, kind="float"),
	PresetOption("dry-multiplier", _("DRY multiplier"), minimum=0, kind="float"),
	PresetOption("dry-base", _("DRY base"), minimum=1, kind="float"),
	PresetOption("dry-allowed-length", _("DRY allowed repetition length"), minimum=0, kind="int"),
	PresetOption("dry-penalty-last-n", _("DRY penalty window"), minimum=0, kind="int"),
	PresetOption("mirostat", _("Mirostat mode"), ("0", "1", "2")),
	PresetOption("mirostat-lr", _("Mirostat learning rate"), minimum=0, kind="float"),
	PresetOption("mirostat-ent", _("Mirostat entropy target"), minimum=0, kind="float"),
)
OPTION_BY_KEY = {option.key: option for option in OPTIONS}
ALIASES = {
	"c": "ctx-size", "ngl": "gpu-layers", "n-gpu-layers": "gpu-layers", "fa": "flash-attn",
	"ctk": "cache-type-k", "ctv": "cache-type-v", "ncmoe": "n-cpu-moe", "cmoe": "cpu-moe",
	"t": "threads", "tb": "threads-batch", "b": "batch-size", "ub": "ubatch-size",
	"lm": "load-mode", "temp": "temperature", "n": "n-predict", "predict": "n-predict",
}
SOURCE_KEYS = {"hf-repo", "hf-file", "spec-draft-hf", "spec-draft-model"}
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?$")
_FILE_RE = re.compile(r"^[^\\\r\n\x00:]+\.gguf$", re.IGNORECASE)


def canonical_key(key: str) -> str:
	return ALIASES.get(key.lower(), key.lower())


def _invalid(option: PresetOption) -> ValueError:
	return ValueError(_("Invalid value for llama.cpp option {option}.").format(option=option.key))


def _validate_numeric(option: PresetOption, value: str) -> str:
	try:
		number = float(value) if option.kind == "float" else int(value)
	except (TypeError, ValueError) as exc:
		raise _invalid(option) from exc
	if option.kind == "float":
		if not math.isfinite(number):
			raise _invalid(option)
		number = float(number)
	else:
		number = int(number)
	if option.minimum is not None and number < option.minimum:
		raise _invalid(option)
	if option.maximum is not None and number > option.maximum:
		raise _invalid(option)
	return str(number)


def validate_option_value(key: str, raw: object) -> str:
	"""Return the canonical value for one supported option."""
	canonical = canonical_key(str(key))
	option = OPTION_BY_KEY.get(canonical)
	if option is None:
		raise ValueError(_("Unsupported llama.cpp preset option: {option}.").format(option=canonical))
	value = str(raw).strip()
	if not value or any(ord(char) < 32 for char in value):
		raise _invalid(option)
	if canonical == "spec-type":
		modes = [part.strip().lower() for part in value.split(",")]
		if not modes or any(mode not in SPEC_TYPES for mode in modes):
			raise _invalid(option)
		return ",".join(modes)
	if option.choices:
		if value not in option.choices:
			raise _invalid(option)
		return value
	if option.kind in {"int", "float"}:
		canonical_value = _validate_numeric(option, value)
		if canonical == "repeat-penalty" and float(canonical_value) <= 0:
			raise _invalid(option)
		return canonical_value
	if canonical == "gpu-layers":
		if value not in {"auto", "all"} and not (value.isdecimal() and int(value) >= 0):
			raise _invalid(option)
	return value


def validate_options(options: dict[str, str]) -> dict[str, str]:
	result = {}
	for key, raw in options.items():
		canonical = canonical_key(str(key))
		if canonical in result:
			raise ValueError(_("Duplicate llama.cpp option: {option}.").format(option=canonical))
		result[canonical] = validate_option_value(canonical, raw)
	for left, right in (("cpu-moe", "n-cpu-moe"), ("kv-offload", "no-kv-offload")):
		if left in result and right in result:
			raise ValueError(_("Conflicting llama.cpp options: {first} and {second}.").format(first=left, second=right))
	return result


def validate_repo(value: object) -> str:
	repo = str(value).strip()
	if not _REPO_RE.fullmatch(repo):
		raise ValueError(_("Hugging Face repository must be owner/model[:quant]."))
	return repo


def validate_repo_file(value: object) -> str:
	file_name = str(value).strip()
	if (not _FILE_RE.fullmatch(file_name) or file_name.startswith(("/", "./"))
			or ".." in file_name.split("/")):
		raise ValueError(_("Hugging Face file must be a repository-relative .gguf path."))
	return file_name


def _repo_has_quant(repo: str) -> bool:
	return ":" in repo


def validate_source_fields(fields: dict[str, str]) -> dict[str, str]:
	"""Validate and canonicalize the Hugging Face source fields of one preset."""
	values = {key: str(value).strip() for key, value in fields.items()
		if value is not None and str(value).strip()}
	unknown = set(values) - SOURCE_KEYS
	if unknown:
		raise ValueError(_("Unsupported preset source key: {key}.").format(key=sorted(unknown)[0]))
	repo = values.get("hf-repo")
	if not repo:
		raise ValueError(_("hf-repo is required."))
	repo = validate_repo(repo)
	file_name = values.get("hf-file")
	if file_name:
		file_name = validate_repo_file(file_name)
		if _repo_has_quant(repo):
			raise ValueError(_("Remove the :quant suffix when hf-file is set."))
	draft_repo = values.get("spec-draft-hf")
	draft_file = values.get("spec-draft-model")
	if draft_file and not draft_repo:
		raise ValueError(_("spec-draft-model requires spec-draft-hf."))
	if draft_repo:
		draft_repo = validate_repo(draft_repo)
	if draft_file:
		draft_file = validate_repo_file(draft_file)
		if _repo_has_quant(draft_repo):
			raise ValueError(_("Remove the :quant suffix when spec-draft-model is set."))
	result = {"hf-repo": repo}
	if file_name:
		result["hf-file"] = file_name
	if draft_repo:
		result["spec-draft-hf"] = draft_repo
	if draft_file:
		result["spec-draft-model"] = draft_file
	return result
