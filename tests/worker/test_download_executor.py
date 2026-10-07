# -*- coding: utf-8 -*-
"""Unit and integration tests for Worker download, verify, and unpack executors."""

from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import threading
import time
from typing import Any
import zipfile

import pytest

from tests.support import load_addon_module

cancellation_mod = load_addon_module("core.job.cancellation")
client_mod = load_addon_module("core.job.client")
dto_mod = load_addon_module("core.job.dto")
interfaces_mod = load_addon_module("providers.interfaces")
dl_client_mod = load_addon_module("providers.runtime.download_client")
model_dl_mod = load_addon_module("providers.runtime.model_download")
download_exec_mod = load_addon_module("worker.executors.download")
model_dl_job_mod = load_addon_module("worker.executors.model_download_job")
unpack_mod = load_addon_module("worker.executors.unpack")
verify_mod = load_addon_module("worker.executors.verify")

CancellationToken = cancellation_mod.CancellationToken
MockJobClient = client_mod.MockJobClient
JobProgress = dto_mod.JobProgress
JobResult = dto_mod.JobResult
JobSpec = dto_mod.JobSpec
JobStatus = dto_mod.JobStatus
DownloadCancelledError = interfaces_mod.DownloadCancelledError
WorkerDownloadClient = dl_client_mod.WorkerDownloadClient
ModelDownloadError = model_dl_mod.ModelDownloadError
OperationCancelledError = download_exec_mod.OperationCancelledError
stream_download = download_exec_mod.stream_download
execute_model_download_job = model_dl_job_mod.execute_model_download_job
execute_runtime_download_job = model_dl_job_mod.execute_runtime_download_job
UnpackError = unpack_mod.UnpackError
unpack_zip = unpack_mod.unpack_zip
ChecksumMismatchError = verify_mod.ChecksumMismatchError
stream_sha256 = verify_mod.stream_sha256


class RangeTestingHTTPHandler(BaseHTTPRequestHandler):
	"""Local test HTTP server supporting GET, Range requests, and chunked transfer."""

	payload_data = b"0123456789" * 10000  # 100 KB payload

	def log_message(self, format: str, *args: Any) -> None:
		pass  # Silence stderr logging

	def do_GET(self) -> None:
		total_len = len(self.payload_data)
		range_hdr = self.headers.get("Range")

		if range_hdr and range_hdr.startswith("bytes="):
			parts = range_hdr[6:].split("-")
			start = int(parts[0]) if parts[0] else 0
			end = int(parts[1]) if parts[1] else total_len - 1
			end = min(end, total_len - 1)
			length = end - start + 1

			self.send_response(206)
			self.send_header("Content-Type", "application/octet-stream")
			self.send_header("Content-Range", f"bytes {start}-{end}/{total_len}")
			self.send_header("Content-Length", str(length))
			self.end_headers()
			self.wfile.write(self.payload_data[start : end + 1])
		else:
			self.send_response(200)
			self.send_header("Content-Type", "application/octet-stream")
			self.send_header("Content-Length", str(total_len))
			self.end_headers()
			self.wfile.write(self.payload_data)


@pytest.fixture(scope="module")
def local_http_server():
	"""Spawn local in-process HTTP server on loopback with random port."""
	server = HTTPServer(("127.0.0.1", 0), RangeTestingHTTPHandler)
	port = server.server_port
	t = threading.Thread(target=server.serve_forever, daemon=True)
	t.start()
	yield f"http://127.0.0.1:{port}"
	server.shutdown()
	server.server_close()


def test_stream_download_basic(local_http_server: str, tmp_path: Path):
	dest = tmp_path / "test_download.bin"
	progress_updates: list[tuple[int, int]] = []

	def on_prog(done: int, total: int, speed: float, eta: float | None) -> None:
		progress_updates.append((done, total))

	bytes_written = stream_download(
		f"{local_http_server}/test.bin",
		dest,
		on_progress=on_prog,
		chunk_size=16384,
	)

	assert bytes_written == len(RangeTestingHTTPHandler.payload_data)
	assert dest.read_bytes() == RangeTestingHTTPHandler.payload_data
	assert len(progress_updates) > 0


