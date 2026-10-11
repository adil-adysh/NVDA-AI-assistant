"""Host failure, native fallback, and adapter shutdown contracts."""

from __future__ import annotations

import queue
import sys
import threading
import types
from types import SimpleNamespace

import pytest

from tests.support import ADDON_ROOT, load_module, register_package


NAMESPACE = "adapter_fallback_testpkg"
register_package(NAMESPACE, ADDON_ROOT)
for package_name in ("config", "core", "service", "ui", "utils"):
	register_package(f"{NAMESPACE}.{package_name}", ADDON_ROOT / package_name)


def _stub(relative_name: str, **attributes: object) -> types.ModuleType:
	module = types.ModuleType(f"{NAMESPACE}.{relative_name}")
	for name, value in attributes.items():
		setattr(module, name, value)
	sys.modules[module.__name__] = module
	return module


class _LifecycleState:
	FAILED = "failed"
	HIDDEN = "hidden"


class _Lifecycle:
	def __init__(self) -> None:
		self.state = "stopped"
		self.failed = False

	def mark_failed(self) -> None:
		self.failed = True
		self.state = _LifecycleState.FAILED


class _HostUnavailableError(Exception):
	pass


class _Renderer:
	def __init__(self, **_kwargs) -> None:
		self.closed = False

	def register_host_closed_handler(self, _handler) -> None:
		return None

	def close(self) -> None:
		self.closed = True


_stub("config.settings", get_image_mime_type=lambda: "image/png", get_chat_auto_read=lambda: False, get_chat_status_announcements=lambda: True)
_stub("service.error_presentation", ErrorPresentation=object, present_error=lambda error: error)
_stub("service.provider_controls", provider_control_service=SimpleNamespace())
_stub("ui.host_lifecycle", HostLifecycleService=_Lifecycle, HostLifecycleState=_LifecycleState)
load_module(f"{NAMESPACE}.ui.intent", ADDON_ROOT / "ui" / "intent.py")
native_fallbacks: list[tuple[object, ...]] = []
nvda_ui = _stub(
	"ui.nvda_ui",
	queue=lambda callback, *args: native_fallbacks.append((callback, *args)) or callback(*args),
	message=lambda *_args: None,
	play_streaming_tone=lambda: None,
)
_stub(
	"ui.accessibility",
	coerce_announcement_text=lambda *args: None,
	queue_response_announcement=lambda *args: None,
	strip_html_for_announcement=lambda value: value,
)
_stub("ui.host_renderer", HostRenderer=_Renderer, HostUnavailableError=_HostUnavailableError)
_stub("ui.attachment_context", extract_attachment_context=lambda *_args: None)
_stub("ui.view_models", ChatWindowViewModel=object, DisplayResultViewModel=object)
_stub("ui.stream_projection", StreamProjection=object)
_stub("utils.markdown", render_markdown_to_html=lambda value: value)

adapter_module = load_module(f"{NAMESPACE}.ui.adapter", ADDON_ROOT / "ui" / "adapter.py")
# The module owns a singleton; close it immediately so collection never leaks a worker.
adapter_module.ui_adapter.close()


@pytest.mark.parametrize('mode, expected', [
	('display_only', ['display']), ('speak_only', ['speak']), ('speak_then_display', ['sequence']),
])
def test_one_shot_output_mode_and_reopening(monkeypatch, mode, expected):
	adapter = adapter_module.UIAdapter.__new__(adapter_module.UIAdapter)
	adapter._last_one_shot_result = None
	adapter._one_shot_generation = 0
	events = []
	view = SimpleNamespace(success=True, is_html=False, output_text='Answer', message=None)
	monkeypatch.setattr(adapter_module, 'coerce_announcement_text', lambda *_args: 'Answer')
	monkeypatch.setattr(adapter_module.nvda_ui, 'message', lambda text: events.append('speak'))
	adapter.render_display = lambda result: events.append('display')
	adapter.render_display_after_speech = lambda result, **kwargs: events.append('sequence')
	adapter.present_one_shot(view, mode)
	assert events == expected
	assert adapter.show_last_result()
	assert events[-1] == 'display'


def test_cancelled_one_shot_is_not_spoken_or_retained(monkeypatch):
	from importlib import import_module
	cancellation = import_module(f'{NAMESPACE}.core.cancellation')
	adapter = adapter_module.UIAdapter.__new__(adapter_module.UIAdapter)
	adapter._last_one_shot_result = None
	adapter._one_shot_generation = 0
	callbacks = []
	retained = []
	monkeypatch.setattr(adapter_module.nvda_ui, 'queue', lambda callback, *args: callbacks.append(lambda: callback(*args)))
	token = cancellation.CancellationToken()
	with cancellation.cancellation_scope(token):
		adapter.present_one_shot(SimpleNamespace(success=True), 'speak_only', on_present=lambda: retained.append(True))
	token.cancel()
	callbacks[0]()
	assert adapter._last_one_shot_result is None
	assert retained == []


