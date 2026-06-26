# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path


TESTS = [
    "test_preview_scale.py",
    "test_rip_core.py",
    "test_native_backend.py",
    "test_inkcalc.py",
    "test_halftone.py",
    "test_ppd_profiles.py",
    "test_plate_bits.py",
]


def run_test(test: str, timeout: float, root: Path) -> bool:
    started = time.perf_counter()
    module_name = test[:-3] if test.endswith(".py") else test
    runner = (
        "import faulthandler, os, sys, unittest; "
        "faulthandler.enable(); "
        "faulthandler.dump_traceback_later(float(sys.argv[2]), repeat=False, exit=True); "
        "suite = unittest.defaultTestLoader.loadTestsFromName(sys.argv[1]); "
        "result = unittest.TextTestRunner(verbosity=1).run(suite); "
        "sys.stdout.flush(); sys.stderr.flush(); "
        "os._exit(0 if result.wasSuccessful() else 1)"
    )
    cmd = [sys.executable, "-X", "faulthandler", "-c", runner, module_name, str(max(1.0, timeout - 1.0))]
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as stdout_file:
        stdout_path = Path(stdout_file.name)
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as stderr_file:
            stderr_path = Path(stderr_file.name)
            process = subprocess.Popen(
                cmd,
                cwd=str(root),
                text=True,
                stdout=stdout_file,
                stderr=stderr_file,
                close_fds=True,
            )
            try:
                return_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = None

    elapsed = time.perf_counter() - started
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
    stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
    _unlink_best_effort(stdout_path)
    _unlink_best_effort(stderr_path)

    if return_code is None:
        print(f"TIMEOUT {test} after {elapsed:.2f}s", flush=True)
        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, end="", file=sys.stderr)
        return False

    status = "OK" if return_code == 0 else "FAIL"
    print(f"{status} {test} code={return_code} time={elapsed:.2f}s", flush=True)
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="", file=sys.stderr)
    return return_code == 0


def _unlink_best_effort(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Run project tests with a per-file timeout.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per test-file timeout in seconds.")
    parser.add_argument("tests", nargs="*", default=TESTS, help="Optional test files to run.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ok = True
    for test in args.tests:
        ok = run_test(test, args.timeout, root) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
