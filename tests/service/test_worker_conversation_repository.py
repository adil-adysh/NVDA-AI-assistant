from tests.support import load_addon_module

repo = load_addon_module("service.chat.repository_worker", namespace="worker_repository_tests")
canonical = load_addon_module("core.canonical", namespace="worker_repository_tests")


def test_worker_repository_roundtrip(tmp_path, monkeypatch):
	executor = load_addon_module("worker.executors.conversation", namespace="worker_repository_tests")
	backends = load_addon_module("service.chat.repository_backends", namespace="worker_repository_tests")
	dto = load_addon_module("core.job.dto", namespace="worker_repository_tests")
	cancel = load_addon_module("core.job.cancellation", namespace="worker_repository_tests")
	monkeypatch.setattr(executor, "_repository", backends.JsonConversationRepository(tmp_path / "history.json"))
	class Client:
		def run_job(self, kind, payload, **kwargs):
			spec = dto.JobSpec(job_id="repository", job_type=kind, payload=payload)
			return executor.execute_conversation_job(spec, cancel.CancellationToken(spec.job_id)).result_data
	store = repo.WorkerConversationRepository(Client())
	store.save("chat", [canonical.Message(role="user", parts=(canonical.Part(type="text", text="Hello"),))])
	assert store.exists("chat")
	assert store.load("chat").snapshot()[0].parts[0].text == "Hello"
	assert store.list_summaries()[0].conversation_id == "chat"
	assert store.delete("chat")
	assert not store.exists("chat")
