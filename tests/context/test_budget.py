from __future__ import annotations

import unittest

from tests.support import load_addon_module


resolve_context_window_tokens = load_addon_module(
	"context.budget", namespace="budget_tests"
).resolve_context_window_tokens


class ContextWindowResolutionTests(unittest.TestCase):
	def test_model_metadata_is_authoritative_for_cloud(self) -> None:
		self.assertEqual(
			resolve_context_window_tokens(
				provider_id="openai",
				model_context_tokens=128000,
				model_configured_tokens=4096,
				global_configured_tokens=8192,
			),
			128000,
		)

	def test_local_model_pin_is_capped_by_model_metadata(self) -> None:
		self.assertEqual(
			resolve_context_window_tokens(
				provider_id="ollama",
				model_context_tokens=8192,
				model_configured_tokens=16384,
				global_configured_tokens=4096,
			),
			8192,
		)

	def test_local_model_pin_precedes_global_setting_without_metadata(self) -> None:
		self.assertEqual(
			resolve_context_window_tokens(
				provider_id="llama-cpp-server",
				model_context_tokens=None,
				model_configured_tokens=16384,
				global_configured_tokens=4096,
			),
			16384,
		)

	def test_local_global_setting_is_next_fallback(self) -> None:
		self.assertEqual(
			resolve_context_window_tokens(
				provider_id="litert-lm",
				model_context_tokens=None,
				model_configured_tokens=None,
				global_configured_tokens=4096,
			),
			4096,
		)

	def test_cloud_uses_256k_default_without_metadata(self) -> None:
		self.assertEqual(
			resolve_context_window_tokens(
				provider_id="gemini",
				model_context_tokens=None,
				model_configured_tokens=4096,
				global_configured_tokens=8192,
			),
			262144,
		)


if __name__ == "__main__":
	unittest.main()
