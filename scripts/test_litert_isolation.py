"""Isolation test for litert-lm runtime in a temp directory.

Verifies:
1. pip install --target to a temp dir
2. Import from sys.path injection
3. Minimum file set needed
4. Total size measurement
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def main():
    test_dir = Path(tempfile.mkdtemp(prefix="litert_test_"))
    target_dir = test_dir / "litert_runtime"
    print(f"Test directory: {test_dir}")
    print(f"Target install dir: {target_dir}")
    print()

    # --- Step 1: pip install litert-lm-api to target dir ---
    print("=== Step 1: pip install litert-lm-api to temp target ===")
    result = run([
        sys.executable, "-m", "pip", "install",
        "--target", str(target_dir),
        "--no-deps",  # litert-lm-api has zero deps, but be explicit
        "litert-lm-api==0.13.1",
    ])
    print(result.stdout[-500:] if result.stdout else "")
    if result.returncode != 0:
        print(f"STDERR: {result.stderr[-500:]}")
        print("FAILED: pip install")
        shutil.rmtree(test_dir)
        return 1
    print("pip install succeeded")
    print()

    # --- Step 2: List what was installed ---
    print("=== Step 2: Installed files ===")
    all_files = list(target_dir.rglob("*"))
    py_files = [f for f in all_files if f.suffix == ".py"]
    dll_files = [f for f in all_files if f.suffix == ".dll"]
    other = [f for f in all_files if f.suffix not in (".py", ".dll") and not f.is_dir()]
    
    print(f"  Total items: {len(all_files)}")
    print(f"  Python files: {len(py_files)}")
    for f in sorted(py_files):
        print(f"    {f.relative_to(target_dir)}")
    print(f"  DLL files: {len(dll_files)}")
    for f in sorted(dll_files):
        print(f"    {f.relative_to(target_dir)}")
    if other:
        print(f"  Other files: {len(other)}")
        for f in sorted(other):
            print(f"    {f.relative_to(target_dir)}")
    print()

    # --- Step 3: Measure size ---
    print("=== Step 3: Size measurement ===")
    total_size = sum(f.stat().st_size for f in all_files if f.is_file())
    dll_size = sum(f.stat().st_size for f in dll_files)
    py_size = sum(f.stat().st_size for f in py_files)
    print(f"  Total size: {total_size:,} bytes ({total_size / 1024 / 1024:.1f} MB)")
    print(f"  DLL size:   {dll_size:,} bytes ({dll_size / 1024 / 1024:.1f} MB)")
    print(f"  Python:     {py_size:,} bytes ({py_size / 1024:.0f} KB)")
    print()

    # --- Step 4: Import from sys.path injection ---
    print("=== Step 4: Test import from sys.path injection ===")
    sys.path.insert(0, str(target_dir))
    
    # Check if Windows can load the DLL
    target_dll = list(target_dir.rglob("litert-lm*.dll"))
    if target_dll:
        print(f"  Found DLLs: {[d.name for d in target_dll]}")
    
    try:
        import litert_lm
        print(f"  Imported litert_lm from: {litert_lm.__file__}")
        print(f"  Has Engine: {hasattr(litert_lm, 'Engine')}")
        print(f"  Has Conversation: {hasattr(litert_lm, 'Conversation')}")
        print(f"  Version info available: {hasattr(litert_lm, 'set_min_log_severity')}")
        
        # Check that the native lib loaded
        lib = litert_lm._ffi._get_lib()
        print(f"  Native library loaded: {lib}")
        print("  IMPORT SUCCESS")
    except Exception as e:
        print(f"  IMPORT FAILED: {e}")
        print()
        # Check for DLL load issues
        import ctypes
        try:
            dll_path = str(target_dir / "litert_lm" / "litert-lm.dll")
            if os.path.exists(dll_path):
                ctypes.CDLL(dll_path)
                print(f"  Direct ctypes load of {dll_path} succeeded")
            else:
                # Try in subdirectories
                for dll in target_dir.rglob("litert-lm.dll"):
                    ctypes.CDLL(str(dll))
                    print(f"  Direct ctypes load of {dll} succeeded")
        except Exception as dll_err:
            print(f"  Direct ctypes load also failed: {dll_err}")
        shutil.rmtree(test_dir)
        return 1
    finally:
        sys.path.remove(str(target_dir))
    print()

    # --- Step 5: Clean up ---
    shutil.rmtree(test_dir)
    print("=== All tests passed! ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
