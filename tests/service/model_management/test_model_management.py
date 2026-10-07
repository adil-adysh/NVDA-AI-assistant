# -*- coding: utf-8 -*-
"""Unit tests for Centralized Model Management Service and Resource Arbitration.

Validates:
- Invariant A11: Centralized multi-modal model management.
- Invariant A12: Multi-modal resource arbitration across CHAT, VISION, OCR, TRANSCRIPTION.
- Invariant A13: Runtime-neutral standardized storage policy.
- Invariant A14: Explicit availability / fail-closed configured-model policy (no silent fallbacks).
- Invariant A15: Separation of model specification from runtime state.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import time

import pytest

from tests.support import load_addon_module

desc_mod = load_addon_module("service.model_management.descriptors")
arb_mod = load_addon_module("service.model_management.arbitration")
svc_mod = load_addon_module("service.model_management.service")

Modality = desc_mod.Modality
ModelDescriptor = desc_mod.ModelDescriptor
ModelReadinessStatus = desc_mod.ModelReadinessStatus
ModelResourceSpec = desc_mod.ModelResourceSpec
ModelSourceSpec = desc_mod.ModelSourceSpec

HardwareProfile = arb_mod.HardwareProfile
HardwareTier = arb_mod.HardwareTier
ResourceArbitrator = arb_mod.ResourceArbitrator

ModelManagementService = svc_mod.ModelManagementService
ModelUnavailableError = svc_mod.ModelUnavailableError


def make_dummy_descriptor(
	model_id: str = "test-model-1",
	provider_id: str = "litert",
	modality: Modality = Modality.CHAT,
	ram_bytes: int = 4 * 1024**3,
	vram_bytes: int = 2 * 1024**3,
	filename: str = "test-model.bin",
	source_kind: str = "huggingface_file",
) -> ModelDescriptor:
	return ModelDescriptor(
		model_id=model_id,
		display_name=f"Test {model_id}",
		provider_id=provider_id,
		modality=modality,
		capabilities=frozenset(["generate", "streaming"]),
		source=ModelSourceSpec(
			kind=source_kind,
			location="repo/model",
			filename=filename,
			revision="main",
			sha256="abcdef123456",
		),
		resources=ModelResourceSpec(
			ram_bytes=ram_bytes,
			vram_bytes=vram_bytes,
			compute_target="gpu" if vram_bytes > 0 else "cpu",
			context_window=4096,
		),
		priority=100,
		description="Dummy test descriptor",
	)


def test_model_descriptor_immutability_and_serialization():
	desc = make_dummy_descriptor()

	# Frozen dataclass immutability
	with pytest.raises((FrozenInstanceError, AttributeError)):
		desc.display_name = "New Name"  # type: ignore

	# Serialization roundtrip
	as_dict = desc.to_dict()
	restored = ModelDescriptor.from_dict(as_dict)
	assert restored.model_id == desc.model_id
	assert restored.modality == desc.modality
	assert restored.capabilities == desc.capabilities
	assert restored.resources.ram_bytes == desc.resources.ram_bytes
	assert restored.source.filename == desc.source.filename


def test_resource_arbitration_hardware_tiers():
	# 1. Low-End: < 16GB RAM or < 2GB VRAM -> Strict exclusive single model
	low_profile = HardwareProfile.detect(ram_bytes=8 * 1024**3, vram_bytes=1 * 1024**3)
	assert low_profile.tier == HardwareTier.LOW_END

	low_arbitrator = ResourceArbitrator(low_profile)
	m1 = make_dummy_descriptor("model-1", modality=Modality.CHAT)
	m2 = make_dummy_descriptor("model-2", modality=Modality.OCR)

	# First allocation
	dec1 = low_arbitrator.request_allocation(m1)
	assert dec1.can_allocate is True
	assert dec1.target_device == "cpu"
	low_arbitrator.commit_allocation(m1, dec1.target_device)

	# Second allocation requires evicting m1
	dec2 = low_arbitrator.request_allocation(m2)
	assert dec2.can_allocate is True
	assert "model-1" in dec2.models_to_evict

	# 2. Mid-Range: 16-32GB RAM, 4-6GB VRAM -> 1 GPU LLM + 1 CPU helper
	mid_profile = HardwareProfile.detect(ram_bytes=16 * 1024**3, vram_bytes=6 * 1024**3)
	assert mid_profile.tier == HardwareTier.MID_RANGE

	mid_arbitrator = ResourceArbitrator(mid_profile)
	chat_model = make_dummy_descriptor("chat-llm", modality=Modality.CHAT, vram_bytes=4 * 1024**3)
	ocr_helper = make_dummy_descriptor("ocr-fast", modality=Modality.OCR, vram_bytes=0)

	dec_chat = mid_arbitrator.request_allocation(chat_model)
	assert dec_chat.can_allocate is True
	assert dec_chat.target_device == "gpu"
	mid_arbitrator.commit_allocation(chat_model, dec_chat.target_device)

	# Helper allocates on CPU without evicting the GPU LLM
	dec_ocr = mid_arbitrator.request_allocation(ocr_helper)
	assert dec_ocr.can_allocate is True
	assert dec_ocr.target_device == "cpu"
	assert len(dec_ocr.models_to_evict) == 0


def test_ephemeral_idle_reaper():
	arbitrator = ResourceArbitrator(ephemeral_idle_timeout_seconds=0.1)
	chat_desc = make_dummy_descriptor("chat-main", modality=Modality.CHAT)
	ocr_desc = make_dummy_descriptor("ocr-ephemeral", modality=Modality.OCR)

	arbitrator.commit_allocation(chat_desc, "gpu")
	arbitrator.commit_allocation(ocr_desc, "cpu")

	# Immediately: no reapable models
	assert arbitrator.get_reapable_models() == ()

	# Wait for ephemeral idle timeout
	time.sleep(0.15)

	# OCR is ephemeral -> reapable; Chat is permanent -> NOT reapable
	reapable = arbitrator.get_reapable_models()
	assert "ocr-ephemeral" in reapable
	assert "chat-main" not in reapable

	# Record activity resets timer
	arbitrator.record_activity("ocr-ephemeral")
	assert arbitrator.get_reapable_models() == ()


def test_model_management_service_registry_and_negative_visibility(tmp_path: Path):
	svc = ModelManagementService(models_root_dir=tmp_path)
	m1 = make_dummy_descriptor("m1", provider_id="litert", modality=Modality.CHAT)
	m2 = make_dummy_descriptor("m2", provider_id="litert", modality=Modality.VISION)

	svc.register_model(m1)
	svc.register_model(m2)

	assert len(svc.list_models()) == 2

	# Hide m1 (negative visibility)
	svc.hide_model("litert", "m1")
	assert svc.is_model_hidden("litert", "m1") is True

	# Visible only excludes m1
	visible = svc.list_models(visible_only=True)
	assert len(visible) == 1
	assert visible[0].model_id == "m2"

	# visible_only=False includes both
	all_models = svc.list_models(visible_only=False)
	assert len(all_models) == 2

	# Unhide m1
	svc.unhide_model("litert", "m1")
	assert svc.is_model_hidden("litert", "m1") is False
	assert len(svc.list_models(visible_only=True)) == 2


def test_configured_model_policy_fail_closed(tmp_path: Path):
	svc = ModelManagementService(models_root_dir=tmp_path)
	desc = make_dummy_descriptor("gemma-2b", provider_id="litert", filename="gemma.bin")
	svc.register_model(desc)

	# Configure as active CHAT model
	svc.configure_model(Modality.CHAT, "litert", "gemma-2b")

	# File does not exist yet -> NOT_DOWNLOADED
	status = svc.check_model_readiness("litert", "gemma-2b")
	assert status == ModelReadinessStatus.NOT_DOWNLOADED

	# Invariant A14: get_active_model_or_raise MUST raise ModelUnavailableError,
	# NEVER silently fallback to another model!
	with pytest.raises(ModelUnavailableError, match="not ready"):
		svc.get_active_model_or_raise(Modality.CHAT)

	# When file is created, status becomes READY
	model_file = svc.get_model_storage_path("litert", "gemma.bin")
	model_file.parent.mkdir(parents=True, exist_ok=True)
	model_file.write_bytes(b"dummy model weights")

	status_ready = svc.check_model_readiness("litert", "gemma-2b")
	assert status_ready == ModelReadinessStatus.READY

	active_desc = svc.get_active_model_or_raise(Modality.CHAT)
	assert active_desc.model_id == "gemma-2b"


def test_cloud_model_readiness_immediately_ready(tmp_path: Path):
	svc = ModelManagementService(models_root_dir=tmp_path)
	cloud_desc = make_dummy_descriptor(
		"gpt-4o",
		provider_id="openai",
		modality=Modality.CHAT,
		source_kind="cloud_endpoint",
	)
	svc.register_model(cloud_desc)
	svc.configure_model(Modality.CHAT, "openai", "gpt-4o")

	# Cloud endpoint is immediately READY
	status = svc.check_model_readiness("openai", "gpt-4o")
	assert status == ModelReadinessStatus.READY

	active = svc.get_active_model_or_raise(Modality.CHAT)
	assert active.model_id == "gpt-4o"
