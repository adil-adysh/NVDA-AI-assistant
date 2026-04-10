import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from ollama_client import OllamaClient, OllamaClientError

try:
    client = OllamaClient(baseURL='http://127.0.0.1:11434', model='gemma4:e2b', timeoutSeconds=10)
    messages = [{'role': 'user', 'content': 'Hello from NVDA add-on chat validation'}]
    response = client.chat(messages)
    print('CHAT_OK')
    print('model:', response.model)
    print('text:', response.text)
except Exception as exc:
    print('CHAT_ERROR', type(exc).__name__, exc)
