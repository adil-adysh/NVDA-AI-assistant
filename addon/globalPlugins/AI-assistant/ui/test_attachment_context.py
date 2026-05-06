# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
	sys.path.insert(0, str(MODULE_DIR))

PACKAGE_NAME = "ui_testpkg"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(MODULE_DIR)]
sys.modules.setdefault(PACKAGE_NAME, package)


def _load_module(module_name: str, file_name: str):
	spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.{module_name}", MODULE_DIR / file_name)
	if spec is None or spec.loader is None:
		raise RuntimeError(f"Unable to load {module_name}")
	module = importlib.util.module_from_spec(spec)
	sys.modules[spec.name] = module
	spec.loader.exec_module(module)
	return module


attachment_context = _load_module("attachment_context", "attachment_context.py")
extract_attachment_context = attachment_context.extract_attachment_context


class AttachmentContextTests(unittest.TestCase):
	def test_extracts_first_image_and_file_context(self) -> None:
		context = extract_attachment_context(
			[
				{"kind": "image", "name": "one.png", "image_base64": "abc"},
				{"kind": "file", "name": "notes.txt", "text": "hello"},
			],
			attached_file_label="Attached file",
		)

		self.assertEqual(context.image_base64, "abc")
		self.assertEqual(context.file_context, "Attached file: notes.txt\nhello")
		self.assertEqual(context.image_count, 1)

	def test_counts_multiple_images_without_overwriting_first_image(self) -> None:
		context = extract_attachment_context(
			[
				{"kind": "image", "name": "first.png", "image_base64": "first"},
				{"kind": "image", "name": "second.png", "image_base64": "second"},
			],
		)

		self.assertEqual(context.image_base64, "first")
		self.assertEqual(context.image_count, 2)

	def test_ignores_non_list_input(self) -> None:
		context = extract_attachment_context(None)

		self.assertIsNone(context.image_base64)
		self.assertEqual(context.file_context, "")
		self.assertEqual(context.image_count, 0)


if __name__ == "__main__":
	unittest.main()
