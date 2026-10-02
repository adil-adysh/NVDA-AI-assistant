# -*- coding: utf-8 -*-
"""OpenAI-compatible llama.cpp server provider."""

from __future__ import annotations

from ..config import OpenAICompatConfig
from ..interfaces import LLMProviderError, ProgressCallback, ProviderModelInfo, SamplingDefaults
from ..llama_manager import LlamaCppModelManager
from ..runtime.llama_models import llama_model_capabilities, llama_model_context_window
from .openai_compat import OpenAICompatProvider


class LlamaCppServerProvider(OpenAICompatProvider):
	"""Ensure the managed llama-server exists before inference."""

	def __init__(self, config: OpenAICompatConfig) -> None:
		super().__init__(config)
		self._llama_manager = LlamaCppModelManager(config=config)

	def ensure_model_available(self, on_progress: ProgressCallback | None = None) -> str | None:
		model_id = str(self._config.model_name or "").strip()
		if not model_id:
			raise LLMProviderError("No llama.cpp model is configured")
		record = self._llama_manager.find_record(model_id)
		if record is None:
			raise LLMProviderError(f"Unknown llama.cpp model: {model_id}")
		self._llama_manager.ensure_running(record, on_progress=on_progress)
		return record.model_id

	def list_models(self) -> tuple[ProviderModelInfo, ...]:
		models: dict[str, ProviderModelInfo] = {}
		server_items = {
			str(item.get("id", "")).strip(): item
			for item in self._llama_manager.list_server_models()
			if str(item.get("id", "")).strip()
		}
		for record in self._llama_manager._catalog.list_records():
			server_item = next(
				(item for sid, item in server_items.items() if record.matches_server_id(sid)),
				None,
			)
			models[record.model_id] = self._model_info(record.model_id, server_item, record=record)
		for server_id, item in server_items.items():
			record = self._llama_manager.find_record(server_id)
			model_id = record.model_id if record is not None else server_id
			if model_id not in models:
				models[model_id] = self._model_info(model_id, item, record=record)
		return tuple(sorted(models.values(), key=lambda m: m.display_name.lower()))

	def get_model_info(self, model_name: str | None = None) -> ProviderModelInfo | None:
		requested = str(model_name or self._config.model_name or "").strip()
		if not requested:
			return None
		models = self.list_models()
		for model in models:
			if model.id.lower() == requested.lower():
				return model
		record = self._llama_manager.find_record(requested)
		if record is not None:
			for model in models:
				if record.matches_server_id(model.id):
					return model
		return None

	def supports_image_description(self) -> bool:
		info = self.get_model_info()
		return info is not None and info.supports("image_input")

	def _model_info(
		self,
		model_id: str,
		item: dict[str, object] | None = None,
		record: object | None = None,
	) -> ProviderModelInfo:
		item = item or {}
		context_window = llama_model_context_window(item)
		if context_window is None and record is not None:
			context_window = getattr(record, "context_window", None)
		capabilities = llama_model_capabilities(item) if item else (
			getattr(record, "capabilities", None)
			or ("chat", "completion", "streaming", "text_input", "text_output")
		)
		return ProviderModelInfo(
			id=model_id,
			provider=self.provider_name(),
			display_name=model_id,
			owned_by=str(item.get("owned_by", "llamacpp")),
			created=item.get("created") if isinstance(item.get("created"), int) else None,
			context_window=context_window,
			capabilities=capabilities,
			sampling_defaults=SamplingDefaults(temperature=1.0, top_p=1.0),
			raw=item,
		)

	def _resolve_model(self) -> str:
		configured = super()._resolve_model()
		record = self._llama_manager.find_record(configured)
		return record.model_id if record is not None else configured

	def close(self) -> None:
		self._llama_manager.close()
		super().close()
