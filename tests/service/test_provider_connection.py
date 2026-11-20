from dataclasses import replace
from unittest.mock import Mock

import pytest

from tests.support import load_addon_module

config_module = load_addon_module("providers.config", namespace="provider_connection_testpkg")


@pytest.mark.parametrize("provider_id", ["openai", "gemini", "ollama", "litert-lm", "llama-cpp-server"])
def test_connection_uses_draft_without_activation_and_closes_client(provider_id):
	service = load_addon_module("service.provider_connection", namespace="provider_connection_testpkg")
	config = config_module.OpenAICompatConfig(provider=provider_id, model_name="", timeout_seconds=300,
		enable_progress=False, num_ctx=0, max_retries=4, retry_backoff_seconds=1,
		generate_temperature=.2, generate_top_k=0, generate_top_p=1, generate_max_tokens=512,
		base_url="http://localhost:12345/draft", api_key="draft-key")
	client = Mock()
	client.check_connection.return_value = 2
	factory = Mock(return_value=client)
	assert service.ProviderConnectionService(provider_factory=factory).check(config) == 2
	assert factory.call_args.args[0] == replace(config, timeout_seconds=15, max_retries=0)
	client.list_models.assert_not_called()
	client.close.assert_called_once()
	client.check_connection.side_effect = RuntimeError("offline")
	with pytest.raises(RuntimeError, match="offline"):
		service.ProviderConnectionService(provider_factory=factory).check(config)
	assert client.close.call_count == 2
