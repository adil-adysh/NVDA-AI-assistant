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
	assert normalize_output_schema(True) is True
	assert normalize_output_schema(False) is False
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


def test_ref_sibling_assertions_are_enforced() -> None:
	schema = {
		"type": "object",
		"properties": {"value": {"$ref": "#/$defs/non_negative", "maximum": 3}},
		"$defs": {"non_negative": {"minimum": 0}},
	}
	assert validate_arguments(schema, {"value": 2}) == ()
	assert validate_arguments(schema, {"value": 4})
	assert validate_arguments(schema, {"value": -1})


def test_conditional_and_dependent_required_assertions_are_enforced() -> None:
	schema = {
		"type": "object",
		"if": {"properties": {"kind": {"const": "file"}}, "required": ["kind"]},
		"then": {"required": ["path"]},
		"else": {"required": ["url"]},
		"dependentRequired": {"credential": ["user"]},
	}
	assert validate_arguments(schema, {"kind": "file", "path": "a"}) == ()
	assert validate_arguments(schema, {"kind": "file"})
	assert validate_arguments(schema, {"credential": "secret"})


def test_property_names_and_contains_cardinality_are_enforced() -> None:
	schema = {
		"type": "object",
		"propertyNames": {"pattern": "^[a-z]+$"},
		"properties": {"items": {"type": "array", "contains": {"type": "integer", "minimum": 3}, "minContains": 2, "maxContains": 2}},
	}
	assert validate_arguments(schema, {"items": [3, 4, "x"]}) == ()
	assert validate_arguments(schema, {"items": [3]})
	assert validate_arguments(schema, {"Bad": 1, "items": [3, 4, 5]})


def test_unsupported_assertion_vocabulary_fails_closed() -> None:
	with pytest.raises(ToolSchemaError, match="unevaluatedProperties.*not supported"):
		ToolDefinition(name="strict", description="strict", input_schema={"type": "object", "unevaluatedProperties": False})


def test_zero_multiple_of_is_rejected_and_integer_accepts_integral_float() -> None:
	with pytest.raises(ToolSchemaError, match="multipleOf.*greater than zero"):
		ToolDefinition(name="bad", description="bad", input_schema={"type": "object", "properties": {"n": {"multipleOf": 0}}})
	assert validate_arguments({"type": "object", "properties": {"n": {"type": "integer"}}}, {"n": 2.0}) == ()
	assert validate_arguments({"type": "object", "properties": {"n": {"multipleOf": 0.1}}}, {"n": 0.3}) == ()


def test_json_numeric_and_nested_value_equality_survives_frozen_schemas() -> None:
	schema = {
		"type": "object",
		"properties": {
			"value": {"const": {"items": [1, {"enabled": True}]}},
			"unique": {"type": "array", "uniqueItems": True},
		},
	}
	assert validate_arguments(schema, {"value": {"items": [1.0, {"enabled": True}]}, "unique": [1, 2]}) == ()
	assert validate_arguments(schema, {"value": {"items": [1, {"enabled": True}]}, "unique": [1, 1.0]})


def test_nested_repetition_patterns_are_rejected_but_simple_patterns_work() -> None:
	with pytest.raises(ToolSchemaError, match="unsafe regular expression"):
		ToolDefinition(name="unsafe", description="unsafe", input_schema={"type": "object", "properties": {"x": {"pattern": "(a+)+$"}}})
	schema = {"type": "object", "properties": {"x": {"pattern": "^[a-z]{1,20}$"}}}
	assert validate_arguments(schema, {"x": "safe"}) == ()
	assert validate_arguments(schema, {"x": "Bad"})


@pytest.mark.parametrize(
	"schema",
	[
		{"type": None},
		{"required": None},
		{"properties": None},
		{"properties": {"value": {"maximum": None}}},
		{"properties": {"value": {"multipleOf": None}}},
	],
)
def test_present_validation_keywords_cannot_use_null_as_omission(schema) -> None:
	with pytest.raises(ToolSchemaError):
		ToolDefinition(name="invalid", description="invalid", input_schema={"type": "object", **schema})


def test_empty_prefix_items_is_a_valid_draft_2020_12_schema() -> None:
	assert normalize_output_schema({"type": "array", "prefixItems": []}) == {
		"type": "array",
		"prefixItems": [],
	}


def test_min_max_contains_without_contains_are_valid_annotations() -> None:
	schema = {"type": "array", "minContains": 2, "maxContains": 3}
	assert normalize_output_schema(schema) == schema
	assert validate_arguments({"type": "object", "properties": {"values": schema}}, {"values": []}) == ()


def test_unknown_required_vocabulary_fails_closed() -> None:
	with pytest.raises(ToolSchemaError, match="required vocabulary.*not supported"):
		ToolDefinition(
			name="vocabulary",
			description="required vocabulary",
			input_schema={
				"type": "object",
				"$vocabulary": {"https://example.invalid/vocab/custom": True},
			},
		)


def test_schema_payload_size_is_bounded_for_input_and_output_schemas() -> None:
	oversized = {"type": "object", "description": "x" * (256 * 1024 + 1)}
	with pytest.raises(ToolSchemaError, match="schema exceeds.*byte limit"):
		normalize_input_schema(oversized)
	with pytest.raises(ToolSchemaError, match="schema exceeds.*byte limit"):
		normalize_output_schema(oversized)


def test_definition_schema_and_metadata_are_deeply_immutable() -> None:
	definition = ToolDefinition(
		name="immutable",
		description="immutable",
		input_schema={"type": "object", "properties": {"x": {"enum": ["a", "b"]}}},
		metadata={"nested": {"items": [1, 2]}},
		annotations=definition_module.ToolAnnotations(raw={"nested": {"items": [1, 2]}}),
	)
	fingerprint = definition.schema_fingerprint
	with pytest.raises(TypeError):
		definition.input_schema["properties"]["x"]["type"] = "integer"
	with pytest.raises((TypeError, AttributeError)):
		definition.input_schema["properties"]["x"]["enum"].append("c")
	with pytest.raises(TypeError):
		definition.metadata["nested"]["new"] = True
	with pytest.raises((TypeError, AttributeError)):
		definition.annotations.raw["nested"]["items"].append(3)
	assert definition.schema_fingerprint == fingerprint
