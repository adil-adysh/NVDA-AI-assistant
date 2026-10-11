from pathlib import Path

import pytest

from tests.support import load_addon_module


paths = load_addon_module('providers.runtime.paths', namespace='litert_path_contract')
adapter = load_addon_module('providers.runtime.server', namespace='litert_path_contract')
executor = load_addon_module('worker.executors.litert', namespace='litert_path_contract')
worker = load_addon_module('worker.server', namespace='litert_path_contract')


def test_worker_defaults_match_installer_layout(tmp_path, monkeypatch):
	monkeypatch.setenv('APPDATA', str(tmp_path))
	for version in ('0.15.0', 'custom-version'):
		assert executor.default_runtime_dir(version) == paths.get_runtime_path('litert-lm', version)


@pytest.mark.parametrize('operation', ['ensure_ready', 'restart'])
def test_adapter_sends_installed_runtime_paths_to_worker(tmp_path, monkeypatch, operation):
	monkeypatch.setenv('APPDATA', str(tmp_path))
	supervisor = adapter.LiteRTServerSupervisor(version='custom-version')
	python = paths.get_runtime_path('litert-lm', 'custom-version') / 'python.exe'
	python.parent.mkdir(parents=True)
	python.touch()
	commands = []
	progress = []
	launches = []
	responses = []
	class ProcessBoundary:
		def ensure_ready(self, executable, args, env, identity, **kwargs):
			launches.append((executable, env))
			return {'state': 'ready_owned', 'is_ready': True}
		restart = ensure_ready
	worker_executor = executor.LiteRTWorkerExecutor(supervisor=ProcessBoundary())
	server = worker.WorkerServer.__new__(worker.WorkerServer)
	server.get_litert_executor = lambda: worker_executor
	class CommandPipe:
		is_connected = True
		def write_frame(self, response):
			responses.append(response)
	server._cmd_server = CommandPipe()
	class Client:
		def send_command(self, command, **kwargs):
			commands.append(command)
			server._handle_command(command)
			return responses[-1]
	monkeypatch.setattr(supervisor, '_get_native', lambda: None)
	monkeypatch.setattr(supervisor, '_get_worker_client', lambda **kwargs: Client())
	getattr(supervisor, operation)(on_progress=progress.append)
	if operation == 'ensure_ready':
		assert progress == []
	assert Path(commands[0]['python_exe']) == python
	assert Path(commands[0]['litert_dir']) == supervisor._litert_dir()
	assert commands[0]['version'] == 'custom-version'
	assert Path(launches[0][0]) == python
	assert Path(launches[0][1]['LITERT_LM_DIR']) == supervisor._litert_dir()


def test_native_ready_server_does_not_announce_start(tmp_path, monkeypatch):
	monkeypatch.setenv('APPDATA', str(tmp_path))
	class Native:
		def status(self):
			return type('Status', (), {'state': 'ready_owned'})()
		def ensure_ready(self, *args, **kwargs):
			return type('Status', (), {'is_ready': True})()
	supervisor = adapter.LiteRTServerSupervisor(native_supervisor=Native())
	monkeypatch.setattr(adapter, '_resolve_litert_python', lambda path: path)
	progress = []
	assert supervisor.ensure_ready(on_progress=progress.append).is_ready
	assert progress == []


def test_server_progress_translates_template_before_formatting(tmp_path, monkeypatch):
	import builtins
	monkeypatch.setenv('APPDATA', str(tmp_path))
	monkeypatch.setattr(builtins, '_', lambda text: 'translated: ' + text, raising=False)
	class Native:
		def status(self):
			return type('Status', (), {'state': 'ready_owned'})()
		def ensure_ready(self, *args, **kwargs):
			return type('Status', (), {'is_ready': True})()
	supervisor = adapter.LiteRTServerSupervisor(native_supervisor=Native())
	monkeypatch.setattr(adapter, '_resolve_litert_python', lambda path: path)
	progress = []
	supervisor.ensure_ready(on_progress=progress.append)
	assert progress == []
	progress_module = load_addon_module('core.readiness_progress', namespace='litert_translation_contract')
	assert progress_module.render_readiness_stage('starting') == 'translated: Starting local AI server…'
