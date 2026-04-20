# -*- coding: utf-8 -*-
from __future__ import annotations

from textInfos import POSITION_ALL


class TextExtractor:
	def extract_text(self, obj: object) -> str:
		for target in self._text_targets(obj):
			textInfo = self._make_text_info(target)
			if textInfo is None:
				continue

			text = self._extract_text_info_text(textInfo)
			if text:
				return text

		fragments: list[str] = []
		for attr in ("name", "value", "description", "displayText"):
			try:
				value = getattr(obj, attr, None)
			except Exception:
				value = None
			if isinstance(value, str) and value.strip():
				fragments.append(value.strip())
		return "\n".join(fragments)

	def _text_targets(self, obj: object):
		yield obj
		for attr in ("rootNVDAObject", "parent", "next", "previous"):
			try:
				target = getattr(obj, attr, None)
			except Exception:
				target = None
			if target is not None:
				yield target

	def _make_text_info(self, obj: object):
		if not hasattr(obj, "makeTextInfo"):
			return None
		try:
			return obj.makeTextInfo(POSITION_ALL)
		except Exception:
			return None

	def _extract_text_info_text(self, textInfo: object) -> str | None:
		for method_name in ("getTextWithFields", "text"):
			try:
				value = getattr(textInfo, method_name, None)
			except Exception:
				value = None
			if callable(value):
				try:
					result = value()
					if isinstance(result, str) and result.strip():
						return result
				except Exception:
					pass
			elif isinstance(value, str) and value.strip():
				return value
		return None
