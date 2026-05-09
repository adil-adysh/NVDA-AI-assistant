# -*- coding: utf-8 -*-
from __future__ import annotations

from collections.abc import Sequence
import base64
import importlib
import json
from pathlib import Path
import tempfile
import time
from typing import Any

from logHandler import log

from ...config.defaults import DEFAULT_CONFIG_PATH
from ...core.canonical import Message, Part
from .repository import ConversationRepository, ConversationSummary
from .session import ConversationSession


def _default_memory_engine_path() -> Path:
	return Path(DEFAULT_CONFIG_PATH).expanduser().resolve().with_name("conversations.db")


def _default_json_store_path() -> Path:
	return Path(DEFAULT_CONFIG_PATH).expanduser().resolve().with_name("conversations.json")


def _truncate(text: str, limit: int) -> str:
	normalized = " ".join(text.split())
	if len(normalized) <= limit:
		return normalized
	return normalized[: max(0, limit - 1)].rstrip() + "..."


def _part_to_dict(part: Part) -> dict[str, Any]:
	payload: dict[str, Any] = {"type": part.type}
	if part.text is not None:
		payload["text"] = part.text
	if part.image is not None:
		payload["image_base64"] = base64.b64encode(part.image).decode("ascii")
	if part.tool_name is not None:
		payload["tool_name"] = part.tool_name
	if part.tool_args is not None:
		payload["tool_args"] = dict(part.tool_args)
	if part.tool_result is not None:
		payload["tool_result"] = dict(part.tool_result)
	return payload


def _message_to_dict(message: Message) -> dict[str, Any]:
	return {
		"role": message.role,
		"parts": [_part_to_dict(part) for part in message.parts],
	}


def _part_from_dict(payload: dict[str, Any]) -> Part:
	image_bytes = None
	image_base64 = payload.get("image_base64")
	if isinstance(image_base64, str) and image_base64:
		image_bytes = base64.b64decode(image_base64)
	return Part(
		type=str(payload.get("type", "text")),
		text=payload.get("text") if isinstance(payload.get("text"), str) else None,
		image=image_bytes,
		tool_name=payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else None,
		tool_args=payload.get("tool_args") if isinstance(payload.get("tool_args"), dict) else None,
		tool_result=payload.get("tool_result") if isinstance(payload.get("tool_result"), dict) else None,
	)


def _message_from_dict(payload: dict[str, Any]) -> Message:
	parts_payload = payload.get("parts") if isinstance(payload.get("parts"), list) else []
	parts = tuple(_part_from_dict(part) for part in parts_payload if isinstance(part, dict))
	role = payload.get("role") if isinstance(payload.get("role"), str) else "user"
	return Message(role=role, parts=parts)


def _messages_to_json(messages: Sequence[Message]) -> str:
	return json.dumps([_message_to_dict(message) for message in messages], ensure_ascii=False)


def _messages_from_json(payload: str | None) -> list[Message]:
	if not isinstance(payload, str) or not payload.strip():
		return []
	data = json.loads(payload)
	if not isinstance(data, list):
		return []
	return [_message_from_dict(item) for item in data if isinstance(item, dict)]


def _derive_summary(conversation_id: str, messages: Sequence[Message], updated_at: float | None = None) -> ConversationSummary:
	first_user_text = ""
	latest_text = ""
	for message in messages:
		for part in message.parts:
			if part.type != "text" or not isinstance(part.text, str) or not part.text.strip():
				continue
			if not first_user_text and message.role == "user":
				first_user_text = part.text.strip()
			latest_text = part.text.strip()
	if not first_user_text and latest_text:
		first_user_text = latest_text
	title = _truncate(first_user_text or "New conversation", 72)
	preview = _truncate(latest_text, 120) if latest_text else ""
	return ConversationSummary(
		conversation_id=conversation_id,
		title=title,
		preview=preview,
		message_count=len(messages),
		updated_at=updated_at if isinstance(updated_at, (int, float)) else time.time(),
	)


