"""Operator tool for the U2 storage-source migration (explicit, never automatic).

Commands::

    python -m platform_core.storage_source_migration_cli status --sqlite ... [--dsn ...]
    python -m platform_core.storage_source_migration_cli export --sqlite ... --out snapshot.json
    python -m platform_core.storage_source_migration_cli import --dsn ... --snapshot snapshot.json
    python -m platform_core.storage_source_migration_cli report --dsn ... --snapshot snapshot.json
    python -m platform_core.storage_source_migration_cli admit --dsn ... --sqlite ... \
        --operator ... --reason ... [--snapshot snapshot.json]
    python -m platform_core.storage_source_migration_cli finish --dsn ... --sqlite ...
    python -m platform_core.storage_source_migration_cli abort --sqlite ...

``admit`` is the only command that publishes the local admission record.  It runs
the fenced protocol in :mod:`platform_core.storage_source_cutover`: it blocks
SQLite writers, re-exports the current SQLite copy, imports and reconciles
PostgreSQL in one transaction, publishes the durable cutover row, and only then
writes the admission record atomically.  ``finish`` releases a transition that was
interrupted after publication; ``abort`` releases one that was never published.
Nothing here touches production unless an operator runs it against the production
DSN, and no command enables the PostgreSQL provider by itself.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .storage.source_repository import DEFAULT_SCOPE
from .storage_source_cutover import (
    abort_cutover,
    admit_cutover,
    cutover_status,
    finish_cutover,
    rollback_cutover,
    summarize_error,
)
from .storage_source_migration import (
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


def _reset_to_idle(connection) -> None:
    """Release any implicit read transaction before the fenced cutover starts.

    Psycopg opens a transaction for the first statement of a non-autocommit
    connection; the schema inspection is read-only, so the clean way back to IDLE
    is a rollback (never a commit of unrelated work).
    """
    from psycopg.pq import TransactionStatus

    if connection.info.transaction_status != TransactionStatus.IDLE:
        connection.rollback()


def _ensure_schema(connection) -> dict:
    from .storage_source_postgres_schema import ensure_schema, schema_status

    status = schema_status(connection)
    if not status["up_to_date"]:
        status = ensure_schema(connection, allow_upgrade=True)
    _reset_to_idle(connection)
    return status


def command_status(args) -> int:
    local = cutover_status(args.sqlite)
    payload = {
        "sqlite": local["sqlite_path"],
        "state": local["state"],
        "sqlite_writable": local["sqlite_writable"],
        "postgres_writable": local["postgres_writable"],
        "admission_record": local["admission_record"],
        "transition": local["transition"],
    }
    if args.dsn:
        with _connect(args.dsn) as connection:
            from .storage_source_postgres_schema import schema_status

            payload["schema"] = schema_status(connection)
            target = export_target_snapshot(connection, args.scope)
        payload["target"] = {
            "counts": target["counts"],
            "default": next(
                (row["id"] for row in target["rows"] if row["is_default"]), None
            ),
            "content_digest": target["content_digest"],
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
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
    print(
        json.dumps(
            {"imported": counters, "report": reconcile(snapshot, target)},
            ensure_ascii=False,
            indent=2,
        )
    )
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
    expected = None
    if args.snapshot:
        expected = str(_load_snapshot(args.snapshot)["content_digest"])
    with _connect(args.dsn) as connection:
        _ensure_schema(connection)
        result = admit_cutover(
            connection,
            args.sqlite,
            scope=args.scope,
            operator=args.operator,
            reason=args.reason,
            expected_source_digest=expected,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_finish(args) -> int:
    with _connect(args.dsn) as connection:
        result = finish_cutover(connection, args.sqlite)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_rollback(args) -> int:
    if not args.operator.strip() or not args.reason.strip():
        raise SystemExit("rollback requires --operator and --reason")
    expected = None
    if args.snapshot:
        expected = str(_load_snapshot(args.snapshot)["content_digest"])
    with _connect(args.dsn) as connection:
        _ensure_schema(connection)
        result = rollback_cutover(
            connection,
            args.sqlite,
            operator=args.operator,
            reason=args.reason,
            expected_target_digest=expected,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_abort(args) -> int:
    if args.dsn:
        with _connect(args.dsn) as connection:
            result = abort_cutover(args.sqlite, connection)
    else:
        result = abort_cutover(args.sqlite)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="storage_source_migration_cli",
        description="U2 storage-source metadata migration (fenced, idempotent).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="local cutover state and target status")
    status.add_argument("--sqlite", required=True)
    status.add_argument("--dsn", default="")
    status.add_argument("--scope", default=DEFAULT_SCOPE)
    status.set_defaults(handler=command_status)

    export = subparsers.add_parser("export", help="deterministic SQLite snapshot")
    export.add_argument("--sqlite", required=True)
    export.add_argument("--scope", default=DEFAULT_SCOPE)
    export.add_argument("--out", required=True)
    export.set_defaults(handler=command_export)

    import_command = subparsers.add_parser("import", help="idempotent import of a snapshot")
    import_command.add_argument("--dsn", required=True)
    import_command.add_argument("--snapshot", required=True)
    import_command.set_defaults(handler=command_import)

    report = subparsers.add_parser("report", help="reconcile a snapshot against the target")
    report.add_argument("--dsn", required=True)
    report.add_argument("--snapshot", required=True)
    report.set_defaults(handler=command_report)

    admit = subparsers.add_parser(
        "admit", help="fenced switch: re-export, import, reconcile and publish admission"
    )
    admit.add_argument("--dsn", required=True)
    admit.add_argument("--sqlite", required=True)
    admit.add_argument("--operator", required=True)
    admit.add_argument("--reason", required=True)
    admit.add_argument("--snapshot", default="")
    admit.add_argument("--scope", default=DEFAULT_SCOPE)
    admit.set_defaults(handler=command_admit)

    finish = subparsers.add_parser(
        "finish", help="release a published transition after proving its state"
    )
    finish.add_argument("--dsn", required=True)
    finish.add_argument("--sqlite", required=True)
    finish.set_defaults(handler=command_finish)

    rollback = subparsers.add_parser(
        "rollback",
        help="reverse switch: export PostgreSQL, import SQLite and publish SQLite authority",
    )
    rollback.add_argument("--dsn", required=True)
    rollback.add_argument("--sqlite", required=True)
    rollback.add_argument("--operator", required=True)
    rollback.add_argument("--reason", required=True)
    rollback.add_argument("--snapshot", default="")
    rollback.set_defaults(handler=command_rollback)

    abort = subparsers.add_parser(
        "abort", help="release an unpublished transition (SQLite stays writable)"
    )
    abort.add_argument("--sqlite", required=True)
    abort.add_argument(
        "--dsn", default="",
        help="needed when an interrupted switch froze the durable PostgreSQL phase",
    )
    abort.set_defaults(handler=command_abort)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as error:  # noqa: BLE001 - the CLI renders stable codes
        print(json.dumps(summarize_error(error), ensure_ascii=False))
        return 2


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    sys.exit(main())
