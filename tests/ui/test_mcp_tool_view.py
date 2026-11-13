"""Pure tests for MCP tool search, filters, and bulk-approval eligibility."""

from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

from tests.support import load_addon_module

view = load_addon_module("ui.mcp_tool_view")


def _tool(
	name: str,
	description: str,
	*,
	title: str | None = None,
	read_only: bool | None = None,
	destructive: bool | None = None,
) -> SimpleNamespace:
	return SimpleNamespace(
		name=name,
		provider_tool_name=name,
		display_title=title,
		description=description,
		tool_id=f"mcp:mcp:server:{name}",
		annotations=SimpleNamespace(read_only_hint=read_only, destructive_hint=destructive),
		input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
		metadata={"server_id": "server"},
	)


def test_search_matches_name_title_and_description_words() -> None:
	tools = [
		_tool("health_snapshot", "Collect a health summary"),
		_tool("search_logs", "Search native logs"),
		_tool("dismiss", "Leave a dialog"),
	]
	assert [tool.name for tool in view.visible_definitions(tools, set(), "health")] == ["health_snapshot"]
	assert [tool.name for tool in view.visible_definitions(tools, set(), "log")] == ["search_logs"]
	# "log" is a substring of "dialog" but not a word there.
	assert [tool.name for tool in view.visible_definitions(tools, set(), "dialog")] == ["dismiss"]


def test_approval_and_read_only_filters() -> None:
	tools = [
		_tool("read_a", "Read A", read_only=True),
		_tool("read_b", "Read B", read_only=True),
		_tool("write_c", "Write C", read_only=False, destructive=True),
	]
	approved = {"mcp:mcp:server:read_a"}
	assert [tool.name for tool in view.visible_definitions(tools, approved, "", view.FILTER_APPROVED)] == [
		"read_a"
	]
	assert [tool.name for tool in view.visible_definitions(tools, approved, "", view.FILTER_DENIED)] == [
		"read_b",
		"write_c",
	]
	assert [tool.name for tool in view.visible_definitions(tools, approved, "", view.FILTER_READ_ONLY)] == [
		"read_a",
		"read_b",
	]


def test_bulk_approval_excludes_approved_and_destructive_tools() -> None:
	tools = [
		_tool("read_a", "Read A", read_only=True),
		_tool("read_b", "Read B", read_only=True),
		_tool("both_hints", "Conflicting hints", read_only=True, destructive=True),
		_tool("write_c", "Write C", read_only=False),
	]
	approved = {"mcp:mcp:server:read_a"}
	assert [tool.name for tool in view.unapproved_read_only(tools, approved)] == ["read_b"]


def test_details_keep_the_full_description_and_schema() -> None:
	description = "First line.\nSecond line with detail. " + "x" * 500
	tool = _tool("sample", description, title="Diagnostics · Sample", read_only=True)
	text = view.details_text(tool, False)
	assert "Diagnostics · Sample" in text
	assert "Second line with detail." in text
	assert '"query"' in text
	assert "Status: denied" in text
	assert "Read-only claim: yes" in text


def test_details_accept_the_frozen_schema_used_by_tool_definitions() -> None:
	tool = _tool("frozen", "Frozen schema")
	tool.input_schema = MappingProxyType(
		{
			"type": "object",
			"properties": MappingProxyType({"query": MappingProxyType({"type": "string"})}),
		}
	)
	text = view.details_text(tool, False)
	assert '"query": {' in text
	assert "mappingproxy" not in text


def test_safe_text_bounds_untrusted_text() -> None:
	assert view.safe_text("a\nb\tc", 3) == "a b"
	assert view.safe_text(None) == ""
