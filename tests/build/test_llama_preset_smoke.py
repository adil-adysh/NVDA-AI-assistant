"""Validate version-1 preset output against the installed llama-server router."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

import pytest

from tests.support import load_addon_module


def test_generated_preset_accepted_by_real_llama_router(tmp_path):
    executable = shutil.which("llama-server")
    if executable is None:
        if os.getenv("NVDA_AI_REQUIRE_LLAMA_TESTS") == "1":
            pytest.fail("Install a supported llama-server for preset compatibility validation")
        pytest.skip("llama-server is not installed")
    # Resolve Scoop's shim so termination always targets the server itself.
    shim = Path(executable).with_suffix(".shim")
    if shim.is_file():
        for line in shim.read_text(encoding="utf-8").splitlines():
            if line.startswith("path = "):
                candidate = Path(line.split("=", 1)[1].strip().strip('"'))
                if candidate.is_file():
                    executable = str(candidate)
                break
    codec_module = load_addon_module("core.llama_preset", namespace="llama_preset_smoke")
    worker_module = load_addon_module("worker.executors.llama", namespace="llama_preset_smoke")
    executor = worker_module.LlamaWorkerExecutor()
    supported = executor.inspect_options(executable)
    assert {"ctx-size", "cache-type-k", "cache-type-v", "flash-attn", "cpu-moe", "n-cpu-moe"} <= supported
    source = tmp_path / "fixture.gguf"
    source.write_bytes(b"GGUF\x03\x00\x00\x00" + bytes(16))
    projector, draft = tmp_path / "mmproj.gguf", tmp_path / "mtp.gguf"
    projector.write_bytes(source.read_bytes())
    draft.write_bytes(source.read_bytes())
    # Router discovery only: explicitly prohibit startup loading and downloads.
    content = codec_module.LlamaPresetCodec().encode([
        {"model_id": "offline-fixture", "kind": "local_file", "source": str(source),
         "preset_options": {"ctx-size": "4096", "cache-type-k": "q8_0", "cache-type-v": "q8_0", "flash-attn": "auto", "n-cpu-moe": "2"},
         "companions": [{"role": "vision", "kind": "local_file", "source": str(projector)},
             {"role": "mtp", "kind": "local_file", "source": str(draft)}]},
    ]).replace("version = 1\n", "version = 1\n\n[*]\nload-on-startup = false\n", 1)
    preset_path = tmp_path / "models.ini"
    preset_path.write_text(content, encoding="utf-8")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    environment = dict(os.environ, LLAMA_CACHE=str(tmp_path / "cache"),
        HF_TOKEN="smoke-test-token", LLAMA_API_KEY="", LLAMA_ARG_HF_REPO="", LLAMA_ARG_MODEL="")
    with (tmp_path / "router.log").open("w+b") as diagnostic:
        process = subprocess.Popen([executable, "--host", "127.0.0.1", "--port", str(port),
            "--models-preset", str(preset_path), "--offline"], env=environment,
            stdout=diagnostic, stderr=diagnostic, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/models", timeout=0.5) as response:
                        payload = json.load(response)
                    assert any(item.get("id") == "offline-fixture" for item in payload["data"]), payload
                    return
                except (OSError, urllib.error.URLError):
                    time.sleep(0.05)
            diagnostic.seek(0)
            pytest.fail(diagnostic.read().decode(errors="replace")[-4000:])
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
