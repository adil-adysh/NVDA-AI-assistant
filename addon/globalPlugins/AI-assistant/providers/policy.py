# -*- coding: utf-8 -*-
"""Declarative provider policies.

This module is the dependency-free policy layer.  Services consume these
policies instead of repeating provider-ID conditionals; adapters remain free
to implement the provider-specific mechanics behind the policy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPolicy:
	provider_id: str
	display_name: str
	kind: str
	credential_groups: tuple[tuple[str, ...], ...] = ()
	has_install_step: bool = False
	requires_runtime: bool = False
	requires_server_url: bool = True
	unsupported_model_markers: tuple[str, ...] = ()

	def has_credentials(self, config: object) -> bool:
		return all(
			any(str(getattr(config, field, "") or "").strip() for field in group)
			for group in self.credential_groups
		)

	def supports_model(self, model_name: str) -> bool:
		name = model_name.strip().lower()
		return not any(marker in name for marker in self.unsupported_model_markers)


PROVIDER_POLICIES: dict[str, ProviderPolicy] = {
	"ollama": ProviderPolicy(
		provider_id="ollama",
		display_name="Ollama",
		kind="local",
	),
	"gemini": ProviderPolicy(
		provider_id="gemini",
		display_name="Gemini",
		kind="cloud",
		credential_groups=(("api_key", "api_token"),),
		unsupported_model_markers=("live-preview", "deep-research-preview", "deep-research-max-preview"),
	),
	"openai": ProviderPolicy(
		provider_id="openai",
		display_name="OpenAI",
		kind="cloud",
		credential_groups=(("api_key",),),
	),
	"litert-lm": ProviderPolicy(
		provider_id="litert-lm",
		display_name="LiteRT-LM",
		kind="local",
		has_install_step=True,
		requires_runtime=True,
	),
	"llama-cpp-server": ProviderPolicy(
		provider_id="llama-cpp-server",
		display_name="llama.cpp server",
		kind="local",
	),
}


def get_provider_policy(provider_id: str) -> ProviderPolicy | None:
	return PROVIDER_POLICIES.get(str(provider_id or "").strip().lower())
