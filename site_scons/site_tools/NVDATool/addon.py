import zipfile
from collections.abc import Iterable
from pathlib import Path


def isTestArtifact(path: Path) -> bool:
	"""Return whether an add-on-relative path belongs to the test toolchain.

	This is an unconditional packaging boundary.  The caller's configurable
	exclusions remain useful for project-specific files, but tests must never
	enter a distributable add-on even if that configuration is changed.
	"""
	parts = tuple(part.casefold() for part in path.parts)
	name = parts[-1] if parts else ""
	return (
		any(part in {"test", "tests", "__pycache__", ".pytest_cache"} for part in parts[:-1])
		or name == "conftest.py"
		or name.startswith("test_")
		or name.endswith("_test.py")
		or name.endswith((".pyc", ".pyo"))
	)



def matchesNoPatterns(path: Path, patterns: Iterable[str]) -> bool:
	"""Checks if the path, the first argument, does not match any of the patterns passed as the second argument."""
	return not any((path.match(pattern) for pattern in patterns))


def createAddonBundleFromPath(path: str | Path, dest: str, excludePatterns: Iterable[str]):
	"""Creates a bundle from a directory that contains an addon manifest file."""
	if isinstance(path, str):
		path = Path(path)
	basedir = path.absolute()
	with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
		for p in basedir.rglob("*"):
			if p.is_dir():
				continue
			pathInBundle = p.relative_to(basedir)
			if not isTestArtifact(pathInBundle) and matchesNoPatterns(pathInBundle, excludePatterns):
				z.write(p, pathInBundle)
	return dest
