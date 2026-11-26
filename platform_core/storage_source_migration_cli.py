"""Operator tool for the U2 storage-source migration (explicit, never automatic).

Commands::

    python -m platform_core.storage_source_migration_cli status --dsn ...
    python -m platform_core.storage_source_migration_cli export --sqlite ... --out snapshot.json
    python -m platform_core.storage_source_migration_cli import --dsn ... --snapshot snapshot.json
    python -m platform_core.storage_source_migration_cli report --dsn ... --snapshot snapshot.json
    python -m platform_core.storage_source_migration_cli admit --dsn ... --snapshot snapshot.json \
        --sqlite ... --operator ... --reason ...

``admit`` is the only command that writes the local admission record, and it
refuses unless the target reconciles exactly.  Nothing here touches production
unless an operator runs it against the production DSN.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .storage.source_repository import (
    CONTRACT_VERSION,
    DEFAULT_SCOPE,
    admission_record_path,
)
from .storage_source_migration import (
    StorageSourceMigrationError,
    export_snapshot,
    export_target_snapshot,
    import_snapshot,
    reconcile,
)


def _psycopg():
    try:
        import psycopg
    except ImportError as error:  # pragma: no cover - operator environment
        raise SystemExit("psycopg 3 is required: " + str(error)) from error
    return psycopg


def _connect(dsn: str):
    psycopg = _psycopg()
    from psycopg.rows import dict_row

    return psycopg.connect(dsn, row_factory=dict_row)


def _load_snapshot(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _ensure_schema(connection) -> dict:
    from .storage_source_postgres_schema import ensure_schema, schema_status

    status = schema_status(connection)
    if status["up_to_date"]:
        return status
    return ensure_schema(connection, allow_upgrade=True)


def _status(connection, scope: str) -> dict:
    from .storage_source_postgres_schema import schema_status

    source = None
    return {"scope": scope, "schema": schema_status(connection), "target": source}


def command_status(args) -> int:
    with _connect(args.dsn) as connection:
        status = _status(connection, args.scope)
        target = export_target_snapshot(connection, args.scope)
    print(
        json.dumps(
            {
                "scope": args.scope,
                "schema": status["schema"],
                "target_counts": target["counts"],
                "target_default": next(
                    (row["id"] for row in target["rows"] if row["is_default"]), None
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_export(args) -> int:
    snapshot = export_snapshot(args.sqlite, args.scope)
    Path(args.out).write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "written": args.out,
                "counts": snapshot["counts"],
                "content_digest": snapshot["content_digest"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_import(args) -> int:
    snapshot = _load_snapshot(args.snapshot)
    with _connect(args.dsn) as connection:
        _ensure_schema(connection)
        with connection.transaction():
            counters = import_snapshot(connection, snapshot)
        target = export_target_snapshot(connection, snapshot["scope"])
    print(json.dumps({"imported": counters, "report": reconcile(snapshot, target)}, ensure_ascii=False, indent=2))
    return 0


def command_report(args) -> int:
    snapshot = _load_snapshot(args.snapshot)
    with _connect(args.dsn) as connection:
        target = export_target_snapshot(connection, snapshot["scope"])
    report = reconcile(snapshot, target)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["same"] else 1


def command_admit(args) -> int:
    if not args.operator.strip() or not args.reason.strip():
        raise SystemExit("admit requires --operator and --reason")
    if not args.sqlite:
        raise SystemExit("admit requires --sqlite to bind the admission to a local owner")
    snapshot = _load_snapshot(args.snapshot)
    with _connect(args.dsn) as connection:
        _ensure_schema(connection)
        target = export_target_snapshot(connection, snapshot["scope"])
        report = reconcile(snapshot, target)
        if not report["same"]:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit("refusing to admit: the target does not reconcile")
        record_path = admission_record_path(args.sqlite)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "contract_version": CONTRACT_VERSION,
            "admission_id": uuid.uuid4().hex,
            "scope": str(snapshot["scope"]),
            "authoritative_provider": "postgresql",
            "source_count": int(snapshot["counts"]["sources"]),
            "content_digest": str(snapshot["content_digest"]),
            "writer_generation": 1,
            "admitted_at": datetime.now(timezone.utc).isoformat(),
            "revoked_at": None,
            "operator": args.operator.strip(),
            "reason": args.reason.strip(),
        }
        record_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps({"admitted": True, "record": str(record_path)}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="storage_source_migration_cli",
        description="U2 storage-source metadata migration (explicit, idempotent).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="schema and target source status")
    status.add_argument("--dsn", required=True)
    status.add_argument("--scope", default=DEFAULT_SCOPE)
    status.set_defaults(handler=command_status)

    export = subparsers.add_parser("export", help="deterministic SQLite snapshot")
    export.add_argument("--sqlite", required=True)
    export.add_argument("--scope", default=DEFAULT_SCOPE)
    export.add_argument("--out", required=True)
    export.set_defaults(handler=command_export)

    for name, handler, help_text in (
        ("import", command_import, "idempotent import of a snapshot"),
        ("report", command_report, "reconcile a snapshot against the target"),
        ("admit", command_admit, "write the local admission after a clean reconcile"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--dsn", required=True)
        command.add_argument("--snapshot", required=True)
        if name == "admit":
            command.add_argument("--sqlite", required=True)
            command.add_argument("--operator", required=True)
            command.add_argument("--reason", required=True)
        command.set_defaults(handler=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except StorageSourceMigrationError as error:
        print(json.dumps({"code": error.code, "detail": error.detail}, ensure_ascii=False))
        return 2


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    sys.exit(main())
