# -*- coding: utf-8 -*-
"""JSON Schema acceptance, preservation and argument validation."""
from __future__ import annotations

import importlib

import pytest

from tests.support import ADDON_ROOT, register_package

NAMESPACE = "tool_schema_testpkg"
register_package(NAMESPACE, ADDON_ROOT)
schema_module = importlib.import_module(f"{NAMESPACE}.tools.schema")
definition_module = importlib.import_module(f"{NAMESPACE}.tools.definition")

ToolDefinition = definition_module.ToolDefinition
ToolSchemaError = schema_module.ToolSchemaError
normalize_input_schema = schema_module.normalize_input_schema
normalize_output_schema = schema_module.normalize_output_schema
serialize_schema = schema_module.serialize_schema
schema_fingerprint = schema_module.schema_fingerprint
validate_arguments = schema_module.validate_arguments


def _nested_schema() -> dict:
	return {
		"type": "object",
		"properties": {
			"query": {"type": "string", "minLength": 2, "pattern": "^[a-z]+$"},
			"limit": {"type": "integer", "minimum": 1, "maximum": 10},
			"filters": {
				"type": "array",
				"items": {
					"type": "object",
					"properties": {
						"field": {"type": "string", "enum": ["title", "body"]},
						"value": {"type": "string"},
					},
					"required": ["field"],
					"additionalProperties": False,
				},
				"minItems": 1,
			},
		},
		"required": ["query"],
		"additionalProperties": False,
		"$defs": {"mode": {"type": "string", "enum": ["fast", "exact"]}},
	}


def test_empty_schema_normalizes_to_object() -> None:
	schema = normalize_input_schema(None)
	assert schema == {"type": "object", "properties": {}}


def test_legacy_parameters_are_folded_into_full_schema() -> None:
	definition = ToolDefinition(
		name="legacy",
		description="legacy tool",
		parameters={"path": {"type": "string"}},
		required=["path"],
	)
	assert definition.input_schema["type"] == "object"
	assert definition.input_schema["required"] == ["path"]
	assert definition.input_schema["properties"]["path"]["type"] == "string"


def test_nested_schema_survives_registration_and_serialization() -> None:
	definition = ToolDefinition(
		name="search",
		description="search documents",
		input_schema=_nested_schema(),
		output_schema={"type": "object", "properties": {"ids": {"type": "array"}}},
	)
	assert definition.input_schema == _nested_schema()
	serialized = definition.to_dict()
	assert serialized["function"]["parameters"]["properties"]["filters"]["items"]["properties"]["field"]["enum"] == [
		"title",
		"body",
	]
	assert definition.output_schema["properties"]["ids"]["type"] == "array"
	assert "$defs" in serialized["function"]["parameters"]


def test_schema_dicts_are_not_mutated_or_aliased() -> None:
	source = _nested_schema()
	before = serialize_schema(source)
	definition = ToolDefinition(name="search", description="search", input_schema=source)
	# Mutating the caller's dictionary must not affect the definition.
	source["properties"]["query"]["minLength"] = 99
	assert definition.input_schema["properties"]["query"]["minLength"] == 2
	assert serialize_schema(source) != before
	# Mutating a serialized copy must not affect the definition either.
	serialized = definition.to_dict()
	serialized["function"]["parameters"]["properties"]["query"]["minLength"] = 50
	assert definition.input_schema["properties"]["query"]["minLength"] == 2


def test_deterministic_serialization_is_key_order_independent() -> None:
	first = {"type": "object", "description": "x", "properties": {"b": {"type": "string"}, "a": {"type": "integer"}}}
	second = {"properties": {"a": {"type": "integer"}, "b": {"type": "string"}}, "description": "x", "type": "object"}
	assert serialize_schema(first) == serialize_schema(second)
	assert schema_fingerprint(first) == schema_fingerprint(second)


def test_output_schema_is_optional_and_validated() -> None:
	assert normalize_output_schema(None) is None
	output = normalize_output_schema({"type": "array", "items": {"type": "string"}})
	assert output["type"] == "array"
	with pytest.raises(ToolSchemaError, match="outputSchema.type"):
		normalize_output_schema({"type": "nonsense"})


@pytest.mark.parametrize(
	"payload, message",
	[
		({"type": "array"}, "must be objects"),
		({"type": "object", "properties": []}, r"properties.*must be a JSON object"),
		({"type": "object", "$ref": "https://example.com/schema"}, "only local references"),
		({"type": "object", "$ref": "#/$defs/missing"}, "unresolved reference"),
		({"type": "object", "properties": {"x": {"type": "bogus"}}}, "unsupported JSON type"),
		({"type": "object", "required": "x"}, "list of strings"),
		({"type": "object", "properties": {"x": {"pattern": "["}}}, "invalid regular expression"),
	],
)
def test_invalid_schemas_fail_with_actionable_errors(payload, message) -> None:
	with pytest.raises(ToolSchemaError, match=message):
		ToolDefinition(name="broken", description="broken", input_schema=payload)


def test_local_refs_are_resolved_for_argument_validation() -> None:
	schema = {
		"type": "object",
		"properties": {"mode": {"$ref": "#/$defs/mode"}},
		"$defs": {"mode": {"type": "string", "enum": ["fast", "exact"]}},
		"required": ["mode"],
	}
	assert validate_arguments(schema, {"mode": "fast"}) == ()
	violations = validate_arguments(schema, {"mode": "slow"})
	assert [item.path for item in violations] == ["$.mode"]


def test_required_nested_array_enum_and_constraints() -> None:
	schema = _nested_schema()
	assert validate_arguments(schema, {"query": "abc"}) == ()
	violations = validate_arguments(
		schema,
		{"query": "A", "limit": 0, "filters": [{"field": "unknown"}]},
	)
	paths = {violation.path for violation in violations}
	assert "$.query" in paths
	assert "$.limit" in paths
	assert "$.filters[0].field" in paths
	assert "$.filters[0].value" not in paths


def test_additional_properties_and_missing_required() -> None:
	schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}
	violations = validate_arguments(schema, {"b": "x"})
	assert {violation.path for violation in violations} == {"$.a", "$.b"}


def test_arguments_must_be_objects() -> None:
	violations = validate_arguments({"type": "object", "properties": {}}, ["not", "an", "object"])
	assert violations
	assert "arguments must be a JSON object" in violations[0].message


def test_one_of_and_any_of() -> None:
	schema = {
		"type": "object",
		"properties": {"value": {"anyOf": [{"type": "string"}, {"type": "integer", "minimum": 2}]}},
	}
	assert validate_arguments(schema, {"value": "x"}) == ()
	assert validate_arguments(schema, {"value": 3}) == ()
	assert validate_arguments(schema, {"value": 1})
	assert validate_arguments(schema, {"value": True})
