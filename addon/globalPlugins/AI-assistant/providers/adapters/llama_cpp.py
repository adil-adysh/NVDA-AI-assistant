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
		models: list[ProviderModelInfo] = []
		for item in self._llama_manager.list_server_models():
			server_id = str(item.get("id", "")).strip()
			if not server_id:
				continue
			record = self._llama_manager.find_record(server_id)
			model_id = record.model_id if record is not None else server_id
			models.append(self._model_info(model_id, item))
		return tuple(models)

	def get_model_info(self, model_name: str | None = None) -> ProviderModelInfo | None:
		requested = str(model_name or self._config.model_name or "").strip()
		for item in self._llama_manager.list_server_models():
			server_id = str(item.get("id", "")).strip()
			record = self._llama_manager.find_record(server_id)
			if server_id == requested or (record is not None and record.matches_server_id(requested)):
				return self._model_info(record.model_id if record is not None else server_id, item)
		return None

	def supports_image_description(self) -> bool:
		info = self.get_model_info()
		return info is not None and info.supports("image_input")

	def _model_info(self, model_id: str, item: dict[str, object]) -> ProviderModelInfo:
		return ProviderModelInfo(
			id=model_id,
			provider=self.provider_name(),
			display_name=model_id,
			owned_by=str(item.get("owned_by", "llamacpp")),
			created=item.get("created") if isinstance(item.get("created"), int) else None,
			context_window=llama_model_context_window(item),
			capabilities=llama_model_capabilities(item),
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
