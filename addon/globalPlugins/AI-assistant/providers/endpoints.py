# -*- coding: utf-8 -*-
"""Endpoint resolution for OpenAI-compatible HTTP providers."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


class EndpointConfigurationError(ValueError):
	"""Raised when a provider endpoint cannot be resolved safely."""


@dataclass(frozen=True, slots=True)
class OpenAIEndpoints:
	"""Absolute endpoints used by an OpenAI-compatible provider."""

	service_url: str
	chat_url: str
	models_url: str


def resolve_openai_endpoints(
	base_url: str,
	chat_path: str,
	models_path: str,
) -> OpenAIEndpoints:
	"""Resolve paths without duplicating an existing API prefix.

	``base_url`` may be a service root (``http://host``) or a legacy API
	root (``http://host/v1``). Endpoint values can be absolute URLs or paths.
	"""
	service_url = _normalize_base_url(base_url)
	return OpenAIEndpoints(
		service_url=service_url,
		chat_url=_resolve_endpoint(service_url, chat_path),
		models_url=_resolve_endpoint(service_url, models_path),
	)


def _normalize_base_url(value: str) -> str:
	parsed = urlsplit(str(value or "").strip())
	if parsed.scheme not in {"http", "https"} or not parsed.netloc:
		raise EndpointConfigurationError("Provider URL must be an absolute HTTP(S) URL.")
	if parsed.query or parsed.fragment:
		raise EndpointConfigurationError("Provider URL cannot include a query string or fragment.")
	return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _resolve_endpoint(base_url: str, endpoint: str) -> str:
	endpoint = str(endpoint or "").strip()
	if not endpoint:
		raise EndpointConfigurationError("Provider endpoint path cannot be empty.")
	parsed_endpoint = urlsplit(endpoint)
	if parsed_endpoint.scheme or parsed_endpoint.netloc:
		if parsed_endpoint.scheme not in {"http", "https"} or not parsed_endpoint.netloc:
			raise EndpointConfigurationError("Provider endpoint must be an absolute HTTP(S) URL.")
		if parsed_endpoint.query or parsed_endpoint.fragment:
			raise EndpointConfigurationError("Provider endpoint cannot include a query string or fragment.")
		return urlunsplit(
			(parsed_endpoint.scheme, parsed_endpoint.netloc, parsed_endpoint.path.rstrip("/"), "", "")
		)
	if parsed_endpoint.query or parsed_endpoint.fragment:
		raise EndpointConfigurationError("Provider endpoint cannot include a query string or fragment.")
	endpoint_parts = [part for part in parsed_endpoint.path.split("/") if part]
	if not endpoint_parts:
		raise EndpointConfigurationError("Provider endpoint path cannot be empty.")
	parsed_base = urlsplit(base_url)
	base_parts = [part for part in parsed_base.path.split("/") if part]
	if endpoint_parts[: len(base_parts)] == base_parts:
		combined_parts = endpoint_parts
	else:
		combined_parts = [*base_parts, *endpoint_parts]
	return urlunsplit((parsed_base.scheme, parsed_base.netloc, "/" + "/".join(combined_parts), "", ""))
