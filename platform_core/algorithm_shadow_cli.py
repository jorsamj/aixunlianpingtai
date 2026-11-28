"""Small read-only-first CLI for the W5 algorithm shadow.

Usage:
  python -m platform_core.algorithm_shadow_cli export --db PATH --project ID --out FILE
  python -m platform_core.algorithm_shadow_cli validate --snapshot FILE
  python -m platform_core.algorithm_shadow_cli import --snapshot FILE --dsn DSN
  python -m platform_core.algorithm_shadow_cli reconcile --snapshot FILE --dsn DSN --project ID
  python -m platform_core.algorithm_shadow_cli inspect --dsn DSN --project ID
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .algorithm_shadow import (
    AlgorithmShadowError,
    export_snapshot_from_path,
    import_snapshot,
    load_shadow_snapshot,
    load_snapshot,
    reconcile,
    write_snapshot,
)


def _postgres(dsn: str):
    try:
        import psycopg
    except ImportError as error:
        raise AlgorithmShadowError(
            "ALGORITHM_SHADOW_PSYCOPG_MISSING",
            "psycopg is required for PostgreSQL shadow commands",
        ) from error
    return psycopg.connect(dsn)


def _dsn(value: str | None) -> str:
    dsn = str(value or os.environ.get("ALGORITHM_SHADOW_DSN") or "").strip()
    if not dsn:
        raise AlgorithmShadowError(
            "ALGORITHM_SHADOW_DSN_MISSING",
            "PostgreSQL DSN is required through --dsn or ALGORITHM_SHADOW_DSN",
        )
    return dsn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="algorithm-shadow")
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export")
    export.add_argument("--db", required=True, help="existing algorithms.sqlite3")
    export.add_argument("--project", required=True)
    export.add_argument("--out", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--snapshot", required=True)

    imp = sub.add_parser("import")
    imp.add_argument("--snapshot", required=True)
    imp.add_argument("--dsn", help="isolated PostgreSQL DSN; else ALGORITHM_SHADOW_DSN")

    rec = sub.add_parser("reconcile")
    rec.add_argument("--snapshot", required=True)
    rec.add_argument("--dsn", help="isolated PostgreSQL DSN; else ALGORITHM_SHADOW_DSN")
    rec.add_argument("--project", required=True)

    inspect = sub.add_parser("inspect")
    inspect.add_argument("--dsn", help="isolated PostgreSQL DSN; else ALGORITHM_SHADOW_DSN")
    inspect.add_argument("--project", required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "export":
            snapshot = export_snapshot_from_path(args.db, args.project)
            path = write_snapshot(snapshot, args.out)
            print(json.dumps({"out": str(path), "revision": snapshot["algorithm_revision"],
                              "digest": snapshot["snapshot_digest"]}, ensure_ascii=False))
            return 0
        if args.command == "validate":
            snapshot = load_snapshot(args.snapshot)
            print(json.dumps({"valid": True, "revision": snapshot["algorithm_revision"],
                              "counts": snapshot["counts"], "digest": snapshot["snapshot_digest"]},
                             ensure_ascii=False))
            return 0
        if args.command == "import":
            snapshot = load_snapshot(args.snapshot)
            with _postgres(_dsn(args.dsn)) as connection:
                changed = import_snapshot(connection, snapshot)
            print(json.dumps({"imported": bool(changed), "revision": snapshot["algorithm_revision"],
                              "digest": snapshot["snapshot_digest"]}, ensure_ascii=False))
            return 0
        if args.command == "reconcile":
            source = load_snapshot(args.snapshot)
            with _postgres(_dsn(args.dsn)) as connection:
                shadow = load_shadow_snapshot(connection, args.project)
            print(json.dumps(reconcile(source, shadow), ensure_ascii=False))
            return 0
        if args.command == "inspect":
            with _postgres(_dsn(args.dsn)) as connection:
                shadow = load_shadow_snapshot(connection, args.project)
            print(json.dumps({"found": shadow is not None,
                              "revision": shadow.get("algorithm_revision") if shadow else None,
                              "digest": shadow.get("snapshot_digest") if shadow else None,
                              "counts": shadow.get("counts") if shadow else None},
                             ensure_ascii=False))
            return 0
        return 2
    except AlgorithmShadowError as error:
        print(json.dumps({"error": error.code, "message": str(error), "detail": error.detail},
                         ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
