import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE_URL = 'http://127.0.0.1:11434'
MODEL_NAME = 'gemma4:e2b'
TIMEOUT_SECONDS = 300


def request_json(path: str, payload: Any | None = None, method: str | None = None) -> tuple[int, Any]:
    url = BASE_URL.rstrip('/') + path
    headers = {
        'Accept': 'application/json',
    }
    body = None
    if payload is not None:
        body = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if method is None:
        method = 'POST' if payload is not None else 'GET'
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        text = response.read().decode('utf-8', errors='replace')
        status = getattr(response, 'status', None) or getattr(response, 'getcode', lambda: None)()
        return status, json.loads(text)


def print_result(name: str, status: int, payload: Any) -> None:
    print(f'=== {name} ===')
    print('status:', status)
    print('payload:', json.dumps(payload, indent=2)[:1600])
    print()


def probe_metadata() -> None:
    for name, path, payload in [
        ('ps', '/api/ps', None),
        ('tags', '/api/tags', None),
        ('show', '/api/show', {'model': MODEL_NAME}),
    ]:
        try:
            status, result = request_json(path, payload)
            print_result(name, status, result)
        except Exception as exc:
            print(f'ERROR [{name}] {type(exc).__name__}: {exc}')
            print()


def probe_chat_text() -> None:
    payload = {
        'model': MODEL_NAME,
        'messages': [
            {'role': 'user', 'content': 'Hello from NVDA chat probe.'},
        ],
        'stream': False,
    }
    try:
        status, result = request_json('/api/chat', payload)
        print_result('chat-text', status, result)
    except Exception as exc:
        print(f'ERROR [chat-text] {type(exc).__name__}: {exc}')
        print()


def probe_chat_image() -> None:
    sample_image = create_sample_png_base64()
    payload = {
        'model': MODEL_NAME,
        'messages': [
            {
                'role': 'user',
                'content': 'Please describe this image.',
                'images': [sample_image],
            }
        ],
        'stream': False,
    }
    try:
        status, result = request_json('/api/chat', payload)
        print_result('chat-image', status, result)
    except Exception as exc:
        print(f'ERROR [chat-image] {type(exc).__name__}: {exc}')
        print()


def create_sample_png_base64() -> str:
    png_bytes = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8' \
        'zwAAAgEBAS/nSDEAAAAASUVORK5CYII='
    )
    return base64.b64encode(png_bytes).decode('ascii')


def main() -> None:
    print('Ollama API probe base_url=', BASE_URL)
    probe_metadata()
    probe_chat_text()
    probe_chat_image()


if __name__ == '__main__':
    main()
