from __future__ import annotations

import builtins
import math
import re
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any, Optional, cast

import wx
from gui import guiHelper
from logHandler import log

from ..config import defaults
from ..providers.interfaces import DownloadCancelledError
from .task_runner import UiDispatcher

_ = cast(Callable[[str], str], getattr(builtins, "_", lambda s: s))

_BYTES_PER_MB = 1024 * 1024
_BYTES_PER_GB = 1024 * 1024 * 1024
_PATTERN = re.compile(r"\((\d+)/(\d+)\)")


def bytes_to_mb(bytes_value: int) -> float:
	return bytes_value / _BYTES_PER_MB


def bytes_to_gb(bytes_value: int) -> float:
	return bytes_value / _BYTES_PER_GB


def format_size(bytes_value: int) -> str:
	if bytes_value >= _BYTES_PER_GB:
		return f"{bytes_to_gb(bytes_value):.1f} GB"
	return f"{bytes_to_mb(bytes_value):.0f} MB"


def format_eta(seconds: float) -> str:
	if seconds < 0:
		return "estimating time"
	rounded = int(round(seconds))
	if rounded < 10:
		return "almost done"
	if rounded < 60:
		return f"{rounded} seconds remaining"
	if rounded < 3600:
		minutes = int(round(rounded / 60))
		return f"{minutes} minutes remaining"
	hours = int(round(rounded / 3600))
	return f"{hours} hours remaining"


# ------------------------------------------------------------------
# Modal download progress dialog (reusable across model & runtime downloads)
# ------------------------------------------------------------------


