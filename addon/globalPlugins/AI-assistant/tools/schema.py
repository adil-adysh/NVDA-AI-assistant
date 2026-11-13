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
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import math
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from urllib.parse import unquote

MAX_SCHEMA_DEPTH = 64
MAX_SCHEMA_BYTES = 256 * 1024
MAX_ARGUMENT_DEPTH = 64
MAX_REPORTED_VIOLATIONS = 20

_JSON_TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})
_SCHEMA_MAP_KEYS = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas")
_SCHEMA_LIST_KEYS = ("allOf", "anyOf", "oneOf")
_NUMERIC_KEYS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf")
_LENGTH_KEYS = (
	"minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties",
	"minContains", "maxContains",
)
_UNSUPPORTED_ASSERTIONS = frozenset({"unevaluatedProperties", "unevaluatedItems", "$dynamicRef", "$dynamicAnchor"})
MAX_REGEX_PATTERN_CHARS = 512
MAX_REGEX_INPUT_CHARS = 8192
_SUPPORTED_SCHEMA_URIS = frozenset({
	"https://json-schema.org/draft/2020-12/schema",
	"http://json-schema.org/draft/2020-12/schema",
})


class FrozenList(tuple[Any, ...]):
	"""Immutable JSON array with list-compatible equality for public schemas."""

	def __new__(cls, items: Any = ()) -> "FrozenList":
		return super().__new__(cls, items)

	def __eq__(self, other: object) -> bool:
		if isinstance(other, (list, tuple)):
			return tuple.__eq__(self, tuple(other))
		return NotImplemented

	__hash__ = None


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
	return thaw_json(schema)


def freeze_json(value: Any) -> Any:
	"""Recursively freeze JSON-like values used by published tool definitions."""
	if isinstance(value, Mapping):
		if not all(isinstance(key, str) for key in value):
			raise TypeError("JSON object keys must be strings")
		return MappingProxyType({key: freeze_json(item) for key, item in value.items()})
	if isinstance(value, (list, tuple)):
		return FrozenList(freeze_json(item) for item in value)
	if value is None or isinstance(value, (bool, str, int)):
		return value
	if isinstance(value, float) and math.isfinite(value):
		return value
	raise TypeError(f"value of type {type(value).__name__} is not JSON data")


def thaw_json(value: Any) -> Any:
	"""Copy frozen JSON-like mappings/sequences into ordinary dicts/lists."""
	if isinstance(value, Mapping):
		return {key: thaw_json(item) for key, item in value.items()}
	if isinstance(value, (list, tuple)):
		return [thaw_json(item) for item in value]
	return copy.deepcopy(value)


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
	_validate_schema_payload_size(schema, path)
	cloned = thaw_json(schema)
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


