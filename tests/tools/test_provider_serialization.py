# -*- coding: utf-8 -*-
"""Provider serialization keeps complete JSON schemas and surfaces bad JSON."""
from __future__ import annotations

import importlib

from tests.support import ADDON_ROOT, register_package

NAMESPACE = "tool_provider_serialization_testpkg"
register_package(NAMESPACE, ADDON_ROOT)
tools = importlib.import_module(f"{NAMESPACE}.tools")
canonical = importlib.import_module(f"{NAMESPACE}.core.canonical")
openai_compat = importlib.import_module(f"{NAMESPACE}.providers.adapters.openai_compat")

build_function_tool_definition = tools.build_function_tool_definition
normalize_tool_calls = tools.normalize_tool_calls
Tool = canonical.Tool


NESTED_SCHEMA = {
	"type": "object",
	"properties": {
		"filters": {
			"type": "array",
			"items": {
				"type": "object",
				"properties": {
					"field": {"type": "string", "enum": ["title", "body"]},
					"value": {"$ref": "#/$defs/text"},
				},
				"required": ["field"],
			},
		},
		"limit": {"type": "integer", "minimum": 1, "maximum": 50},
	},
	"required": ["filters"],
	"additionalProperties": False,
	"$defs": {"text": {"type": "string", "minLength": 1}},
}


def _tool(input_schema=None) -> Tool:
	return Tool(
		name="search",
		description="Search",
		input_schema=input_schema if input_schema is not None else NESTED_SCHEMA,
	)


def test_openai_style_definition_preserves_full_schema() -> None:
	wire = build_function_tool_definition(_tool())
	parameters = wire["function"]["parameters"]
	assert parameters["properties"]["filters"]["items"]["properties"]["field"]["enum"] == ["title", "body"]
	assert parameters["properties"]["limit"]["maximum"] == 50
	assert parameters["$defs"]["text"]["minLength"] == 1
	assert parameters["additionalProperties"] is False


def test_provider_adapter_serializer_uses_full_schema() -> None:
	definitions = openai_compat.OpenAICompatProvider._build_tool_definitions([_tool()])
	assert definitions is not None
	parameters = definitions[0]["function"]["parameters"]
	assert parameters["properties"]["filters"]["type"] == "array"
	assert "$defs" in parameters


def test_legacy_tool_without_input_schema_still_serializes() -> None:
	legacy = Tool(name="legacy", description="Legacy", parameters={"path": {"type": "string"}}, required=("path",))
	wire = build_function_tool_definition(legacy)
	parameters = wire["function"]["parameters"]
	assert parameters == {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}


def test_serialized_schema_is_a_copy() -> None:
	tool = _tool()
	wire = build_function_tool_definition(tool)
	wire["function"]["parameters"]["properties"]["filters"]["items"]["properties"]["field"]["enum"].append("mutated")
	assert tool.input_schema["properties"]["filters"]["items"]["properties"]["field"]["enum"] == ["title", "body"]


def test_normalize_tool_calls_decodes_json_arguments() -> None:
	calls = normalize_tool_calls(
		[{"id": "1", "function": {"name": "search", "arguments": '{"filters": [{"field": "title"}]}'}}]
	)
	assert calls is not None
	assert calls[0].name == "search"
	assert calls[0].arguments == {"filters": [{"field": "title"}]}
	assert calls[0].parse_error is None


def test_malformed_json_is_recorded_not_silently_emptied() -> None:
	calls = normalize_tool_calls([{"id": "1", "function": {"name": "search", "arguments": "{not json"}}])
	assert calls is not None
	assert calls[0].arguments == {}
	assert calls[0].parse_error is not None
	assert "malformed JSON" in calls[0].parse_error
	assert calls[0].raw_arguments == "{not json"


def test_non_object_json_arguments_are_rejected() -> None:
	calls = normalize_tool_calls([{"id": "1", "function": {"name": "search", "arguments": "[1, 2]"}}])
	assert calls is not None
	assert calls[0].parse_error is not None
	assert calls[0].arguments == {}


def test_ollama_style_tool_decode_is_supported() -> None:
	calls = normalize_tool_calls([{"id": "1", "function": {"name": "search", "arguments": {"limit": 3}}}])
	assert calls is not None
	assert calls[0].arguments == {"limit": 3}
	assert calls[0].parse_error is None
