from tests.support import load_addon_module

manager = load_addon_module("embeddings.manager", namespace="embedding_worker_ports")
candle = load_addon_module("embeddings.candle", namespace="embedding_worker_ports")


class Client:
	def __init__(self):
		self.calls = []
	def run_job(self, kind, payload, **kwargs):
		self.calls.append((kind, payload))
		return {"success": True, "vectors": [[1.0, 2.0]], "models": [], "cached": True}


def test_embedding_inference_uses_worker():
	client = Client()
	adapter = candle.CandleEmbeddingAdapter("model", worker_client=client)
	assert adapter.embed(["hello"]) == ((1.0, 2.0),)
	assert client.calls[0][0] == "embedding"


def test_embedding_lifecycle_uses_worker():
	client = Client()
	service = manager.EmbeddingModelService(worker_client=client)
	assert service.list_models() == ()
	assert service.is_cached("model")
	service.prepare("model")
	service.delete("model")
	assert [call[1]["operation"] for call in client.calls] == ["list", "cached", "prepare", "delete"]


def test_large_embedding_input_preserves_order_across_worker_batches():
	class BatchClient(Client):
		def run_job(self, kind, payload, **kwargs):
			self.calls.append((kind, payload))
			assert len(payload["texts"]) <= 256
			return {"success": True, "vectors": [[float(text)] for text in payload["texts"]]}
	client = BatchClient()
	adapter = candle.CandleEmbeddingAdapter("model", worker_client=client)
	assert adapter.embed([str(index) for index in range(300)]) == tuple((float(index),) for index in range(300))
	assert len(client.calls) == 2


def test_retrieval_keeps_query_and_documents_on_the_same_model(monkeypatch):
	client = Client()
	selected = ["harrier-oss-v1-270m"]
	adapter = candle.CandleEmbeddingAdapter(worker_client=client)
	monkeypatch.setattr(adapter, "_selected_model", lambda: selected[0])
	retrieval = adapter.for_retrieval()
	retrieval.embed_query("question", "find answers")
	selected[0] = "all-MiniLM-L6-v2"
	retrieval.embed(["document"])
	assert [payload["model_id"] for _, payload in client.calls] == ["harrier-oss-v1-270m"] * 2
	assert client.calls[0][1]["texts"] == ["Instruct: find answers\nQuery: question"]
	assert adapter.for_retrieval().model_key.startswith("candle:all-MiniLM-L6-v2")


def test_preparation_and_deletion_invalidate_the_vector_cache_key(monkeypatch):
	client = Client()
	service = manager.EmbeddingModelService(worker_client=client)
	adapter = candle.CandleEmbeddingAdapter(worker_client=client)
	monkeypatch.setattr(adapter, "_selected_model", lambda: "managed-model")
	initial = adapter.for_retrieval()
	service.prepare("managed-model")
	prepared = adapter.for_retrieval()
	service.delete("managed-model")
	assert len({initial.model_key, prepared.model_key, adapter.for_retrieval().model_key}) == 3


def test_prepare_localizes_worker_progress_stages():
	class ProgressClient(Client):
		def run_job(self, kind, payload, *, on_progress, **kwargs):
			on_progress("embedding.download")
			on_progress("embedding.validate")
			return super().run_job(kind, payload, **kwargs)

	progress = []
	service = manager.EmbeddingModelService(worker_client=ProgressClient())
	service.prepare("progress-model", progress=progress.append)
	assert progress == [
		"Downloading embedding model files if needed...",
		"Loading and validating the embedding model...",
		"Embedding model is ready.",
	]
