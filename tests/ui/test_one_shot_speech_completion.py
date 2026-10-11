from enum import Enum
from types import ModuleType, SimpleNamespace
import sys

import pytest

from tests.support import PROJECT_ROOT, load_addon_module, load_module


@pytest.mark.parametrize('finish', ['completed', 'cancelled', 'speech_off'])
def test_nvda_completion_or_speech_cancel_delivers_once(monkeypatch, finish):
	# NVDA's synthesis and event loop are process-owned; keep its command and
	# extension-point definitions real while replacing the running speech engine.
	monkeypatch.setitem(sys.modules, 'ui', SimpleNamespace(message=lambda text: None, nh3=SimpleNamespace(clean=lambda text: text)))
	monkeypatch.setitem(sys.modules, 'queueHandler', SimpleNamespace())
	monkeypatch.setitem(sys.modules, 'synthDriverHandler', SimpleNamespace(getSynth=lambda: None))
	speech = ModuleType('speech')
	speech.__path__ = [str(PROJECT_ROOT.parent / 'nvda' / 'source' / 'speech')]
	monkeypatch.setitem(sys.modules, 'speech', speech)
	for name in ('speech.commands', 'speech.types', 'speech.extensions'):
		monkeypatch.setitem(sys.modules, name, ModuleType(name))
	commands = load_module('speech.commands', PROJECT_ROOT.parent / 'nvda' / 'source' / 'speech' / 'commands.py')
	load_module('speech.types', PROJECT_ROOT.parent / 'nvda' / 'source' / 'speech' / 'types.py')
	extensions = load_module('speech.extensions', PROJECT_ROOT.parent / 'nvda' / 'source' / 'speech' / 'extensions.py')
	class SpeechMode(Enum):
		talk = 1
		off = 2
	speech.SpeechMode = SpeechMode
	speech.getState = lambda: SimpleNamespace(speechMode=SpeechMode.off if finish == 'speech_off' else SpeechMode.talk)
	sequences = []
	speech.speak = sequences.append
	module = load_addon_module('ui.nvda_ui', namespace='one_shot_speech_tests')
	delivered = []
	module.queue_speech_then('Answer', lambda: delivered.append('display'))
	if finish != 'speech_off':
		assert not delivered
		assert isinstance(sequences[0][-1], commands.CallbackCommand)
		if finish == 'cancelled':
			extensions.pre_speechCanceled.notify()
		else:
			sequences[0][-1].run()
		# A repeated event or late synthesis callback must not display twice.
		extensions.pre_speechCanceled.notify()
		sequences[0][-1].run()
	assert delivered == ['display']
