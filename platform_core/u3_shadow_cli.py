"""Operator CLI for the U3 shadow migration (read-only source, isolated target)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .u3_shadow import (
    U3MigrationError,
    export_project_snapshot,
    import_project_snapshot,
    read_target_snapshot,
    reconcile,
    schema_checksum,
)


def _connect(dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as error:  # pragma: no cover - operator environment
        raise SystemExit("psycopg 3 is required: " + str(error)) from error
    return psycopg.connect(dsn, row_factory=dict_row)


def command_export(args) -> int:
    snapshot = export_project_snapshot(args.project_dir, args.project)
    Path(args.out).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"written": args.out, "counts": snapshot["counts"],
                      "content_digest": snapshot["content_digest"],
                      "revisions": snapshot["revisions"]}, ensure_ascii=False, indent=2))
    return 0


def command_import(args) -> int:
    """Import one snapshot file.

    Trust boundary: the file is read as-is and the import can only prove that the
    snapshot is structurally complete and self-consistent (counts, digests,
    content_digest, table_state). It cannot prove where the file came from, so
    this entry point is an internal controlled-ops path: use a snapshot produced
    by ``u3_shadow_cli export`` from the authoritative SQLite owners. There is no
    cryptographic signature or key management in this build.
    """
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    with _connect(args.dsn) as connection:
        counters = import_project_snapshot(connection, snapshot)
        target = read_target_snapshot(connection, snapshot["project_id"])
    print(json.dumps({"imported": counters, "report": reconcile(snapshot, target)},
                     ensure_ascii=False, indent=2))
    return 0


def command_report(args) -> int:
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    with _connect(args.dsn) as connection:
        target = read_target_snapshot(connection, snapshot["project_id"])
    report = reconcile(snapshot, target)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["same"] else 1


def command_status(args) -> int:
    print(json.dumps({"schema_checksum": schema_checksum(),
                      "project": args.project, "project_dir": args.project_dir}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="u3_shadow_cli",
        description="U3 materials/GT/negative-pool shadow migration (never writes production).")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--project-dir", required=True)
    status.add_argument("--project", required=True)
    status.set_defaults(handler=command_status)
    export = sub.add_parser("export")
    export.add_argument("--project-dir", required=True)
    export.add_argument("--project", required=True)
    export.add_argument("--out", required=True)
    export.set_defaults(handler=command_export)
    for name, handler in (("import", command_import), ("report", command_report)):
        command = sub.add_parser(name)
        command.add_argument("--dsn", required=True)
        command.add_argument("--snapshot", required=True)
        command.set_defaults(handler=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (U3MigrationError, Exception) as error:  # noqa: BLE001 - CLI boundary
        code = getattr(error, "code", type(error).__name__)
        print(json.dumps({"code": code, "detail": getattr(error, "detail", str(error))},
                         ensure_ascii=False))
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
