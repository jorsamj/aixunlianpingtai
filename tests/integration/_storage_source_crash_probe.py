"""Real process-termination probe for the storage-source cutover (SIGKILL).

Run as a subprocess by ``tests/integration/test_storage_source_postgres.py``.
The process terminates itself abruptly (SIGKILL on POSIX, TerminateProcess on
Windows) at one precise protocol point, so the parent can verify the *persisted*
state and the recovery path without any cleanup running.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys


def _abrupt_exit() -> None:  # pragma: no cover - the process dies here
    sig = getattr(signal, "SIGKILL", signal.SIGTERM)
    os.kill(os.getpid(), sig)
    os._exit(9)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--sqlite", required=True)
    parser.add_argument(
        "--phase",
        required=True,
        choices=("before_commit", "after_commit_before_record", "after_record_before_marker"),
    )
    args = parser.parse_args(argv)

    import psycopg

    from platform_core import storage_source_cutover as cutover

    if args.phase == "before_commit":
        def die(*_args, **_kwargs):
            _abrupt_exit()

        cutover.import_snapshot = die
    elif args.phase == "after_commit_before_record":
        real_write = cutover._write_json_atomic

        def die(path, payload):
            if path.name == "cutover_admission.json":
                _abrupt_exit()
            return real_write(path, payload)

        cutover._write_json_atomic = die
    else:
        real_write = cutover._write_json_atomic

        def die(path, payload):
            if path.name.endswith(".transition") and str(
                payload.get("phase")
            ) == "POSTGRES_ACTIVE":
                _abrupt_exit()
            return real_write(path, payload)

        cutover._write_json_atomic = die

    with psycopg.connect(args.dsn) as connection:
        cutover.admit_cutover(
            connection,
            args.sqlite,
            operator="crash-probe",
            reason=args.phase,
        )
    print("probe finished without being killed", file=sys.stderr)
    return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
