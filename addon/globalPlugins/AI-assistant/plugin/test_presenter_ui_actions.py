# -*- coding: utf-8 -*-
# Pylint cannot infer attributes assigned to types.ModuleType() fakes used
# to stub NVDA-internal modules (E1101 ``__name__``/dynamic attribute
# false positives, e.g. ``ui_adapter_module.ui_adapter``).
# Tests intentionally inspect presenter internals (W0212) and deliberately
# duplicate the self-contained synthetic-package bootstrap (R0801).
# pylint: disable=no-member,protected-access,duplicate-code
from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
PACKAGE_NAME = "presenter_ui_action_testpkg"


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


@dataclass(frozen=True)
class _ProviderState:
	provider: str
	model_name: str


class _FakeUIAdapter:
	def __init__(self) -> None:
		self.result_action_handler = None
		self.session_metadata_provider = None
		self.render_display_calls = []

	def register_result_action_handler(self, handler) -> None:
		self.result_action_handler = handler

	def register_session_metadata_provider(self, provider) -> None:
		self.session_metadata_provider = provider

	def open_chat_view(self, *args, **kwargs) -> None:
		pass

	def sync_session_state(self, *args, **kwargs) -> None:
		pass

	def render_display(self, *args, **kwargs) -> None:
		self.render_display_calls.append({"args": args, "kwargs": kwargs})

	def close(self) -> None:
		pass


class _FakeResultActionStore:
	def __init__(self) -> None:
		self._payloads: dict[str, dict[str, object]] = {}
		self._next_token = 0

	def put(self, payload: dict[str, object]) -> str:
		self._next_token += 1
		token = f"token-{self._next_token}"
		self._payloads[token] = dict(payload)
		return token

	def pop(self, token: str) -> dict[str, object] | None:
		payload = self._payloads.pop(token, None)
		return dict(payload) if payload is not None else None

	def clear(self) -> None:
		self._payloads.clear()


class _FakeProviderCatalogService:
	def list_active_models(self):
		return ()


class _FakeProviderReadinessService:
	def evaluate_active(self):
		return None


class _FakeToolRegistry:
	pass


@dataclass(frozen=True)
class _FakeDeleteResult:
	deleted: bool
	active_conversation_deleted: bool
	active_conversation_id: str | None


class _FakeConversationService:
	def __init__(self) -> None:
		self.delete_result = _FakeDeleteResult(False, False, None)
		self.open_calls: list[dict[str, object]] = []
		self.user_context_calls: list[dict[str, object | None]] = []
		self.assistant_result_calls: list[str] = []

	def open_conversation(self, **kwargs):
		self.open_calls.append(dict(kwargs))
		return "conv-active"

	def add_user_context(self, *, content=None, image_base64=None):
		self.user_context_calls.append({"content": content, "image_base64": image_base64})
		return "conv-active"

	def add_assistant_result(self, content):
		self.assistant_result_calls.append(content)
		return "conv-active"

	def current_conversation_id(self):
		return "conv-active"

	def history_transport(self):
		return []

	def list_conversation_summaries(self):
		return []

	def delete_conversation(self, _conversation_id: str):
		return self.delete_result


def _item(item_id: str, content: str | None = None, image_base64: str | None = None):
	"""Build a minimal context/output item stand-in (SimpleNamespace)."""
	return types.SimpleNamespace(id=item_id, content=content, image_base64=image_base64)


def _make_result(context_items=(), output_items=(), metadata: dict[str, object] | None = None):
	return types.SimpleNamespace(
		context_items=tuple(context_items),
		output_items=tuple(output_items),
		metadata={"result_actions": True, **(metadata or {})},
	)


class _FakeChatCoordinator:
	pass


def _build_session_state(*_args, **_kwargs):
	class _SessionState:
		def to_metadata(self) -> dict[str, object]:
			return {}

	return _SessionState()


def _merge_session_metadata(metadata, session_state):
	merged = dict(metadata) if isinstance(metadata, dict) else {}
	merged.update(session_state.to_metadata())
	return merged


def _merge_presentation_intent(metadata: dict[str, object], **kwargs) -> dict[str, object]:
	merged = dict(metadata)
	merged.update(kwargs)
	return merged


