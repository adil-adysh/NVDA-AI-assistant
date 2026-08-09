# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from test_bootstrap import load_module

intent = load_module("intent", "intent.py")
view_models = load_module("view_models", "view_models.py")

ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND = intent.ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND
DISPLAY_VARIANT_RESULT_ACTIONS = intent.DISPLAY_VARIANT_RESULT_ACTIONS
FOCUS_TARGET_PRIMARY_ACTION = intent.FOCUS_TARGET_PRIMARY_ACTION
TOOLBAR_ACTION_CLOSE = intent.TOOLBAR_ACTION_CLOSE
TOOLBAR_ACTION_COPY_MARKDOWN = intent.TOOLBAR_ACTION_COPY_MARKDOWN
TOOLBAR_ACTION_COPY_TEXT = intent.TOOLBAR_ACTION_COPY_TEXT
build_display_presentation = intent.build_display_presentation
DisplayResultViewModel = view_models.DisplayResultViewModel
ResultActionViewModel = view_models.ResultActionViewModel


class ViewModelTransportTests(unittest.TestCase):
	def test_display_result_transport_metadata_includes_display_presentation(self) -> None:
		view_model = DisplayResultViewModel(
			use_case_id="summary",
			title="Summary",
			output_text="Example",
			actions=(ResultActionViewModel(id="add_summary_to_chat", label="Add Summary to Chat", kind="add_summary_to_chat"),),
			display_presentation=build_display_presentation(
				variant=DISPLAY_VARIANT_RESULT_ACTIONS,
				initial_focus=FOCUS_TARGET_PRIMARY_ACTION,
				toolbar_actions=(
					TOOLBAR_ACTION_COPY_TEXT,
					TOOLBAR_ACTION_COPY_MARKDOWN,
					TOOLBAR_ACTION_CLOSE,
				),
			),
			controls_visible=False,
			attention_policy=ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND,
		)

		metadata = view_model.transport_metadata()

		self.assertEqual(metadata["display_presentation"]["variant"], DISPLAY_VARIANT_RESULT_ACTIONS)
		self.assertEqual(metadata["display_presentation"]["initial_focus"], FOCUS_TARGET_PRIMARY_ACTION)
		self.assertEqual(
			metadata["display_presentation"]["toolbar"]["actions"],
			[TOOLBAR_ACTION_COPY_TEXT, TOOLBAR_ACTION_COPY_MARKDOWN, TOOLBAR_ACTION_CLOSE],
		)
		self.assertEqual(metadata["controls_visible"], False)
		self.assertEqual(metadata["attention_policy"], ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND)
		self.assertEqual(metadata["actions"][0]["id"], "add_summary_to_chat")


if __name__ == "__main__":
	unittest.main()
