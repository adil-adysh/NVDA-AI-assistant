import math
import re
import subprocess
import time
from typing import Any, Callable, Optional

from ..config import defaults

_BYTES_PER_MB = 1024 * 1024
_BYTES_PER_GB = 1024 * 1024 * 1024
_PATTERN = re.compile(r"\((\d+)/(\d+)\)")


def bytes_to_mb(bytes_value: int) -> float:
    return bytes_value / _BYTES_PER_MB


def bytes_to_gb(bytes_value: int) -> float:
    return bytes_value / _BYTES_PER_GB


def format_size(bytes_value: int) -> str:
    if bytes_value >= _BYTES_PER_GB:
        return f"{bytes_to_gb(bytes_value):.1f} GB"
    return f"{bytes_to_mb(bytes_value):.0f} MB"


def format_eta(seconds: float) -> str:
    if seconds < 0:
        return "estimating time"
    rounded = int(round(seconds))
    if rounded < 10:
        return "almost done"
    if rounded < 60:
        return f"{rounded} seconds remaining"
    if rounded < 3600:
        minutes = int(round(rounded / 60))
        return f"{minutes} minutes remaining"
    hours = int(round(rounded / 3600))
    return f"{hours} hours remaining"


class DownloadProgressTracker:
    def __init__(self, speak: Callable[[str], None]) -> None:
        self._speak = speak
        self.total_bytes: Optional[int] = None
        self.last_downloaded_bytes = 0
        self.last_time = time.time()
        self.speed_samples: list[float] = []
        self.last_announced_percent = -1
        self.last_announce_time = 0.0
        self.start_time = 0.0
        self.announced_start = False
        self.finished = False

    def process_event(self, event: dict[str, Any]) -> None:
        if self.finished:
            return

        if "total" not in event or "completed" not in event:
            return

        try:
            downloaded_bytes = int(event.get("completed", -1))
            total_bytes = int(event.get("total", -1))
        except (TypeError, ValueError):
            return

        self._process_download(downloaded_bytes, total_bytes)

    def process_line(self, line: str) -> None:
        if self.finished:
            return

        if "(" not in line or "/" not in line:
            return

        match = _PATTERN.search(line)
        if not match:
            return

        downloaded_bytes = int(match.group(1))
        total_bytes = int(match.group(2))
        self._process_download(downloaded_bytes, total_bytes)

    def _process_download(self, downloaded_bytes: int, total_bytes: int) -> None:
        if total_bytes <= 0:
            return

        if self.total_bytes is None:
            self.total_bytes = total_bytes
        elif total_bytes != self.total_bytes:
            total_bytes = self.total_bytes

        if downloaded_bytes < self.last_downloaded_bytes:
            return

        now = time.time()

        if not self.announced_start:
            self._speak(
                "Downloading model, total size " + format_size(total_bytes)
            )
            self.announced_start = True
            self.start_time = now
            self.last_time = now
            self.last_downloaded_bytes = downloaded_bytes
            self.last_announce_time = now
            if downloaded_bytes >= total_bytes:
                self._speak("Download complete")
                self.last_announced_percent = 100
                self.finished = True
            return

        delta_bytes = downloaded_bytes - self.last_downloaded_bytes
        delta_time = now - self.last_time
        if delta_time > 0 and delta_bytes >= 0:
            instant_speed = delta_bytes / delta_time
            self.speed_samples.append(instant_speed)
            if len(self.speed_samples) > 5:
                self.speed_samples.pop(0)

        avg_speed = (
            sum(self.speed_samples) / len(self.speed_samples)
            if self.speed_samples
            else 0.0
        )

        progress_percent = math.floor((downloaded_bytes / total_bytes) * 100)
        remaining_bytes = total_bytes - downloaded_bytes
        eta_seconds = (
            remaining_bytes / avg_speed if avg_speed > 0 else -1
        )

        time_since_last = now - self.last_announce_time
        speed_mb = avg_speed / _BYTES_PER_MB
        if speed_mb >= 20:
            threshold_percent = 20
            threshold_time = 15
        elif speed_mb >= 2:
            threshold_percent = 10
            threshold_time = 10
        else:
            threshold_percent = 5
            threshold_time = 15

        should_announce = False
        if progress_percent == 100:
            should_announce = True
        elif progress_percent >= self.last_announced_percent + threshold_percent:
            should_announce = True
        elif time_since_last >= threshold_time:
            should_announce = True

        if progress_percent == self.last_announced_percent and progress_percent != 100:
            should_announce = False

        if should_announce:
            if progress_percent == 100:
                self._speak("Download complete")
            else:
                self._speak(
                    f"{progress_percent}% complete, {format_eta(eta_seconds)}"
                )
            self.last_announced_percent = progress_percent
            self.last_announce_time = now

        self.last_downloaded_bytes = downloaded_bytes
        self.last_time = now

        if progress_percent == 100:
            self.finished = True


def example_usage() -> None:
    def speak(text: str) -> None:
        print("SPEAK:", text)

    tracker = DownloadProgressTracker(speak=speak)
    command = [defaults.DEFAULT_OLLAMA_CLI, "pull", defaults.DEFAULT_OLLAMA_MODEL]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    if process.stdout is None:
        return

    for raw_line in process.stdout:
        line = raw_line.strip()
        tracker.process_line(line)

    process.wait()


if __name__ == "__main__":
    example_usage()
