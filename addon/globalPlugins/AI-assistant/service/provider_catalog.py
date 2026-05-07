# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Callable

from ..config.settings import get_active_provider_config
from ..providers.config import ProviderConfig
from ..providers.factory import ProviderFactory
from ..providers.interfaces import ProviderModelInfo
from .provider_readiness import ProviderReadinessService


ProviderFactoryFn = Callable[[ProviderConfig], object]


class ProviderCatalogService:
	def __init__(
		self,
		readiness_service: ProviderReadinessService | None = None,
		config_resolver: Callable[[], ProviderConfig] = get_active_provider_config,
		provider_factory: ProviderFactoryFn = ProviderFactory.create_provider,
	) -> None:
		self._readiness_service = readiness_service or ProviderReadinessService()
		self._config_resolver = config_resolver
		self._provider_factory = provider_factory

	def list_active_models(self) -> tuple[ProviderModelInfo, ...]:
		return self.list_models(self._config_resolver())

	def list_models(self, config: ProviderConfig) -> tuple[ProviderModelInfo, ...]:
		readiness = self._readiness_service.evaluate(config)
		if not readiness.can_list_models:
			return ()

		provider = self._provider_factory(config)
		try:
			return provider.list_models()
		finally:
			provider.close()
