#!/usr/bin/env python3
"""Generate protocol constants and enums from ``scripts/protocol.yaml``.

Produces three files:

* ``addon/globalPlugins/AI-assistant/ui/host_protocol_constants.py``
* ``nvda_ui_host/src/protocol_commands.rs``
* ``nvda_ui_host/webui/src/lib/protocol-commands.ts``

Usage::

    python scripts/generate_protocol.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / "scripts" / "protocol.yaml"
PAYLOAD_TYPES = {"string", "integer", "boolean", "array", "object", "json"}


def _load_spec() -> dict[str, Any]:
	import yaml

	with open(SPEC_PATH, encoding="utf-8") as fh:
		spec = yaml.safe_load(fh)
	_validate_spec(spec)
	return spec


def _validate_spec(spec: dict[str, Any]) -> None:
	"""Fail generation when the declarative contract is internally inconsistent."""
	for command in spec.get("commands", []):
		command_id = command["id"]
		fields = set(command.get("required_payload_fields", ()))
		types = command.get("required_payload_types", {})
		if set(types) != fields:
			raise ValueError(
				f"Command {command_id} must declare exactly one type for each required payload field"
			)
		unknown_types = set(types.values()) - PAYLOAD_TYPES
		if unknown_types:
			raise ValueError(f"Command {command_id} uses unsupported payload types: {sorted(unknown_types)}")


# ---------------------------------------------------------------------------
# Python output
# ---------------------------------------------------------------------------

_PY_HEADER = '''\
# -*- coding: utf-8 -*-
"""Auto-generated protocol command and event name constants.

Generated from ``scripts/protocol.yaml`` by ``scripts/generate_protocol.py``.
DO NOT EDIT BY HAND.
"""
from __future__ import annotations
'''


def _generate_python(spec: dict[str, Any]) -> str:
	lines: list[str] = [_PY_HEADER, ""]
	for cmd in spec["commands"]:
		lines.append(f'COMMAND_{cmd["snake"].upper()} = "{cmd["id"]}"')
	lines.append("")
	for evt in spec["events"]:
		lines.append(f'EVENT_{evt["snake"].upper()} = "{evt["id"]}"')
	lines.append("")
	lines.append("COMMAND_NAMES = (")
	for cmd in spec["commands"]:
		lines.append(f'\t"{cmd["id"]}",')
	lines.append(")")
	lines.append("")
	lines.append("EVENT_NAMES = (")
	for evt in spec["events"]:
		lines.append(f'\t"{evt["id"]}",')
	lines.append(")")
	lines.append("")
	lines.append("COMMAND_REQUIRED_FIELDS = {")
	for cmd in spec["commands"]:
		lines.append(f'\t"{cmd["id"]}": {tuple(cmd.get("required_payload_fields", ()))!r},')
	lines.append("}")
	lines.append("")
	lines.append("COMMAND_REQUIRED_FIELD_TYPES = {")
	for cmd in spec["commands"]:
		types = cmd.get("required_payload_types", {})
		lines.append(f'\t"{cmd["id"]}": {types!r},')
	lines.append("}")
	return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rust output
# ---------------------------------------------------------------------------

_RS_HEADER = """\
// Auto-generated protocol command and event enums.
//
// Generated from ``scripts/protocol.yaml`` by ``scripts/generate_protocol.py``.
// DO NOT EDIT BY HAND.

