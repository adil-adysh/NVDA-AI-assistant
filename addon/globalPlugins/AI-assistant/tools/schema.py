# -*- coding: utf-8 -*-
"""Dependency-free JSON Schema support for tool definitions.

Why not ``jsonschema``: its native ``rpds-py`` dependency would have to be
vendored into the NVDA add-on and loaded inside NVDA.  This module implements
the draft 2020-12 subset that tool definitions and MCP servers use, preserves
unknown keywords verbatim, and fails with actionable, bounded errors instead of
silently dropping schema information.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

MAX_SCHEMA_DEPTH = 64
MAX_ARGUMENT_DEPTH = 64
MAX_REPORTED_VIOLATIONS = 20

_JSON_TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})
_SCHEMA_MAP_KEYS = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas")
_SCHEMA_LIST_KEYS = ("allOf", "anyOf", "oneOf", "prefixItems")
_NUMERIC_KEYS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf")
_LENGTH_KEYS = ("minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties")


class ToolSchemaError(ValueError):
	"""Raised when a tool schema is structurally invalid."""


@dataclass(frozen=True, slots=True)
class SchemaViolation:
	path: str
	message: str

	def __str__(self) -> str:
		return f"{self.path}: {self.message}"


def clone_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
	"""Return a deep, mutation-isolated copy of a provider-supplied schema."""
	return copy.deepcopy(dict(schema))


def normalize_input_schema(schema: Mapping[str, Any] | None, *, path: str = "inputSchema") -> dict[str, Any]:
	"""Validate and copy an input schema, guaranteeing an object root.

	The returned schema is independent of the caller's dictionary; nested
	objects, arrays, ``$defs``, references and constraints are preserved.
	"""
	if schema is None:
		normalized: dict[str, Any] = {"type": "object", "properties": {}}
		return normalized
	if not isinstance(schema, Mapping):
		raise ToolSchemaError(f"{path}: schema must be a JSON object, got {type(schema).__name__}")
	cloned = copy.deepcopy(dict(schema))
	_validate_schema_node(cloned, path, depth=0, root=cloned)
	_assert_no_ref_cycle(cloned, path)
	root_type = cloned.get("type")
	if root_type is None:
		if any(key in cloned for key in ("$ref", "anyOf", "oneOf", "allOf", "not", "if")):
			raise ToolSchemaError(
				f"{path}: tool input schemas must declare \"type\": \"object\" at the root "
				"(combinators and $ref roots are not supported for tool arguments)"
			)
		cloned["type"] = "object"
	elif root_type != "object":
		raise ToolSchemaError(
			f"{path}: tool input schemas must be objects, got type {root_type!r}"
		)
	if "properties" not in cloned:
		cloned["properties"] = {}
	elif not isinstance(cloned["properties"], Mapping):
		raise ToolSchemaError(f"{path}.properties: must be a JSON object")
	return cloned


def normalize_output_schema(schema: Mapping[str, Any] | None, *, path: str = "outputSchema") -> dict[str, Any] | None:
	"""Validate and copy an optional output schema (any JSON type is allowed)."""
	if schema is None:
		return None
	if not isinstance(schema, Mapping):
		raise ToolSchemaError(f"{path}: schema must be a JSON object, got {type(schema).__name__}")
	cloned = copy.deepcopy(dict(schema))
	_validate_schema_node(cloned, path, depth=0, root=cloned)
	_assert_no_ref_cycle(cloned, path)
	return cloned


def validate_arguments(
	schema: Mapping[str, Any] | None,
	arguments: Any,
	*,
	max_errors: int = MAX_REPORTED_VIOLATIONS,
) -> tuple[SchemaViolation, ...]:
	"""Validate decoded arguments against an input schema.

	Returns bounded, stable violations.  It never mutates the schema or the
	arguments, and never coerces values.
	"""
	if schema is None:
		return ()
	if not isinstance(arguments, Mapping):
		return (SchemaViolation("$", f"arguments must be a JSON object, got {type(arguments).__name__}"),)
	errors: list[SchemaViolation] = []
	_validate_value(
		dict(arguments),
		schema,
		schema,
		"$",
		errors,
		depth=0,
		active_refs=(),
		max_errors=max_errors,
	)
	return tuple(errors[:max_errors])


def format_violations(violations: Sequence[SchemaViolation]) -> str:
	"""Render bounded, actionable argument errors."""
	if not violations:
		return ""
	lines = [str(violation) for violation in violations]
	if len(violations) >= MAX_REPORTED_VIOLATIONS:
		lines.append("… further validation errors omitted")
	return "\n".join(lines)


def serialize_schema(schema: Mapping[str, Any]) -> str:
	"""Deterministic compact JSON used for fingerprints and diagnostics."""
	return json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def schema_fingerprint(schema: Mapping[str, Any]) -> str:
	return hashlib.sha256(serialize_schema(schema).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Schema structure validation
# ---------------------------------------------------------------------------

def _validate_schema_node(schema: Any, path: str, *, depth: int, root: Mapping[str, Any]) -> None:
	if depth > MAX_SCHEMA_DEPTH:
		raise ToolSchemaError(f"{path}: schema nesting exceeds {MAX_SCHEMA_DEPTH} levels")
	if isinstance(schema, bool):
		return
	if not isinstance(schema, Mapping):
		raise ToolSchemaError(f"{path}: schema must be an object or boolean, got {type(schema).__name__}")
	for key in schema:
		if not isinstance(key, str):
			raise ToolSchemaError(f"{path}: schema keywords must be strings, got {key!r}")

	schema_type = schema.get("type")
	if schema_type is not None:
		if isinstance(schema_type, str):
			if schema_type not in _JSON_TYPES:
				raise ToolSchemaError(f"{path}.type: unsupported JSON type {schema_type!r}")
		elif isinstance(schema_type, Sequence) and not isinstance(schema_type, (str, bytes)):
			if not schema_type:
				raise ToolSchemaError(f"{path}.type: type list must not be empty")
			for item in schema_type:
				if not isinstance(item, str) or item not in _JSON_TYPES:
					raise ToolSchemaError(f"{path}.type: unsupported JSON type {item!r}")
		else:
			raise ToolSchemaError(f"{path}.type: must be a string or a list of strings")

	reference = schema.get("$ref")
	if reference is not None:
		if not isinstance(reference, str):
			raise ToolSchemaError(f"{path}.$ref: must be a string")
		if not reference.startswith("#"):
			raise ToolSchemaError(
				f"{path}.$ref: only local references are supported, got {reference!r}"
			)
		_resolve_ref(reference, schema_root=root, path=path, strict=True)

	for key in _SCHEMA_MAP_KEYS:
		value = schema.get(key)
		if value is None:
			continue
		if not isinstance(value, Mapping):
			raise ToolSchemaError(f"{path}.{key}: must be a JSON object")
		for name, subschema in value.items():
			if not isinstance(name, str):
				raise ToolSchemaError(f"{path}.{key}: keys must be strings")
			_validate_schema_node(subschema, f"{path}.{key}[{name!r}]", depth=depth + 1, root=root)

	for key in _SCHEMA_LIST_KEYS:
		value = schema.get(key)
		if value is None:
			continue
		if not isinstance(value, list) or not value:
			raise ToolSchemaError(f"{path}.{key}: must be a non-empty list of schemas")
		for index, subschema in enumerate(value):
			_validate_schema_node(subschema, f"{path}.{key}[{index}]", depth=depth + 1, root=root)

	for key in ("items", "additionalProperties", "propertyNames", "contains", "not", "if", "then", "else"):
		value = schema.get(key)
		if value is None:
			continue
		if key == "items" and isinstance(value, list):
			for index, subschema in enumerate(value):
				_validate_schema_node(subschema, f"{path}.items[{index}]", depth=depth + 1, root=root)
			continue
		_validate_schema_node(value, f"{path}.{key}", depth=depth + 1, root=root)

	required = schema.get("required")
	if required is not None:
		if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
			raise ToolSchemaError(f"{path}.required: must be a list of strings")
		if len(set(required)) != len(required):
			raise ToolSchemaError(f"{path}.required: contains duplicate names")

	enum = schema.get("enum")
	if enum is not None:
		if not isinstance(enum, list) or not enum:
			raise ToolSchemaError(f"{path}.enum: must be a non-empty list")
		if len({serialize_schema({"const": item}) for item in enum}) != len(enum):
			raise ToolSchemaError(f"{path}.enum: contains duplicate values")

	for key in _NUMERIC_KEYS:
		value = schema.get(key)
		if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)):
			raise ToolSchemaError(f"{path}.{key}: must be a number")
	for key in _LENGTH_KEYS:
		value = schema.get(key)
		if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
			raise ToolSchemaError(f"{path}.{key}: must be a non-negative integer")
	for key in ("uniqueItems",):
		value = schema.get(key)
		if value is not None and not isinstance(value, bool):
			raise ToolSchemaError(f"{path}.{key}: must be a boolean")
	pattern = schema.get("pattern")
	if pattern is not None:
		if not isinstance(pattern, str):
			raise ToolSchemaError(f"{path}.pattern: must be a string")
		try:
			re.compile(pattern)
		except re.error as error:
			raise ToolSchemaError(f"{path}.pattern: invalid regular expression: {error}") from error
	format_value = schema.get("format")
	if format_value is not None and not isinstance(format_value, str):
		raise ToolSchemaError(f"{path}.format: must be a string")


def _assert_no_ref_cycle(root: Mapping[str, Any], path: str) -> None:
	def walk(node: Any, chain: tuple[str, ...]) -> None:
		if isinstance(node, bool) or not isinstance(node, Mapping):
			return
		reference = node.get("$ref")
		if isinstance(reference, str):
			if reference in chain:
				raise ToolSchemaError(f"{path}.$ref: circular reference {reference!r} is not supported")
			target = _resolve_ref(reference, schema_root=root, path=path, strict=False)
			if target is not None:
				walk(target, (*chain, reference))
		for key, value in node.items():
			if key == "$ref":
				continue
			if isinstance(value, Mapping):
				walk(value, chain)
			elif isinstance(value, list):
				for item in value:
					walk(item, chain)

	walk(root, ())


def _resolve_ref(reference: str, *, schema_root: Mapping[str, Any], path: str, strict: bool) -> Any:
	fragment = unquote(reference[1:])
	if fragment in ("", "/"):
		return schema_root
	if not fragment.startswith("/"):
		if strict:
			raise ToolSchemaError(f"{path}.$ref: unsupported reference {reference!r}")
		return None
	current: Any = schema_root
	for raw_token in fragment.lstrip("/").split("/"):
		token = raw_token.replace("~1", "/").replace("~0", "~")
		if isinstance(current, Mapping) and token in current:
			current = current[token]
			continue
		if isinstance(current, list) and token.isdigit() and int(token) < len(current):
			current = current[int(token)]
			continue
		if strict:
			raise ToolSchemaError(f"{path}.$ref: unresolved reference {reference!r}")
		return None
	return current


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

def _validate_value(
	value: Any,
	schema: Any,
	root: Mapping[str, Any],
	path: str,
	errors: list[SchemaViolation],
	*,
	depth: int,
	active_refs: tuple[str, ...],
	max_errors: int,
) -> None:
	if len(errors) >= max_errors:
		return
	if depth > MAX_ARGUMENT_DEPTH:
		errors.append(SchemaViolation(path, f"value nesting exceeds {MAX_ARGUMENT_DEPTH} levels"))
		return
	if isinstance(schema, bool):
		if not schema:
			errors.append(SchemaViolation(path, "value is not allowed by a false schema"))
		return
	if not isinstance(schema, Mapping):
		return

	reference = schema.get("$ref")
	if isinstance(reference, str):
		if reference in active_refs:
			errors.append(SchemaViolation(path, f"circular reference {reference!r}"))
			return
		target = _resolve_ref(reference, schema_root=root, path=path, strict=False)
		if target is None:
			errors.append(SchemaViolation(path, f"unresolved schema reference {reference!r}"))
			return
		_validate_value(
			value, target, root, path, errors,
			depth=depth, active_refs=(*active_refs, reference), max_errors=max_errors,
		)
		return

	all_of = schema.get("allOf")
	if isinstance(all_of, list):
		for subschema in all_of:
			_validate_value(value, subschema, root, path, errors, depth=depth + 1,
				active_refs=active_refs, max_errors=max_errors)

	any_of = schema.get("anyOf")
	if isinstance(any_of, list) and not _matches_any(value, any_of, root):
		errors.append(SchemaViolation(path, "value does not match any allowed schema (anyOf)"))

	one_of = schema.get("oneOf")
	if isinstance(one_of, list):
		matches = sum(1 for subschema in one_of if _matches(value, subschema, root))
		if matches != 1:
			errors.append(SchemaViolation(path, f"value must match exactly one schema (oneOf), matched {matches}"))

	not_schema = schema.get("not")
	if isinstance(not_schema, (Mapping, bool)) and _matches(value, not_schema, root):
		errors.append(SchemaViolation(path, "value matches a disallowed schema (not)"))

	if "const" in schema and not _json_equal(value, schema["const"]):
		errors.append(SchemaViolation(path, f"expected constant {schema['const']!r}"))

	enum = schema.get("enum")
	if isinstance(enum, list) and not any(_json_equal(value, item) for item in enum):
		errors.append(SchemaViolation(path, f"value must be one of {enum!r}"))

	expected_types = _declared_types(schema)
	if expected_types and not any(_type_matches(value, item) for item in expected_types):
		errors.append(
			SchemaViolation(path, f"expected type {'/'.join(sorted(expected_types))}, got {_type_name(value)}")
		)
		return

	if isinstance(value, str):
		_validate_string(value, schema, path, errors)
	elif isinstance(value, bool):
		pass
	elif isinstance(value, (int, float)):
		_validate_number(value, schema, path, errors)
	elif isinstance(value, list):
		_validate_array(value, schema, root, path, errors, depth=depth, active_refs=active_refs,
			max_errors=max_errors)
	elif isinstance(value, Mapping):
		_validate_object(value, schema, root, path, errors, depth=depth, active_refs=active_refs,
			max_errors=max_errors)


def _validate_string(value: str, schema: Mapping[str, Any], path: str, errors: list[SchemaViolation]) -> None:
	minimum = schema.get("minLength")
	if isinstance(minimum, int) and len(value) < minimum:
		errors.append(SchemaViolation(path, f"string is shorter than {minimum} characters"))
	maximum = schema.get("maxLength")
	if isinstance(maximum, int) and len(value) > maximum:
		errors.append(SchemaViolation(path, f"string is longer than {maximum} characters"))
	pattern = schema.get("pattern")
	if isinstance(pattern, str):
		try:
			matched = re.search(pattern, value) is not None
		except re.error:
			matched = True
		if not matched:
			errors.append(SchemaViolation(path, f"string does not match pattern {pattern!r}"))


def _validate_number(value: int | float, schema: Mapping[str, Any], path: str, errors: list[SchemaViolation]) -> None:
	minimum = schema.get("minimum")
	if isinstance(minimum, (int, float)) and value < minimum:
		errors.append(SchemaViolation(path, f"value is less than minimum {minimum}"))
	maximum = schema.get("maximum")
	if isinstance(maximum, (int, float)) and value > maximum:
		errors.append(SchemaViolation(path, f"value is greater than maximum {maximum}"))
	exclusive_minimum = schema.get("exclusiveMinimum")
	if isinstance(exclusive_minimum, (int, float)) and value <= exclusive_minimum:
		errors.append(SchemaViolation(path, f"value must be greater than {exclusive_minimum}"))
	exclusive_maximum = schema.get("exclusiveMaximum")
	if isinstance(exclusive_maximum, (int, float)) and value >= exclusive_maximum:
		errors.append(SchemaViolation(path, f"value must be less than {exclusive_maximum}"))
	multiple_of = schema.get("multipleOf")
	if isinstance(multiple_of, (int, float)) and multiple_of > 0:
		quotient = value / multiple_of
		if abs(quotient - round(quotient)) > 1e-9:
			errors.append(SchemaViolation(path, f"value must be a multiple of {multiple_of}"))


def _validate_array(
	value: list[Any],
	schema: Mapping[str, Any],
	root: Mapping[str, Any],
	path: str,
	errors: list[SchemaViolation],
	*,
	depth: int,
	active_refs: tuple[str, ...],
	max_errors: int,
) -> None:
	minimum = schema.get("minItems")
	if isinstance(minimum, int) and len(value) < minimum:
		errors.append(SchemaViolation(path, f"array has fewer than {minimum} items"))
	maximum = schema.get("maxItems")
	if isinstance(maximum, int) and len(value) > maximum:
		errors.append(SchemaViolation(path, f"array has more than {maximum} items"))
	if schema.get("uniqueItems") is True:
		serialized = [serialize_schema({"const": item}) for item in value]
		if len(set(serialized)) != len(serialized):
			errors.append(SchemaViolation(path, "array items must be unique"))

	prefix_items = schema.get("prefixItems")
	item_schema = schema.get("items")
	start = 0
	if isinstance(prefix_items, list):
		for index, subschema in enumerate(prefix_items):
			if index >= len(value):
				break
			_validate_value(value[index], subschema, root, _index_path(path, index), errors,
				depth=depth + 1, active_refs=active_refs, max_errors=max_errors)
		start = len(prefix_items)
	if isinstance(item_schema, Mapping) or isinstance(item_schema, bool):
		for index in range(start, len(value)):
			_validate_value(value[index], item_schema, root, _index_path(path, index), errors,
				depth=depth + 1, active_refs=active_refs, max_errors=max_errors)


def _validate_object(
	value: Mapping[str, Any],
	schema: Mapping[str, Any],
	root: Mapping[str, Any],
	path: str,
	errors: list[SchemaViolation],
	*,
	depth: int,
	active_refs: tuple[str, ...],
	max_errors: int,
) -> None:
	minimum = schema.get("minProperties")
	if isinstance(minimum, int) and len(value) < minimum:
		errors.append(SchemaViolation(path, f"object has fewer than {minimum} properties"))
	maximum = schema.get("maxProperties")
	if isinstance(maximum, int) and len(value) > maximum:
		errors.append(SchemaViolation(path, f"object has more than {maximum} properties"))

	properties = schema.get("properties")
	properties = properties if isinstance(properties, Mapping) else {}
	required = schema.get("required")
	required = required if isinstance(required, list) else []
	for name in required:
		if isinstance(name, str) and name not in value:
			errors.append(SchemaViolation(_property_path(path, name), "required property is missing"))

	pattern_properties = schema.get("patternProperties")
	pattern_properties = pattern_properties if isinstance(pattern_properties, Mapping) else {}
	additional = schema.get("additionalProperties", True)
	known = set(name for name in properties if isinstance(name, str))
	matched_by_pattern: set[str] = set()

	for name, item in value.items():
		property_path = _property_path(path, name)
		handled = False
		if name in properties:
			_validate_value(item, properties[name], root, property_path, errors, depth=depth + 1,
				active_refs=active_refs, max_errors=max_errors)
			handled = True
		for pattern, subschema in pattern_properties.items():
			try:
				pattern_matches = isinstance(name, str) and re.search(pattern, name) is not None
			except re.error:
				pattern_matches = False
			if pattern_matches:
				matched_by_pattern.add(name)
				_validate_value(item, subschema, root, property_path, errors, depth=depth + 1,
					active_refs=active_refs, max_errors=max_errors)
				handled = True
		if handled or name in known or name in matched_by_pattern:
			continue
		if additional is False:
			errors.append(SchemaViolation(property_path, "additional properties are not allowed"))
		elif isinstance(additional, (Mapping, bool)):
			_validate_value(item, additional, root, property_path, errors, depth=depth + 1,
				active_refs=active_refs, max_errors=max_errors)


def _declared_types(schema: Mapping[str, Any]) -> tuple[str, ...]:
	declared = schema.get("type")
	if isinstance(declared, str):
		return (declared,)
	if isinstance(declared, list):
		return tuple(item for item in declared if isinstance(item, str))
	return ()


def _type_matches(value: Any, expected: str) -> bool:
	if expected == "object":
		return isinstance(value, Mapping)
	if expected == "array":
		return isinstance(value, list)
	if expected == "string":
		return isinstance(value, str)
	if expected == "number":
		return isinstance(value, (int, float)) and not isinstance(value, bool)
	if expected == "integer":
		return isinstance(value, int) and not isinstance(value, bool)
	if expected == "boolean":
		return isinstance(value, bool)
	if expected == "null":
		return value is None
	return False


def _type_name(value: Any) -> str:
	if value is None:
		return "null"
	if isinstance(value, bool):
		return "boolean"
	if isinstance(value, int):
		return "integer"
	if isinstance(value, float):
		return "number"
	if isinstance(value, str):
		return "string"
	if isinstance(value, list):
		return "array"
	if isinstance(value, Mapping):
		return "object"
	return type(value).__name__


def _json_equal(left: Any, right: Any) -> bool:
	if isinstance(left, bool) or isinstance(right, bool):
		return isinstance(left, bool) and isinstance(right, bool) and left == right
	if isinstance(left, (int, float)) and isinstance(right, (int, float)):
		return left == right
	if type(left) is not type(right):
		return False
	if isinstance(left, Mapping) and isinstance(right, Mapping):
		return set(left.keys()) == set(right.keys()) and all(
			_json_equal(left[key], right[key]) for key in left
		)
	if isinstance(left, list):
		return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
	return left == right


def _matches(value: Any, schema: Any, root: Mapping[str, Any]) -> bool:
	trial: list[SchemaViolation] = []
	_validate_value(value, schema, root, "$", trial, depth=0, active_refs=(), max_errors=1)
	return not trial


def _matches_any(value: Any, schemas: Sequence[Any], root: Mapping[str, Any]) -> bool:
	return any(_matches(value, schema, root) for schema in schemas)


def _property_path(path: str, name: Any) -> str:
	if isinstance(name, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
		return f"{path}.{name}"
	return f"{path}[{name!r}]"


def _index_path(path: str, index: int) -> str:
	return f"{path}[{index}]"
