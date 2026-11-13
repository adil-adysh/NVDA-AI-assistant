from __future__ import annotations

import pytest

from tests.support.bootstrap import load_addon_module

mcp_config = load_addon_module("config.mcp_servers")
settings = load_addon_module("config.settings")
yaml_store = load_addon_module("config.yaml_store")


def test_mcp_server_config_round_trips_stdio_and_http():
    stdio = mcp_config.McpServerConfig.from_dict({
        "server_id": "local-tools",
        "name": "Local tools",
        "transport": "stdio",
        "enabled": True,
        "command": "C:/tools/server.exe",
        "args": ["--safe"],
    })
    http = mcp_config.McpServerConfig.from_dict({
        "server_id": "web-tools",
        "name": "Web tools",
        "transport": "streamable_http",
        "enabled": False,
        "url": "https://tools.example.test/mcp",
    })

    assert mcp_config.McpServerConfig.from_dict(stdio.to_dict()) == stdio
    assert mcp_config.McpServerConfig.from_dict(http.to_dict()) == http


@pytest.mark.parametrize("url", [
    "http://example.test/mcp",
    "https://user:pass@example.test/mcp",
    "file:///tmp/mcp",
    "https://tools.example.test/mcp#fragment",
    "https://tools.example.test/mcp?token=secret",
])
def test_http_config_rejects_untrusted_endpoint_shapes(url):
    with pytest.raises(ValueError):
        mcp_config.McpServerConfig.from_dict({
            "server_id": "web-tools", "transport": "streamable_http", "url": url,
        })


def test_server_config_rejects_invalid_identity_and_command_arguments():
    with pytest.raises(ValueError, match="server_id"):
        mcp_config.McpServerConfig.from_dict({
            "server_id": "../escape", "transport": "stdio", "command": "tool.exe",
        })
    with pytest.raises(ValueError, match="args"):
        mcp_config.McpServerConfig.from_dict({
            "server_id": "local", "transport": "stdio", "command": "tool.exe", "args": "--unsafe",
        })


def test_mcp_server_configuration_persists_only_validated_records(monkeypatch):
    class Store:
        value = None

        def get(self, _key, default):
            return default if self.value is None else self.value

        def set(self, _key, value):
            self.value = value

    store = Store()
    monkeypatch.setattr(settings, "_config_store", store)
    settings.set_mcp_servers([{
        "server_id": "local", "transport": "stdio", "command": "tool.exe", "args": [],
    }])
    assert settings.get_mcp_servers()[0].server_id == "local"
    with pytest.raises(ValueError):
        settings.set_mcp_servers([{"server_id": "bad/id", "transport": "stdio", "command": "tool.exe"}])
    assert settings.get_mcp_servers()[0].server_id == "local"


def test_mcp_tool_approvals_round_trip_and_reject_non_mcp_ids(monkeypatch):
    class Store:
        value = None

        def get(self, _key, default):
            return default if self.value is None else self.value

        def set(self, _key, value):
            self.value = value

    store = Store()
    monkeypatch.setattr(settings, "_config_store", store)
    settings.set_mcp_approved_tool_ids(["mcp:local:read", "mcp:web:search", "mcp:local:read"])
    assert settings.get_mcp_approved_tool_ids() == frozenset({"mcp:local:read", "mcp:web:search"})
    with pytest.raises(ValueError):
        settings.set_mcp_approved_tool_ids(["native:get_time"])


def test_mcp_bearer_token_is_encrypted_and_reloaded_by_reference(tmp_path, monkeypatch):
    # Collection imports the add-on through many isolated namespaces. Load a
    # single fresh settings/store/DPAPI module graph here so ctypes function
    # signatures cannot retain an older `_DATA_BLOB` class from another test.
    from tests.support.bootstrap import load_addon_module

    isolated_settings = load_addon_module("config.settings", namespace="mcp_secret_test")
    isolated_yaml_store = load_addon_module("config.yaml_store", namespace="mcp_secret_test")
    path = tmp_path / "mcp.yaml"
    monkeypatch.setattr(isolated_settings, "_config_store", isolated_yaml_store.YamlConfigStore(path=path))
    token = "secret-bearer-value"
    isolated_settings.set_mcp_server_token("remote", token)

    persisted = path.read_text(encoding="utf-8")
    assert token not in persisted
    assert "!!enc:" in persisted
    monkeypatch.setattr(isolated_settings, "_config_store", isolated_yaml_store.YamlConfigStore(path=path))
    assert isolated_settings.get_mcp_server_token("remote") == token
