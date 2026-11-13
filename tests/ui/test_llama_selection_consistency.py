from types import SimpleNamespace
from unittest.mock import Mock

from tests.support import load_addon_module


def test_adapter_and_manager_exclude_missing_sources_and_keep_exact_ids(tmp_path):
    manager_module = load_addon_module("providers.llama_manager", namespace="selection_ux")
    records = load_addon_module("providers.runtime.llama_models", namespace="selection_ux")
    adapter = load_addon_module("providers.adapters.llama_cpp", namespace="selection_ux")
    supervisor = Mock()
    supervisor.list_models.return_value = ({"id": "missing", "status": {"value": "unloaded"}},)
    manager = manager_module.LlamaCppModelManager(cache_dir=tmp_path, supervisor=supervisor)
    manager._catalog.upsert(records.LlamaModelRecord("missing", str(tmp_path / "missing.gguf"), "local_file"))
    manager._catalog.upsert(records.LlamaModelRecord("remote", "owner/model", "hugging_face", display_name="Everyday", preset_options={"ctx-size": "4096"}))
    provider = object.__new__(adapter.LlamaCppServerProvider)
    provider._provider_id = "llama-cpp-server"
    provider._config = SimpleNamespace(model_name="remote", num_ctx=8192)
    provider._llama_manager = manager
    assert [model.id for model in provider.list_models()] == manager.get_available_model_ids() == ["remote"]
    info = provider.list_models()[0]
    assert info.display_name == "Everyday" and info.context_window == 4096