def _build_display_presentation(**kwargs) -> dict[str, object]:
	return dict(kwargs)


def _render_markdown_to_html(text: str) -> str:
	return f"<p>{text}</p>"


def _no_op(*_args, **_kwargs) -> None:
	return None


_register_package(PACKAGE_NAME, ROOT_DIR)
_register_package(f"{PACKAGE_NAME}.plugin", MODULE_DIR)
_register_package(f"{PACKAGE_NAME}.config", ROOT_DIR / "config")
_register_package(f"{PACKAGE_NAME}.core", ROOT_DIR / "core")
_register_package(f"{PACKAGE_NAME}.service", ROOT_DIR / "service")
_register_package(f"{PACKAGE_NAME}.ui", ROOT_DIR / "ui")
_register_package(f"{PACKAGE_NAME}.utils", ROOT_DIR / "utils")

log_handler_module = types.ModuleType("logHandler")
log_handler_module.log = types.SimpleNamespace(debug=_no_op, warning=_no_op, exception=_no_op)
sys.modules["logHandler"] = log_handler_module

config_state_module = types.ModuleType(f"{PACKAGE_NAME}.config.state")
config_state_module.ProviderState = _ProviderState
sys.modules[config_state_module.__name__] = config_state_module

config_settings_module = types.ModuleType(f"{PACKAGE_NAME}.config.settings")
config_settings_module.get_provider_state = lambda: _ProviderState(provider="ollama", model_name="test-model")
sys.modules[config_settings_module.__name__] = config_settings_module

core_events_module = types.ModuleType(f"{PACKAGE_NAME}.core.events")
core_events_module.ProgressEvent = object
sys.modules[core_events_module.__name__] = core_events_module

service_chat_module = types.ModuleType(f"{PACKAGE_NAME}.service.chat")
service_chat_module.ChatCoordinator = _FakeChatCoordinator
service_chat_module.ConversationService = _FakeConversationService
sys.modules[service_chat_module.__name__] = service_chat_module

provider_catalog_module = types.ModuleType(f"{PACKAGE_NAME}.service.provider_catalog")
provider_catalog_module.ProviderCatalogService = _FakeProviderCatalogService
sys.modules[provider_catalog_module.__name__] = provider_catalog_module

provider_readiness_module = types.ModuleType(f"{PACKAGE_NAME}.service.provider_readiness")
provider_readiness_module.ProviderReadinessService = _FakeProviderReadinessService
sys.modules[provider_readiness_module.__name__] = provider_readiness_module

tools_module = types.ModuleType(f"{PACKAGE_NAME}.tools")
tools_module.ToolRegistry = _FakeToolRegistry
sys.modules[tools_module.__name__] = tools_module

ui_adapter_module = types.ModuleType(f"{PACKAGE_NAME}.ui.adapter")
ui_adapter_module.ui_adapter = _FakeUIAdapter()
sys.modules[ui_adapter_module.__name__] = ui_adapter_module

ui_action_store_module = types.ModuleType(f"{PACKAGE_NAME}.ui.action_store")
ui_action_store_module.ResultActionStore = _FakeResultActionStore
sys.modules[ui_action_store_module.__name__] = ui_action_store_module

ui_intent_module = types.ModuleType(f"{PACKAGE_NAME}.ui.intent")
ui_intent_module.ATTENTION_POLICY_ACTIVATE_AND_FOCUS = "activate_and_focus"
ui_intent_module.ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND = "foreground_if_background"
ui_intent_module.DISPLAY_VARIANT_RESULT_ACTIONS = "result_actions"
ui_intent_module.DISPLAY_VARIANT_STANDARD = "standard"
ui_intent_module.FOCUS_TARGET_COMPOSER = "composer"
ui_intent_module.FOCUS_TARGET_CONTENT = "content"
ui_intent_module.FOCUS_TARGET_PRIMARY_ACTION = "primary_action"
ui_intent_module.INTERACTION_MODE_CHAT = "chat"
ui_intent_module.INTERACTION_MODE_DISPLAY = "display"
ui_intent_module.TOOLBAR_ACTION_CLEAR = "clear"
ui_intent_module.TOOLBAR_ACTION_CLOSE = "close"
ui_intent_module.TOOLBAR_ACTION_COPY_MARKDOWN = "copy_markdown"
ui_intent_module.TOOLBAR_ACTION_COPY_TEXT = "copy_text"
ui_intent_module.build_display_presentation = _build_display_presentation
ui_intent_module.merge_presentation_intent = _merge_presentation_intent
sys.modules[ui_intent_module.__name__] = ui_intent_module

