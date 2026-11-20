# -*- coding: utf-8 -*-
"""Unit tests for providers.litert_models module."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.support import load_addon_module

litert_models = load_addon_module("providers.litert_models")
ModelVariant = litert_models.ModelVariant
LiteRTModelDef = litert_models.LiteRTModelDef
build_import_candidates = litert_models.build_import_candidates
_build_import_candidates = litert_models._build_import_candidates


class BuildImportCandidatesTests(unittest.TestCase):
	def test_vision_community_catalog_has_complete_verified_inventory(self) -> None:
		expected_repositories = {
			"litert-community/LFM3-VL-2B-LiteRT",
			"litert-community/WeVisOne-VL-4B",
			"litert-community/WeVisOne-VL-2B",
			"litert-community/MiniCPM-V-4.7-1B",
			"litert-community/LFM2.5-VL-3B",
			"litert-community/LFM2.5-VL-1.6B",
			"litert-community/LFM2.5-VL-450M",
			"litert-community/North-Micro-Vision-Instruct",
			"litert-community/Qwen2-VL-2B",
			"litert-community/Ovis2.5-2B",
			"litert-community/InternVL3_5-4B",
			"litert-community/InternVL3_5-2B",
			"litert-community/InternVL3_5-1B",
			"litert-community/InternVL3-2B",
			"litert-community/InternVL3-1B",
			"litert-community/SmolVLM2-2.2B",
			"litert-community/SmolVLM2-500M",
			"litert-community/LLaVA-OneVision-0.5B",
			"litert-community/Mage-VL",
			"litert-community/Qwen3.5-0.8B",
			"litert-community/Qwen3.5-2B",
		}
		models = litert_models.VISION_COMMUNITY_MODELS
		self.assertEqual({model.model_id for model in models}, expected_repositories)
		self.assertEqual(len({model.friendly_name for model in models}), len(models))
		self.assertEqual(len({model.local_filename for model in models}), len(models))
		for model in models:
			with self.subTest(model=model.model_id):
				self.assertTrue(model.filename.endswith(".litertlm"))
				self.assertTrue(model.size_hint_human)
				self.assertTrue(model.description)
				self.assertTrue(model.license_)
				self.assertTrue(model.vision)
			self.assertEqual(
				litert_models.lookup_by_friendly_name(model.friendly_name),
				(model, None),
			)

	def test_none_definition_returns_empty_list(self) -> None:
		self.assertEqual(build_import_candidates(None), [])
		self.assertEqual(_build_import_candidates(None), [])

	def test_definition_without_has_variants_returns_filename(self) -> None:
		obj = SimpleNamespace(filename="test-model.litertlm")
		self.assertEqual(build_import_candidates(obj), ["test-model.litertlm"])

	def test_definition_with_empty_variants_returns_primary(self) -> None:
		obj = SimpleNamespace(
			has_variants=True,
			filename="primary.litertlm",
			variants=(),
		)
		self.assertEqual(build_import_candidates(obj), ["primary.litertlm"])

	def test_prioritizes_gpu_when_gpu_available(self) -> None:
		v_cpu = ModelVariant(
			variant_id="cpu",
			friendly_name="cpu-var",
			filename="model-cpu.litertlm",
			display_label="CPU",
			platform_hint="cpu",
			size_hint_human="1GB",
			description="CPU variant",
		)
		v_gpu = ModelVariant(
			variant_id="gpu",
			friendly_name="gpu-var",
			filename="model-gpu.litertlm",
			display_label="GPU",
			platform_hint="gpu",
			size_hint_human="1GB",
			description="GPU variant",
		)
		model_def = SimpleNamespace(
			has_variants=True,
			filename="primary.litertlm",
			variants=(v_cpu, v_gpu),
		)

		with patch.object(litert_models, "has_gpu", return_value=True):
			candidates = build_import_candidates(model_def)
		self.assertEqual(
			candidates,
			["model-gpu.litertlm", "model-cpu.litertlm", "primary.litertlm"],
		)

	def test_prioritizes_cpu_when_gpu_not_available(self) -> None:
		v_cpu = ModelVariant(
			variant_id="cpu",
			friendly_name="cpu-var",
			filename="model-cpu.litertlm",
			display_label="CPU",
			platform_hint="cpu",
			size_hint_human="1GB",
			description="CPU variant",
		)
		v_gpu = ModelVariant(
			variant_id="gpu",
			friendly_name="gpu-var",
			filename="model-gpu.litertlm",
			display_label="GPU",
			platform_hint="gpu",
			size_hint_human="1GB",
			description="GPU variant",
		)
		model_def = SimpleNamespace(
			has_variants=True,
			filename="primary.litertlm",
			variants=(v_cpu, v_gpu),
		)

		with patch.object(litert_models, "has_gpu", return_value=False):
			candidates = build_import_candidates(model_def)
		self.assertEqual(
			candidates,
			["model-cpu.litertlm", "model-gpu.litertlm", "primary.litertlm"],
		)

	def test_skips_variants_with_empty_filename(self) -> None:
		v_empty = SimpleNamespace(filename="", platform_hint="gpu")
		v_cpu = SimpleNamespace(filename="cpu.litertlm", platform_hint="cpu")
		model_def = SimpleNamespace(
			has_variants=True,
			filename="primary.litertlm",
			variants=(v_empty, v_cpu),
		)

		with patch.object(litert_models, "has_gpu", return_value=True):
			candidates = build_import_candidates(model_def)
		self.assertEqual(candidates, ["cpu.litertlm", "primary.litertlm"])


if __name__ == "__main__":
	unittest.main()
