# -*- coding: utf-8 -*-
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

interfaces_module = _load_module(
	f"{PACKAGE_NAME}.providers.interfaces",
	ROOT_DIR / "providers" / "interfaces.py",
)
error_presentation_module = _load_module(
	f"{PACKAGE_NAME}.service.error_presentation",
	ROOT_DIR / "service" / "error_presentation.py",
)

LLMProviderError = interfaces_module.LLMProviderError
MissingCredentialsError = interfaces_module.MissingCredentialsError
UnsupportedModelError = interfaces_module.UnsupportedModelError
present_error = error_presentation_module.present_error


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

	def test_provider_runtime_errors_are_not_hidden(self) -> None:
		presentation = present_error(LLMProviderError("Gemini request timed out."))

		self.assertEqual(presentation.title, "Provider request failed")
		self.assertEqual(presentation.message, "Gemini request timed out.")

	def test_internal_errors_are_generic(self) -> None:
		presentation = present_error(RuntimeError("stack-specific detail"))

		self.assertEqual(presentation.title, "Internal error")
		self.assertEqual(presentation.message, "Something went wrong inside the add-on. Please try again.")
		self.assertTrue(presentation.is_internal)


if __name__ == "__main__":
	unittest.main()
