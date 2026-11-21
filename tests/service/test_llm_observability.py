from __future__ import annotations

import importlib
import pytest

from tests.support import ADDON_ROOT, register_package


NAMESPACE = "llm_observability_testpkg"
register_package(NAMESPACE, ADDON_ROOT)
llm = importlib.import_module(f"{NAMESPACE}.service.llm")
messages = importlib.import_module(f"{NAMESPACE}.core.messages")
tooling = importlib.import_module(f"{NAMESPACE}.core.tooling")
cancellation = importlib.import_module(f"{NAMESPACE}.core.cancellation")
provider_interfaces = importlib.import_module(f"{NAMESPACE}.providers.interfaces")


class Reporter:
	def __init__(self):
		self.records = []

	def report(self, metric):
		self.records.append(metric.to_log_record())

	def report_event(self, event):
		self.records.append(event.to_record())

	def is_enabled(self):
		return True


class Provider:
	def provider_name(self):
		return "test-provider"

	def summarize(self, prompt, stream_handler=None):
		return messages.SummaryResponse(text="private response", model="org/model")

	def summarize_structured(self, prompt, schema=None, stream_handler=None):
		return messages.SummaryResponse(text="private structured response", model="org/model")

	def describe_image(self, image_base64, prompt, stream_handler=None):
		return messages.SummaryResponse(text="private image response", model="org/model")

	def generate(self, messages, tools=None, stream_handler=None):
		return globals()["messages"].LLMResponse(text="private chat response", model="org/model")


def test_one_shot_and_chat_provider_calls_are_recorded_without_content(monkeypatch):
	monkeypatch.setattr(llm, "is_streaming_enabled", lambda: False)
	provider = Provider()
	reporter = Reporter()
	service = llm.ProviderLLMService(provider, metrics_reporter=reporter)
	service.summarize("private prompt")
	service.summarize_structured("private prompt", {})
	service.describe_image("private image bytes", "private image prompt")
	service.generate([])
	assert [record["request_type"] for record in reporter.records] == [
		"summary", "structured_summary", "image_description", "chat"
	]
	assert all(record["provider"] == "test-provider" and record["model"] == "org/model" for record in reporter.records)
	assert all(record["success"] is True for record in reporter.records)
	assert "private" not in str(reporter.records)


def test_provider_error_is_recorded_by_type_and_propagated_without_message(monkeypatch):
	class FailedProvider(Provider):
		def summarize(self, prompt, stream_handler=None):
			raise provider_interfaces.LLMProviderError("private https://secret.example/path")
	monkeypatch.setattr(llm, "is_streaming_enabled", lambda: False)
	reporter = Reporter()
	with pytest.raises(provider_interfaces.LLMProviderError, match="private"):
		llm.ProviderLLMService(FailedProvider(), metrics_reporter=reporter).summarize("prompt")
	assert reporter.records[0]["success"] is False
	assert reporter.records[0]["error_type"] == "LLMProviderError"
	assert "secret.example" not in str(reporter.records)
	assert "private" not in str(reporter.records)


def test_disabled_metrics_are_not_created_for_requests(monkeypatch):
	monkeypatch.setattr(llm, "is_streaming_enabled", lambda: False)
	class DisabledReporter(Reporter):
		def is_enabled(self):
			return False
	provider = Provider()
	reporter = DisabledReporter()
	response = llm.ProviderLLMService(provider, metrics_reporter=reporter).summarize("prompt")
	assert response.model == "org/model"
	assert reporter.records == []


def test_cancellation_is_recorded_and_still_propagates(monkeypatch):
	token = cancellation.CancellationToken()
	class CancelledProvider(Provider):
		def summarize(self, prompt, stream_handler=None):
			token.cancel()
			return messages.SummaryResponse(text="late response", model="org/model")
	monkeypatch.setattr(llm, "is_streaming_enabled", lambda: False)
	reporter = Reporter()
	service = llm.ProviderLLMService(CancelledProvider(), metrics_reporter=reporter)
	with cancellation.cancellation_scope(token), pytest.raises(cancellation.RequestCancelled):
		service.summarize("prompt")
	assert reporter.records[0]["success"] is False
	assert reporter.records[0]["error_type"] == "RequestCancelled"


def test_each_chat_model_follow_up_is_recorded_as_a_request(monkeypatch):
	monkeypatch.setattr(llm, "is_streaming_enabled", lambda: False)
	call = tooling.ToolCall(name="test_tool", arguments={}, id="call-1")
	class TwoStepProvider(Provider):
		def __init__(self):
			self.calls = 0
		def generate(self, messages, tools=None, stream_handler=None):
			self.calls += 1
			if self.calls == 1:
				return globals()["messages"].LLMResponse(text="", model="org/model", tool_calls=[call])
			return globals()["messages"].LLMResponse(text="final", model="org/model")
	class Executor:
		def execute_tool_calls(self, tool_calls, **kwargs):
			return []
	reporter = Reporter()
	service = llm.ProviderLLMService(TwoStepProvider(), Executor(), metrics_reporter=reporter)
	service.generate_with_transcript([])
	assert [record["request_type"] for record in reporter.records] == ["chat", "chat"]
