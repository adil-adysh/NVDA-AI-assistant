import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import load_addon_module

hf_cache = load_addon_module("core.hf_cache", namespace="hf_cache_tests")
CachedArtifact = hf_cache.CachedArtifact
cache_roots = hf_cache.cache_roots
read_gguf_metadata = hf_cache.read_gguf_metadata
scan_cached_artifacts = hf_cache.scan_cached_artifacts


def _string(value: str) -> bytes:
	raw = value.encode("utf-8")
	return struct.pack("<Q", len(raw)) + raw


def make_gguf(path: Path, metadata: dict[str, str], *, version: int = 3) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	parts = [b"GGUF", struct.pack("<I", version), struct.pack("<Q", 0), struct.pack("<Q", len(metadata))]
	for key, value in metadata.items():
		parts.extend([_string(key), struct.pack("<I", 8), _string(value)])
	path.write_bytes(b"".join(parts))


class HuggingFaceCacheTests(unittest.TestCase):
	def _cache(self, root: Path, models: dict[str, dict[str, str]], *, commit: str = "a" * 40) -> Path:
		repo = root / "models--org--model"
		(repo / "refs").mkdir(parents=True)
		(repo / "refs" / "main").write_text(commit + "\n", encoding="utf-8")
		snapshot = repo / "snapshots" / commit
		snapshot.mkdir(parents=True)
		for relative, metadata in models.items():
			make_gguf(snapshot / relative, metadata)
		return repo

	def test_reads_gguf_metadata_without_reading_tensors(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "model.gguf"
			make_gguf(path, {"general.architecture": "qwen3moe", "general.name": "Test"})
			self.assertEqual(read_gguf_metadata(path)["general.architecture"], "qwen3moe")

	def test_rejects_non_gguf_and_truncated_files(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "bad.gguf"
			path.write_bytes(b"NOTGGUF")
			with self.assertRaises(ValueError):
				read_gguf_metadata(path)

	def test_scan_uses_refs_main_snapshot_and_classifies_files(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			commit = "b" * 40
			repo = self._cache(root, {
				"model-Q4_K_M.gguf": {"general.architecture": "llama"},
				"dflash-draft-NVFP4.gguf": {"general.architecture": "llama"},
				"mmproj-F16.gguf": {"general.architecture": "clip"},
			}, commit=commit)
			older = repo / "snapshots" / ("c" * 40)
			older.mkdir()
			make_gguf(older / "wrong.gguf", {"general.architecture": "llama"})
			repositories = scan_cached_artifacts([root])
			self.assertEqual(len(repositories), 1)
			self.assertEqual(repositories[0].revision, commit)
			self.assertTrue(repositories[0].revision_confirmed)
			roles = {item.path: item.role for item in repositories[0].artifacts}
			self.assertEqual(roles["model-Q4_K_M.gguf"], "main")
			self.assertEqual(roles["dflash-draft-NVFP4.gguf"], "draft")
			self.assertEqual(roles["mmproj-F16.gguf"], "projector")
			self.assertNotIn("wrong.gguf", roles)
			model = next(item for item in repositories[0].artifacts if item.path == "model-Q4_K_M.gguf")
			self.assertEqual(model.quant, "Q4_K_M")

	def test_scan_falls_back_to_newest_snapshot_when_main_is_missing(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			repo = root / "models--org--model"
			(repo / "refs").mkdir(parents=True)
			snapshot = repo / "snapshots" / ("d" * 40)
			snapshot.mkdir(parents=True)
			make_gguf(snapshot / "model.gguf", {"general.architecture": "llama"})
			repositories = scan_cached_artifacts([root])
			self.assertEqual(len(repositories), 1)
			self.assertFalse(repositories[0].revision_confirmed)

	def test_scan_skips_malformed_and_broken_links(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			repo = self._cache(root, {"model.gguf": {"general.architecture": "llama"}})
			snapshot = repo / "snapshots" / ("a" * 40)
			try:
				(snapshot / "broken.gguf").symlink_to(snapshot / "missing.gguf")
			except OSError:
				pass
			(snapshot / "bad.gguf").write_bytes(b"GGUF" + b"\0" * 4)
			repositories = scan_cached_artifacts([root])
			self.assertEqual([item.path for item in repositories[0].artifacts], ["model.gguf"])

	def test_split_group_is_exposed_once_and_marks_completeness(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			self._cache(root, {
				"model-00001-of-00002.gguf": {"general.architecture": "llama"},
				"model-00002-of-00002.gguf": {"general.architecture": "llama"},
				"other-00001-of-00003.gguf": {"general.architecture": "llama"},
			})
			repositories = scan_cached_artifacts([root])
			artifacts = {item.path: item for item in repositories[0].artifacts}
			self.assertIn("model-00001-of-00002.gguf", artifacts)
			self.assertNotIn("model-00002-of-00002.gguf", artifacts)
			self.assertTrue(artifacts["model-00001-of-00002.gguf"].complete)
			self.assertEqual(artifacts["model-00001-of-00002.gguf"].parts, 2)
			self.assertFalse(artifacts["other-00001-of-00003.gguf"].complete)

	def test_cache_roots_honor_environment_and_dedupe(self) -> None:
		with tempfile.TemporaryDirectory() as directory:
			home = Path(directory) / "hf-home"
			explicit = Path(directory) / "explicit"
			with mock.patch.dict(os.environ, {"HF_HOME": str(home), "HF_HUB_CACHE": str(explicit)}, clear=False):
				roots = cache_roots()
			values = [str(path) for path in roots]
			self.assertIn(str((home / "hub").resolve()), values)
			self.assertIn(str(explicit.resolve()), values)
			self.assertEqual(len(values), len(set(values)))


if __name__ == "__main__":
	unittest.main()
