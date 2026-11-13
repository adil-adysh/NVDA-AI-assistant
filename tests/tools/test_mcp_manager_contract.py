"""Cross-language smoke test for the prototype's JSON-lines process contract."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def test_rust_manager_json_lines_contract() -> None:
	root = Path(__file__).resolve().parents[2]
	manifest = root / "mcp_client_prototype" / "Cargo.toml"
	metadata = subprocess.run(
		["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1", "--manifest-path", str(manifest)],
		cwd=root,
		capture_output=True,
		text=True,
		check=True,
	)
	metadata_value = json.loads(metadata.stdout)
	cargo_target = Path(metadata_value["target_directory"])
	cargo_target_triple = "x86_64-pc-windows-msvc" if os.name == "nt" else ""
	if os.environ.get("CARGO_BUILD_TARGET"):
		cargo_target_triple = os.environ["CARGO_BUILD_TARGET"]
	debug = cargo_target / cargo_target_triple / "debug" if cargo_target_triple else cargo_target / "debug"
	manager = debug / ("mcp_manager.exe" if os.name == "nt" else "mcp_manager")
	fixture = debug / ("mock_mcp.exe" if os.name == "nt" else "mock_mcp")
	built = subprocess.run(
		["cargo", "build", "--locked", "--features", "fixture-server", "--manifest-path", str(manifest),
			"--bin", "mcp_manager", "--bin", "mock_mcp"],
		cwd=root,
		capture_output=True,
		text=True,
		check=False,
	)
	assert built.returncode == 0, built.stderr
	assert manager.is_file()
	assert fixture.is_file()
	process = subprocess.Popen(
		[manager],
		stdin=subprocess.PIPE,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
		encoding="utf-8",
	)
	assert process.stdin is not None and process.stdout is not None
	pending_responses: dict[str, dict] = {}

	def exchange(message: dict) -> dict:
		process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
		process.stdin.flush()
		return response_for(message["id"])

	def response_for(expected_id: str) -> dict:
		if expected_id in pending_responses:
			return pending_responses.pop(expected_id)
		while True:
			line = process.stdout.readline()
			assert line, "manager closed stdout before replying"
			response = json.loads(line)
			if response.get("id") == expected_id:
				return response
			if isinstance(response.get("id"), str) and response["id"]:
				pending_responses[response["id"]] = response

	try:
		process.stdin.write(json.dumps({"op": "hello", "id": "oversized", "protocol_version": 1})[:-1] + ",\"padding\":\"" + ("x" * (1024 * 1024 + 4)) + "\"}\n")
		process.stdin.flush()
		oversized = json.loads(process.stdout.readline())
		assert oversized["error"]["category"] == "message_too_large"
		hello = exchange({"op": "hello", "id": "hello", "protocol_version": 1})
		assert hello["ok"] is True
		connected = exchange({
			"op": "connect_stdio",
			"id": "connect",
			"server_id": "fixture",
			"executable": str(fixture),
			"args": [],
		})
		assert connected["ok"] is True
		listed = exchange({"op": "list_tools", "id": "list", "server_id": "fixture"})
		echo = next(tool for tool in listed["tools"] if tool["name"] == "echo")
		assert echo["inputSchema"]["type"] == "object"
		invoked = exchange({
			"op": "invoke",
			"id": "invoke",
			"server_id": "fixture",
			"manager_session_id": listed["manager_session_id"],
			"server_incarnation": listed["server_incarnation"],
			"catalog_generation": listed["catalog_generation"],
			"tool_name": "echo",
			"arguments": {"value": {"source": "python"}},
			"timeout_ms": 5000,
		})
		assert invoked["structured_content"] == {
			"value": {"source": "python"},
			"prefix": "stdio:",
		}
		assert invoked["tool_name"] == "echo"

		marker = Path(tempfile.gettempdir()) / f"mcp-manager-{os.getpid()}-{time.time_ns()}.marker"
		slow = {
			"op": "invoke",
			"id": "slow-call",
			"server_id": "fixture",
			"manager_session_id": listed["manager_session_id"],
			"server_incarnation": listed["server_incarnation"],
			"catalog_generation": listed["catalog_generation"],
			"tool_name": "slow",
			"arguments": {"marker_path": str(marker)},
			"timeout_ms": 120000,
		}
		process.stdin.write(json.dumps(slow, separators=(",", ":")) + "\n")
		process.stdin.flush()
		deadline = time.monotonic() + 5
		while not marker.exists() and time.monotonic() < deadline:
			time.sleep(0.01)
		assert marker.exists(), "fixture did not begin the slow tool call"
		cancel = exchange({"op": "cancel", "id": "cancel-request", "target_id": "slow-call"})
		assert cancel["cancellation_requested"] is True
		cancelled_call = response_for("slow-call")
		assert cancelled_call["uncertain"] is True
		assert cancelled_call["error"]["category"] == "cancelled"
		marker.unlink(missing_ok=True)
		shutdown = exchange({"op": "shutdown", "id": "shutdown"})
		assert shutdown["shutdown"] is True
		process.stdin.close()
		assert process.wait(timeout=10) == 0
	finally:
		if process.poll() is None:
			process.kill()
			process.wait(timeout=5)
