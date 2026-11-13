"""Supported llama preset options shared by import, UI and worker export."""
from dataclasses import dataclass

from .translation import _


@dataclass(frozen=True)
class PresetOption:
	key: str
	label: str
	choices: tuple[str, ...] = ()
	minimum: int | None = None


CACHE_TYPES = ("f16", "q8_0", "q4_0", "f32", "bf16", "q4_1", "iq4_nl", "q5_0", "q5_1")
OPTIONS = (
	PresetOption("ctx-size", _("Context length (tokens)"), minimum=0),
	PresetOption("gpu-layers", _("GPU layers (auto, all, or a number)")),
	PresetOption("flash-attn", _("Flash Attention"), ("auto", "on", "off")),
	PresetOption("cache-type-k", _("Key cache precision"), CACHE_TYPES),
	PresetOption("cache-type-v", _("Value cache precision"), CACHE_TYPES),
	PresetOption("kv-offload", _("Offload KV cache to GPU"), ("true",)),
	PresetOption("no-kv-offload", _("Keep KV cache on CPU"), ("true",)),
	PresetOption("cpu-moe", _("Keep all MoE experts on CPU"), ("true",)),
	PresetOption("n-cpu-moe", _("MoE layers with experts on CPU"), minimum=0),
	PresetOption("moe-cache-mib", _("MoE GPU cache (MiB)"), minimum=0),
	PresetOption("threads", _("Generation CPU threads"), minimum=1),
	PresetOption("threads-batch", _("Prompt CPU threads"), minimum=1),
	PresetOption("batch-size", _("Logical batch size"), minimum=1),
	PresetOption("ubatch-size", _("Physical batch size"), minimum=1),
	PresetOption("reasoning", _("Reasoning"), ("on", "off", "auto")),
	PresetOption("reasoning-format", _("Reasoning format"), ("none", "deepseek", "deepseek-legacy", "auto")),
	PresetOption("load-mode", _("Model loading mode"), ("auto", "none", "mmap", "mlock", "mmap+mlock", "dio")),
	PresetOption("parallel", _("Parallel server slots"), minimum=1),
	PresetOption("spec-draft-model", _("Speculative draft model path")),
	PresetOption("spec-type", _("Speculative decoding mode"), ("none", "draft-simple", "draft-mtp")),
	PresetOption("mmproj", _("Multimodal projector path")),
	PresetOption("jinja", _("Enable Jinja templates"), ("true",)),
	PresetOption("chat-template", _("Chat template")),
	PresetOption("load-on-startup", _("Load model when server starts"), ("true", "false")),
	PresetOption("stop-timeout", _("Model stop timeout (seconds)"), minimum=0),
	PresetOption("dedup-cache-models", _("Hide duplicate cached model entries"), ("true", "false")),
)
OPTION_BY_KEY = {option.key: option for option in OPTIONS}
ALIASES = {"model-draft": "spec-draft-model", "md": "spec-draft-model", "np": "parallel", "c": "ctx-size", "ngl": "gpu-layers", "n-gpu-layers": "gpu-layers", "fa": "flash-attn",
	"ctk": "cache-type-k", "ctv": "cache-type-v", "ncmoe": "n-cpu-moe", "cmoe": "cpu-moe",
	"t": "threads", "tb": "threads-batch", "b": "batch-size", "ub": "ubatch-size", "m": "model",
	"hf": "hf-repo", "hfr": "hf-repo", "hff": "hf-file", "kvo": "kv-offload", "nkvo": "no-kv-offload"}
ENV_KEYS = {"LLAMA_ARG_N_GPU_LAYERS": "gpu-layers", "LLAMA_ARG_CTX_SIZE": "ctx-size",
	"LLAMA_ARG_FLASH_ATTN": "flash-attn", "LLAMA_ARG_CACHE_TYPE_K": "cache-type-k",
	"LLAMA_ARG_CACHE_TYPE_V": "cache-type-v", "LLAMA_ARG_N_CPU_MOE": "n-cpu-moe",
	"LLAMA_ARG_CPU_MOE": "cpu-moe", "LLAMA_ARG_MOE_CACHE_MIB": "moe-cache-mib"}
SOURCE_KEYS = {"model", "hf-repo", "hf-file"}


def canonical_key(key: str) -> str:
	return ENV_KEYS.get(key.upper(), ALIASES.get(key.lower(), key.lower()))


def validate_options(options: dict[str, str]) -> dict[str, str]:
	result = {}
	for key, raw in options.items():
		key = canonical_key(key)
		option = OPTION_BY_KEY.get(key)
		if option is None:
			raise ValueError(_("Unsupported llama.cpp preset option: {option}.").format(option=key))
		value = str(raw).strip()
		valid = bool(value) and not any(ord(char) < 32 for char in value)
		if option.choices:
			valid = valid and value in option.choices
		if option.minimum is not None:
			try:
				valid = valid and int(value) >= option.minimum
				value = str(int(value))
			except ValueError:
				valid = False
		if key == "gpu-layers":
			valid = valid and (value in {"auto", "all"} or (value.isdecimal() and int(value) >= 0))
		if not valid:
			raise ValueError(_("Invalid value for llama.cpp option {option}.").format(option=key))
		if key in result:
			raise ValueError(_("Duplicate llama.cpp option: {option}.").format(option=key))
		result[key] = value
	for left, right in (("cpu-moe", "n-cpu-moe"), ("kv-offload", "no-kv-offload")):
		if left in result and right in result:
			raise ValueError(_("Conflicting llama.cpp options: {first} and {second}.").format(first=left, second=right))
	return result
