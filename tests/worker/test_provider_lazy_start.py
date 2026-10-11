"""Provider operations explicitly request startup; status stays passive."""

import pytest

from tests.support import load_addon_module

namespace = "provider_lazy_tests"
worker = load_addon_module("plugin.worker_supervisor", namespace=namespace)
litert = load_addon_module("providers.runtime.server", namespace=namespace)
llama = load_addon_module("providers.runtime.llama_server", namespace=namespace)
downloads = load_addon_module("providers.runtime.download_client", namespace=namespace)
runtime_downloads = load_addon_module("providers.runtime.download", namespace=namespace)
model_downloads = load_addon_module("providers.runtime.model_download", namespace=namespace)


@pytest.mark.parametrize("supervisor", [litert.LiteRTServerSupervisor, llama.LlamaServerSupervisor])
def test_lookup_is_passive_but_operation_connects(supervisor, monkeypatch):
	calls = []
	class Client:
		is_connected = True
	client = Client()
	monkeypatch.setattr(worker, "get_worker_client", lambda: None)
	monkeypatch.setattr(worker, "ensure_worker_client", lambda: calls.append("start") or client, raising=False)
	provider = supervisor()
	assert provider._get_worker_client() is None
	assert calls == []
	assert provider._get_worker_client(start=True) is client
	assert calls == ["start"]


def test_cached_service_download_checks_checksum(tmp_path, monkeypatch):
	path = tmp_path / "cached-model"
	path.write_bytes(b"corrupt")
	service = model_downloads.ModelDownloadService()
	monkeypatch.setattr(service, "_model_path", lambda name: path)
	with pytest.raises(model_downloads.ModelDownloadError, match="SHA-256"):
		service.download("cached", "unused", expected_sha256="0" * 64)
	assert path.read_bytes() == b"corrupt"


def test_download_operation_starts_worker_and_uses_jobs(monkeypatch):
	jobs = object()
	class Client:
		def get_job_client(self):
			return jobs
	monkeypatch.setattr(worker, "get_worker_client", lambda: None)
	monkeypatch.setattr(worker, "ensure_worker_client", lambda: Client(), raising=False)
	assert downloads.WorkerDownloadClient()._get_client() is jobs


@pytest.mark.parametrize("kind", ["runtime", "model"])
def test_first_service_download_resolves_lazy_worker(kind, tmp_path, monkeypatch):
	calls = []
	client = object()
	monkeypatch.setattr(worker, "_worker_owner", object())
	monkeypatch.setattr(worker, "get_worker_client", lambda: None)
	monkeypatch.setattr(worker, "ensure_worker_client", lambda: calls.append("start") or client)
	class Adapter:
		def __init__(self, supplied):
			assert supplied is client
		def download_runtime(self, **kwargs):
			return tmp_path / "runtime"
		def download_model(self, **kwargs):
			return tmp_path / "model"
	monkeypatch.setattr(downloads, "WorkerDownloadClient", Adapter)
	def unexpected_direct(*args, **kwargs):
		raise AssertionError("First download bypassed the lazy worker")
	monkeypatch.setattr(runtime_downloads, "_download_url_resume", unexpected_direct)
	monkeypatch.setattr(model_downloads, "_download_url_resume", unexpected_direct)
	if kind == "runtime":
		service = runtime_downloads.RuntimeDownloadService(url_builder=lambda config: "https://invalid/runtime.zip")
		monkeypatch.setattr(service, "is_downloaded", lambda *args: False)
		assert service.download(runtime="litert-lm", version="0.15.0") == tmp_path / "runtime"
	else:
		service = model_downloads.ModelDownloadService()
		monkeypatch.setattr(service, "_model_path", lambda name: tmp_path / "missing-model")
		assert service.download(model_name="example", url="https://invalid/model") == tmp_path / "model"
	assert calls == ["start"]