def test_speak_then_display_waits_for_speech_completion(monkeypatch):
	adapter = adapter_module.UIAdapter.__new__(adapter_module.UIAdapter)
	adapter._last_one_shot_result = None
	adapter._one_shot_generation = 0
	completed, rendered = [], []
	monkeypatch.setattr(adapter_module, 'coerce_announcement_text', lambda *_args: 'Answer')
	monkeypatch.setattr(adapter_module.nvda_ui, 'queue_speech_then', lambda text, callback: completed.append(callback), raising=False)
	adapter.render_display = rendered.append
	view = SimpleNamespace(success=True, is_html=False, output_text='Answer', message=None)
	adapter.present_one_shot(view, 'speak_then_display')
	assert not rendered
	assert adapter._last_one_shot_result is view
	completed[0]()
	assert rendered == [view]


def test_speak_only_uses_plain_html_text_without_opening_host(monkeypatch):
	accessibility = load_module('one_shot_accessibility', ADDON_ROOT / 'ui' / 'accessibility.py')
	adapter = adapter_module.UIAdapter.__new__(adapter_module.UIAdapter)
	adapter._last_one_shot_result = None
	adapter._one_shot_generation = 0
	messages = []
	monkeypatch.setattr(adapter_module, 'strip_html_for_announcement', accessibility.strip_html_for_announcement)
	monkeypatch.setattr(adapter_module.nvda_ui, 'message', messages.append)
	adapter.present_one_shot(SimpleNamespace(success=True, is_html=True, output_html='<p>Hello <b>world</b></p>'), 'speak_only')
	assert messages == ['Hello world']


@pytest.mark.parametrize('replacement', ['new_result', 'explicit_reopen'])
def test_old_speech_callback_cannot_redisplay_after_newer_presentation(monkeypatch, replacement):
	adapter = adapter_module.UIAdapter.__new__(adapter_module.UIAdapter)
	adapter._last_one_shot_result = None
	adapter._one_shot_generation = 0
	completed, rendered = [], []
	monkeypatch.setattr(adapter_module, 'coerce_announcement_text', lambda *_args: 'Answer')
	monkeypatch.setattr(adapter_module.nvda_ui, 'queue_speech_then', lambda text, callback: completed.append(callback), raising=False)
	adapter.render_display = rendered.append
	view = SimpleNamespace(success=True, is_html=False, output_text='Answer', message=None)
	adapter.present_one_shot(view, 'speak_then_display')
	if replacement == 'new_result':
		new_view = SimpleNamespace(success=True)
		adapter.present_one_shot(new_view, 'display_only')
		assert rendered == [new_view]
	else:
		assert adapter.show_last_result()
		assert rendered == [view]
	completed[0]()
	assert len(rendered) == 1


def test_error_does_not_replace_last_result_or_follow_speak_only_mode():
	adapter = adapter_module.UIAdapter.__new__(adapter_module.UIAdapter)
	previous, failure = object(), SimpleNamespace(success=False)
	adapter._last_one_shot_result = previous
	adapter._one_shot_generation = 0
	rendered = []
	adapter.render_display = rendered.append
	adapter.present_one_shot(failure, 'speak_only')
	assert rendered == [failure]
	assert adapter._last_one_shot_result is previous


def test_host_failure_marks_lifecycle_and_dispatches_native_fallback() -> None:
	adapter = adapter_module.UIAdapter.__new__(adapter_module.UIAdapter)
	adapter._host_lifecycle = _Lifecycle()
	adapter._command_queue = queue.Queue()
	adapter._running = True
	fallback_called: list[bool] = []

	def fail() -> None:
		raise _HostUnavailableError

	adapter._command_queue.put((fail, lambda: fallback_called.append(True)))
	adapter._command_queue.put(adapter_module._STOP_WORKER)
	adapter._worker_loop()

	assert adapter._host_lifecycle.failed
	assert fallback_called == [True]
	assert native_fallbacks[-1][0] is not None


def test_close_wakes_and_joins_worker_thread() -> None:
	adapter = adapter_module.UIAdapter()
	assert adapter._worker_thread.is_alive()

	adapter.close()

	assert not adapter._worker_thread.is_alive()
	assert adapter._host_renderer.closed


def test_dispatch_after_close_uses_native_fallback() -> None:
	adapter = adapter_module.UIAdapter()
	adapter.close()
	fallback_called: list[bool] = []

	adapter._dispatch_host_command(lambda: None, lambda: fallback_called.append(True))

	assert fallback_called == [True]


