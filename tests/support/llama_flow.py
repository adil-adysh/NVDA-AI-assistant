"""Real catalog/manager/worker command wiring with a process-owned runtime double."""
import struct
from types import SimpleNamespace

from tests.support import load_addon_module


def gguf(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GGUF" + struct.pack("<IQQ", 3, 0, 0) + bytes(32))
    return path


class RuntimeSurface:
    """Only process lifecycle is replaced; model policy and file writes stay real."""
    executable = "test-llama-server"
    models_error = None
    is_running = False
    is_adopted = False

    def __init__(self):
        self.models = ()
        self.starts = []
        self.stops = 0

    def list_models(self, **kwargs):
        return self.models

    def status(self, **kwargs):
        return SimpleNamespace(is_running=self.is_running, is_adopted=self.is_adopted)

    def stop(self, **kwargs):
        self.stops += 1
        self.is_running = False

    def start(self, source, **kwargs):
        self.starts.append((source, kwargs))
        self.is_running = True
        self.models = ({"id": kwargs["model_id"], "status": {"value": "unloaded"}},)

    def wait_until_ready(self, **kwargs):
        return True

    def is_healthy(self):
        return self.is_running

    def matches_startup_configuration(self, *args, **kwargs):
        return True


class CommandClient:
    def __init__(self, dispatch, assets, llama):
        self.dispatch = dispatch
        self.server = SimpleNamespace(get_model_asset_executor=lambda: assets,
            get_llama_executor=lambda: llama, _default_cache_roots=lambda: [])
        self.commands = []

    def send_command(self, frame, **kwargs):
        self.commands.append(frame)
        responses = []
        self.dispatch.execute_runtime_command(self.server, frame, responses.append)
        assert responses, frame
        return responses[-1]


def llama_flow(tmp_path, monkeypatch):
    namespace = "llama_journeys"
    module = load_addon_module("providers.llama_manager", namespace=namespace)
    asset_module = load_addon_module("worker.executors.model_assets", namespace=namespace)
    worker = load_addon_module("worker.executors.llama", namespace=namespace)
    commands = load_addon_module("worker.runtime_commands", namespace=namespace)
    settings = load_addon_module("config.settings", namespace=namespace)
    store = load_addon_module("config.yaml_store", namespace=namespace)
    monkeypatch.setattr(settings, "_config_store", store.YamlConfigStore(tmp_path / "settings.yaml"))
    sampling = load_addon_module("config.model_config", namespace=namespace)
    # Per-model settings are an in-process application store, isolated from NVDA.
    saved = {}
    monkeypatch.setattr(sampling, "get_model_sampling", lambda provider, model: saved.get(model, sampling.ModelSamplingConfig()))
    monkeypatch.setattr(sampling, "set_model_sampling", lambda provider, model, values: saved.__setitem__(model, values))
    assets = asset_module.ModelAssetExecutor()
    executor = worker.LlamaWorkerExecutor(supervisor=SimpleNamespace(), owned_cache_root=tmp_path / "managed/cache")
    monkeypatch.setattr(executor, "inspect_options", lambda executable: set(worker.OPTION_BY_KEY))
    client = CommandClient(commands, assets, executor)
    runtime = RuntimeSurface()
    manager = module.LlamaCppModelManager(config=SimpleNamespace(model_name="", num_ctx=8192),
        cache_dir=tmp_path / "managed", supervisor=runtime, worker_client=client)
    return SimpleNamespace(manager=manager, runtime=runtime, client=client, assets=assets,
        executor=executor, module=module, sampling=sampling, saved=saved, settings=settings)
