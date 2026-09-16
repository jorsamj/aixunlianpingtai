from __future__ import annotations

import subprocess
import sys


COMMON = ["-m", "pytest", "--disable-plugin-autoload", "--confcutdir=tests/unit", "-q"]
CASES = [
    (
        "import-cache",
        ["-c", "import platform_core.training_bundle_cache; print('IMPORT_CACHE_OK')"],
    ),
    (
        "import-training-tasks",
        ["-c", "import platform_core.training_tasks; print('IMPORT_TRAINING_TASKS_OK')"],
    ),
    (
        "isolation-only",
        [*COMMON, "--basetemp=.diag-isolation", "tests/unit/test_training_bundle_isolation.py"],
    ),
    (
        "cache-only",
        [*COMMON, "--basetemp=.diag-cache", "tests/unit/test_training_bundle_cache.py"],
    ),
    (
        "combined",
        [
            *COMMON,
            "--basetemp=.diag-combined",
            "tests/unit/test_training_bundle_isolation.py",
            "tests/unit/test_training_bundle_cache.py",
        ],
    ),
    (
        "pytest-main-return",
        [
            "-c",
            "import pytest; "
            "args=['--disable-plugin-autoload','--confcutdir=tests/unit','--basetemp=.diag-main','-q',"
            "'tests/unit/test_training_bundle_isolation.py','tests/unit/test_training_bundle_cache.py']; "
            "code=pytest.main(args); print(f'PYTEST_MAIN_RETURN={int(code)}'); raise SystemExit(int(code))",
        ],
    ),
]


def main() -> int:
    observed = {}
    for name, args in CASES:
        print(f"\n===== DIAG {name} =====", flush=True)
        completed = subprocess.run(
            [sys.executable, *args],
            text=True,
            capture_output=True,
            check=False,
        )
        observed[name] = completed.returncode
        if completed.stdout:
            print("--- stdout ---", flush=True)
            print(completed.stdout, flush=True)
        if completed.stderr:
            print("--- stderr ---", flush=True)
            print(completed.stderr, flush=True)
        print(f"DIAG_RETURN_CODE[{name}]={completed.returncode}", flush=True)
    print("\n===== DIAG SUMMARY =====", flush=True)
    for name, returncode in observed.items():
        print(f"{name}: {returncode}", flush=True)
    # Diagnostic workflow must finish after recording every child result. The
    # permanent gate remains fail-closed and is not changed by this helper.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