def test_stream_download_range_resume(local_http_server: str, tmp_path: Path):
	dest = tmp_path / "test_resume.bin"
	# Pre-seed 30,000 bytes
	seed_bytes = RangeTestingHTTPHandler.payload_data[:30000]
	dest.write_bytes(seed_bytes)

	bytes_written = stream_download(
		f"{local_http_server}/test.bin",
		dest,
		resume_from=30000,
		chunk_size=16384,
	)

	assert bytes_written == len(RangeTestingHTTPHandler.payload_data)
	assert dest.read_bytes() == RangeTestingHTTPHandler.payload_data


def test_stream_download_cancellation(local_http_server: str, tmp_path: Path):
	dest = tmp_path / "test_cancel.bin"
	token = CancellationToken("job-cancel")
	token.cancel()

	with pytest.raises(OperationCancelledError):
		stream_download(
			f"{local_http_server}/test.bin",
			dest,
			cancel_token=token,
		)


def test_stream_sha256_verify_success_and_mismatch(tmp_path: Path):
	file_path = tmp_path / "test_hash.bin"
	data = b"Arbitrary test data for SHA-256 verification" * 1000
	file_path.write_bytes(data)
	expected_hash = hashlib.sha256(data).hexdigest()

	# Success
	computed = stream_sha256(file_path, expected_sha256=expected_hash, chunk_size=1024)
	assert computed == expected_hash

	# Mismatch
	with pytest.raises(ChecksumMismatchError):
		stream_sha256(
			file_path,
			expected_sha256="0000000000000000000000000000000000000000000000000000000000000000",
		)

	# Cancellation
	token = CancellationToken("job-cancel-hash")
	token.cancel()
	with pytest.raises(OperationCancelledError):
		stream_sha256(file_path, cancel_token=token)


def test_unpack_zip_safe_and_atomic(tmp_path: Path):
	zip_file = tmp_path / "bundle.zip"
	dest_dir = tmp_path / "installed_runtime"

	file1_content = b"Binary content of server executable"
	file1_hash = hashlib.sha256(file1_content).hexdigest()
	manifest = {
		"runtime": "test-runtime",
		"version": "1.0.0",
		"platform": "windows-x64",
		"files": {"bin/server.exe": file1_hash},
	}

	with zipfile.ZipFile(zip_file, "w") as zf:
		zf.writestr("manifest.json", json.dumps(manifest))
		zf.writestr("bin/server.exe", file1_content)

	unpacked = unpack_zip(zip_file, dest_dir)
	assert unpacked == dest_dir
	assert (dest_dir / "manifest.json").exists()
	assert (dest_dir / "bin" / "server.exe").read_bytes() == file1_content


def test_unpack_zip_zip_slip_protection(tmp_path: Path):
	zip_file = tmp_path / "evil.zip"
	dest_dir = tmp_path / "safe_extract"

	with zipfile.ZipFile(zip_file, "w") as zf:
		# Intentionally create path traversal entry
		zf.writestr("../evil.txt", b"evil exploit")

	with pytest.raises(UnpackError, match="Zip-slip path traversal"):
		unpack_zip(zip_file, dest_dir)


def test_model_download_job_e2e(local_http_server: str, tmp_path: Path):
	dest_model = tmp_path / "models" / "gemma.bin"
	expected_hash = hashlib.sha256(RangeTestingHTTPHandler.payload_data).hexdigest()

	spec = JobSpec(
		job_id="dl-001",
		job_type="model_download",
		payload={
			"url": f"{local_http_server}/test.bin",
			"dest_path": str(dest_model),
			"model_name": "gemma.bin",
			"expected_sha256": expected_hash,
		},
	)
	token = CancellationToken("dl-001")
	progress_events: list[JobProgress] = []

	res = execute_model_download_job(
		spec,
		token,
		emit_progress=lambda p: progress_events.append(p),
	)

	assert res.status == JobStatus.COMPLETED
	assert res.result_data["cached"] is False
	assert dest_model.exists()
	assert dest_model.read_bytes() == RangeTestingHTTPHandler.payload_data
	assert len(progress_events) > 0

	# Re-executing returns cached = True immediately
	res_cached = execute_model_download_job(
		spec,
		token,
		emit_progress=lambda p: None,
	)
	assert res_cached.status == JobStatus.COMPLETED
	assert res_cached.result_data["cached"] is True


