from tests.support import load_addon_module


def test_seed_pin_reset_preserves_thinking_preference(tmp_path, monkeypatch):
    module = load_addon_module("config.model_config", namespace="llama_seed_store")
    monkeypatch.setattr(module, "_store_path", lambda: tmp_path / "models.json")
    module.set_model_thinking("llama-cpp-server", "a", True)
    module.set_model_sampling("llama-cpp-server", "a", module.ModelSamplingConfig(seed=42, temperature=0.2))
    assert module.get_model_sampling("llama-cpp-server", "a").seed == 42
    module.set_model_sampling("llama-cpp-server", "a", module.ModelSamplingConfig(temperature=0.2))
    assert module.get_model_sampling("llama-cpp-server", "a").seed is None
    assert module.get_model_thinking("llama-cpp-server", "a")
