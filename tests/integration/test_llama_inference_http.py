"""Native HTTP client plus real llama adapter against a deterministic local server."""
import importlib

import pytest

from tests.support import load_addon_module
from tests.support.llama_flow import llama_flow
from tests.support.llama_http import router_http


@pytest.fixture
def inference(tmp_path, monkeypatch):
    flow = llama_flow(tmp_path, monkeypatch)
    namespace = "llama_journeys"
    adapter = load_addon_module("providers.adapters.llama_cpp", namespace=namespace)
    compat = importlib.import_module(f"{namespace}.providers.adapters.openai_compat")
    # Namespace loaders reload configuration per fixture; keep the real resolver
    # attached to that fixture rather than a prior fixture's persistence module.
    monkeypatch.setattr(compat, "resolve_model_sampling", flow.sampling.resolve_model_sampling)
    if importlib.import_module(f"{namespace}.providers.adapters.openai_compat").llm_client is None:
        pytest.fail("Build the native llm_client extension before integration testing")
    config_module = load_addon_module("providers.config", namespace=namespace)
    canonical = load_addon_module("core.canonical", namespace=namespace)
    monkeypatch.setattr(adapter, "LlamaCppModelManager", lambda config: flow.manager)
    with router_http() as http:
        config = config_module.OpenAICompatConfig(provider="llama-cpp-server", model_name="a",
            base_url=f"http://127.0.0.1:{http.port}", timeout_seconds=2, enable_progress=False, num_ctx=8192,
            max_retries=0, retry_backoff_seconds=0, generate_temperature=0.2, generate_top_k=0,
            generate_top_p=0.9, generate_max_tokens=128)
        flow.manager._config = config
        flow.manager.create_configuration("owner/model", "a", "A")
        provider = adapter.LlamaCppServerProvider(config)
        try:
            yield flow, provider, http, canonical
        finally:
            provider.close()


def posted(http):
    return [body for method, path, body in http.requests if method == "POST" and path == "/v1/chat/completions"]


def test_lazy_first_inference_uses_selected_id_and_native_http(inference):
    flow, provider, http, canonical = inference
    assert not flow.runtime.starts
    provider.ensure_model_available()
    result = provider.generate([canonical.Message("user", (canonical.Part("text", text="hello"),))])
    assert result.text == "Fixture answer" and result.model == "a"
    assert len(flow.runtime.starts) == 1
    assert posted(http)[0]["model"] == "a"
    assert posted(http)[0]["messages"][0]["content"] == "hello"


def test_streaming_summary_delivers_accumulated_answer(inference):
    _, provider, http, _ = inference
    partials = []
    result = provider.summarize("Summarize", lambda text, count: partials.append((text, count)))
    assert result.text == "Fixture answer"
    assert partials[-1] == ("Fixture answer", 14)
    assert posted(http)[0]["stream"] is True


def test_structured_summary_sends_llama_schema_shape(inference):
    _, provider, http, _ = inference
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}}
    http.answer = '{"summary":"answer"}'
    result = provider.summarize_structured("Summarize", schema)
    assert result.text == '{"summary":"answer"}'
    assert posted(http)[0]["response_format"] == {"type": "json_object", "schema": schema}


def test_image_request_encodes_image_and_prompt_on_compatible_endpoint(inference):
    flow, provider, http, _ = inference
    flow.manager.set_runtime_options("a", {"mmproj": "projector.gguf"})
    result = provider.describe_image("aW1hZ2U=", "describe")
    assert result.text == "Fixture answer"
    parts = posted(http)[0]["messages"][-1]["content"]
    assert any(part.get("text") == "describe" for part in parts)
    assert any(part.get("image_url", {}).get("url", "").endswith("aW1hZ2U=") for part in parts)


def test_stream_cancellation_preserves_partial_answer(inference):
    _, provider, http, _ = inference
    cancellation = load_addon_module("core.cancellation", namespace="llama_journeys")
    token = cancellation.CancellationToken()
    def partial(text, count):
        cancellation.record_partial(text, count)
        token.cancel()
    with cancellation.cancellation_scope(token), pytest.raises(cancellation.RequestCancelled) as stopped:
        provider.summarize("Summarize", partial)
    assert stopped.value.partial_text == "Fixture "
    assert len(posted(http)) == 1


def test_http_failure_is_reported_without_successful_empty_answer(inference):
    _, provider, http, canonical = inference
    http.chat_status = 500
    with pytest.raises(Exception, match="500|fixture failure"):
        provider.generate([canonical.Message("user", (canonical.Part("text", text="hello"),))])


def test_explicit_seed_is_sent_as_request_setting(inference):
    flow, provider, http, canonical = inference
    flow.saved["a"] = flow.sampling.ModelSamplingConfig(seed=42)
    provider.generate([canonical.Message("user", (canonical.Part("text", text="hello"),))])
    assert posted(http)[0]["seed"] == 42
