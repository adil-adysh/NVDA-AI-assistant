"""Bounded-output subprocess execution with cooperative child cancellation."""
import subprocess
import tempfile
import time


def run_cancellable(command, *, env, timeout, creationflags, token):
	deadline = time.monotonic() + timeout
	token.check_cancelled()
	with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
		process = subprocess.Popen(command, env=env, stdout=stdout, stderr=stderr,
			creationflags=creationflags)
		try:
			while process.poll() is None:
				token.check_cancelled()
				if time.monotonic() >= deadline:
					raise subprocess.TimeoutExpired(command[:3], timeout)
				token.wait(0.05)
			token.check_cancelled()
		finally:
			if process.poll() is None:
				process.kill()
				process.wait(timeout=5)
		stdout.seek(0)
		stderr.seek(0)
		return subprocess.CompletedProcess(command, process.returncode,
			stdout.read(128 * 1024).decode("utf-8", errors="replace"),
			stderr.read(128 * 1024).decode("utf-8", errors="replace"))
