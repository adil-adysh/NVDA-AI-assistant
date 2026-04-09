import urllib.request
import urllib.error
import socket

base = 'http://127.0.0.1:11434'
paths = ['/api/tags', '/api/ps', '/api/show', '/api/pull']
for path in paths:
    if path == '/api/show':
        data = b'{"model": "gemma4:e2b"}'
    elif path == '/api/pull':
        data = b'{"model": "gemma4:e2b"}'
    else:
        data = None
    try:
        req = urllib.request.Request(base + path, data=data, headers={"Accept": "application/json", "Content-Type": "application/json"} if data else {"Accept": "application/json"}, method='POST' if data else 'GET')
        with urllib.request.urlopen(req, timeout=5) as r:
            text = r.read().decode('utf-8')
            print(path, 'STATUS', r.status)
            print(text[:800])
    except Exception as e:
        print(path, 'ERROR', repr(e))