ui_nvda_ui_module = types.ModuleType(f"{PACKAGE_NAME}.ui.nvda_ui")
ui_nvda_ui_module.format_browseable_title = lambda title, provider_state: title
ui_nvda_ui_module.message = _no_op
ui_nvda_ui_module.queue = _no_op
ui_nvda_ui_module.play_streaming_tone = _no_op
sys.modules[ui_nvda_ui_module.__name__] = ui_nvda_ui_module

ui_session_state_module = types.ModuleType(f"{PACKAGE_NAME}.ui.session_state")
ui_session_state_module.build_session_state = _build_session_state
ui_session_state_module.merge_session_metadata = _merge_session_metadata
sys.modules[ui_session_state_module.__name__] = ui_session_state_module

ui_view_models_module = types.ModuleType(f"{PACKAGE_NAME}.ui.view_models")
ui_view_models_module.ChatWindowViewModel = types.SimpleNamespace
ui_view_models_module.DisplayResultViewModel = types.SimpleNamespace
ui_view_models_module.ResultActionViewModel = types.SimpleNamespace
sys.modules[ui_view_models_module.__name__] = ui_view_models_module

utils_markdown_module = types.ModuleType(f"{PACKAGE_NAME}.utils.markdown")
utils_markdown_module.render_markdown_to_html = _render_markdown_to_html
sys.modules[utils_markdown_module.__name__] = utils_markdown_module

ui_actions_module = _load_module(f"{PACKAGE_NAME}.plugin.ui_actions", MODULE_DIR / "ui_actions.py")
presenter_module = _load_module(f"{PACKAGE_NAME}.plugin.presenter", MODULE_DIR / "presenter.py")

UseCasePresenter = presenter_module.UseCasePresenter


