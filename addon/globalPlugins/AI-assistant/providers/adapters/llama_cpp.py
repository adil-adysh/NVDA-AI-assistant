# -*- coding: utf-8 -*-
"""OpenAI-compatible llama.cpp server provider."""

from __future__ import annotations

from ..config import OpenAICompatConfig
from ..interfaces import LLMProviderError, ProgressCallback
from ..llama_manager import LlamaCppModelManager
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

	def _resolve_model(self) -> str:
		configured = super()._resolve_model()
		record = self._llama_manager.find_record(configured)
		return record.model_id if record is not None else configured

	def close(self) -> None:
		self._llama_manager.close()
		super().close()
