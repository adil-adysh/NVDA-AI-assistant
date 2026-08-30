"""Cross-layer contract from context collection through presentation."""

from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace

from tests.plugin import test_presenter_ui_actions as presenter_harness
from tests.support import ADDON_ROOT, load_module, register_package


NAMESPACE = "use_case_flow_testpkg"
register_package(NAMESPACE, ADDON_ROOT)
register_package(f"{NAMESPACE}.use_case", ADDON_ROOT / "use_case")
registry = types.ModuleType(f"{NAMESPACE}.use_case.registry")
registry.build_default_use_cases = lambda: ()
sys.modules[registry.__name__] = registry

engine_module = load_module(
	f"{NAMESPACE}.use_case.engine",
	ADDON_ROOT / "use_case" / "engine.py",
)
context_types = importlib.import_module(f"{NAMESPACE}.context.types")
context_pipeline = importlib.import_module(f"{NAMESPACE}.context.pipeline")
declarative = importlib.import_module(f"{NAMESPACE}.use_case.declarative")
llm_module = importlib.import_module(f"{NAMESPACE}.service.llm")


class _PageCollector:
	def handles_request(self, request) -> bool:
		return isinstance(request, context_types.PageTextRequest)

	def collect_for_request(self, _request, input_):
		return SimpleNamespace(
			facts={"extraction_snapshot": input_.extraction_snapshot},
			text=input_.extraction_snapshot.text,
			image_base64=None,
			metadata={"language": "en"},
		)


class _Provider:
	def __init__(self) -> None:
		self.prompts: list[str] = []

	def summarize(self, prompt: str, stream_handler=None):
		self.prompts.append(prompt)
		return SimpleNamespace(text="Model answer", provider="contract-provider", model="contract-model")

	def provider_name(self) -> str:
		return "contract-provider"

	def get_model_info(self, model_name=None):
		return None

	def supports_streaming(self) -> bool:
		return False


def test_engine_pipeline_llm_service_and_presenter_flow(monkeypatch) -> None:
	monkeypatch.setattr(llm_module, "is_streaming_enabled", lambda: False)
	provider = _Provider()
	llm_service = llm_module.ProviderLLMService(provider)
	pipeline = context_pipeline.ContextPipeline(
		(_PageCollector(),),
		lambda callable_: callable_(),
		page_extractor=lambda: context_types.ExtractionSnapshot(
			"Title", "Browser", "Collected page text", False
		),
	)
	definition = declarative.DeclarativeUseCaseDefinition(
		id="architecture-flow",
		description="Architecture flow",
		extraction_intent=context_types.ExtractionIntent(
			requests=(context_types.PageTextRequest(),)
		),
		prompt_key="architecture_flow",
		result_message="Complete",
	)
	use_case = declarative.DeclarativeUseCase(
		definition,
		lambda context: f"Summarize: {context.text}",
	)
	engine = engine_module.UseCaseEngine(
		llm_service=llm_service,
		context_pipeline=pipeline,
		use_cases=(use_case,),
	)

	result = engine.execute("architecture-flow")

	presenter = presenter_harness.UseCasePresenter(
		chat_coordinator=presenter_harness._FakeChatCoordinator(),
		conversation_service=presenter_harness._FakeConversationService(),
		tool_registry=presenter_harness._FakeToolRegistry(),
		provider_catalog=presenter_harness._FakeProviderCatalogService(),
		readiness_service=presenter_harness._FakeProviderReadinessService(),
	)
	presenter._refresh_available_models_async = lambda _state: None
	presenter_harness.ui_adapter_module.ui_adapter.render_display_calls.clear()
	presenter.present_use_case_result(result, "Architecture flow")

	assert provider.prompts == ["Summarize: Collected page text"]
	assert result.output_text == "Model answer"
	assert len(presenter_harness.ui_adapter_module.ui_adapter.render_display_calls) == 1
	view_model = presenter_harness.ui_adapter_module.ui_adapter.render_display_calls[0]["args"][0]
	assert view_model.output_text == "Model answer"
