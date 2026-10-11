"""Regression coverage for worker download transport and file integrity."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import uuid

import pytest

from tests.support import load_addon_module

download = load_addon_module("worker.executors.download", namespace="download_integrity_tests")
jobs = load_addon_module("worker.executors.model_download_job", namespace="download_integrity_tests")
dto = load_addon_module("core.job.dto", namespace="download_integrity_tests")
cancellation = load_addon_module("core.job.cancellation", namespace="download_integrity_tests")
client = load_addon_module("providers.runtime.download_client", namespace="download_integrity_tests")
transport = load_addon_module("service.worker_client", namespace="download_integrity_tests")
server_module = load_addon_module("worker.server", namespace="download_integrity_tests")
direct = load_addon_module("providers.runtime.download", namespace="direct_download_integrity_tests")


@pytest.fixture
def http_url():
	class Handler(BaseHTTPRequestHandler):
		def log_message(self, *args):
			pass

		def do_GET(self):
			if self.path == "/unknown-total":
				self.send_response(206)
				self.send_header("Content-Range", "bytes 4-7/*")
				body = b"efgh"
			elif self.path == "/unsatisfiable":
				self.send_response(416)
				self.send_header("Content-Range", "bytes */8")
				body = b""
			elif self.path == "/wrong-range":
				self.send_response(206)
				self.send_header("Content-Range", "bytes 0-3/8")
				body = b"abcd"
			else:
				self.send_response(200)
				body = b"abcd"
			self.send_header("Content-Length", "8" if self.path == "/truncated" else "4")
			self.end_headers()
			self.wfile.write(body)

	http = HTTPServer(("127.0.0.1", 0), Handler)
	thread = threading.Thread(target=http.serve_forever, daemon=True)
	thread.start()
	try:
		yield f"http://127.0.0.1:{http.server_port}"
	finally:
		http.shutdown()
		http.server_close()
		thread.join()


def test_truncated_response_is_not_completed(http_url, tmp_path):
	with pytest.raises(download.DownloadError):
		download.stream_download(f"{http_url}/truncated", tmp_path / "model.part", max_retries=0)


def test_mismatched_range_does_not_append_corrupt_data(http_url, tmp_path):
	part = tmp_path / "model.part"
	part.write_bytes(b"abcd")
	with pytest.raises(download.DownloadError):
		download.stream_download(f"{http_url}/wrong-range", part, resume_from=4, max_retries=0)
	assert part.read_bytes() == b"abcd"


def test_unknown_range_total_preserves_known_expected_size(http_url, tmp_path):
	part = tmp_path / "model.part"
	part.write_bytes(b"abcd")
	with pytest.raises(download.DownloadError):
		download.stream_download(
			f"{http_url}/unknown-total", part, resume_from=4, expected_size=12, max_retries=0,
		)


@pytest.mark.parametrize("route", ["truncated", "wrong-range", "unsatisfiable"])
def test_direct_download_rejects_incomplete_responses(http_url, tmp_path, monkeypatch, route):
	part = tmp_path / "model.part"
	part.write_bytes(b"abcd")
	monkeypatch.setattr(direct, "_MAX_RETRIES", 0)
	with pytest.raises((OSError, direct.RuntimeDownloadError)):
		direct._download_url_resume(f"{http_url}/{route}", part, resume_from=0 if route == "truncated" else 4)


def test_cached_model_must_match_requested_checksum(tmp_path):
	model = tmp_path / "model.bin"
	model.write_bytes(b"corrupt")
	spec = dto.JobSpec(job_id="cached-integrity", job_type="model_download", payload={
		"url": "http://127.0.0.1:1/unused", "dest_path": str(model), "expected_sha256": "0" * 64,
	})
	result = jobs.execute_model_download_job(spec, cancellation.CancellationToken(spec.job_id), lambda p: None)
	assert result.status == dto.JobStatus.FAILED
	assert result.error_code == "CHECKSUM_MISMATCH"
	assert model.read_bytes() == b"corrupt"


def test_download_accepts_supervisors_worker_client(http_url, tmp_path):
	token = uuid.uuid4().hex
	cmd_pipe = rf"\\.\pipe\download_integrity_cmd_{token}"
	evt_pipe = rf"\\.\pipe\download_integrity_evt_{token}"
	server = server_module.WorkerServer(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
	worker = transport.NamedPipeWorkerClient(cmd_pipe_name=cmd_pipe, evt_pipe_name=evt_pipe)
	server.start()
	try:
		worker.connect()
		destination = tmp_path / "model.bin"
		result = client.WorkerDownloadClient(worker).download_model(
			f"{http_url}/valid", destination, timeout_seconds=3,
		)
		assert result == destination
		assert destination.read_bytes() == b"abcd"
	finally:
		worker.disconnect()
		server.shutdown()