class MemoryEngineConversationRepository:
	_MESSAGES_TABLE = "conversation_messages"
	_META_TABLE = "conversation_meta"

	def __init__(self, engine: Any | None = None, db_path: str | Path | None = None) -> None:
		self._db_path = Path(db_path) if db_path is not None else _default_memory_engine_path()
		self._db_path.parent.mkdir(parents=True, exist_ok=True)
		if engine is None:
			module = importlib.import_module("memory_engine")
			engine = module.MemoryEngine(str(self._db_path))
		self._engine = engine
		for table_name in (self._MESSAGES_TABLE, self._META_TABLE):
			self._engine.create_table(table_name)

	def exists(self, conversation_id: str) -> bool:
		return bool(self._engine.contains(conversation_id, self._MESSAGES_TABLE))

	def load(self, conversation_id: str) -> ConversationSession:
		return ConversationSession(_messages=_messages_from_json(self._engine.get(conversation_id, self._MESSAGES_TABLE)))

	def save(self, conversation_id: str, messages: Sequence[Message]) -> None:
		stored_messages = list(messages)
		summary = _derive_summary(conversation_id, stored_messages)
		self._engine.set(conversation_id, _messages_to_json(stored_messages), self._MESSAGES_TABLE)
		self._engine.set(conversation_id, json.dumps(summary.to_metadata(), ensure_ascii=False), self._META_TABLE)

	def list_summaries(self) -> list[ConversationSummary]:
		summaries: list[ConversationSummary] = []
		for conversation_id in self._engine.keys(self._META_TABLE):
			payload = self._engine.get(conversation_id, self._META_TABLE)
			if not isinstance(payload, str) or not payload.strip():
				continue
			try:
				data = json.loads(payload)
			except Exception:
				log.exception("Failed to parse stored conversation metadata for %s", conversation_id)
				continue
			if not isinstance(data, dict):
				continue
			message_count = int(data.get("message_count") or 0)
			if message_count <= 0:
				continue
			title = str(data.get("title") or "New conversation")
			preview = str(data.get("preview") or "")
			if preview == title:
				preview = ""
			summaries.append(
				ConversationSummary(
					conversation_id=conversation_id,
					title=title,
					preview=preview,
					message_count=message_count,
					updated_at=float(data.get("updated_at") or 0.0),
				)
			)
		summaries.sort(key=lambda item: item.updated_at, reverse=True)
		return summaries

	def delete(self, conversation_id: str) -> bool:
		deleted_messages = bool(self._engine.delete(conversation_id, self._MESSAGES_TABLE))
		deleted_meta = bool(self._engine.delete(conversation_id, self._META_TABLE))
		return deleted_messages or deleted_meta


class JsonConversationRepository:
	def __init__(self, file_path: str | Path | None = None) -> None:
		self._file_path = Path(file_path) if file_path is not None else _default_json_store_path()
		self._file_path.parent.mkdir(parents=True, exist_ok=True)

	def exists(self, conversation_id: str) -> bool:
		store = self._load_store()
		return conversation_id in store["messages"]

	def load(self, conversation_id: str) -> ConversationSession:
		store = self._load_store()
		payload = store["messages"].get(conversation_id)
		return ConversationSession(_messages=_messages_from_json(payload if isinstance(payload, str) else None))

	def save(self, conversation_id: str, messages: Sequence[Message]) -> None:
		store = self._load_store()
		stored_messages = list(messages)
		summary = _derive_summary(conversation_id, stored_messages)
		store["messages"][conversation_id] = _messages_to_json(stored_messages)
		store["meta"][conversation_id] = summary.to_metadata()
		self._write_store(store)

	def list_summaries(self) -> list[ConversationSummary]:
		store = self._load_store()
		summaries = [
			ConversationSummary(
				conversation_id=conversation_id,
				title=str(payload.get("title") or "New conversation"),
				preview="" if str(payload.get("preview") or "") == str(payload.get("title") or "New conversation") else str(payload.get("preview") or ""),
				message_count=int(payload.get("message_count") or 0),
				updated_at=float(payload.get("updated_at") or 0.0),
			)
			for conversation_id, payload in store["meta"].items()
			if isinstance(payload, dict) and int(payload.get("message_count") or 0) > 0
		]
		summaries.sort(key=lambda item: item.updated_at, reverse=True)
		return summaries

	def delete(self, conversation_id: str) -> bool:
		store = self._load_store()
		deleted_messages = store["messages"].pop(conversation_id, None) is not None
		deleted_meta = store["meta"].pop(conversation_id, None) is not None
		if deleted_messages or deleted_meta:
			self._write_store(store)
		return deleted_messages or deleted_meta

	def _load_store(self) -> dict[str, dict[str, Any]]:
		if not self._file_path.exists():
			return {"messages": {}, "meta": {}}
		try:
			data = json.loads(self._file_path.read_text(encoding="utf-8"))
		except Exception:
			log.exception("Failed to load JSON conversation repository from %s", self._file_path)
			return {"messages": {}, "meta": {}}
		if not isinstance(data, dict):
			return {"messages": {}, "meta": {}}
		messages = data.get("messages") if isinstance(data.get("messages"), dict) else {}
		meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
		return {"messages": messages, "meta": meta}

	def _write_store(self, store: dict[str, dict[str, Any]]) -> None:
		with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(self._file_path.parent)) as handle:
			json.dump(store, handle, ensure_ascii=False, indent=2)
			temp_path = Path(handle.name)
		temp_path.replace(self._file_path)


def build_default_conversation_repository() -> ConversationRepository:
	try:
		return MemoryEngineConversationRepository()
	except Exception:
		log.exception("Falling back to JSON conversation repository because memory_engine is unavailable")
		return JsonConversationRepository()
