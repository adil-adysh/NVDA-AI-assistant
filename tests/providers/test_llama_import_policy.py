from unittest.mock import Mock

import pytest

from tests.support import load_addon_module

module = load_addon_module("providers.llama_manager", namespace="llama_import_policy")
requests = load_addon_module("providers.model_import", namespace="llama_import_policy")


@pytest.mark.parametrize("source,variant,artifact", [
    ("owner/model:Q4_K_M", "Q4_K_M", None),
    ("owner/model#file=sub/model.gguf", None, "sub/model.gguf"),
])
def test_import_preserves_validated_selectors(tmp_path, source, variant, artifact):
    manager = module.LlamaCppModelManager(cache_dir=tmp_path, supervisor=Mock())
    request = requests.parse_model_import_source(source, "selected", "llama-cpp-server")
    manager.import_model(request, Mock())
    record = manager._catalog.find("selected")
    assert record.variant == variant
    assert record.artifact == artifact


def test_unsupported_revision_is_rejected_before_registration(tmp_path):
    manager = module.LlamaCppModelManager(cache_dir=tmp_path, supervisor=Mock())
    request = requests.parse_model_import_source("owner/model@v1", "selected", "llama-cpp-server")
    with pytest.raises(module.LLMProviderError, match="revision"):
        manager.import_model(request, Mock())
    assert not manager._catalog.list_records()
