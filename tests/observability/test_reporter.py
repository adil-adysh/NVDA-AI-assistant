from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from tests.support import load_addon_module


reporter_module = load_addon_module("observability.reporter", namespace="observability_reporter_tests")
metrics_module = load_addon_module("observability.metrics", namespace="observability_reporter_tests")


def configure_reporter(monkeypatch, tmp_path: Path, *, enabled: bool = True) -> Path:
	path = tmp_path / "metrics.jsonl"
	monkeypatch.setattr(reporter_module, "get_request_metrics_logging_enabled", lambda: enabled)
	monkeypatch.setattr(reporter_module, "get_request_metrics_log_path", lambda: str(path))
	return path


def test_disabled_logging_does_not_create_files(monkeypatch, tmp_path):
	path = configure_reporter(monkeypatch, tmp_path, enabled=False)
	reporter_module.FileMetricsReporter().report_event(
		reporter_module.DiagnosticEvent("task_started", attributes={"task": "catalog_refresh"})
	)
	assert not path.exists()


def test_request_metric_record_contains_only_safe_request_metadata(monkeypatch, tmp_path):
	path = configure_reporter(monkeypatch, tmp_path)
	metric = metrics_module.RequestMetrics(
		request_type="chat",
		provider="openai",
		model="org/model",
		duration_ms=125.5,
		success=False,
		error_type="LLMProviderError",
	)
	reporter_module.FileMetricsReporter().report(metric)
	record = json.loads(path.read_text(encoding="utf-8"))
	assert record == {
		"record_type": "request_metric",
		"schema_version": 1,
		"timestamp": record["timestamp"],
		"request_type": "chat",
		"provider": "openai",
		"model": "org/model",
		"duration_ms": 125.5,
		"success": False,
		"error_type": "LLMProviderError",
	}
	assert "secret" not in path.read_text(encoding="utf-8")


def test_request_metric_does_not_treat_absolute_paths_as_model_ids():
	for path in (
		"/home/user/models/private.litertlm",
		"models/private.gguf",
		"../private/model",
		"./alice/model",
		"C:alice/model",
		"localhost:8080/v1/models",
		"alice:secret@api.internal.example/v1/models",
		"api.internal.example/v1/models",
		"Users/Alice/private/checkpoint",
		"C:private.txt",
		"192.168.1.23:8080",
	):
		record = metrics_module.RequestMetrics(
			request_type="chat",
			provider="local",
			model=path,
			duration_ms=10,
			success=True,
		).to_log_record()
		assert record["model"] == "unknown"


def test_locked_backup_does_not_erase_other_generations(monkeypatch, tmp_path):
	path = configure_reporter(monkeypatch, tmp_path)
	monkeypatch.setattr(reporter_module.FileMetricsReporter, "MAX_LOG_BYTES", 1)
	path.write_text("active", encoding="utf-8")
	backups = [tmp_path / f"metrics.jsonl.{index:020d}-{index:08x}" for index in range(1, 4)]
	for index, backup in enumerate(backups, 1):
		backup.write_text(f"backup-{index}", encoding="utf-8")
	original_unlink = Path.unlink
	def refuse_locked_backup(source, *, missing_ok=False):
		if source == backups[0]:
			raise PermissionError("backup held without delete sharing")
		return original_unlink(source, missing_ok=missing_ok)
	monkeypatch.setattr(Path, "unlink", refuse_locked_backup)
	for _ in range(4):
		reporter_module.FileMetricsReporter().report_event(
			reporter_module.DiagnosticEvent("task_completed", attributes={"task": "catalog_refresh"})
		)
	assert path.read_text(encoding="utf-8") == "active"
	assert [backup.read_text(encoding="utf-8") for backup in backups] == ["backup-1", "backup-2", "backup-3"]


def test_rotation_ignores_unrelated_sibling_files(monkeypatch, tmp_path):
	path = configure_reporter(monkeypatch, tmp_path)
	monkeypatch.setattr(reporter_module.FileMetricsReporter, "MAX_LOG_BYTES", 1)
	monkeypatch.setattr(reporter_module.FileMetricsReporter, "BACKUP_COUNT", 1)
	path.write_text("active", encoding="utf-8")
	notes = tmp_path / "metrics.jsonl.notes"
	notes.write_text("keep this file", encoding="utf-8")
	reporter_module.FileMetricsReporter().report_event(
		reporter_module.DiagnosticEvent("task_completed", attributes={"task": "catalog_refresh"})
	)
	assert notes.read_text(encoding="utf-8") == "keep this file"
	assert len([p for p in tmp_path.iterdir() if p.name.startswith("metrics.jsonl.") and p != notes]) == 1


def test_rotation_supports_paths_with_glob_metacharacters(monkeypatch, tmp_path):
	path = tmp_path / "metrics[blue].jsonl"
	monkeypatch.setattr(reporter_module, "get_request_metrics_logging_enabled", lambda: True)
	monkeypatch.setattr(reporter_module, "get_request_metrics_log_path", lambda: str(path))
	monkeypatch.setattr(reporter_module.FileMetricsReporter, "MAX_LOG_BYTES", 1)
	monkeypatch.setattr(reporter_module.FileMetricsReporter, "BACKUP_COUNT", 1)
	for index in range(3):
		reporter_module.FileMetricsReporter().report_event(
			reporter_module.DiagnosticEvent("task_completed", attributes={"task": f"task_{index}"})
		)
	assert path.exists()
	assert len(list(tmp_path.iterdir())) == 2


def test_reporter_rotates_oldest_records_to_bounded_backups(monkeypatch, tmp_path):
	path = configure_reporter(monkeypatch, tmp_path)
	monkeypatch.setattr(reporter_module.FileMetricsReporter, "MAX_LOG_BYTES", 150)
	monkeypatch.setattr(reporter_module.FileMetricsReporter, "BACKUP_COUNT", 2)
	reporter = reporter_module.FileMetricsReporter()
	for index in range(8):
		reporter.report_event(reporter_module.DiagnosticEvent("task_completed", attributes={"task": f"task_{index}"}))
	assert path.exists()
	backups = list(tmp_path.glob("metrics.jsonl.*"))
	assert len(backups) == 2
	for candidate in backups:
		for line in candidate.read_text(encoding="utf-8").splitlines():
			json.loads(line)


def test_reporter_instances_write_complete_json_lines_concurrently(monkeypatch, tmp_path):
	path = configure_reporter(monkeypatch, tmp_path)
	def write_event(index: int) -> None:
		reporter_module.FileMetricsReporter().report_event(
			reporter_module.DiagnosticEvent("task_completed", attributes={"task": f"task_{index}"})
		)
	with ThreadPoolExecutor(max_workers=8) as pool:
		list(pool.map(write_event, range(100)))
	records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
	assert len(records) == 100
	assert {record["attributes"]["task"] for record in records} == {f"task_{index}" for index in range(100)}
