import json
import urllib.request
import urllib.error
import socket

base = 'http://127.0.0.1:11434'
model = 'gemma4:e2b'
req = urllib.request.Request(
    base + '/api/pull',
    data=json.dumps({'model': model}).encode('utf-8'),
    headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
    method='POST',
)

print('requesting /api/pull', model)
try:
    with urllib.request.urlopen(req, timeout=10) as response:
        print('status', response.status)
        print('headers', response.getheaders())
        try:
            chunk = response.read(1024)
            print('chunk repr', repr(chunk[:400]))
            print('chunk text', chunk.decode('utf-8', errors='replace'))
        except Exception as exc:
            print('read error', exc)
except Exception as exc:
    print('open error', repr(exc))