def normalize_output_schema(
	schema: Mapping[str, Any] | bool | None,
	*,
	path: str = "outputSchema",
) -> dict[str, Any] | bool | None:
	"""Validate and copy an optional output schema (any JSON type is allowed)."""
	if schema is None:
		return None
	if isinstance(schema, bool):
		return schema
	if not isinstance(schema, Mapping):
		raise ToolSchemaError(f"{path}: schema must be a JSON object, got {type(schema).__name__}")
	_validate_schema_payload_size(schema, path)
	cloned = thaw_json(schema)
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
	return json.dumps(thaw_json(schema), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
	for keyword in _UNSUPPORTED_ASSERTIONS.intersection(schema):
		raise ToolSchemaError(
			f"{path}.{keyword}: this assertion is not supported by the tool validator; "
			"remove it or use supported constraints"
		)
	if depth == 0 and "$schema" in schema:
		dialect = schema["$schema"]
		if not isinstance(dialect, str):
			raise ToolSchemaError(f"{path}.$schema: must be a string naming the Draft 2020-12 dialect")
		if dialect.removesuffix("#") not in _SUPPORTED_SCHEMA_URIS:
			raise ToolSchemaError(
				f"{path}.$schema: only JSON Schema Draft 2020-12 is supported, got {dialect!r}"
			)
	if "$vocabulary" in schema:
		vocabulary = schema["$vocabulary"]
		if not isinstance(vocabulary, Mapping):
			raise ToolSchemaError(f"{path}.$vocabulary: must be a JSON object")
		for vocabulary_uri, required in vocabulary.items():
			if not isinstance(vocabulary_uri, str) or not isinstance(required, bool):
				raise ToolSchemaError(f"{path}.$vocabulary: expected string URIs and boolean values")
			if required:
				raise ToolSchemaError(
					f"{path}.$vocabulary: required vocabulary {vocabulary_uri!r} is not supported"
				)

	schema_type = schema.get("type")
	if "type" in schema:
		if isinstance(schema_type, str):
			if schema_type not in _JSON_TYPES:
				raise ToolSchemaError(f"{path}.type: unsupported JSON type {schema_type!r}")
		elif isinstance(schema_type, Sequence) and not isinstance(schema_type, (str, bytes)):
			if not schema_type:
				raise ToolSchemaError(f"{path}.type: type list must not be empty")
			for item in schema_type:
				if not isinstance(item, str) or item not in _JSON_TYPES:
					raise ToolSchemaError(f"{path}.type: unsupported JSON type {item!r}")
			if len(set(schema_type)) != len(schema_type):
				raise ToolSchemaError(f"{path}.type: type list contains duplicates")
		else:
			raise ToolSchemaError(f"{path}.type: must be a string or a list of strings")

	reference = schema.get("$ref")
	if "$ref" in schema:
		if not isinstance(reference, str):
			raise ToolSchemaError(f"{path}.$ref: must be a string")
		if not reference.startswith("#"):
			raise ToolSchemaError(
				f"{path}.$ref: only local references are supported, got {reference!r}"
			)
		_resolve_ref(reference, schema_root=root, path=path, strict=True)

	for key in _SCHEMA_MAP_KEYS:
		if key not in schema:
			continue
		value = schema[key]
		if not isinstance(value, Mapping):
			raise ToolSchemaError(f"{path}.{key}: must be a JSON object")
		for name, subschema in value.items():
			if not isinstance(name, str):
				raise ToolSchemaError(f"{path}.{key}: keys must be strings")
			_validate_schema_node(subschema, f"{path}.{key}[{name!r}]", depth=depth + 1, root=root)

	for key in _SCHEMA_LIST_KEYS:
		if key not in schema:
			continue
		value = schema[key]
		if not isinstance(value, (list, tuple)) or not value:
			raise ToolSchemaError(f"{path}.{key}: must be a non-empty list of schemas")
		for index, subschema in enumerate(value):
			_validate_schema_node(subschema, f"{path}.{key}[{index}]", depth=depth + 1, root=root)
	if "prefixItems" in schema:
		prefix_items = schema["prefixItems"]
		if not isinstance(prefix_items, (list, tuple)):
			raise ToolSchemaError(f"{path}.prefixItems: must be an array of schemas")
		for index, subschema in enumerate(prefix_items):
			_validate_schema_node(subschema, f"{path}.prefixItems[{index}]", depth=depth + 1, root=root)

	for key in ("items", "additionalProperties", "propertyNames", "contains", "not", "if", "then", "else"):
		if key not in schema:
			continue
		value = schema[key]
		if key == "items" and isinstance(value, (list, tuple)):
			raise ToolSchemaError(f"{path}.items: Draft 2020-12 requires a single schema; use prefixItems for tuples")
		_validate_schema_node(value, f"{path}.{key}", depth=depth + 1, root=root)

	dependent_required = schema.get("dependentRequired")
	if "dependentRequired" in schema:
		if not isinstance(dependent_required, Mapping):
			raise ToolSchemaError(f"{path}.dependentRequired: must be a JSON object")
		for name, dependencies in dependent_required.items():
			if not isinstance(name, str) or not isinstance(dependencies, (list, tuple)) or not all(isinstance(item, str) for item in dependencies):
				raise ToolSchemaError(f"{path}.dependentRequired: values must be arrays of strings")
			if len(set(dependencies)) != len(dependencies):
				raise ToolSchemaError(f"{path}.dependentRequired[{name!r}]: contains duplicate names")

	required = schema.get("required")
	if "required" in schema:
		if not isinstance(required, (list, tuple)) or not all(isinstance(item, str) for item in required):
			raise ToolSchemaError(f"{path}.required: must be a list of strings")
		if len(set(required)) != len(required):
			raise ToolSchemaError(f"{path}.required: contains duplicate names")

	enum = schema.get("enum")
	if "enum" in schema:
		if not isinstance(enum, (list, tuple)) or not enum:
			raise ToolSchemaError(f"{path}.enum: must be a non-empty list")
		if len({serialize_schema({"const": item}) for item in enum}) != len(enum):
			raise ToolSchemaError(f"{path}.enum: contains duplicate values")

	for key in _NUMERIC_KEYS:
		if key not in schema:
			continue
		value = schema[key]
		if (
			not isinstance(value, (int, float)) or isinstance(value, bool)
			or (isinstance(value, float) and not math.isfinite(value))
		):
			raise ToolSchemaError(f"{path}.{key}: must be a number")
		if key == "multipleOf" and value <= 0:
			raise ToolSchemaError(f"{path}.multipleOf: must be greater than zero")
	for key in _LENGTH_KEYS:
		if key not in schema:
			continue
		value = schema[key]
		if not isinstance(value, int) or isinstance(value, bool) or value < 0:
			raise ToolSchemaError(f"{path}.{key}: must be a non-negative integer")
	for key in ("uniqueItems",):
		if key in schema and not isinstance(schema[key], bool):
			raise ToolSchemaError(f"{path}.{key}: must be a boolean")
	pattern = schema.get("pattern")
	if "pattern" in schema:
		_validate_pattern(pattern, f"{path}.pattern")
	pattern_properties = schema.get("patternProperties")
	if isinstance(pattern_properties, Mapping):
		for pattern in pattern_properties:
			_validate_pattern(pattern, f"{path}.patternProperties[{pattern!r}]")
	format_value = schema.get("format")
	if "format" in schema and not isinstance(format_value, str):
		raise ToolSchemaError(f"{path}.format: must be a string")


def _validate_schema_payload_size(schema: Mapping[str, Any], path: str) -> None:
	"""Reject oversized/cyclic/non-JSON schema data before copying it."""
	used = 0
	active: set[int] = set()

	def charge(amount: int) -> None:
		nonlocal used
		used += amount
		if used > MAX_SCHEMA_BYTES:
			raise ToolSchemaError(
				f"{path}: schema exceeds the {MAX_SCHEMA_BYTES}-byte limit"
			)

	def encoded_length(value: Any) -> int:
		try:
			return len(
				json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
			)
		except (TypeError, ValueError, OverflowError) as error:
			raise ToolSchemaError(f"{path}: schema must contain only finite JSON values") from error

	def visit(value: Any, depth: int) -> None:
		if depth > MAX_SCHEMA_DEPTH:
			raise ToolSchemaError(f"{path}: schema nesting exceeds {MAX_SCHEMA_DEPTH} levels")
		if isinstance(value, Mapping):
			identity = id(value)
			if identity in active:
				raise ToolSchemaError(f"{path}: schema contains a cycle")
			active.add(identity)
			charge(2)
			for index, (key, child) in enumerate(value.items()):
				if not isinstance(key, str):
					raise ToolSchemaError(f"{path}: schema object keys must be strings")
				charge(encoded_length(key) + 1 + int(index > 0))
				visit(child, depth + 1)
			active.remove(identity)
		elif isinstance(value, (list, tuple)):
			identity = id(value)
			if identity in active:
				raise ToolSchemaError(f"{path}: schema contains a cycle")
			active.add(identity)
			charge(2)
			for index, child in enumerate(value):
				charge(int(index > 0))
				visit(child, depth + 1)
			active.remove(identity)
		else:
			charge(encoded_length(value))

	visit(schema, 0)


def _validate_pattern(pattern: Any, path: str) -> None:
	if not isinstance(pattern, str):
		raise ToolSchemaError(f"{path}: must be a string")
	if len(pattern) > MAX_REGEX_PATTERN_CHARS:
		raise ToolSchemaError(f"{path}: regular expression exceeds {MAX_REGEX_PATTERN_CHARS} characters")
	try:
		re.compile(pattern)
	except re.error as error:
		raise ToolSchemaError(f"{path}: invalid regular expression: {error}") from error
	if not _is_safe_regex(pattern):
		raise ToolSchemaError(
			f"{path}: unsafe regular expression; nested repetition, ambiguous repeated groups, "
			"backreferences, lookarounds, and excessive bounded repetition are not supported"
		)


def _is_safe_regex(pattern: str) -> bool:
	"""Conservatively accept a bounded subset of Python/ECMA-style patterns.

	At most one quantifier may be unbounded. It cannot be combined with other
	quantifiers because Python's backtracking engine can otherwise revisit
	ambiguous partitions for each search position. Bounded quantifiers have a
	small aggregate work ceiling; ambiguous repeated groups are rejected.
	Runtime matching also caps pattern and candidate string lengths.
	"""
	stack: list[dict[str, bool]] = []
	in_class = False
	escaped = False
	last_group_risky = False
	unbounded_count = 0
	quantifier_count = 0
	bounded_work = 1
	index = 0
	while index < len(pattern):
		char = pattern[index]
		if escaped:
			if char.isdigit() or char in {"g", "k"}:
				return False
			escaped = False
			last_group_risky = False
		elif char == "\\":
			escaped = True
		elif in_class:
			if char == "]":
				in_class = False
			last_group_risky = False
		elif char == "[":
			in_class = True
			last_group_risky = False
		elif char == "(" :
			if index + 1 < len(pattern) and pattern[index + 1] == "?":
				return False
			stack.append({"repeat": False, "alternate": False})
			last_group_risky = False
		elif char == "|":
			if stack:
				stack[-1]["alternate"] = True
			last_group_risky = False
		elif char == ")":
			if not stack:
				return False
			group = stack.pop()
			last_group_risky = group["repeat"] or group["alternate"]
			if stack and last_group_risky:
				stack[-1]["repeat"] = True
		elif char in "*+?{":
			if char == "{":
				match = re.match(r"\{(\d+)(?:,(\d*)?)?\}", pattern[index:])
				if match is None:
					last_group_risky = False
					index += 1
					continue
				upper = match.group(2)
				if "," in match.group(0) and upper == "":
					unbounded_count += 1
				else:
					low = int(match.group(1))
					max_value = int(upper) if upper is not None else low
					if max_value > 256:
						return False
					bounded_work *= max(1, max_value - low + 1)
					quantifier_count += 1
				index += len(match.group(0)) - 1
			elif char in "*+":
				unbounded_count += 1
			else:
				bounded_work *= 2
				quantifier_count += 1
			if bounded_work > 256 or quantifier_count > 8:
				return False
			if last_group_risky:
				return False
			if stack:
				stack[-1]["repeat"] = True
			last_group_risky = False
		else:
			last_group_risky = False
		index += 1
	return (
		not escaped
		and not in_class
		and not stack
		and unbounded_count <= 1
		and not (unbounded_count and quantifier_count)
	)


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

	all_of = schema.get("allOf")
	if isinstance(all_of, (list, tuple)):
		for subschema in all_of:
			_validate_value(value, subschema, root, path, errors, depth=depth + 1,
				active_refs=active_refs, max_errors=max_errors)

	any_of = schema.get("anyOf")
	if isinstance(any_of, (list, tuple)) and not _matches_any(value, any_of, root):
		errors.append(SchemaViolation(path, "value does not match any allowed schema (anyOf)"))

	one_of = schema.get("oneOf")
	if isinstance(one_of, (list, tuple)):
		matches = sum(1 for subschema in one_of if _matches(value, subschema, root))
		if matches != 1:
			errors.append(SchemaViolation(path, f"value must match exactly one schema (oneOf), matched {matches}"))

	not_schema = schema.get("not")
	if isinstance(not_schema, (Mapping, bool)) and _matches(value, not_schema, root):
		errors.append(SchemaViolation(path, "value matches a disallowed schema (not)"))

	if "const" in schema and not _json_equal(value, schema["const"]):
		errors.append(SchemaViolation(path, f"expected constant {schema['const']!r}"))

	enum = schema.get("enum")
	if isinstance(enum, (list, tuple)) and not any(_json_equal(value, item) for item in enum):
		errors.append(SchemaViolation(path, f"value must be one of {enum!r}"))

	expected_types = _declared_types(schema)
	if expected_types and not any(_type_matches(value, item) for item in expected_types):
		errors.append(
			SchemaViolation(path, f"expected type {'/'.join(sorted(expected_types))}, got {_type_name(value)}")
		)
		return
	if "if" in schema:
		branch = "then" if _matches(value, schema["if"], root) else "else"
		if branch in schema:
			_validate_value(value, schema[branch], root, path, errors, depth=depth + 1,
				active_refs=active_refs, max_errors=max_errors)

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
		if len(value) > MAX_REGEX_INPUT_CHARS:
			errors.append(SchemaViolation(path, f"string exceeds regex input limit of {MAX_REGEX_INPUT_CHARS} characters"))
			return
		try:
			matched = re.search(pattern, value) is not None
		except re.error as error:
			errors.append(SchemaViolation(path, f"invalid regular expression: {error}"))
			return
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
		try:
			if Fraction(Decimal(str(value))) % Fraction(Decimal(str(multiple_of))) != 0:
				errors.append(SchemaViolation(path, f"value must be a multiple of {multiple_of}"))
		except (InvalidOperation, ValueError):
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
		keys = [_json_key(item) for item in value]
		if len(set(keys)) != len(keys):
			errors.append(SchemaViolation(path, "array items must be unique"))
	contains = schema.get("contains")
	if isinstance(contains, (Mapping, bool)):
		match_count = sum(1 for item in value if _matches(item, contains, root))
		minimum_contains = schema.get("minContains", 1)
		maximum_contains = schema.get("maxContains")
		if match_count < minimum_contains:
			errors.append(SchemaViolation(path, f"array has fewer than {minimum_contains} matching items (contains)"))
		if isinstance(maximum_contains, int) and match_count > maximum_contains:
			errors.append(SchemaViolation(path, f"array has more than {maximum_contains} matching items (contains)"))

	prefix_items = schema.get("prefixItems")
	item_schema = schema.get("items")
	start = 0
	if isinstance(prefix_items, (list, tuple)):
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
	required = required if isinstance(required, (list, tuple)) else []
	for name in required:
		if isinstance(name, str) and name not in value:
			errors.append(SchemaViolation(_property_path(path, name), "required property is missing"))
	dependent_required = schema.get("dependentRequired")
	if isinstance(dependent_required, Mapping):
		for name, dependencies in dependent_required.items():
			if name in value and isinstance(dependencies, (list, tuple)):
				for dependency in dependencies:
					if dependency not in value:
						errors.append(SchemaViolation(_property_path(path, dependency), f"required by property {name!r}"))
	dependent_schemas = schema.get("dependentSchemas")
	if isinstance(dependent_schemas, Mapping):
		for name, subschema in dependent_schemas.items():
			if name in value:
				_validate_value(value, subschema, root, path, errors, depth=depth + 1,
					active_refs=active_refs, max_errors=max_errors)
	property_names = schema.get("propertyNames")
	if isinstance(property_names, (Mapping, bool)):
		for name in value:
			name_path = f"{path}.<propertyName:{name}>"
			_validate_value(name, property_names, root, name_path, errors, depth=depth + 1,
				active_refs=active_refs, max_errors=max_errors)

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
			if len(name) > MAX_REGEX_INPUT_CHARS:
				errors.append(SchemaViolation(property_path, f"property name exceeds regex input limit of {MAX_REGEX_INPUT_CHARS} characters"))
				continue
			try:
				pattern_matches = isinstance(name, str) and re.search(pattern, name) is not None
			except re.error as error:
				errors.append(SchemaViolation(property_path, f"invalid regular expression: {error}"))
				continue
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
	if isinstance(declared, Sequence) and not isinstance(declared, (str, bytes)):
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
		return (
			isinstance(value, int) and not isinstance(value, bool)
			or isinstance(value, float) and math.isfinite(value) and value.is_integer()
		)
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
	if isinstance(left, Mapping) and isinstance(right, Mapping):
		return set(left.keys()) == set(right.keys()) and all(
			_json_equal(left[key], right[key]) for key in left
		)
	if isinstance(left, (list, tuple)) or isinstance(right, (list, tuple)):
		if not isinstance(left, (list, tuple)) or not isinstance(right, (list, tuple)):
			return False
		return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
	if type(left) is not type(right):
		return False
	return left == right


def _json_key(value: Any) -> Any:
	"""Return a hashable JSON identity key using mathematical number equality."""
	if value is None:
		return ("null",)
	if isinstance(value, bool):
		return ("boolean", value)
	if isinstance(value, (int, float)):
		try:
			return ("number", Fraction(Decimal(str(value))))
		except (InvalidOperation, ValueError, OverflowError):
			return ("number", repr(value))
	if isinstance(value, str):
		return ("string", value)
	if isinstance(value, Mapping):
		return ("object", tuple(sorted((key, _json_key(item)) for key, item in value.items())))
	if isinstance(value, (list, tuple)):
		return ("array", tuple(_json_key(item) for item in value))
	return (type(value).__name__, repr(value))


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
