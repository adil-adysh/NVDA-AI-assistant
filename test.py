# Standalone IPC smoke-test script: the pipe connect/send/read helpers are
# intentionally duplicated here so the script runs without importing the
# addon package (R0801).
# pylint: disable=duplicate-code
import time
import json
import win32file
import pywintypes

PIPE_NAME = r'\\.\pipe\nvda_ai_assistant_ui'


def connect_to_pipe():
	print("Connecting to pipe:", PIPE_NAME)

	while True:
		try:
			handle = win32file.CreateFile(
				PIPE_NAME,
				win32file.GENERIC_READ | win32file.GENERIC_WRITE,
				0,
				None,
				win32file.OPEN_EXISTING,
				0,
				None
			)
			print("✅ Connected to pipe")
			return handle

		except pywintypes.error as e:
			if e.winerror == 2:
				print("⏳ Pipe not found, waiting...")
			elif e.winerror == 231:
				print("⏳ Pipe busy, waiting...")
			else:
				print(f"⚠️ Unexpected error: {e}")

			time.sleep(1)


def send_command(handle):
	command = {
		"action": "display_result",
		"request_id": "test-1",
		"protocol_version": 1,
		"payload": {
			"output_text": "🔥 Hello from Python IPC test"
		}
	}

	message = json.dumps(command) + "\n"

	print("➡️ Sending:", message.strip())

	win32file.WriteFile(handle, message.encode("utf-8"))
	print("✅ Message sent")


def read_response(handle):
	print("📥 Waiting for response (optional)...")

	try:
		while True:
			_, data = win32file.ReadFile(handle, 4096)
			text = data.decode("utf-8").strip()
			if text:
				print("⬅️ Received:", text)
				break
	except pywintypes.error as e:
		print("ℹ️ No response or read failed:", e)


def main():
	handle = connect_to_pipe()

	send_command(handle)

	# Optional: read response from Rust
	read_response(handle)

	print("✅ Test complete")


if __name__ == "__main__":
	main()
