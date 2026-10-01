"""Composition tests for managed-provider startup during NVDA initialization."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from tests.support import load_addon_module


startup = load_addon_module(
	"plugin.local_provider_startup",
	namespace="local_provider_startup_testpkg",
)


@dataclass
class ControlledThread:
	target: Any
	name: str
	daemon: bool
	started: bool = False

	def start(self) -> None:
		self.started = True

	def run(self) -> None:
		self.target()


class ThreadFactory:
	def __init__(self) -> None:
		self.threads: list[ControlledThread] = []

	def __call__(self, *, target, name: str, daemon: bool) -> ControlledThread:
		thread = ControlledThread(target=target, name=name, daemon=daemon)
		self.threads.append(thread)
		return thread


@pytest.mark.parametrize(
	("provider", "expected_name"),
	[
		("litert-lm", "litert-lmServerAutoStart"),
		("llama-cpp-server", "llama-cpp-serverServerAutoStart"),
	],
)
def test_active_enabled_local_provider_is_scheduled(provider: str, expected_name: str) -> None:
	factory = ThreadFactory()
	ready_calls: list[str] = []

	thread = startup.schedule_active_local_provider_start(
		provider=provider,
		litert_enabled=True,
		llama_enabled=True,
		litert_installed=True,
		ensure_ready=lambda: ready_calls.append(provider),
		report_error=lambda *_args: None,
		thread_factory=factory,
	)

	assert thread is factory.threads[0]
	assert thread.started and thread.daemon
	assert thread.name == expected_name
	assert ready_calls == []
	thread.run()
	assert ready_calls == [provider]


@pytest.mark.parametrize(
	("provider", "litert_enabled", "llama_enabled", "litert_installed"),
	[
		("openai", True, True, True),
		("litert-lm", False, True, True),
		("litert-lm", True, True, False),
		("llama-cpp-server", True, False, True),
	],
)
def test_inactive_disabled_or_uninstalled_provider_is_not_scheduled(
	provider: str,
	litert_enabled: bool,
	llama_enabled: bool,
	litert_installed: bool,
) -> None:
	factory = ThreadFactory()

	thread = startup.schedule_active_local_provider_start(
		provider=provider,
		litert_enabled=litert_enabled,
		llama_enabled=llama_enabled,
		litert_installed=litert_installed,
		ensure_ready=lambda: None,
		report_error=lambda *_args: None,
		thread_factory=factory,
	)

	assert thread is None
	assert factory.threads == []


def test_startup_failure_is_reported_without_escaping_worker() -> None:
	factory = ThreadFactory()
	reported: list[tuple[Exception, str]] = []
	thread = startup.schedule_active_local_provider_start(
		provider="litert-lm",
		litert_enabled=True,
		llama_enabled=True,
		litert_installed=True,
		ensure_ready=lambda: (_ for _ in ()).throw(RuntimeError("controlled failure")),
		report_error=lambda error, provider: reported.append((error, provider)),
		thread_factory=factory,
	)

	assert thread is not None
	thread.run()
	assert len(reported) == 1
	assert str(reported[0][0]) == "controlled failure"
	assert reported[0][1] == "litert-lm"


def test_litert_with_existing_process_still_enters_readiness_path() -> None:
	"""No running-state shortcut may bypass health/fingerprint validation."""
	factory = ThreadFactory()
	readiness_checks: list[str] = []
	thread = startup.schedule_active_local_provider_start(
		provider="litert-lm",
		litert_enabled=True,
		llama_enabled=True,
		litert_installed=True,
		ensure_ready=lambda: readiness_checks.append("health-and-fingerprint"),
		report_error=lambda *_args: None,
		thread_factory=factory,
	)

	assert thread is not None
	thread.run()
	assert readiness_checks == ["health-and-fingerprint"]
