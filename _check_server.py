"""Quick script to check litert-lm server process and test vision."""
import json
import os
import subprocess
import urllib.request

# 1. Get command line of python processes
print("=== Python processes ===")
r = subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     'Get-CimInstance Win32_Process -Filter "Name=\'python.exe\'" | ForEach-Object { "$($_.ProcessId): $($_.CommandLine)" }'],
    capture_output=True, text=True, timeout=10
)
print(r.stdout)

# 2. Check env vars of the server
print("\n=== Server models ===")
req = urllib.request.Request("http://localhost:9379/v1/models")
with urllib.request.urlopen(req, timeout=5) as resp:
    data = json.loads(resp.read())
    for m in data["data"]:
        print(f"  {m['id']}")

# 3. Test text chat
print("\n=== Text chat test (E2B) ===")
payload = json.dumps({
    "model": "litert-community/gemma-4-E2B-it-litert-lm",
    "messages": [{"role": "user", "content": "Reply with just the word: OK"}],
    "max_tokens": 20
}).encode()
req = urllib.request.Request("http://localhost:9379/v1/chat/completions", data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=30) as resp:
    result = json.loads(resp.read())
    print(f"  Response: {result['choices'][0]['message']['content']}")

# 4. Test vision
print("\n=== Vision test (E2B) ===")
# 10x10 blue PNG base64
b64 = "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAAEUlEQVR4nGNgYPiPF41KY0EA8INjnagJNDwAAAAASUVORK5CYII="
payload = json.dumps({
    "model": "litert-community/gemma-4-E2B-it-litert-lm",
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "Describe this image in one short sentence."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        ]
    }],
    "max_tokens": 100
}).encode()
req = urllib.request.Request("http://localhost:9379/v1/chat/completions", data=payload, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
        print(f"  Response: {result['choices'][0]['message']['content']}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"  HTTP {e.code}: {body[:500]}")
except Exception as e:
    print(f"  Error: {e}")

# 5. Also test E4B vision
print("\n=== Vision test (E4B) ===")
payload = json.dumps({
    "model": "litert-community/gemma-4-E4B-it-litert-lm",
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "Describe this image in one short sentence."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        ]
    }],
    "max_tokens": 100
}).encode()
req = urllib.request.Request("http://localhost:9379/v1/chat/completions", data=payload, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
        print(f"  Response: {result['choices'][0]['message']['content']}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"  HTTP {e.code}: {body[:500]}")
except Exception as e:
    print(f"  Error: {e}")

print("\nDone.")
