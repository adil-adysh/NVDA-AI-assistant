# -*- coding: utf-8 -*-
from __future__ import annotations

import builtins
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from ..providers.interfaces import LLMProviderError, ProviderConfigurationError, UnsupportedModelError


def _translate(message: str) -> str:
	return message


Translator = Callable[[str], str]
_ = cast(Translator, getattr(builtins, "_", _translate))


@dataclass(frozen=True, slots=True)
class ErrorPresentation:
	title: str
	message: str
	is_internal: bool = False


def present_error(error: Exception, translate: Translator | None = None) -> ErrorPresentation:
	translate = translate or _
	message_text = str(error).strip()
	if isinstance(error, UnsupportedModelError):
		return ErrorPresentation(
			title=translate("Unsupported model"),
			message=message_text or translate("The selected model is not supported for this workflow."),
		)
	if isinstance(error, ProviderConfigurationError):
		return ErrorPresentation(
			title=translate("Provider configuration problem"),
			message=message_text or translate("The selected provider is not configured correctly."),
		)
	if isinstance(error, LLMProviderError):
		return ErrorPresentation(
			title=translate("Provider request failed"),
			message=message_text or translate("The selected provider could not complete the request."),
		)
	return ErrorPresentation(
		title=translate("Internal error"),
		message=translate("Something went wrong inside the add-on. Please try again."),
		is_internal=True,
	)