def test_runtime_download_job_e2e(tmp_path: Path):
	zip_file = tmp_path / "server_bundle.zip"
	dest_runtime = tmp_path / "runtimes" / "litert-1.0.0"

	file_content = b"runtime binary payload"
	manifest = {
		"runtime": "litert-lm",
		"version": "1.0.0",
		"platform": "windows-x64",
		"files": {"litert-lm.exe": hashlib.sha256(file_content).hexdigest()},
	}

	with zipfile.ZipFile(zip_file, "w") as zf:
		zf.writestr("manifest.json", json.dumps(manifest))
		zf.writestr("litert-lm.exe", file_content)

	# Use file:// URL scheme
	file_url = zip_file.as_uri()

	spec = JobSpec(
		job_id="dl-rt-001",
		job_type="runtime_download",
		payload={
			"url": file_url,
			"dest_dir": str(dest_runtime),
			"runtime": "litert-lm",
			"version": "1.0.0",
		},
	)
	token = CancellationToken("dl-rt-001")
	events: list[JobProgress] = []

	res = execute_runtime_download_job(
		spec,
		token,
		emit_progress=lambda p: events.append(p),
	)

	assert res.status == JobStatus.COMPLETED
	assert (dest_runtime / "manifest.json").exists()
	assert (dest_runtime / "litert-lm.exe").read_bytes() == file_content


def test_worker_download_client_with_mock_job_client(tmp_path: Path):
	mock_client = MockJobClient()
	dl_client = WorkerDownloadClient(mock_client)
	dest_file = tmp_path / "downloaded_model.bin"

	original_submit = mock_client.submit_job

	def _auto_complete_submit(spec: JobSpec):
		job_id = original_submit(spec)

		def _background_work():
			time.sleep(0.02)
			mock_client.simulate_progress(
				job_id,
				progress_pct=50.0,
				status_message="Downloading 50%",
				bytes_completed=500,
				bytes_total=1000,
			)
			time.sleep(0.02)
			dest_file.write_bytes(b"dummy model data")
			mock_client.simulate_complete(
				job_id,
				result_data={"path": str(dest_file)},
			)

		threading.Thread(target=_background_work, daemon=True).start()
		return job_id

	mock_client.submit_job = _auto_complete_submit

	progress_seen = []
	bytes_seen = []

	result_path = dl_client.download_model(
		url="https://example.com/model.bin",
		dest_path=dest_file,
		on_progress=lambda p: progress_seen.append(p.progress_pct),
		on_bytes_progress=lambda d, t: bytes_seen.append((d, t)),
		timeout_seconds=5.0,
	)

	assert result_path == dest_file
	assert 50.0 in progress_seen
	assert (500, 1000) in bytes_seen


def test_worker_download_client_cancellation(tmp_path: Path):
	mock_client = MockJobClient()
	dl_client = WorkerDownloadClient(mock_client)
	dest_file = tmp_path / "cancelled_model.bin"
	cancel_evt = threading.Event()

	def _cancel_shortly():
		time.sleep(0.05)
		cancel_evt.set()

	threading.Thread(target=_cancel_shortly, daemon=True).start()

	with pytest.raises(DownloadCancelledError):
		dl_client.download_model(
			url="https://example.com/large_model.bin",
			dest_path=dest_file,
			cancel_event=cancel_evt,
			timeout_seconds=5.0,
		)
