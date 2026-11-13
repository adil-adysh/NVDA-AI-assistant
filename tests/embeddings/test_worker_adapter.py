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
	adapter = candle.CandleEmbeddingAdapter(worker_client=client)
	adapter._sync_selected_model = lambda: None
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
	adapter = candle.CandleEmbeddingAdapter(worker_client=client)
	adapter._sync_selected_model = lambda: None
	assert adapter.embed([str(index) for index in range(300)]) == tuple((float(index),) for index in range(300))
	assert len(client.calls) == 2
