from __future__ import annotations

import importlib
import pytest
from tests.support import ADDON_ROOT, register_package

NAMESPACE = 'inference_cancellation_testpkg'
register_package(NAMESPACE, ADDON_ROOT)
llm = importlib.import_module(f'{NAMESPACE}.service.llm')
coordinator_module = importlib.import_module(f'{NAMESPACE}.service.chat.coordinator')
messages = importlib.import_module(f'{NAMESPACE}.core.messages')
repository_module = importlib.import_module(f'{NAMESPACE}.service.chat.repository_backends')


def cancellation():
	return importlib.import_module(f'{NAMESPACE}.core.cancellation')


def test_stopped_marker_is_translatable(monkeypatch):
	import builtins
	monkeypatch.setattr(builtins, '_', lambda text: 'translated: ' + text, raising=False)
	result = coordinator_module.ChatCoordinator._stopped_result('partial')
	assert result.response.text == 'partial\n\ntranslated: [Stopped]'


class Provider:
	def provider_name(self):
		return 'controlled'
	def get_model_info(self, model_name=None):
		return None
	def generate(self, messages, tools=None, stream_handler=None):
		return globals()['messages'].LLMResponse(text='answer')


def test_cancelled_request_never_calls_provider(monkeypatch):
	api = cancellation()
	token = api.CancellationToken()
	token.cancel()
	provider = Provider()
	monkeypatch.setattr(provider, 'generate', lambda **kw: pytest.fail('cancelled request reached provider'))
	with api.cancellation_scope(token), pytest.raises(api.RequestCancelled):
		llm.ProviderLLMService(provider).generate([])


def test_stopped_partial_is_saved_and_late_chunks_ignored(monkeypatch, tmp_path):
	api = cancellation()
	token = api.CancellationToken()
	monkeypatch.setattr(llm, 'is_streaming_enabled', lambda: True)
	class StreamingProvider(Provider):
		def generate(self, messages, tools=None, stream_handler=None):
			stream_handler('partial', 7)
			token.cancel()
			try:
				stream_handler('partial late', 12)
			except Exception as error:
				raise RuntimeError('provider wrapped callback') from error
			return globals()['messages'].LLMResponse(text='late answer')
	repo = repository_module.JsonConversationRepository(tmp_path / 'conversations.json')
	chat = coordinator_module.ChatCoordinator(llm.ProviderLLMService(StreamingProvider()), repository=repo)
	chat.activate_conversation('one')
	partials = []
	response = chat.send_message('question', progress_callback=lambda text, count: partials.append(text), cancellation_token=token)
	assert response.text == 'partial\n\n[Stopped]'
	assert response.raw == {'cancelled': True}
	assert partials == ['partial']
	assert [item.content for item in chat.get_history()] == ['question', 'partial\n\n[Stopped]']
	assert len(repo.load('one').snapshot()) == 2


def test_stopped_turn_is_discarded_when_conversation_changes(monkeypatch):
	api = cancellation()
	token = api.CancellationToken()
	class SwitchingProvider(Provider):
		def generate(self, messages, tools=None, stream_handler=None):
			chat.activate_conversation('two')
			token.cancel()
			return globals()['messages'].LLMResponse(text='late answer')
	chat = coordinator_module.ChatCoordinator(llm.ProviderLLMService(SwitchingProvider()))
	chat.activate_conversation('one')
	response = chat.send_message('question', cancellation_token=token)
	assert response.raw == {'cancelled': True}
	assert chat.get_history() == []
	assert not chat.last_turn_committed()


def test_record_stopped_before_generation_validates_conversation():
	chat = coordinator_module.ChatCoordinator(llm.ProviderLLMService(Provider()))
	chat.activate_conversation('one')
	response = chat.record_stopped_turn('question', None, '', 'one')
	assert response.text == '[Stopped]'
	chat.activate_conversation('two')
	with pytest.raises(RuntimeError, match='conversation changed'):
		chat.record_stopped_turn('old question', None, 'partial', 'one')
	assert chat.get_history() == []

def test_cancellation_between_tool_calls_skips_remaining_tools(monkeypatch):
	api = cancellation()
	token = api.CancellationToken()
	tooling = importlib.import_module(f'{NAMESPACE}.core.tooling')
	calls = [tooling.ToolCall(id='1', name='first', arguments={}), tooling.ToolCall(id='2', name='second', arguments={})]
	class ToolProvider(Provider):
		def generate(self, **kwargs):
			return messages.LLMResponse(text='', tool_calls=calls)
	class Executor:
		def execute_tool_calls(self, tool_calls):
			assert tool_calls == calls[:1]
			token.cancel()
			return []
	with api.cancellation_scope(token), pytest.raises(api.RequestCancelled):
		llm.ProviderLLMService(ToolProvider(), Executor()).generate([])


@pytest.mark.parametrize('method,args', [('summarize', ('prompt',)), ('describe_image', ('image', 'prompt')), ('summarize_structured', ('prompt', {}))])
def test_summary_and_image_cancel_after_nonstream_response(method, args):
	api = cancellation()
	token = api.CancellationToken()
	provider = Provider()
	def respond(*args, **kwargs):
		token.cancel()
		return messages.SummaryResponse(text='late result', model='model')
	setattr(provider, method, respond)
	with api.cancellation_scope(token), pytest.raises(api.RequestCancelled):
		getattr(llm.ProviderLLMService(provider), method)(*args)


def test_scope_is_request_local_and_restores_outer_token():
	api = cancellation()
	outer = api.CancellationToken()
	inner = api.CancellationToken()
	inner.cancel()
	with api.cancellation_scope(outer):
		with api.cancellation_scope(inner), pytest.raises(api.RequestCancelled):
			api.check_cancelled()
		api.check_cancelled()
	api.check_cancelled()

def test_context_retrieval_cannot_move_submission_into_another_conversation():
	class SwitchingContext:
		def retrieve(self, *args, **kwargs):
			chat.activate_conversation('two')
			return 'context'
		def clear(self):
			pass
	chat = coordinator_module.ChatCoordinator(llm.ProviderLLMService(Provider()), page_context_provider=SwitchingContext())
	chat.activate_conversation('one')
	with pytest.raises(RuntimeError, match='conversation changed'):
		chat.send_message('question', expected_conversation_id='one')
	assert chat.get_history() == []
