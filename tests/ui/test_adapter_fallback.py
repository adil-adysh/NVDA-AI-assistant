"""Host failure, native fallback, and adapter shutdown contracts."""

from __future__ import annotations

import queue
import sys
import types
from types import SimpleNamespace

from tests.support import ADDON_ROOT, load_module, register_package


NAMESPACE = "adapter_fallback_testpkg"
register_package(NAMESPACE, ADDON_ROOT)
for package_name in ("config", "service", "ui", "utils"):
	register_package(f"{NAMESPACE}.{package_name}", ADDON_ROOT / package_name)


def _stub(relative_name: str, **attributes: object) -> types.ModuleType:
	module = types.ModuleType(f"{NAMESPACE}.{relative_name}")
	for name, value in attributes.items():
		setattr(module, name, value)
	sys.modules[module.__name__] = module
	return module


class _LifecycleState:
	FAILED = "failed"


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


_stub("config.settings", get_image_mime_type=lambda: "image/png")
_stub("service.error_presentation", ErrorPresentation=object, present_error=lambda error: error)
_stub("service.provider_controls", provider_control_service=SimpleNamespace())
_stub("ui.host_lifecycle", HostLifecycleService=_Lifecycle, HostLifecycleState=_LifecycleState)
_stub(
	"ui.intent",
	ATTENTION_POLICY_FOREGROUND_IF_BACKGROUND="foreground",
	merge_presentation_intent=lambda *args, **kwargs: {},
)
native_fallbacks: list[tuple[object, ...]] = []
nvda_ui = _stub(
	"ui.nvda_ui",
	queue=lambda callback, *args: native_fallbacks.append((callback, *args)) or callback(*args),
	message=lambda *_args: None,
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
