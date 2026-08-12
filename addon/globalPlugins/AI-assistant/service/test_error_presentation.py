# -*- coding: utf-8 -*-
# Test files deliberately duplicate the self-contained synthetic-package
# bootstrap so each suite can run standalone (R0801).
# pylint: disable=duplicate-code
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "error_presentation_testpkg"


def _register_package(name: str, path: Path | None = None) -> types.ModuleType:
	module = types.ModuleType(name)
	if path is not None:
		module.__path__ = [str(path)]
	sys.modules[name] = module
	return module


def _load_module(module_name: str, file_path: Path):
	spec = importlib.util.spec_from_file_location(module_name, file_path)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[module_name] = module
	spec.loader.exec_module(module)
	return module


_register_package(PACKAGE_NAME, ROOT_DIR)
_register_package(f"{PACKAGE_NAME}.providers", ROOT_DIR / "providers")
_register_package(f"{PACKAGE_NAME}.service", ROOT_DIR / "service")

# error_presentation.present_error lazily imports the NVDA-bound image
# package (screen curtain); stub it so this suite stays standalone.
_register_package(f"{PACKAGE_NAME}.image")
_register_package(f"{PACKAGE_NAME}.image.screen_curtain")


class _ScreenCurtainErrorStub(Exception):
	"""Stand-in for image.screen_curtain.ScreenCurtainError."""


sys.modules[f"{PACKAGE_NAME}.image.screen_curtain"].ScreenCurtainError = _ScreenCurtainErrorStub

interfaces_module = _load_module(
	f"{PACKAGE_NAME}.providers.interfaces",
	ROOT_DIR / "providers" / "interfaces.py",
)
error_mapping_module = _load_module(
	f"{PACKAGE_NAME}.providers.error_mapping",
	ROOT_DIR / "providers" / "error_mapping.py",
)
error_presentation_module = _load_module(
	f"{PACKAGE_NAME}.service.error_presentation",
	ROOT_DIR / "service" / "error_presentation.py",
)

LLMProviderError = interfaces_module.LLMProviderError
MissingCredentialsError = interfaces_module.MissingCredentialsError
UnsupportedModelError = interfaces_module.UnsupportedModelError
FeatureNotSupportedError = interfaces_module.FeatureNotSupportedError
present_error = error_presentation_module.present_error
suggest_for_status = error_mapping_module.suggest_for_status


class ErrorPresentationTests(unittest.TestCase):
	def test_provider_configuration_errors_stay_actionable(self) -> None:
		presentation = present_error(MissingCredentialsError("Gemini API key is required."))

		self.assertEqual(presentation.title, "Provider configuration problem")
		self.assertEqual(presentation.message, "Gemini API key is required.")
		self.assertFalse(presentation.is_internal)

	def test_unsupported_model_errors_keep_specific_message(self) -> None:
		presentation = present_error(UnsupportedModelError("This model only supports Interactions API."))

		self.assertEqual(presentation.title, "Unsupported model")
		self.assertEqual(presentation.message, "This model only supports Interactions API.")

	def test_feature_not_supported_is_actionable(self) -> None:
		presentation = present_error(
			FeatureNotSupportedError(
				"The selected model gemma-4-e2b-gpu does not support image description. "
				"Switch to a vision-capable model on LiteRT-LM to describe images."
			)
		)

		self.assertEqual(presentation.title, "Feature not supported")
		self.assertIn("The selected model gemma-4-e2b-gpu does not support image description", presentation.message)
		self.assertIn("Switch to a vision-capable model", presentation.message)
		self.assertFalse(presentation.is_internal)

	def test_feature_not_supported_falls_back_gracefully(self) -> None:
		presentation = present_error(FeatureNotSupportedError(""))

		self.assertEqual(presentation.title, "Feature not supported")
		self.assertFalse(presentation.is_internal)

	def test_provider_runtime_errors_are_not_hidden(self) -> None:
		presentation = present_error(LLMProviderError("Gemini request timed out."))

		self.assertEqual(presentation.title, "Provider request failed")
		self.assertEqual(presentation.message, "Gemini request timed out.")

	def test_internal_errors_are_generic(self) -> None:
		presentation = present_error(RuntimeError("stack-specific detail"))

		self.assertEqual(presentation.title, "Internal error")
		self.assertEqual(presentation.message, "Something went wrong inside the add-on. Please try again.")
		self.assertTrue(presentation.is_internal)

	def test_rate_limit_mapped_to_actionable(self) -> None:
		suggestion = suggest_for_status(429)
		self.assertEqual(suggestion.summary, "Rate limit exceeded")
		self.assertTrue(suggestion.actionable)

	def test_server_error_mapped_to_actionable(self) -> None:
		suggestion = suggest_for_status(500)
		self.assertEqual(suggestion.summary, "Server error")
		self.assertTrue(suggestion.actionable)

	def test_timeout_error_mapped_correctly(self) -> None:
		suggestion = suggest_for_status(504)
		self.assertEqual(suggestion.summary, "Request timed out")
		self.assertTrue(suggestion.actionable)

	def test_unknown_status_code_falls_back_gracefully(self) -> None:
		suggestion = suggest_for_status(418)
		self.assertEqual(suggestion.summary, "Provider request failed")
		self.assertTrue(suggestion.actionable)

	def test_none_status_falls_back_gracefully(self) -> None:
		suggestion = suggest_for_status(None, fallback_detail="Custom error detail")
		self.assertEqual(suggestion.summary, "Provider request failed")
		self.assertIn("Custom error detail", suggestion.detail)

	def test_llm_provider_error_with_status_code_uses_mapping(self) -> None:
		error = LLMProviderError("Gemini request failed with status 429.")
		presentation = present_error(error)
		# LLMProviderError has no status_code attr, so uses generic message
		self.assertEqual(presentation.title, "Provider request failed")
		self.assertFalse(presentation.is_internal)


if __name__ == "__main__":
	unittest.main()