class DownloadProgressDialog(wx.Dialog):
	"""Modal progress dialog for background downloads.

	Blocks all interaction with the parent window, shows a progress
	label and gauge, and auto-closes when the download thread finishes.
	The user can cancel the download via a Cancel button or Escape key.
	"""

	def __init__(
		self,
		parent: wx.Window,
		title: str,
		initial_message: str = "",
	) -> None:
		super().__init__(
			parent,
			title=title,
			style=wx.DEFAULT_DIALOG_STYLE,
		)
		self._completed = False
		self._closed = False
		self._cancel_event = threading.Event()
		self._completion_lock = threading.Lock()

		sizer = wx.BoxSizer(wx.VERTICAL)

		self._label = wx.StaticText(self, label=initial_message)
		sizer.Add(self._label, flag=wx.ALL | wx.EXPAND, border=12)

		sizer.AddSpacer(8)

		self._gauge = wx.Gauge(self, range=100, size=(380, 22))
		sizer.Add(self._gauge, flag=wx.LEFT | wx.RIGHT | wx.EXPAND, border=12)

		sizer.AddSpacer(12)

		# Cancel button
		button_sizer = guiHelper.ButtonHelper(wx.HORIZONTAL)
		self._cancel_btn = button_sizer.addButton(
			self,
			wx.ID_CANCEL,
			# TRANSLATORS: Button to cancel an in-progress download.
			label=_("Cancel"),
		)
		self._cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
		sizer.Add(button_sizer.sizer, flag=wx.ALIGN_CENTER | wx.BOTTOM, border=12)

		self.SetSizer(sizer)
		sizer.Fit(self)
		self.SetMinSize((420, -1))

		# Escape key routes to cancel (dialog-level keyboard routing).
		self.SetEscapeId(wx.ID_CANCEL)

		self.CentreOnParent()
		self.Raise()

		# Close button / Alt+F4 / Escape all route through cancel.
		self.Bind(wx.EVT_CLOSE, self._on_close)

	@property
	def cancel_event(self) -> threading.Event:
		"""A ``threading.Event`` that is set when the user requests cancellation.

		Download worker threads should check ``cancel_event.is_set()``
		periodically and raise :exc:`DownloadCancelledError` to abort.
		"""
		return self._cancel_event

	def _on_cancel(self, _event: wx.Event) -> None:
		"""User pressed Cancel — signal the worker thread to stop."""
		if self._completed:
			return
		self._cancel_event.set()
		self._cancel_btn.Disable()
		# TRANSLATORS: Label shown when user has requested download cancellation.
		self._post_ui(lambda: self._label.SetLabel(_("Cancelling...")))

	def _on_close(self, event: wx.CloseEvent) -> None:
		"""Route title-bar close / Alt+F4 to cancel; allow close when done."""
		if self._completed:
			event.Skip()
		else:
			self._on_cancel(event)

	# ------------------------------------------------------------------
	# Thread-safe progress updates
	# ------------------------------------------------------------------

	def update_message(self, message: str) -> None:
		"""Update the label. Safe from any thread."""
		self._post_ui(lambda: self._label.SetLabel(message))

	def update_progress(self, downloaded: int, total: int) -> None:
		"""Update the gauge. Safe from any thread."""
		self._post_ui(lambda: self._do_update_progress(downloaded, total))

	def _post_ui(self, callback: Callable[[], None]) -> None:
		"""Post only while the dialog is alive; workers may finish late."""
		UiDispatcher.post(lambda: callback() if not self._closed else None)

	def _do_update_progress(self, downloaded: int, total: int) -> None:
		if total and total > 0:
			pct = min(downloaded * 100 // total, 100)
			self._gauge.SetRange(100)
			self._gauge.SetValue(pct)
		else:
			# Indeterminate — pulse the gauge.
			val = self._gauge.GetValue()
			self._gauge.SetValue(0 if val >= 100 else val + 5)

	# ------------------------------------------------------------------
	# Completion
	# ------------------------------------------------------------------

	def signal_complete(self, success: bool, message: str | None = None) -> None:
		"""Mark download as finished and close the dialog.

		On failure, shows an error message box before closing.
		Cancelled downloads close silently (the partial file is kept).
		"""
		with self._completion_lock:
			if self._completed:
				return
			self._completed = True
		self._post_ui(lambda: self._finish(success, message))

	def _finish(self, success: bool, message: str | None) -> None:
		if not self._cancel_event.is_set() and message:
			self._do_show_final_message(success, message)
		self._closed = True
		self.EndModal(wx.ID_OK)

	def _do_show_final_message(self, success: bool, message: str) -> None:
		icon = wx.ICON_INFORMATION if success else wx.ICON_ERROR
		wx.MessageBox(message, self.GetTitle(), icon, parent=self)

	# ------------------------------------------------------------------
	# Convenience launcher
	# ------------------------------------------------------------------

	@classmethod
	def run(
		cls,
		parent: wx.Window,
		title: str,
		worker: Callable[..., Any],
		on_complete: Callable[[], Any] | None = None,
		initial_message: str = "",
		worker_args: tuple[Any, ...] = (),
	) -> None:
		"""Create, show, and manage the dialog for a background download.

		*worker* is called as ``worker(dialog, *worker_args)`` from a
		daemon thread. It should periodically call
		``dialog.update_message()`` / ``dialog.update_progress()`` and
		finish with ``dialog.signal_complete(success, message)``.

		The worker can check ``dialog.cancel_event.is_set()`` to detect
		user cancellation and should raise :exc:`DownloadCancelledError`
		to abort cleanly.

		If *worker* raises, the dialog closes and shows the error.
		*on_complete* runs on the main thread after the dialog is destroyed.
		"""
		dlg = cls(parent, title, initial_message)

		def wrapper() -> None:
			try:
				worker(dlg, *worker_args)
			except DownloadCancelledError:
				log.debug("Download cancelled by user")
				# Partial file left in place for future resume.
				dlg.signal_complete(False)
			except Exception as exc:
				log.error("Download failed: %s", exc)
				dlg.signal_complete(
					False,
					# TRANSLATORS: Generic download failure; {error} is the reason.
					_("Download failed: {error}").format(error=exc),
				)

		thread = threading.Thread(target=wrapper, daemon=True)
		thread.start()
		dlg.ShowModal()
		dlg.Destroy()

		if on_complete is not None:
			on_complete()


# ------------------------------------------------------------------
# Ollama download progress tracker (pre-existing)
# ------------------------------------------------------------------


class DownloadProgressTracker:
	def __init__(self, speak: Callable[[str], None]) -> None:
		self._speak = speak
		self.total_bytes: Optional[int] = None
		self.last_downloaded_bytes = 0
		self.last_time = time.time()
		self.speed_samples: list[float] = []
		self.last_announced_percent = -1
		self.last_announce_time = 0.0
		self.start_time = 0.0
		self.announced_start = False
		self.finished = False

	def process_event(self, event: dict[str, Any]) -> None:
		if self.finished:
			return

		if "total" not in event or "completed" not in event:
			return

		try:
			downloaded_bytes = int(event.get("completed", -1))
			total_bytes = int(event.get("total", -1))
		except (TypeError, ValueError):
			return

		self._process_download(downloaded_bytes, total_bytes)

	def process_line(self, line: str) -> None:
		if self.finished:
			return

		if "(" not in line or "/" not in line:
			return

		match = _PATTERN.search(line)
		if not match:
			return

		downloaded_bytes = int(match.group(1))
		total_bytes = int(match.group(2))
		self._process_download(downloaded_bytes, total_bytes)

	def _process_download(self, downloaded_bytes: int, total_bytes: int) -> None:
		if total_bytes <= 0:
			return

		if self.total_bytes is None:
			self.total_bytes = total_bytes
		elif total_bytes != self.total_bytes:
			total_bytes = self.total_bytes

		if downloaded_bytes < self.last_downloaded_bytes:
			return

		now = time.time()

		if not self.announced_start:
			self._speak("Downloading model, total size " + format_size(total_bytes))
			self.announced_start = True
			self.start_time = now
			self.last_time = now
			self.last_downloaded_bytes = downloaded_bytes
			self.last_announce_time = now
			if downloaded_bytes >= total_bytes:
				self._speak("Download complete")
				self.last_announced_percent = 100
				self.finished = True
			return

		delta_bytes = downloaded_bytes - self.last_downloaded_bytes
		delta_time = now - self.last_time
		if delta_time > 0 and delta_bytes >= 0:
			instant_speed = delta_bytes / delta_time
			self.speed_samples.append(instant_speed)
			if len(self.speed_samples) > 5:
				self.speed_samples.pop(0)

		avg_speed = sum(self.speed_samples) / len(self.speed_samples) if self.speed_samples else 0.0

		progress_percent = math.floor((downloaded_bytes / total_bytes) * 100)
		remaining_bytes = total_bytes - downloaded_bytes
		eta_seconds = remaining_bytes / avg_speed if avg_speed > 0 else -1

		time_since_last = now - self.last_announce_time
		speed_mb = avg_speed / _BYTES_PER_MB
		if speed_mb >= 20:
			threshold_percent = 20
			threshold_time = 15
		elif speed_mb >= 2:
			threshold_percent = 10
			threshold_time = 10
		else:
			threshold_percent = 5
			threshold_time = 15

		should_announce = False
		if progress_percent == 100:
			should_announce = True
		elif progress_percent >= self.last_announced_percent + threshold_percent:
			should_announce = True
		elif time_since_last >= threshold_time:
			should_announce = True

		if progress_percent == self.last_announced_percent and progress_percent != 100:
			should_announce = False

		if should_announce:
			if progress_percent == 100:
				self._speak("Download complete")
			else:
				self._speak(f"{progress_percent}% complete, {format_eta(eta_seconds)}")
			self.last_announced_percent = progress_percent
			self.last_announce_time = now

		self.last_downloaded_bytes = downloaded_bytes
		self.last_time = now

		if progress_percent == 100:
			self.finished = True


def example_usage() -> None:
	def speak(text: str) -> None:
		print("SPEAK:", text)

	tracker = DownloadProgressTracker(speak=speak)
	command = [defaults.DEFAULT_OLLAMA_CLI, "pull", defaults.DEFAULT_OLLAMA_MODEL]
	with subprocess.Popen(
		command,
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
		bufsize=1,
	) as process:
		if process.stdout is None:
			return

		for raw_line in process.stdout:
			line = raw_line.strip()
			tracker.process_line(line)

		process.wait()


if __name__ == "__main__":
	example_usage()
