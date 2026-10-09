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
