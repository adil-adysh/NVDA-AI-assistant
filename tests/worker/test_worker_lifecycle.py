"""Application-owned lazy startup and termination races."""

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from tests.support import load_addon_module

module = load_addon_module("plugin.worker_supervisor", namespace="lazy_worker_tests")


class Supervisor:
	def __init__(self, *, succeeds=True):
		self.starts = 0
		self.stops = 0
		self.succeeds = succeeds
		self.entered = threading.Event()
		self.release = threading.Event()
		self.client = object()
		self.is_running = False
		self.stderr_buffer = module.StderrRingBuffer()

	def start(self):
		self.starts += 1
		self.entered.set()
		assert self.release.wait(3)
		self.is_running = self.succeeds
		return self.succeeds

	def get_worker_client(self):
		return self.client if self.is_running else None

	def stop(self):
		self.stops += 1
		self.is_running = False


def test_registration_and_lookup_do_not_launch():
	supervisor = Supervisor()
	owner = module.LazyWorkerOwner(supervisor)
	assert owner.get_client() is None
	assert supervisor.starts == 0
	owner.close()
	with pytest.raises(RuntimeError, match="closed"):
		owner.ensure_client()
	assert supervisor.starts == 0


@pytest.mark.parametrize("succeeds", [True, False])
def test_concurrent_operations_share_startup(succeeds):
	supervisor = Supervisor(succeeds=succeeds)
	owner = module.LazyWorkerOwner(supervisor)
	with ThreadPoolExecutor(max_workers=6) as pool:
		first = pool.submit(owner.ensure_client)
		assert supervisor.entered.wait(1)
		others = [pool.submit(owner.ensure_client) for _ in range(5)]
		supervisor.release.set()
		for future in [first, *others]:
			if succeeds:
				assert future.result() is supervisor.client
			else:
				with pytest.raises(RuntimeError, match="start"):
					future.result()
	assert supervisor.starts == 1
	owner.close()


def test_close_during_startup_discards_connection():
	supervisor = Supervisor()
	owner = module.LazyWorkerOwner(supervisor)
	with ThreadPoolExecutor(max_workers=1) as pool:
		future = pool.submit(owner.ensure_client)
		assert supervisor.entered.wait(1)
		owner.close()
		supervisor.release.set()
		with pytest.raises(RuntimeError, match="closed"):
			future.result()
	assert owner.get_client() is None
	assert supervisor.stops >= 1


def test_background_prelaunch_uses_same_owner():
	supervisor = Supervisor()
	supervisor.release.set()
	owner = module.LazyWorkerOwner(supervisor)
	thread = owner.start_in_background()
	thread.join(3)
	assert not thread.is_alive()
	assert owner.ensure_client() is supervisor.client
	assert supervisor.starts == 1
	owner.close()


def test_delayed_restart_cannot_start_after_owner_close(monkeypatch):
	supervisor = module.WorkerSupervisor(auto_restart=False)
	owner = module.LazyWorkerOwner(supervisor)
	supervisor.state = module.SupervisorState.RESTARTING
	entered, release = threading.Event(), threading.Event()
	original_start = supervisor.start
	spawns = []
	monkeypatch.setattr(supervisor, "_spawn_worker_process", lambda: spawns.append("spawn"))
	monkeypatch.setattr(supervisor, "_connect_and_handshake", lambda: None)
	def paused_start():
		entered.set()
		assert release.wait(3)
		return original_start()
	monkeypatch.setattr(supervisor, "start", paused_start)
	thread = threading.Thread(target=supervisor._delayed_restart, args=(0,))
	thread.start()
	assert entered.wait(1)
	owner.close().join(2)
	release.set()
	thread.join(3)
	assert not thread.is_alive()
	assert spawns == []
	assert not supervisor.is_running


def test_operation_shares_automatic_restart_handshake(monkeypatch):
	supervisor = module.WorkerSupervisor(auto_restart=False)
	owner = module.LazyWorkerOwner(supervisor)
	supervisor.state = module.SupervisorState.RESTARTING
	entered, release = threading.Event(), threading.Event()
	spawns = []
	client = object()
	monkeypatch.setattr(supervisor, "_spawn_worker_process", lambda: spawns.append("spawn"))
	def handshake():
		supervisor.state = module.SupervisorState.HANDSHAKING
		entered.set()
		assert release.wait(3)
		supervisor._worker_client = client
		supervisor.state = module.SupervisorState.RUNNING
	monkeypatch.setattr(supervisor, "_connect_and_handshake", handshake)
	with ThreadPoolExecutor(max_workers=2) as pool:
		restart = pool.submit(supervisor._delayed_restart, 0)
		assert entered.wait(1)
		operation = pool.submit(owner.ensure_client)
		release.set()
		restart.result()
		assert operation.result() is client
	assert spawns == ["spawn"]
	supervisor._worker_client = None
	owner.close().join(2)
