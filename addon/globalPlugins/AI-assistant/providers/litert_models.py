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
        model_id: Hugging Face repo id, e.g. ``"litert-community/gemma-4-E2B-it-litert-lm"``.
        filename: Name of the ``.litertlm`` file inside the repo.
        display_name: Human-readable label shown in the UI.
        description: Short summary of the model.
        size_hint_human: Human-readable size (e.g. ``"~2.1 GB"``).
        gated: Whether the model requires Hugging Face authentication.
        vision: Whether the model supports image (vision) input.
        license_: SPDX license identifier.
        platform_hint: Target platform / architecture hint (e.g. ``"cpu"``).
    """

    model_id: str
    filename: str
    display_name: str
    description: str = ""
    size_hint_human: str = ""
    gated: bool = False
    vision: bool = False
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
    platform_hint="cpu",
)

GEMMA_4_E4B = LiteRTModelDef(
    model_id="litert-community/gemma-4-E4B-it-litert-lm",
    filename="gemma-4-E4B-it.litertlm",
    display_name="Gemma 4 E4B (4.7B)",
    description="Google Gemma 4 E4B — 4.7B parameter instruction-tuned vision-language model in LiteRT-LM format.",
    size_hint_human="~3.5 GB",
    gated=False,
    vision=True,
    platform_hint="cpu",
)

# ── Community models (popular) ────────────────────────────────────

QWEN_CODER_3B = LiteRTModelDef(
    model_id="4ntoine/Qwen2.5-Coder-3B-Instruct-LiteRTLM",
    filename="qwen2.5-coder-3b-instruct-litertlm.litertlm",
    display_name="Qwen 2.5 Coder 3B",
    description="Qwen 2.5 Coder 3B — code-specialised instruction model converted to LiteRT-LM.",
    size_hint_human="~1.8 GB",
    gated=False,
    platform_hint="cpu",
)

LOCO_OPERATOR_4B = LiteRTModelDef(
    model_id="4ntoine/LocoOperator-4B-LiteRTLM",
    filename="loco-operator-4b-litertlm.litertlm",
    display_name="LocoOperator 4B",
    description="LocoOperator 4B — general instruction model in LiteRT-LM format.",
    size_hint_human="~2.5 GB",
    gated=False,
    platform_hint="cpu",
)

# Register all known models here so the provider can enumerate them.
# Order roughly by popularity / capability.
KNOWN_MODELS: tuple[LiteRTModelDef, ...] = (
    GEMMA_4_E2B,
    GEMMA_4_E4B,
    QWEN_CODER_3B,
    LOCO_OPERATOR_4B,
)


def lookup_model(model_id: str) -> LiteRTModelDef | None:
    """Return the model definition for *model_id*, or ``None``."""
    for m in KNOWN_MODELS:
        if m.model_id == model_id or m.filename == model_id:
            return m
    return None


def download_url(model: LiteRTModelDef) -> str:
    """Direct download URL for the model file from Hugging Face."""
    return (
        f"https://huggingface.co/{model.model_id}/resolve/main/{model.filename}"
    )
