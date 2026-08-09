# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from test_bootstrap import load_module

attachment_context = load_module("attachment_context", "attachment_context.py")
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