def test_stop_action_cancels_only_exact_registered_request() -> None:
	adapter = adapter_module.UIAdapter()
	try:
		first = adapter_module.CancellationToken()
		second = adapter_module.CancellationToken()
		adapter._chat_requests.update({"first": ("A", first), "second": ("B", second)})
		adapter._handle_host_ui_action("chat_stop", {"request_id": "first", "conversation_id": "B"})
		assert not first.cancelled and not second.cancelled
		adapter._handle_host_ui_action("chat_stop", {"request_id": "first", "conversation_id": "A"})
		assert first.cancelled and not second.cancelled
		lifecycle = load_module(f"{NAMESPACE}.ui.production_host_lifecycle", ADDON_ROOT / "ui" / "host_lifecycle.py")
		adapter._host_lifecycle = lifecycle.HostLifecycleService()
		adapter._handle_host_closed({})
		assert not second.cancelled
	finally:
		adapter.close()
	assert second.cancelled


def test_request_supersession_and_other_conversation_do_not_match() -> None:
	adapter = adapter_module.UIAdapter()
	try:
		adapter._displayed_conversation_id = "A"
		adapter._chat_requests.update({
			"old": ("A", adapter_module.CancellationToken()),
			"new": ("A", adapter_module.CancellationToken()),
		})
		adapter._latest_chat_requests = {"A": "new"}
		assert not adapter._is_current_chat_request("old", "A")
		assert adapter._is_current_chat_request("new", "A")
		adapter._chat_requests.pop("new")
		assert not adapter._is_current_chat_request("old", "A")
		adapter._displayed_conversation_id = "B"
		assert not adapter._is_current_chat_request("new", "A")
	finally:
		adapter.close()


@pytest.mark.parametrize("wrapped_error", [False, True])
def test_readiness_stop_records_turn_and_finishes_without_focus(monkeypatch, wrapped_error) -> None:
	projection = load_module(f"{NAMESPACE}.ui.production_stream_projection", ADDON_ROOT / "ui" / "stream_projection.py")
	monkeypatch.setattr(adapter_module, "StreamProjection", projection.StreamProjection)
	adapter = adapter_module.UIAdapter()
	token = adapter_module.CancellationToken()
	appends = []
	recorded = []
	adapter._host_renderer.chat_append = lambda *args, **kwargs: appends.append((args, kwargs))
	adapter._displayed_conversation_id = "A"
	adapter._get_localized_strings = lambda: {}
	adapter._extract_attachment_context = lambda *_args: (None, "")
	def readiness(_announce):
		token.cancel()
		if wrapped_error:
			raise RuntimeError("startup failed after cancellation")
	adapter._litert_ready_handler = readiness

	def record(**kwargs):
		recorded.append(kwargs)
		return SimpleNamespace(text="[Stopped]", raw={"cancelled": True})

	coordinator = SimpleNamespace(record_stopped_turn=record, last_turn_committed=lambda: True)
	try:
		adapter._handle_host_chat_submission("hello", "A", coordinator, {}, "request", token)
		assert recorded == [{"text": "hello", "image_base64": None, "partial_text": "", "expected_conversation_id": "A"}]
		assert len(appends) == 2
		assert appends[0][1]["metadata"]["request_id"] == "request"
		metadata = appends[-1][1]["metadata"]
		assert metadata == {"request_id": "request", "cancelled": True, "attention_policy": "none"}
		assert not adapter._chat_requests
	finally:
		adapter.close()


def test_normal_final_metadata_requests_content_focus() -> None:
	adapter = adapter_module.UIAdapter()
	try:
		metadata = adapter._final_answer_metadata({"request_id": "request"})
		assert metadata == {"request_id": "request", "attention_policy": "activate_and_focus", "focus_target": "content"}
	finally:
		adapter.close()


