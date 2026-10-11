import os

from tests.support import load_addon_module


def test_parent_watchdog_recognizes_live_windows_process():
	server_module = load_addon_module('worker.server')
	server = server_module.WorkerServer.__new__(server_module.WorkerServer)
	assert server._is_process_alive(os.getpid())


def test_parent_watchdog_closes_query_handle(monkeypatch):
	import win32api
	import win32process

	server_module = load_addon_module('worker.server')
	server = server_module.WorkerServer.__new__(server_module.WorkerServer)
	closed = []
	class Handle:
		def Close(self):
			closed.append(True)
	monkeypatch.setattr(win32api, 'OpenProcess', lambda *args: Handle())
	monkeypatch.setattr(win32process, 'GetExitCodeProcess', lambda handle: 0)
	assert not server._is_process_alive(123)
	assert closed == [True]