class PresenterUIActionTests(unittest.TestCase):
	def setUp(self) -> None:
		self.conversation_service = _FakeConversationService()
		self.presenter = UseCasePresenter(
			chat_coordinator=_FakeChatCoordinator(),
			conversation_service=self.conversation_service,
			tool_registry=_FakeToolRegistry(),
			provider_catalog=_FakeProviderCatalogService(),
			readiness_service=_FakeProviderReadinessService(),
		)

	def test_handle_result_action_conversation_open_calls_open_chat_window(self) -> None:
		captured: list[dict[str, object | None]] = []
		self.presenter.open_chat_window = lambda **kwargs: captured.append(kwargs)

		self.presenter._handle_result_action("conversation_open", {"conversation_id": "conv-123"})

		self.assertEqual(captured, [{"conversation_id": "conv-123"}])

	def test_open_in_new_chat_creates_new_conversation_with_context_and_result(self) -> None:
		captured: list[dict[str, object | None]] = []
		self.presenter.open_chat_window = lambda **kwargs: captured.append(kwargs)
		token = self.presenter._result_action_store.put(
			{
				"context_items": [
					{"kind": "context", "id": "page_content", "content": "Page content...", "image_base64": None}
				],
				"output_items": [{"kind": "output", "id": "summary", "content": "The summary"}],
			}
		)

		self.presenter._handle_result_action("open_in_new_chat", {"token": token})

		self.assertEqual(len(captured), 1)
		call = captured[0]
		self.assertEqual(call["force_new_conversation"], True)
		seed_messages = call["seed_messages"]
		self.assertEqual(len(seed_messages), 2)
		# Context is user-side material, the result is an assistant message.
		self.assertEqual(seed_messages[0].role, "user")
		self.assertEqual(seed_messages[0].parts[0].text, "Page content...")
		self.assertEqual(seed_messages[1].role, "assistant")
		self.assertEqual(seed_messages[1].parts[0].text, "The summary")

	def test_open_in_new_chat_carries_focused_image_context(self) -> None:
		captured: list[dict[str, object | None]] = []
		self.presenter.open_chat_window = lambda **kwargs: captured.append(kwargs)
		token = self.presenter._result_action_store.put(
			{
				"context_items": [
					{
						"kind": "context",
						"id": "focused_image",
						"content": "Focused element role: button\nName: Save",
						"image_base64": "aW1n",
					}
				],
				"output_items": [
					{"kind": "output", "id": "focused_image_description", "content": "A save button"}
				],
			}
		)

		self.presenter._handle_result_action("open_in_new_chat", {"token": token})

		seed_messages = captured[0]["seed_messages"]
		self.assertEqual(seed_messages[0].role, "user")
		self.assertEqual(seed_messages[0].parts[0].text, "Focused element role: button\nName: Save")
		image_part = seed_messages[0].parts[1]
		self.assertEqual(image_part.type, "image")
		self.assertEqual(image_part.image, b"img")
		self.assertEqual(seed_messages[1].role, "assistant")

	def test_open_chat_window_reuses_current_conversation_by_default(self) -> None:
		self.presenter.open_chat_window()

		self.assertEqual(
			self.conversation_service.open_calls,
			[
				{
					"conversation_id": None,
					"initial_assistant_text": None,
					"initial_image_base64": None,
					"force_new": False,
					"seed_messages": None,
				}
			],
		)

	def test_add_summary_to_chat_injects_assistant_result(self) -> None:
		captured: list[dict[str, object | None]] = []
		self.presenter.open_chat_window = lambda **kwargs: captured.append(kwargs)
		token = self.presenter._result_action_store.put(
			{
				"context_items": [],
				"output_items": [{"kind": "output", "id": "summary", "content": "Summary text"}],
			}
		)

		self.presenter._handle_result_action("add_summary_to_chat", {"token": token, "item_id": "summary"})

		self.assertEqual(self.conversation_service.assistant_result_calls, ["Summary text"])
		self.assertEqual(self.conversation_service.user_context_calls, [])
		self.assertEqual(captured, [{"force_new_conversation": False}])

	def test_add_page_content_to_chat_injects_user_context(self) -> None:
		captured: list[dict[str, object | None]] = []
		self.presenter.open_chat_window = lambda **kwargs: captured.append(kwargs)
		token = self.presenter._result_action_store.put(
			{
				"context_items": [
					{"kind": "context", "id": "page_content", "content": "Page content...", "image_base64": None}
				],
				"output_items": [],
			}
		)

		self.presenter._handle_result_action(
			"add_page_content_to_chat", {"token": token, "item_id": "page_content"}
		)

		self.assertEqual(
			self.conversation_service.user_context_calls,
			[{"content": "Page content...", "image_base64": None}],
		)
		self.assertEqual(self.conversation_service.assistant_result_calls, [])
		self.assertEqual(captured, [{"force_new_conversation": False}])

	def test_add_screenshot_to_chat_injects_user_context_with_image(self) -> None:
		captured: list[dict[str, object | None]] = []
		self.presenter.open_chat_window = lambda **kwargs: captured.append(kwargs)
		token = self.presenter._result_action_store.put(
			{
				"context_items": [
					{"kind": "context", "id": "screenshot", "content": None, "image_base64": "aW1n"}
				],
				"output_items": [],
			}
		)

		self.presenter._handle_result_action(
			"add_screenshot_to_chat", {"token": token, "item_id": "screenshot"}
		)

		self.assertEqual(
			self.conversation_service.user_context_calls,
			[{"content": None, "image_base64": "aW1n"}],
		)
		self.assertEqual(captured, [{"force_new_conversation": False}])

	def test_add_item_with_expired_token_is_noop(self) -> None:
		captured: list[dict[str, object | None]] = []
		self.presenter.open_chat_window = lambda **kwargs: captured.append(kwargs)

		self.presenter._handle_result_action("add_summary_to_chat", {"token": "token-gone", "item_id": "summary"})

		self.assertEqual(self.conversation_service.assistant_result_calls, [])
		self.assertEqual(self.conversation_service.user_context_calls, [])
		self.assertEqual(captured, [])

	def test_add_item_without_token_is_ignored(self) -> None:
		"""Malformed payload without a token is rejected at parse time."""
		captured: list[dict[str, object | None]] = []
		self.presenter.open_chat_window = lambda **kwargs: captured.append(kwargs)

		self.presenter._handle_result_action("add_summary_to_chat", {})

		self.assertEqual(self.conversation_service.assistant_result_calls, [])
		self.assertEqual(captured, [])

	def test_add_item_with_unknown_item_id_is_noop(self) -> None:
		captured: list[dict[str, object | None]] = []
		self.presenter.open_chat_window = lambda **kwargs: captured.append(kwargs)
		token = self.presenter._result_action_store.put(
			{
				"context_items": [],
				"output_items": [{"kind": "output", "id": "summary", "content": "Summary text"}],
			}
		)

		self.presenter._handle_result_action(
			"add_page_content_to_chat", {"token": token, "item_id": "page_content"}
		)

		self.assertEqual(self.conversation_service.assistant_result_calls, [])
		self.assertEqual(self.conversation_service.user_context_calls, [])
		self.assertEqual(captured, [])

	def test_build_result_actions_for_summary(self) -> None:
		result = _make_result(
			context_items=(
				_item("page_content", "Page content..."),
				_item("page_structure", "Page structure..."),
			),
			output_items=(_item("summary", "Summary text"),),
		)

		actions = self.presenter._build_result_actions(result)

		self.assertEqual(
			[(action.id, action.label) for action in actions],
			[
				("add_page_content_to_chat", "Add Page Content to Chat"),
				("add_page_structure_to_chat", "Add Page Structure to Chat"),
				("add_summary_to_chat", "Add Summary to Chat"),
				("open_in_new_chat", "Open in New Chat"),
			],
		)
		# All actions share one token referencing the stored payload; item
		# actions also carry the selected item id.
		token = actions[0].payload["token"]
		for action in actions:
			self.assertEqual(action.payload["token"], token)
		self.assertEqual(actions[0].payload["item_id"], "page_content")
		self.assertEqual(actions[1].payload["item_id"], "page_structure")
		self.assertEqual(actions[2].payload["item_id"], "summary")
		self.assertNotIn("item_id", actions[3].payload)
		stored = self.presenter._result_action_store.pop(token)
		self.assertEqual(
			[(item["kind"], item["id"]) for item in stored["context_items"]],
			[("context", "page_content"), ("context", "page_structure")],
		)
		self.assertEqual(
			[(item["kind"], item["id"]) for item in stored["output_items"]],
			[("output", "summary")],
		)

	def test_build_result_actions_for_structure_summary(self) -> None:
		result = _make_result(
			context_items=(
				_item("page_content", "Page content..."),
				_item("page_structure", "Page structure..."),
			),
			output_items=(_item("structure_summary", "Structure summary text"),),
		)

		actions = self.presenter._build_result_actions(result)

		self.assertEqual(
			[(action.id, action.label) for action in actions],
			[
				("add_page_content_to_chat", "Add Page Content to Chat"),
				("add_page_structure_to_chat", "Add Page Structure to Chat"),
				("add_structure_summary_to_chat", "Add Structure Summary to Chat"),
				("open_in_new_chat", "Open in New Chat"),
			],
		)

	def test_build_result_actions_for_image_description(self) -> None:
		result = _make_result(
			context_items=(_item("screenshot", None, image_base64="aW1n"),),
			output_items=(_item("image_description", "Image description text"),),
		)

		actions = self.presenter._build_result_actions(result)

		self.assertEqual(
			[(action.id, action.label) for action in actions],
			[
				("add_screenshot_to_chat", "Add Screenshot to Chat"),
				("add_image_description_to_chat", "Add Image Description to Chat"),
				("open_in_new_chat", "Open in New Chat"),
			],
		)

	def test_build_result_actions_for_focused_image_description(self) -> None:
		result = _make_result(
			context_items=(_item("focused_image", "Focused element role: button", image_base64="aW1n"),),
			output_items=(_item("focused_image_description", "Focused image description text"),),
		)

		actions = self.presenter._build_result_actions(result)

		self.assertEqual(
			[(action.id, action.label) for action in actions],
			[
				("add_focused_image_to_chat", "Add Focused Image to Chat"),
				("add_focused_image_description_to_chat", "Add Focused Image Description to Chat"),
				("open_in_new_chat", "Open in New Chat"),
			],
		)

	def test_build_result_actions_omits_missing_structure(self) -> None:
		result = _make_result(
			context_items=(_item("page_content", "Page content..."),),
			output_items=(_item("summary", "Summary text"),),
		)

		actions = self.presenter._build_result_actions(result)

		self.assertEqual(
			[action.id for action in actions],
			["add_page_content_to_chat", "add_summary_to_chat", "open_in_new_chat"],
		)

	def test_build_result_actions_omits_empty_output(self) -> None:
		result = _make_result(
			context_items=(_item("screenshot", None, image_base64="aW1n"),),
			output_items=(_item("image_description", "   "),),
		)

		actions = self.presenter._build_result_actions(result)

		self.assertEqual(
			[action.id for action in actions],
			["add_screenshot_to_chat", "open_in_new_chat"],
		)

	def test_build_result_actions_omits_missing_image(self) -> None:
		result = _make_result(
			context_items=(_item("screenshot", None, image_base64=None),),
			output_items=(_item("image_description", "Description text"),),
		)

		actions = self.presenter._build_result_actions(result)

		self.assertEqual(
			[action.id for action in actions],
			["add_image_description_to_chat", "open_in_new_chat"],
		)

	def test_build_result_actions_requires_result_actions_flag(self) -> None:
		result = _make_result(
			context_items=(_item("page_content", "Page content..."),),
			output_items=(_item("summary", "Summary text"),),
			metadata={"result_actions": False},
		)

		actions = self.presenter._build_result_actions(result)

		self.assertEqual(actions, [])

	def test_build_result_actions_without_items_returns_empty(self) -> None:
		result = _make_result(context_items=(), output_items=())

		actions = self.presenter._build_result_actions(result)

		self.assertEqual(actions, [])

	def test_build_result_actions_does_not_expose_legacy_labels(self) -> None:
		result = _make_result(
			context_items=(
				_item("page_content", "Page content..."),
				_item("page_structure", "Page structure..."),
			),
			output_items=(_item("summary", "Summary text"),),
		)

		actions = self.presenter._build_result_actions(result)

		labels = [action.label for action in actions]
		self.assertNotIn("Add to current chat", labels)
		self.assertNotIn("Open Chat", labels)
		ids = [action.id for action in actions]
		self.assertNotIn("attach_to_current", ids)
		self.assertNotIn("open_chat", ids)

	def test_present_use_case_result_focuses_content_for_describe_image(self) -> None:
		ui_adapter_module.ui_adapter.render_display_calls.clear()
		result = types.SimpleNamespace(
			output_text="Image description text",
			output_html=None,
			is_browseable=False,
			metadata={},
			message=None,
			prompt_context=types.SimpleNamespace(use_case_id="describe_image"),
			initial_image_base64="img-123",
		)

		self.presenter.present_use_case_result(result, title="Image description")

		self.assertEqual(len(ui_adapter_module.ui_adapter.render_display_calls), 1)
		view_model = ui_adapter_module.ui_adapter.render_display_calls[0]["args"][0]
		self.assertEqual(view_model.display_presentation["initial_focus"], "content")

	def test_handle_result_action_reopens_chat_when_active_conversation_deleted(self) -> None:
		captured_opens: list[dict[str, object | None]] = []
		update_calls: list[str] = []
		self.presenter.open_chat_window = lambda **kwargs: captured_opens.append(kwargs)
		self.presenter.update_provider_state = lambda *args, **kwargs: update_calls.append("updated")
		self.conversation_service.delete_result = _FakeDeleteResult(
			deleted=True,
			active_conversation_deleted=True,
			active_conversation_id=None,
		)

		self.presenter._handle_result_action("conversation_delete", {"conversation_id": "conv-123"})

		self.assertEqual(captured_opens, [{"force_new_conversation": True}])
		self.assertEqual(update_calls, [])


if __name__ == "__main__":
	unittest.main()