def test_one_shot_stop_remains_available_until_post_speech_presentation(monkeypatch) -> None:
	from importlib import import_module
	from tests.plugin.test_background_shutdown import background, NAMESPACE as BACKGROUND_NAMESPACE, _wait_for_workers
	api = import_module(f"{BACKGROUND_NAMESPACE}.core.cancellation")
	# Both real modules share one cancellation API in the running add-on.
	monkeypatch.setattr(adapter_module, "current_cancellation_token", api.current_cancellation_token)
	monkeypatch.setattr(adapter_module, "cancellation_scope", api.cancellation_scope)
	monkeypatch.setattr(adapter_module, "coerce_announcement_text", lambda *_args: "Summary")
	queued, completed, rendered = [], [], []
	monkeypatch.setattr(background.nvda_ui, "queue", lambda callback, *args: queued.append((callback, args)))
	monkeypatch.setattr(adapter_module.nvda_ui, "queue", lambda callback, *args: queued.append((callback, args)))
	monkeypatch.setattr(adapter_module.nvda_ui, "queue_speech_then", lambda _text, callback: completed.append(callback), raising=False)
	adapter = adapter_module.UIAdapter()
	adapter.render_display = rendered.append
	result = SimpleNamespace(success=True, is_html=False, output_text="Summary", message=None)
	runner = background.BackgroundTaskRunner(object(), SimpleNamespace(execute=lambda *_args, **_kwargs: result), lambda *_args: None)
	try:
		runner.run_use_case_in_background(background.OPEN_CHAT, "Summary", adapter.render_display_after_speech)
		_wait_for_workers(runner)
		callback, args = queued.pop(0)
		callback(*args)
		callback, args = queued.pop(0)
		callback(*args)
		assert completed
		assert runner.cancel_active_requests() == 1
		completed[0]()
		assert not rendered
		assert not runner._requests
	finally:
		runner.close()
		adapter.close()


def test_submission_is_registered_before_thread_start(monkeypatch) -> None:
	adapter = adapter_module.UIAdapter()
	adapter._dispatch_primary_host_command = lambda *_args: None
	adapter._host_renderer.register_chat_submission_handler = lambda handler: setattr(adapter, "submit_chat", handler)
	for name in ("register_ui_action_handler", "register_provider_selection_handler", "register_model_selection_handler", "register_think_mode_handler"):
		setattr(adapter._host_renderer, name, lambda _handler: None)
	started = []

	class CapturedThread:
		def __init__(self, **kwargs):
			self.kwargs = kwargs

		def start(self):
			assert "request" in adapter._chat_requests
			adapter._handle_host_ui_action("chat_stop", {"request_id": "request", "conversation_id": "A"})
			started.append(self.kwargs)

	try:
		adapter.open_chat_view(SimpleNamespace(metadata={"conversation_id": "A"}), coordinator=object())
		monkeypatch.setattr(threading, "Thread", CapturedThread)
		adapter.submit_chat("hello", "A", {"request_id": "request"})
		assert started[0]["args"][-1].cancelled
	finally:
		adapter.close()


@pytest.mark.parametrize("auto_read", [False, True])
def test_chat_completion_speech_is_selected_by_python_setting(monkeypatch, auto_read) -> None:
	adapter = adapter_module.UIAdapter.__new__(adapter_module.UIAdapter)
	adapter._final_answer_metadata = lambda metadata: dict(metadata, focus_target="content")
	monkeypatch.setattr(adapter_module, "get_chat_auto_read", lambda: auto_read)
	monkeypatch.setattr(adapter_module, "render_markdown_to_html", lambda text: f"<p>{text}</p>")
	monkeypatch.setattr(adapter_module, "strip_html_for_announcement", lambda html: html[3:-4])
	metadata = adapter._chat_completion_metadata("request", "Completed answer")
	assert metadata["announcement_text"] == ("Completed answer" if auto_read else "")
	assert metadata["request_id"] == "request"
	assert metadata["focus_target"] == "content"


@pytest.mark.parametrize("alive", [False, True])
def test_reopening_hidden_host_restores_history_after_process_exit(alive) -> None:
	adapter = adapter_module.UIAdapter()
	lifecycle = load_module(f"{NAMESPACE}.ui.hidden_host_lifecycle", ADDON_ROOT / "ui" / "host_lifecycle.py")
	adapter._host_lifecycle = lifecycle.HostLifecycleService()
	adapter._host_lifecycle.mark_hidden()
	adapter._displayed_conversation_id = "A"
	opened, histories = [], []
	adapter._host_renderer.has_live_surface = lambda: alive
	adapter._host_renderer.open_chat = lambda **kwargs: opened.append(kwargs)
	adapter._host_renderer.chat_set_history = lambda *args, **kwargs: histories.append(args)
	for name in ("register_ui_action_handler", "register_provider_selection_handler", "register_model_selection_handler", "register_think_mode_handler"):
		setattr(adapter._host_renderer, name, lambda _handler: None)
	adapter._dispatch_primary_host_command = lambda command, _fallback: command()
	adapter._dispatch_host_command = lambda command, _fallback: command()
	try:
		adapter.open_chat_view(SimpleNamespace(metadata={"conversation_id": "A"}, use_case_id=None, title="Chat", initial_text=None, initial_image_base64=None), history_messages=[{"id": "saved", "role": "assistant", "content": []}])
		assert bool(opened[0]["metadata"].get("preserve_conversation")) == alive
		assert bool(histories) != alive
	finally:
		adapter.close()
