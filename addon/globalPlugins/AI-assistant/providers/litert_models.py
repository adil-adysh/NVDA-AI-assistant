# -*- coding: utf-8 -*-
"""Known LiteRT-LM model definitions.

Each entry describes a model available for download from Hugging Face.
Models are gated — they require the ``gated`` flag to indicate a Hugging
Face login may be needed.  Non-gated models can be downloaded anonymously.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LiteRTModelDef:
	"""Description of a downloadable LiteRT-LM model.

	Attributes:
	    model_id: Hugging Face repo id.
	    filename: Name of the ``.litertlm`` file inside the repo.
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
	    platform_hint: Target platform / architecture hint.
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


# ── Gemma 4 family (litert-community) ─────────────────────────────

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
)

# ── Community models (popular) ────────────────────────────────────

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
)

# ── Gemma 4 12B (litert-community, ungated) ───────────────────────

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
)

# ── Qwen3 family (litert-community, ungated) ──────────────────────

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
	platform_hint="gpu",
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
	platform_hint="gpu",
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
	"""
	lowered = model_id.lower().strip()
	for m in ALL_MODELS:
		if model_id in (m.model_id, m.filename):
			return m
		if m.model_id.lower() == lowered or m.filename.lower() == lowered:
			return m
	return None


def download_url(model: LiteRTModelDef) -> str:
	"""Direct download URL for the model file from Hugging Face."""
	return f"https://huggingface.co/{model.model_id}/resolve/main/{model.filename}"


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
	global _HAS_GPU
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
