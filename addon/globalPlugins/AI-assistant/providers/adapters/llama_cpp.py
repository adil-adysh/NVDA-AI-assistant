# -*- coding: utf-8 -*-
"""OpenAI-compatible llama.cpp server provider."""
from __future__ import annotations

from dataclasses import replace

from ...config.model_config import ModelSamplingConfig, get_model_sampling
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
			raise LLMProviderError("No llama.cpp preset is configured")
		record = self._llama_manager.find_record(model_id)
		if record is None:
			# Older builds exposed raw llama-server IDs such as
			# "owner/repo:QUANT" in the model dropdown. If that repository
			# has exactly one preset, repair the stale selection instead of
			# failing every preload request.
			repo = model_id.split(":", 1)[0].strip()
			candidates = [item for item in self._llama_manager.list_presets()
				if item.repo.casefold() == repo.casefold()]
			if len(candidates) == 1:
				record = candidates[0]
				self._llama_manager.set_active_model(record.model_id)
		if record is None:
			raise LLMProviderError(f"Selected llama.cpp model is not a preset: {model_id}")
		self._llama_manager.ensure_running(record, on_progress=on_progress)
		return record.model_id

	def list_models(self) -> tuple[ProviderModelInfo, ...]:
		models: dict[str, ProviderModelInfo] = {}
		records = self._llama_manager.list_presets()
		server_items = {
			str(item.get("id", "")).strip(): item
			for item in self._llama_manager.list_server_models(refresh=True)
			if str(item.get("id", "")).strip()
		}
		for record in records:
			server_item = next((item for sid, item in server_items.items() if record.matches_server_id(sid)), None)
			models[record.model_id] = self._model_info(record.model_id, server_item, record=record)
		return tuple(sorted(models.values(), key=lambda model: model.display_name.lower()))

	def get_model_info(self, model_name: str | None = None) -> ProviderModelInfo | None:
		requested = str(model_name or self._config.model_name or "").strip()
		if not requested:
			return None
		models = self.list_models()
		for model in models:
			if model.id == requested:
				return model
		case_matches = [model for model in models if model.id.casefold() == requested.casefold()]
		if len(case_matches) == 1:
			return case_matches[0]
		return None

	def supports_image_description(self) -> bool:
		info = self.get_model_info()
		return info is not None and info.supports("image_input")

	def _model_info(self, model_id: str, item: dict[str, object] | None = None,
			record: object | None = None) -> ProviderModelInfo:
		item = item or {}
		context_window = llama_model_context_window(item)
		if record is not None:
			context_window = record.context_window or context_window
		capabilities = record.capabilities if record is not None else ("chat", "completion", "streaming", "text_input", "text_output")
		if item:
			capabilities = tuple(sorted({*capabilities, *llama_model_capabilities(item)}))
		return ProviderModelInfo(
			id=model_id,
			provider=self.provider_name(),
			display_name=getattr(record, "display_name", "") or model_id,
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

	def _resolve_sampling(self, model_id: str) -> ModelSamplingConfig:
		sampling = super()._resolve_sampling(model_id)
		record = self._llama_manager.find_record(model_id)
		if record is None:
			return sampling
		# Requests otherwise send the provider-wide defaults, overriding the
		# server preset. Explicit model sampling pins still take precedence.
		pinned = get_model_sampling(self._provider_id, model_id)
		updates = {}
		for key, field, convert in (
			("temperature", "temperature", float),
			("top-p", "top_p", float),
			("n-predict", "max_tokens", lambda value: None if int(value) == -1 else int(value)),
		):
			if key in record.preset_options and getattr(pinned, field) is None:
				updates[field] = convert(record.preset_options[key])
		return replace(sampling, **updates)

	def close(self) -> None:
		self._llama_manager.close()
		super().close()
