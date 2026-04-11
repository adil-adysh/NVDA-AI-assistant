from pathlib import Path

files = [
    'addon/globalPlugins/AI-assistant/__init__.py',
    'addon/globalPlugins/AI-assistant/chat_ui.py',
    'addon/globalPlugins/AI-assistant/chat_coordinator.py',
    'addon/globalPlugins/AI-assistant/image_description.py',
    'addon/globalPlugins/AI-assistant/page_summary.py',
    'addon/globalPlugins/AI-assistant/base_coordinator.py',
    'addon/globalPlugins/AI-assistant/metrics_reporter.py',
    'addon/globalPlugins/AI-assistant/ollama_client.py',
    'addon/globalPlugins/AI-assistant/providers/ollama_provider.py',
    'addon/globalPlugins/AI-assistant/providers/gemini_provider.py',
    'addon/globalPlugins/AI-assistant/providers/provider_proxy.py',
]
for path_str in files:
    path = Path(path_str)
    text = path.read_text(encoding='utf-8')
    orig = text
    text = text.replace('import logging\n', 'from logHandler import log\n')
    text = text.replace('logger = logging.getLogger(__name__)\n', '')
    text = text.replace('logger = logging.getLogger(__name__)', '')
    text = text.replace('logger.', 'log.')
    if text != orig:
        path.write_text(text, encoding='utf-8')
        print('patched', path_str)
