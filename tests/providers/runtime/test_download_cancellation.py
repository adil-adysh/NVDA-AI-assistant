"""Cancellation contract for provider-owned network downloads."""

from __future__ import annotations

import threading

import pytest

from tests.support import load_addon_module


download = load_addon_module(
	"providers.runtime.download",
	namespace="provider_download_cancellation_testpkg",
)


def test_pre_cancelled_download_never_opens_network_connection(monkeypatch, tmp_path) -> None:
	cancel_event = threading.Event()
	cancel_event.set()
	network_calls: list[object] = []
	monkeypatch.setattr(
		download.urllib.request,
		"urlopen",
		lambda *args, **kwargs: network_calls.append((args, kwargs)),
	)

	with pytest.raises(download.DownloadCancelledError):
		download._download_url_resume(
			"https://example.invalid/model.bin",
			tmp_path / "model.part",
			cancel_event=cancel_event,
		)

	assert network_calls == []