// Note: serde and serde_json are already in scope from the parent protocol.rs.
"""


def _generate_rust(spec: dict[str, Any]) -> str:
	lines: list[str] = [_RS_HEADER]

	# CommandName enum
	lines.append("#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]")
	lines.append('#[serde(rename_all = "snake_case")]')
	lines.append("pub enum CommandName {")
	for cmd in spec["commands"]:
		lines.append(f"    {cmd['rust']},")
	lines.append("}")

	# EventName enum
	lines.append("")
	lines.append("#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]")
	lines.append('#[serde(rename_all = "snake_case")]')
	lines.append("pub enum EventName {")
	for evt in spec["events"]:
		lines.append(f"    {evt['rust']},")
	lines.append("}")

	# UiCommand enum (needed by UiCommand impl blocks in protocol.rs)
	lines.append("")
	lines.append("#[derive(Debug, Clone, PartialEq)]")
	lines.append("pub enum UiCommand {")
	for cmd in spec["commands"]:
		if cmd["id"] == "health_check":
			lines.append(f"    {cmd['rust']},")
		else:
			lines.append(f"    {cmd['rust']}(Value),")
	lines.append("}")

	# UiCommand::command_name()
	lines.append("")
	lines.append("impl UiCommand {")
	lines.append("    pub fn command_name(&self) -> CommandName {")
	lines.append("        match self {")
	for cmd in spec["commands"]:
		if cmd["id"] == "health_check":
			lines.append(f"            UiCommand::{cmd['rust']} => CommandName::{cmd['rust']},")
		else:
			lines.append(f"            UiCommand::{cmd['rust']}(_) => CommandName::{cmd['rust']},")
	lines.append("        }")
	lines.append("    }")

	# UiCommand::payload()
	lines.append("")
	lines.append("    pub fn payload(&self) -> Value {")
	lines.append("        match self {")

	# Handle HealthCheck (no payload) specially
	lines.append("            UiCommand::HealthCheck => Value::Object(Default::default()),")

	# Group all payload-carrying variants with |
	payload_variants = [c["rust"] for c in spec["commands"] if c["id"] != "health_check"]
	grouped = " | ".join(f"UiCommand::{v}(payload)" for v in payload_variants)
	lines.append(f"            {grouped} => payload.clone(),")
	lines.append("        }")
	lines.append("    }")

	# UiCommand::from_command_name()
	lines.append("")
	lines.append("    pub(crate) fn from_command_name(name: CommandName, payload: Value) -> Self {")
	lines.append("        match name {")
	for cmd in spec["commands"]:
		variant = cmd["rust"]
		if cmd["id"] == "health_check":
			lines.append(f"            CommandName::{variant} => UiCommand::{variant},")
		else:
			lines.append(f"            CommandName::{variant} => UiCommand::{variant}(payload),")
	lines.append("        }")
	lines.append("    }")
	lines.append("}")

	lines.append("")
	lines.append("pub fn required_payload_fields(command: &CommandName) -> &'static [&'static str] {")
	lines.append("    match command {")
	for cmd in spec["commands"]:
		fields = cmd.get("required_payload_fields", ())
		field_values = ", ".join(f'"{field}"' for field in fields)
		lines.append(f"        CommandName::{cmd['rust']} => &[{field_values}],")
	lines.append("    }")
	lines.append("}")

	lines.append("")
	lines.append("pub fn required_payload_types(command: &CommandName) -> &'static [(&'static str, &'static str)] {")
	lines.append("    match command {")
	for cmd in spec["commands"]:
		types = cmd.get("required_payload_types", {})
		pairs = ", ".join(f'("{field}", "{type_name}")' for field, type_name in types.items())
		lines.append(f"        CommandName::{cmd['rust']} => &[{pairs}],")
	lines.append("    }")
	lines.append("}")

	return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# TypeScript output
# ---------------------------------------------------------------------------

_TS_HEADER = """\
// Auto-generated protocol command and event name types.
//
// Generated from ``scripts/protocol.yaml`` by ``scripts/generate_protocol.py``.
// DO NOT EDIT BY HAND.
"""


def _generate_typescript(spec: dict[str, Any]) -> str:
	lines: list[str] = [_TS_HEADER, ""]

	cmd_names = [f'"{c["id"]}"' for c in spec["commands"]]
	lines.append(f"export type CommandName = {' | '.join(cmd_names)};")
	lines.append("")

	evt_names = [f'"{e["id"]}"' for e in spec["events"]]
	lines.append(f"export type EventName = {' | '.join(evt_names)};")
	lines.append("")

	chat_cmds = [c for c in spec["commands"] if c.get("chat")]
	chat_names = [f'"{c["id"]}"' for c in chat_cmds]
	lines.append(f"export const CHAT_COMMANDS = new Set<CommandName>([{', '.join(chat_names)}]);")
	lines.append("")
	lines.append("export const COMMAND_REQUIRED_FIELDS: Record<CommandName, readonly string[]> = {")
	for cmd in spec["commands"]:
		fields = cmd.get("required_payload_fields", ())
		field_values = ", ".join(f'"{field}"' for field in fields)
		lines.append(f'\t"{cmd["id"]}": [{field_values}],')
	lines.append("};")
	lines.append("")
	lines.append("export type PayloadFieldType = 'string' | 'integer' | 'boolean' | 'array' | 'object' | 'json';")
	lines.append("")
	lines.append("export const COMMAND_REQUIRED_FIELD_TYPES: Record<CommandName, Readonly<Record<string, PayloadFieldType>>> = {")
	for cmd in spec["commands"]:
		types = cmd.get("required_payload_types", {})
		entries = ", ".join(f'"{field}": "{type_name}"' for field, type_name in types.items())
		lines.append(f'\t"{cmd["id"]}": {{{entries}}},')
	lines.append("};")
	lines.append("")

	return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
	spec = _load_spec()

	outputs: list[tuple[Path, str]] = [
		(
			ROOT / "addon" / "globalPlugins" / "AI-assistant" / "ui" / "host_protocol_constants.py",
			_generate_python(spec),
		),
		(
			ROOT / "nvda_ui_host" / "src" / "protocol_commands.rs",
			_generate_rust(spec),
		),
		(
			ROOT / "nvda_ui_host" / "webui" / "src" / "lib" / "protocol-commands.ts",
			_generate_typescript(spec),
		),
	]

	for path, content in outputs:
		path.write_text(content, encoding="utf-8")
		print(f"  wrote {path.relative_to(ROOT)}")

	print("Done.")


if __name__ == "__main__":
	main()
