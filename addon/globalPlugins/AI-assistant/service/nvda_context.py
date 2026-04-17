# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import api
from logHandler import log
from textInfos import POSITION_ALL

from ..context.types import PageSnapshot, SnapshotType

try:
	import treeInterceptorHandler
except Exception:  # pragma: no cover
	treeInterceptorHandler = None


PageSnapshotMode = Literal["full", "structure_only"]


@dataclass(frozen=True, slots=True)
class FocusObjectContext:
	title: str
	role_text: str
	app_title: str
	window_title: str
	window_handle: int | None
	location: Any | None
	focus_object: object | None
	foreground_object: object | None


@dataclass(frozen=True, slots=True)
class WindowContext:
	window_title: str
	app_title: str
	hwnd: int | None
	location: Any | None
	focus_object: object | None
	foreground_object: object | None


@dataclass(frozen=True, slots=True)
class ClipboardContext:
	text: str | None
	raw_data: Any | None
	format_id: int | None


@dataclass(frozen=True, slots=True)
class PageSnapshotResult:
	snapshot: PageSnapshot | None
	raw_fields: tuple[Any, ...]
	text_info: Any | None
	url: str | None


MAX_PAGE_TEXT_CHARS = 120000


class NVDAContextService:
	"""Host service for NVDA runtime context and clipboard access."""

	def get_focus_object(self) -> object | None:
		try:
			return api.getFocusObject()
		except Exception as error:
			log.debug("NVDAContextService.get_focus_object failed: %s", error)
			return None

	def get_focus_ancestors(self) -> tuple[object, ...]:
		try:
			get_focus_ancestors = getattr(api, "getFocusAncestors", None)
			if not callable(get_focus_ancestors):
				return ()
			ancestors: Any = get_focus_ancestors()
			if not ancestors:
				return ()
			return tuple(ancestors)
		except Exception as error:
			log.debug("NVDAContextService.get_focus_ancestors failed: %s", error)
			return ()

	def get_navigator_object(self) -> object | None:
		try:
			return api.getNavigatorObject()
		except Exception as error:
			log.debug("NVDAContextService.get_navigator_object failed: %s", error)
			return None

	def get_foreground_object(self) -> object | None:
		try:
			return api.getForegroundObject()
		except Exception as error:
			log.debug("NVDAContextService.get_foreground_object failed: %s", error)
			return None

	def get_current_url(self) -> str | None:
		try:
			get_current_url = getattr(api, "getCurrentURL", None)
			if not callable(get_current_url):
				return None
			url = get_current_url()
			if isinstance(url, str) and url.strip():
				return url.strip()
			return None
		except Exception as error:
			log.debug("NVDAContextService.get_current_url failed: %s", error)
			return None

	def get_clipboard_text(self) -> str | None:
		try:
			get_clip_data = getattr(api, "getClipData", None)
			if not callable(get_clip_data):
				return None
			content = get_clip_data()
			if isinstance(content, str):
				return content
			return None
		except Exception as error:
			log.debug("NVDAContextService.get_clipboard_text failed: %s", error)
			return None

	def get_clipboard_data(self, format_id: int) -> Any | None:
		try:
			win_user = getattr(api, "winUser", None)
			if win_user is None:
				return None
			get_clipboard_data = getattr(win_user, "getClipboardData", None)
			if not callable(get_clipboard_data):
				return None
			return get_clipboard_data(format_id)
		except Exception as error:
			log.debug("NVDAContextService.get_clipboard_data failed for format %s: %s", format_id, error)
			return None

	def get_clipboard_context(self, format_id: int | None = None) -> ClipboardContext:
		if format_id is None:
			return ClipboardContext(text=self.get_clipboard_text(), raw_data=None, format_id=None)
		return ClipboardContext(text=None, raw_data=self.get_clipboard_data(format_id), format_id=format_id)

	def get_window_text(self, hwnd: int | None, obj: object | None = None) -> str:
		if hwnd is not None:
			try:
				win_user = getattr(api, "winUser", None)
				if win_user is not None:
					get_window_text = getattr(win_user, "getWindowText", None)
					if callable(get_window_text):
						text = get_window_text(hwnd)
						if isinstance(text, str) and text.strip():
							return text.strip()
			except Exception as error:
				log.debug("NVDAContextService.get_window_text failed for hwnd %s: %s", hwnd, error)

		if obj is not None:
			try:
				window_text = getattr(obj, "windowText", None)
				if isinstance(window_text, str) and window_text.strip():
					return window_text.strip()
			except Exception:
				pass
		return ""

	def get_object_location(self, obj: object | None) -> Any | None:
		if obj is None:
			return None
		try:
			return getattr(obj, "location", None)
		except Exception as error:
			log.debug("NVDAContextService.get_object_location failed: %s", error)
			return None

	def get_window_handle(self, obj: object | None) -> int | None:
		if obj is None:
			return None
		try:
			hwnd = getattr(obj, "windowHandle", None)
			if isinstance(hwnd, int):
				return hwnd
			return None
		except Exception as error:
			log.debug("NVDAContextService.get_window_handle failed: %s", error)
			return None

	def get_tree_interceptor(self, obj: object | None) -> object | None:
		if obj is None:
			return None

		interceptor = getattr(obj, "treeInterceptor", None)
		if self.is_usable_tree_interceptor(interceptor):
			return interceptor

		if treeInterceptorHandler is None:
			return None

		try:
			get_tree_interceptor = getattr(treeInterceptorHandler, "getTreeInterceptor", None)
			if not callable(get_tree_interceptor):
				return None
			resolved = get_tree_interceptor(obj)
			if self.is_usable_tree_interceptor(resolved):
				return resolved
		except Exception as error:
			log.debug("NVDAContextService.get_tree_interceptor failed: %s", error)
		return None

	def is_usable_tree_interceptor(self, interceptor: object | None) -> bool:
		if interceptor is None:
			return False
		if not hasattr(interceptor, "makeTextInfo"):
			return False
		try:
			if getattr(interceptor, "isAlive", True) is False:
				return False
		except Exception:
			return False
		try:
			if getattr(interceptor, "isReady", True) is False:
				return False
		except Exception:
			pass
		return True

	def make_text_info(self, obj: object | None, position: str = POSITION_ALL) -> Any | None:
		if obj is None:
			return None
		make_text_info = getattr(obj, "makeTextInfo", None)
		if not callable(make_text_info):
			return None
		try:
			return make_text_info(position)
		except Exception as error:
			log.debug("NVDAContextService.make_text_info failed: %s", error)
			return None

	def get_app_name(self, obj: object | None) -> str | None:
		if obj is None:
			return None
		try:
			app_module = getattr(obj, "appModule", None)
			if app_module is not None:
				app_name = getattr(app_module, "appName", None)
				if isinstance(app_name, str) and app_name.strip():
					return app_name.strip()
			return None
		except Exception as error:
			log.debug("NVDAContextService.get_app_name failed: %s", error)
			return None

	def get_object_title(self, obj: object | None) -> str | None:
		if obj is None:
			return None
		for attr in ("name", "windowText", "title", "description"):
			try:
				value = getattr(obj, attr, None)
			except Exception:
				value = None
			if isinstance(value, str) and value.strip():
				return value.strip()
		return None

	def get_focus_object_context(self) -> FocusObjectContext:
		focus = self.get_focus_object()
		foreground = self.get_foreground_object()
		window_handle = self.get_window_handle(focus)
		return FocusObjectContext(
			title=self.get_object_title(focus) or "",
			role_text=self._get_role_text(focus),
			app_title=self.get_app_name(focus) or "",
			window_title=self.get_window_text(window_handle, focus),
			window_handle=window_handle,
			location=self.get_object_location(focus),
			focus_object=focus,
			foreground_object=foreground,
		)

	def get_window_context(self) -> WindowContext:
		focus = self.get_focus_object()
		foreground = self.get_foreground_object()
		hwnd = self.get_window_handle(focus)
		return WindowContext(
			window_title=self.get_window_text(hwnd, focus),
			app_title=self.get_app_name(focus) or "",
			hwnd=hwnd,
			location=self.get_object_location(focus),
			focus_object=focus,
			foreground_object=foreground,
		)

	def get_active_page_snapshot(self, mode: PageSnapshotMode = "full") -> PageSnapshotResult:
		interceptor = self._resolve_page_interceptor()
		if interceptor is None:
			return PageSnapshotResult(snapshot=None, raw_fields=(), text_info=None, url=self.get_current_url())

		text_info = self.make_text_info(interceptor)
		raw_fields = self._extract_text_fields(text_info)
		page_text = self._extract_text(text_info) if mode == "full" else ""
		page_text, truncated = self._trim_text(page_text)
		headings, links, buttons, landmarks = self._parse_structured_fields(text_info)
		snapshot = PageSnapshot(
			snapshot_type=SnapshotType.PAGE,
			title=self.get_object_title(interceptor) or "",
			appTitle=self.get_app_name(interceptor) or "",
			text=page_text,
			truncated=truncated,
			headings=tuple(headings),
			links=tuple(links),
			buttons=tuple(buttons),
			landmarks=tuple(landmarks),
		)
		return PageSnapshotResult(snapshot=snapshot, raw_fields=raw_fields, text_info=text_info, url=self.get_current_url())

	def get_page_structure(self) -> PageSnapshotResult:
		return self.get_active_page_snapshot(mode="structure_only")

	def _resolve_page_interceptor(self) -> object | None:
		focus = self.get_focus_object()
		for candidate in (focus, self.get_navigator_object(), self.get_foreground_object()):
			if candidate is None:
				continue
			interceptor = self.get_tree_interceptor(candidate)
			if interceptor is not None:
				return interceptor

		for candidate in (focus, self.get_navigator_object(), self.get_foreground_object()):
			if candidate is None:
				continue
			if hasattr(candidate, "makeTextInfo"):
				return candidate

		return None

	def _extract_text(self, text_info: Any | None) -> str:
		if text_info is None:
			return ""
		try:
			text = getattr(text_info, "text", "")
			if not isinstance(text, str):
				return ""
			return text.strip()
		except Exception as error:
			log.debug("NVDAContextService._extract_text failed: %s", error)
			return ""

	def _extract_text_fields(self, text_info: Any | None) -> tuple[Any, ...]:
		if text_info is None or not hasattr(text_info, "getTextWithFields"):
			return ()
		try:
			fields: Any = text_info.getTextWithFields()
			if isinstance(fields, (list, tuple)):
				return tuple(fields)  # type: ignore[arg-type]
			return (fields,)
		except Exception as error:
			log.debug("NVDAContextService._extract_text_fields failed: %s", error)
			return ()

	def _trim_text(self, text: str) -> tuple[str, bool]:
		if len(text) <= MAX_PAGE_TEXT_CHARS:
			return text, False
		return text[:MAX_PAGE_TEXT_CHARS] + "\n\n[Content trimmed before summarization]\n\n", True

	def _parse_structured_fields(self, text_info: Any | None) -> tuple[tuple[tuple[int | None, str], ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
		headings: list[tuple[int | None, str]] = []
		links: list[str] = []
		buttons: list[str] = []
		landmarks: list[str] = []
		if text_info is None or not hasattr(text_info, "getTextWithFields"):
			return tuple(headings), tuple(links), tuple(buttons), tuple(landmarks)
		try:
			fields = text_info.getTextWithFields()
			for item in fields:
				if not hasattr(item, "command") or not hasattr(item, "field"):
					continue
				field = item.field
				role = self._field_role(field)
				text_value = self._field_text(field)
				if self._is_heading_field(field, role):
					headings.append((None, text_value))
				elif self._is_link_field(field, role):
					links.append(text_value)
				elif self._is_button_field(field, role):
					buttons.append(text_value)
				elif self._is_landmark_field(field, role):
					landmarks.append(text_value)
			return tuple(headings), tuple(links), tuple(buttons), tuple(landmarks)
		except Exception as error:
			log.debug("NVDAContextService._parse_structured_fields failed: %s", error)
		return tuple(headings), tuple(links), tuple(buttons), tuple(landmarks)

	def _field_role(self, field: Any) -> str:
		role = field.get("role")
		if isinstance(role, str):
			return role.lower()
		try:
			return str(role).lower()
		except Exception:
			return ""

	def _field_text(self, field: Any) -> str:
		try:
			if field.get("ia2TextStartOffset") is not None and isinstance(field.get("ia2TextStartOffset"), int):
				return str(field.get("IAccessible2::attribute_tag") or field.get("IAccessible2::attribute_xml-roles") or "").strip()
			return str(field.get("IAccessible2::attribute_tag") or field.get("IAccessible2::attribute_xml-roles") or "").strip()
		except Exception:
			return ""

	def _is_heading_field(self, field: Any, role: str) -> bool:
		return any(token in role for token in ("heading", "section", "article", "banner")) or any(
			token in str(field.get("IAccessible2::attribute_tag") or "").lower()
			for token in ("h1", "h2", "h3", "h4", "h5", "h6")
		)

	def _is_link_field(self, field: Any, role: str) -> bool:
		return any(token in role for token in ("link", "hyperlink")) or "a" == str(field.get("IAccessible2::attribute_tag")).lower()

	def _is_button_field(self, field: Any, role: str) -> bool:
		return any(token in role for token in ("button", "pushbutton")) or "button" == str(field.get("IAccessible2::attribute_tag")).lower()

	def _is_landmark_field(self, field: Any, role: str) -> bool:
		return any(token in role for token in ("main", "navigation", "complementary", "search", "banner", "contentinfo"))

	def _get_role_text(self, obj: object | None) -> str:
		if obj is None:
			return ""
		try:
			role_text = getattr(obj, "roleText", None)
			if isinstance(role_text, str) and role_text.strip():
				return role_text.strip()
			return str(getattr(obj, "role", ""))
		except Exception:
			return ""
