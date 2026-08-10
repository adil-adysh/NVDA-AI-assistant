# -*- coding: utf-8 -*-
"""Known LiteRT-LM model definitions.

Each entry describes a model available for download from Hugging Face.
Models are gated — they require the ``gated`` flag to indicate a Hugging
Face login may be needed.  Non-gated models can be downloaded anonymously.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote


@dataclass(frozen=True)
class ModelVariant:
	"""A specific build of a LiteRT model targeting a particular platform.

	A single HuggingFace repo may contain multiple ``.litertlm`` files —
	each compiled with a different backend (CPU, GPU/WebGPU, Intel NPU,
	etc.).  This dataclass describes one such variant.

	Attributes:
	    variant_id: Short identifier (e.g. ``"cpu"``, ``"gpu"``,
	        ``"intel-lnl"``).  Used as a key in compound identities.
	    filename: Name of the ``.litertlm`` file inside the repo
	        (e.g. ``"gemma-4-E2B-it-gpu.litertlm"``).
	    display_label: Human-readable label for the variant shown in
	        the UI (e.g. ``"GPU (D3D12)"``).
	    platform_hint: Target platform / architecture.
	    size_hint_human: Human-readable size (e.g. ``"~2.1 GB"``).
	    description: Short description of this variant.
	"""

	variant_id: str
	filename: str
	display_label: str = ""
	platform_hint: Literal["cpu", "gpu", "universal"] = "cpu"
	size_hint_human: str = ""
	description: str = ""


@dataclass(frozen=True)
class LiteRTModelDef:
	"""Description of a downloadable LiteRT-LM model.

	Attributes:
	    model_id: Hugging Face repo id.
	    filename: Name of the primary ``.litertlm`` file.  When
	        ``variants`` is non-empty this is the default/CPU variant
	        and is kept for backward compatibility with code that
	        reads ``model.filename`` directly.
	    display_name: Human-readable label shown in the UI.
	    description: Short summary of the model.
	    size_hint_human: Human-readable size (e.g. ``"~2.1 GB"``).
	    gated: Whether the model requires Hugging Face authentication.
	    vision: Whether the model supports image (vision) input.
	    thinking: Whether the model supports reasoning/thinking tokens
	        (e.g. via ``<think>`` tags in the output).
	    mtp: Whether the model supports Multi-Token Prediction (MTP)
	        speculative decoding for faster generation.
	    priority: Display ordering — lower = more recommended.
	        Values ≤ 50 are shown in the "Recommended" group.
	    license_: SPDX license identifier.
	    platform_hint: Target platform / architecture hint for the
	        primary variant.
	    variants: Tuple of :class:`ModelVariant` entries describing
	        platform-specific builds.  When empty the model has a
	        single file (``filename``).
	"""

	model_id: str
	filename: str
	display_name: str
	description: str = ""
	size_hint_human: str = ""
	gated: bool = False
	vision: bool = False
	thinking: bool = False
	mtp: bool = False
	priority: int = 100
	license_: str = "apache-2.0"
	platform_hint: Literal["cpu", "gpu", "universal"] = "universal"
	variants: tuple[ModelVariant, ...] = ()

	# ── Derived properties ──────────────────────────────────────

	@property
	def has_variants(self) -> bool:
		"""``True`` when this model defines multiple platform builds."""
		return len(self.variants) > 0

	@property
	def all_filenames(self) -> tuple[str, ...]:
		"""Every ``.litertlm`` filename across all variants + primary."""
		names = [self.filename]
		names.extend(v.filename for v in self.variants)
		return tuple(dict.fromkeys(names))  # deduplicate, preserve order

	def get_variant(self, variant_id: str) -> ModelVariant | None:
		"""Return the variant with *variant_id*, or ``None``."""
		for v in self.variants:
			if v.variant_id == variant_id:
				return v
		return None

	def recommended_variant(self) -> ModelVariant | None:
		"""Return the best variant for the current hardware.

		On GPU-capable machines returns the first GPU variant;
		otherwise the first CPU variant.  Returns ``None`` when
		the model has no variants declared.
		"""
		if not self.variants:
			return None
		if has_gpu():
			for v in self.variants:
				if v.platform_hint == "gpu":
					return v
		for v in self.variants:
			if v.platform_hint == "cpu":
				return v
		return self.variants[0]



# ── Gemma 4 family (litert-community) ─────────────────────────────

# Gemma 4 E2B variants (from: litert-community/gemma-4-E2B-it-litert-lm)
_GEMMA4_E2B_VARIANTS: tuple[ModelVariant, ...] = (
	ModelVariant("cpu", "gemma-4-E2B-it.litertlm", "CPU (XNNPACK)",
		"cpu", "~2.1 GB",
		"Optimised for CPU inference via XNNPACK. Works on any Windows machine."),
	ModelVariant("gpu", "gemma-4-E2B-it-gpu.litertlm", "GPU (WebGPU / D3D12)",
		"gpu", "~2.1 GB",
		"Accelerated via WebGPU on Direct3D 12. NVIDIA, AMD, Intel Arc."),
	ModelVariant("web", "gemma-4-E2B-it-web.litertlm", "Web (WebGPU)",
		"gpu", "~2.1 GB",
		"WebGPU build for browser-based runtimes."),
	ModelVariant("intel-lnl", "gemma-4-E2B-it_intel_LNL.litertlm", "Intel Lunar Lake (NPU)",
		"gpu", "~2.1 GB",
		"Intel Lunar Lake NPU-accelerated build."),
	ModelVariant("intel-ptl", "gemma-4-E2B-it_intel_PTL.litertlm", "Intel Panther Lake (NPU)",
		"gpu", "~2.1 GB",
		"Intel Panther Lake NPU-accelerated build."),
)

GEMMA_4_E2B = LiteRTModelDef(
	model_id="litert-community/gemma-4-E2B-it-litert-lm",
	filename="gemma-4-E2B-it.litertlm",
	display_name="Gemma 4 E2B (2.6B)",
	description="Google Gemma 4 E2B — 2.6B parameter instruction-tuned vision-language model in LiteRT-LM format.",
	size_hint_human="~2.1 GB",
	gated=False,
	vision=True,
	priority=10,
	platform_hint="cpu",
	mtp=True,
	variants=_GEMMA4_E2B_VARIANTS,
)

# Gemma 4 E4B variants (from: litert-community/gemma-4-E4B-it-litert-lm)
_GEMMA4_E4B_VARIANTS: tuple[ModelVariant, ...] = (
	ModelVariant("cpu", "gemma-4-E4B-it.litertlm", "CPU (XNNPACK)",
		"cpu", "~3.7 GB",
		"Optimised for CPU inference via XNNPACK."),
	ModelVariant("gpu", "gemma-4-E4B-it-gpu.litertlm", "GPU (WebGPU / D3D12)",
		"gpu", "~3.0 GB",
		"Accelerated via WebGPU on Direct3D 12."),
	ModelVariant("web", "gemma-4-E4B-it-web.litertlm", "Web (WebGPU)",
		"gpu", "~3.0 GB",
		"WebGPU build for browser-based runtimes."),
)

GEMMA_4_E4B = LiteRTModelDef(
	model_id="litert-community/gemma-4-E4B-it-litert-lm",
	filename="gemma-4-E4B-it.litertlm",
	display_name="Gemma 4 E4B (4.7B)",
	description="Google Gemma 4 E4B — 4.7B parameter instruction-tuned vision-language model in LiteRT-LM format.",
	size_hint_human="~3.5 GB",
	gated=False,
	vision=True,
	priority=20,
	platform_hint="cpu",
	variants=_GEMMA4_E4B_VARIANTS,
)

# Gemma 4 12B variants (from: litert-community/gemma-4-12B-it-litert-lm)
_GEMMA4_12B_VARIANTS: tuple[ModelVariant, ...] = (
	ModelVariant("cpu", "gemma-4-12B-it.litertlm", "CPU (XNNPACK)",
		"cpu", "~6.5 GB",
		"Optimised for CPU inference via XNNPACK."),
	ModelVariant("gpu", "gemma-4-12B-it-gpu.litertlm", "GPU (WebGPU / D3D12)",
		"gpu", "~6.0 GB",
		"Accelerated via WebGPU on Direct3D 12."),
	ModelVariant("web", "gemma-4-12B-it-web.litertlm", "Web (WebGPU)",
		"gpu", "~6.0 GB",
		"WebGPU build for browser-based runtimes."),
)

GEMMA_4_12B = LiteRTModelDef(
	model_id="litert-community/gemma-4-12B-it-litert-lm",
	filename="gemma-4-12B-it.litertlm",
	display_name="Gemma 4 12B",
	description="Google Gemma 4 12B — large instruction-tuned model for desktop use, text+audio, 32K context, Apache 2.0.",
	size_hint_human="~6.6 GB",
	gated=False,
	vision=False,
	thinking=True,
	priority=50,
	platform_hint="gpu",
	variants=_GEMMA4_12B_VARIANTS,
)

# ── Community models ─────────────────────────────────────────────

# PeppX variants (from: PeppX/gemma-4-e2b-uncensored-litertlm)
_PEPPX_VARIANTS: tuple[ModelVariant, ...] = (
	ModelVariant("max", "gemma-4-E2B-it-Uncensored-MAX.litertlm", "MAX (FP32)",
		"gpu", "~2.5 GB",
		"Full-precision uncensored fine-tune."),
	ModelVariant("int4", "gemma4_uncensored_INT4_8192.litertlm", "INT4 (8K context)",
		"cpu", "~2.6 GB",
		"INT4 quantized with 8192 context window."),
)

PEPPX_UNCENSORED = LiteRTModelDef(
	model_id="PeppX/gemma-4-e2b-uncensored-litertlm",
	filename="gemma-4-E2B-it-Uncensored-MAX.litertlm",
	display_name="Gemma 4 E2B Uncensored",
	description="Community uncensored fine-tune of Gemma 4 E2B — text-only (vision stripped), 2.37 GB, 32K context, Apache 2.0.",
	size_hint_human="~2.4 GB",
	gated=False,
	vision=False,
	priority=100,
	platform_hint="gpu",
	variants=_PEPPX_VARIANTS,
)

# ── Qwen3 family (litert-community, ungated) ──────────────────────

# Qwen3 0.6B variants (from: litert-community/Qwen3-0.6B)
_QWEN3_0_6B_VARIANTS: tuple[ModelVariant, ...] = (
	ModelVariant("base", "Qwen3-0.6B.litertlm", "Base (FP32)",
		"cpu", "~614 MB",
		"Full-precision base model, 4K context."),
	ModelVariant("int4", "qwen3_0_6b_mixed_int4.litertlm", "Mixed INT4",
		"cpu", "~498 MB",
		"Mixed INT4 quantized for reduced memory."),
	ModelVariant("dynamic", "Qwen3-0.6B_dynamic_wi4b32_afp32.litertlm", "Dynamic INT4 (AFP32)",
		"cpu", "~344 MB",
		"Dynamic weight INT4 with asymmetric FP32 activations."),
)

QWEN3_0_6B = LiteRTModelDef(
	model_id="litert-community/Qwen3-0.6B",
	filename="Qwen3-0.6B.litertlm",
	display_name="Qwen3 0.6B",
	description="Alibaba Qwen3 0.6B — tiny efficient model, dynamic INT8, 4K context, 586 MB, Apache 2.0.",
	size_hint_human="~586 MB",
	gated=False,
	vision=False,
	thinking=True,
	priority=30,
	platform_hint="cpu",
	variants=_QWEN3_0_6B_VARIANTS,
)

# Qwen3 1.7B variants (from: litert-community/Qwen3-1.7B)
_QWEN3_1_7B_VARIANTS: tuple[ModelVariant, ...] = (
	ModelVariant("base", "Qwen3_1.7B.litertlm", "Base (FP32)",
		"cpu", "~2.1 GB",
		"Full-precision base model."),
	ModelVariant("dynamic", "Qwen3-1.7B_dynamic_wi4b32_afp32.litertlm", "Dynamic INT4 (AFP32)",
		"cpu", "~977 MB",
		"Dynamic weight INT4 with asymmetric FP32 activations."),
)

QWEN3_1_7B = LiteRTModelDef(
	model_id="litert-community/Qwen3-1.7B",
	filename="Qwen3_1.7B.litertlm",
	display_name="Qwen3 1.7B",
	description="Alibaba Qwen3 1.7B — lightweight instruction model, dynamic INT8, 2.1 GB, Apache 2.0.",
	size_hint_human="~2.1 GB",
	gated=False,
	vision=False,
	thinking=True,
	priority=30,
	platform_hint="cpu",
	variants=_QWEN3_1_7B_VARIANTS,
)

# Qwen3 4B variants (from: litert-community/Qwen3-4B)
_QWEN3_4B_VARIANTS: tuple[ModelVariant, ...] = (
	ModelVariant("int4", "qwen3_4b_mixed_int4.litertlm", "Mixed INT4",
		"cpu", "~2.7 GB",
		"Mixed INT4 quantized, balanced performance/size."),
	ModelVariant("int8", "qwen3_4b_channelwise_int8_float32kv.litertlm", "Channelwise INT8 (FP32 KV)",
		"cpu", "~5.7 GB",
		"Channelwise INT8 with FP32 KV cache for higher quality."),
)

QWEN3_4B = LiteRTModelDef(
	model_id="litert-community/Qwen3-4B",
	filename="qwen3_4b_mixed_int4.litertlm",
	display_name="Qwen3 4B",
	description="Alibaba Qwen3 4B — balanced model, mixed INT4, 2.5 GB, competitive with Gemma 4 E4B, Apache 2.0.",
	size_hint_human="~2.5 GB",
	gated=False,
	vision=False,
	thinking=True,
	priority=20,
	platform_hint="cpu",
	variants=_QWEN3_4B_VARIANTS,
)

# Qwen3 8B variants (from: litert-community/Qwen3-8B)
_QWEN3_8B_VARIANTS: tuple[ModelVariant, ...] = (
	ModelVariant("int4", "qwen3_8b_mixed_int4.litertlm", "Mixed INT4",
		"cpu", "~4.9 GB",
		"Mixed INT4 quantized, good desktop performance."),
	ModelVariant("int8", "qwen3_8b_channelwise_int8_float32kv.litertlm", "Channelwise INT8 (FP32 KV)",
		"cpu", "~8.3 GB",
		"Channelwise INT8 with FP32 KV cache for higher quality."),
)

QWEN3_8B = LiteRTModelDef(
	model_id="litert-community/Qwen3-8B",
	filename="qwen3_8b_mixed_int4.litertlm",
	display_name="Qwen3 8B",
	description="Alibaba Qwen3 8B — large desktop model, mixed INT4, 4.7 GB, strong reasoning, Apache 2.0.",
	size_hint_human="~4.7 GB",
	gated=False,
	vision=False,
	thinking=True,
	priority=50,
	platform_hint="cpu",
	variants=_QWEN3_8B_VARIANTS,
)

# Qwen3 14B variants (from: litert-community/Qwen3-14B)
_QWEN3_14B_VARIANTS: tuple[ModelVariant, ...] = (
	ModelVariant("int4", "qwen3_14b_mixed_int4.litertlm", "Mixed INT4",
		"cpu", "~8.7 GB",
		"Mixed INT4 quantized, largest Qwen3 for desktop."),
	ModelVariant("int8", "qwen3_14b_channelwise_int8_float32kv.litertlm", "Channelwise INT8 (FP32 KV)",
		"cpu", "~14.9 GB",
		"Channelwise INT8 with FP32 KV cache for best quality."),
)

QWEN3_14B = LiteRTModelDef(
	model_id="litert-community/Qwen3-14B",
	filename="qwen3_14b_mixed_int4.litertlm",
	display_name="Qwen3 14B",
	description="Alibaba Qwen3 14B — largest Qwen3 for LiteRT-LM, mixed INT4, 8.3 GB, best quality, Apache 2.0.",
	size_hint_human="~8.3 GB",
	gated=False,
	vision=False,
	thinking=True,
	priority=100,
	platform_hint="cpu",
	variants=_QWEN3_14B_VARIANTS,
)

# ── All known models (full catalog) ─────────────────────────────────

ALL_MODELS: tuple[LiteRTModelDef, ...] = (
	GEMMA_4_E2B,
	GEMMA_4_E4B,
	PEPPX_UNCENSORED,
	GEMMA_4_12B,
	QWEN3_0_6B,
	QWEN3_1_7B,
	QWEN3_4B,
	QWEN3_8B,
	QWEN3_14B,
)

# CPU-only models — GPU models excluded for size/compatibility.
# This is the default recommended set; call :func:`recommended_models`
# for a hardware-aware filtered list.
KNOWN_MODELS: tuple[LiteRTModelDef, ...] = (
	GEMMA_4_E2B,
	GEMMA_4_E4B,
	QWEN3_0_6B,
	QWEN3_1_7B,
	QWEN3_4B,
)


def lookup_model(model_id: str) -> LiteRTModelDef | None:
	"""Return the model definition for *model_id*, or ``None``.

	Searches the **full** catalog (not just ``KNOWN_MODELS``) so that
	capability detection works even for GPU-only entries.

	Matches against canonical ``model_id``, primary ``filename``, and
	all variant filenames — so variant-specific lookups resolve to
	the owning model.
	"""
	lowered = model_id.lower().strip()
	for m in ALL_MODELS:
		if model_id in (m.model_id, m.filename):
			return m
		if m.model_id.lower() == lowered or m.filename.lower() == lowered:
			return m
		# Search variant filenames
		for v in m.variants:
			if model_id == v.filename or v.filename.lower() == lowered:
				return m
	return None


def lookup_variant(variant_filename: str) -> tuple[LiteRTModelDef, ModelVariant] | None:
	"""Return ``(model, variant)`` for *variant_filename*, or ``None``.

	Useful when you have a variant file on disk and need to find both
	the owning model and the variant definition.
	"""
	model = lookup_model(variant_filename)
	if model is None:
		return None
	for v in model.variants:
		if v.filename == variant_filename:
			return (model, v)
	return None


def resolve_identity(name: str) -> str:
	"""Normalize any model reference to the canonical HuggingFace ``model_id``.

	Accepts either a ``model_id`` (e.g.
	``"litert-community/gemma-4-E2B-it-litert-lm"``) or a ``filename``
	(e.g. ``"gemma-4-E2B-it.litertlm"``) and returns the canonical
	``model_id``.  If *name* is not recognised, it is returned as-is.

	This is the **single source of truth** for LiteRT model identity
	resolution — use it whenever a stored model name may be in either
	form (e.g. after migrating from an older add-on version).
	"""
	model = lookup_model(name)
	return model.model_id if model is not None else name


def download_url(model: LiteRTModelDef, variant_filename: str | None = None) -> str:
	"""Direct download URL for a model file from Hugging Face.

	When *variant_filename* is given and differs from *model.filename*,
	returns the URL for that variant file in the same repo.
	"""
	filename = variant_filename if variant_filename else model.filename
	return f"https://huggingface.co/{model.model_id}/resolve/main/{quote(filename, safe='')}"


# ── Hardware detection ──────────────────────────────────────────────


def _detect_gpu_available() -> bool:
	"""Return ``True`` if a usable GPU is detected on this system."""
	# Try CUDA first (NVIDIA).
	try:
		import ctypes  # noqa: F811

		cuda = ctypes.cdll.LoadLibrary("cudart64_12.dll")
		result = cuda.cudaGetDeviceCount(ctypes.byref(ctypes.c_int(0)))
		if result == 0:
			return True
	except OSError:
		pass

	# Try Vulkan (works for AMD / Intel Arc / NVIDIA).
	try:
		import ctypes

		ctypes.cdll.LoadLibrary("vulkan-1.dll")
		return True
	except OSError:
		pass

	return False


# Cache hardware detection — import-time probe is cheap.
_HAS_GPU: bool | None = None


def has_gpu() -> bool:
	"""Check GPU availability (cached)."""
	global _HAS_GPU  # pylint: disable=global-statement
	if _HAS_GPU is None:
		_HAS_GPU = _detect_gpu_available()
	return _HAS_GPU


def recommended_models() -> tuple[LiteRTModelDef, ...]:
	"""Return models recommended for the current hardware.

	On GPU-capable machines this includes larger GPU-targeted models;
	on CPU-only machines it returns the conservative CPU set.
	"""
	if has_gpu():
		return tuple(
			m for m in ALL_MODELS if m.platform_hint in ("cpu", "universal", "gpu") and m.priority <= 60
		)
	return tuple(m for m in ALL_MODELS if m.platform_hint in ("cpu", "universal"))
