"""CLI for the single-domain algorithm migration and cutover (T8.1-T8.3).

Usage::

    python -m platform_core.algorithm_migration_cli schema-status --dsn DSN
    python -m platform_core.algorithm_migration_cli schema-init --dsn DSN --allow-upgrade
    python -m platform_core.algorithm_migration_cli export --db DB --project ID --out FILE
    python -m platform_core.algorithm_migration_cli import --snapshot FILE --dsn DSN [--dry-run] [--resume]
    python -m platform_core.algorithm_migration_cli report --snapshot FILE --dsn DSN [--out FILE]
    python -m platform_core.algorithm_migration_cli verify --db DB --project ID --dsn DSN
    python -m platform_core.algorithm_migration_cli status --dsn DSN --project ID
    python -m platform_core.algorithm_migration_cli cutover-admit --db DB --project ID --dsn DSN \\
        --expected-generation N --operator NAME --reason TEXT [--acknowledge-unported]
    python -m platform_core.algorithm_migration_cli cutover-status --dsn DSN --project ID
    python -m platform_core.algorithm_migration_cli rollback-assess --db DB --dsn DSN [--admission FILE]
    python -m platform_core.algorithm_migration_cli rollback-execute --db DB --dsn DSN \\
        --operator NAME --reason TEXT --confirm

Exit codes: ``0`` success, ``1`` error, ``2`` usage, ``3`` refused by policy.
The DSN is read from ``--dsn``, ``ALGORITHM_MIGRATION_DSN`` or
``ALGORITHM_STORE_POSTGRES_DSN`` and is never echoed back.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .algorithm_cutover import (
    recover_maintenance,
    verify_maintenance_window,
    switch_maintenance_owner,
    resume_maintenance,
    freeze_maintenance_source,
    begin_maintenance_window,
    AlgorithmCutoverError,
    AlgorithmCutoverRefused,
    admit_cutover,
    assess_rollback,
    cutover_status,
    cutover_transition,
    rollback,
    write_admission_record,
)
from .algorithm_migration import (
    CONTRACT_VERSION_V2,
    export_source_snapshot_v2,
    AlgorithmMigrationError,
    build_report,
    content_digest,
    export_source_snapshot,
    import_snapshot,
    run_status,
)
from .algorithm_postgres_schema import (
    AlgorithmSchemaError,
    ensure_schema,
    schema_status,
)
from .algorithm_postgres_store import export_target_snapshot
from .algorithm_repository import (
    AlgorithmRepositoryError,
    admission_record_path,
    load_admission_record,
)
from .algorithm_shadow import (
    AlgorithmShadowError,
    load_snapshot,
    write_snapshot,
)
from .errors import PlatformError

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 3

_REFUSAL_VERDICTS = {"MISMATCH", "TARGET_MISSING"}


def _emit(value, *, stream=None) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str), file=stream or sys.stdout)


def _dsn(value: str | None) -> str:
    dsn = str(
        value
        or os.environ.get("ALGORITHM_MIGRATION_DSN")
        or os.environ.get("ALGORITHM_STORE_POSTGRES_DSN")
        or ""
    ).strip()
    if not dsn:
        raise AlgorithmMigrationError(
            "ALGORITHM_MIGRATION_DSN_MISSING",
            "PostgreSQL DSN is required",
            detail="pass --dsn or set ALGORITHM_MIGRATION_DSN",
        )
    return dsn


def _connect(dsn: str):
    try:
        import psycopg
    except ImportError as error:  # pragma: no cover - environment dependent
        raise AlgorithmMigrationError(
            "ALGORITHM_POSTGRES_DRIVER_MISSING",
            "psycopg 3 is required for PostgreSQL migration commands",
        ) from error
    return psycopg.connect(dsn)


def _record_path(args) -> Path:
    if getattr(args, "admission", None):
        return Path(args.admission)
    return admission_record_path(args.db)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="algorithm-migration")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("schema-status", help="show recorded schema version")
    status.add_argument("--dsn")

    init = sub.add_parser("schema-init", help="create or explicitly upgrade the schema")
    init.add_argument("--dsn")
    init.add_argument("--allow-upgrade", action="store_true")
    init.add_argument("--dry-run", action="store_true")
    init.add_argument("--actor", default="algorithm-migration-cli")

    export = sub.add_parser("export", help="export one project snapshot from SQLite")
    export.add_argument("--db", required=True)
    export.add_argument("--project", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--v2", action="store_true")

    imp = sub.add_parser("import", help="import one snapshot into PostgreSQL")
    imp.add_argument("--snapshot", required=True)
    imp.add_argument("--dsn")
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--resume", action="store_true")
    imp.add_argument("--actor", default="algorithm-migration-cli")
    imp.add_argument("--run-id")

    report = sub.add_parser("report", help="compare a snapshot file with PostgreSQL")
    report.add_argument("--snapshot", required=True)
    report.add_argument("--dsn")
    report.add_argument("--out")

    verify = sub.add_parser("verify", help="fresh source+target verification report")
    verify.add_argument("--db", required=True)
    verify.add_argument("--project", required=True)
    verify.add_argument("--dsn")
    verify.add_argument("--out")
    verify.add_argument("--v2", action="store_true")

    runs = sub.add_parser("status", help="import runs for a project")
    runs.add_argument("--dsn")
    runs.add_argument("--project", required=True)

    admit = sub.add_parser("cutover-admit", help="admit PostgreSQL as the only writer")
    admit.add_argument("--db", required=True)
    admit.add_argument("--project", required=True)
    admit.add_argument("--dsn")
    admit.add_argument("--expected-generation", type=int, required=True)
    admit.add_argument("--operator", required=True)
    admit.add_argument("--reason", required=True)
    admit.add_argument("--acknowledge-unported", action="store_true")
    admit.add_argument("--report", help="optional earlier report file to reject staleness")
    admit.add_argument("--admission", help="admission record path")

    recover = sub.add_parser(
        "maintenance-recover", help="idempotently finish or settle an interrupted window"
    )
    recover.add_argument("--db", required=True)
    recover.add_argument("--dsn")
    recover.add_argument("--project", required=True)
    recover.add_argument("--admission")
    recover.add_argument("--operation-id", default="")
    recover.add_argument("--operator", default="")
    recover.add_argument("--reason", default="")
    recover.add_argument("--acknowledge-unported", action="store_true")
    recover.add_argument("--apply", action="store_true")

    maintenance = sub.add_parser(
        "maintenance-status", help="persisted maintenance phase and next step"
    )
    maintenance.add_argument("--dsn")
    maintenance.add_argument("--project", required=True)
    maintenance.add_argument("--operation-id", default="")

    cutover = sub.add_parser("cutover-status", help="authoritative provider and generation")
    cutover.add_argument("--dsn")
    cutover.add_argument("--project", required=True)

    assess = sub.add_parser("rollback-assess", help="check reverse-restoration evidence")
    assess.add_argument("--db", required=True)
    assess.add_argument("--dsn")
    assess.add_argument("--admission")

    restore = sub.add_parser("rollback-execute", help="restore SQLite and revoke admission")
    restore.add_argument("--db", required=True)
    restore.add_argument("--dsn")
    restore.add_argument("--admission")
    restore.add_argument("--operator", required=True)
    restore.add_argument("--reason", required=True)
    restore.add_argument("--confirm", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "schema-status":
            with _connect(_dsn(args.dsn)) as connection:
                _emit(schema_status(connection))
            return EXIT_OK

        if args.command == "schema-init":
            with _connect(_dsn(args.dsn)) as connection:
                result = ensure_schema(
                    connection,
                    allow_upgrade=bool(args.allow_upgrade),
                    dry_run=bool(args.dry_run),
                    actor=args.actor,
                )
            _emit(result)
            return EXIT_OK

        if args.command == "export":
            snapshot = (
                export_source_snapshot_v2(args.db, args.project)
                if getattr(args, "v2", False) else
                export_source_snapshot(args.db, args.project)
            )
            path = write_snapshot(snapshot, args.out)
            _emit({
                "out": str(path),
                "project_id": snapshot["project_id"],
                "revision": snapshot["algorithm_revision"],
                "counts": snapshot["counts"],
                "snapshot_digest": snapshot["snapshot_digest"],
            })
            return EXIT_OK

        if args.command == "import":
            snapshot = load_snapshot(args.snapshot)
            with _connect(_dsn(args.dsn)) as connection:
                result = import_snapshot(
                    connection,
                    snapshot,
                    dry_run=bool(args.dry_run),
                    resume=bool(args.resume),
                    actor=args.actor,
                    run_id=args.run_id,
                )
            _emit(result)
            return EXIT_OK

        if args.command == "report":
            snapshot = load_snapshot(args.snapshot)
            with _connect(_dsn(args.dsn)) as connection:
                target = export_target_snapshot(
                    connection, snapshot["project_id"],
                    include_cleanup=str(snapshot.get("contract_version")) == CONTRACT_VERSION_V2,
                )
                report = build_report(snapshot, target, schema=schema_status(connection))
            if args.out:
                Path(args.out).write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            _emit(report)
            return EXIT_REFUSED if report["verdict"] in _REFUSAL_VERDICTS else EXIT_OK

        if args.command == "verify":
            snapshot = (
                export_source_snapshot_v2(args.db, args.project)
                if getattr(args, "v2", False) else
                export_source_snapshot(args.db, args.project)
            )
            with _connect(_dsn(args.dsn)) as connection:
                target = export_target_snapshot(
                    connection, args.project,
                    include_cleanup=str(snapshot.get("contract_version")) == CONTRACT_VERSION_V2,
                )
                report = build_report(snapshot, target, schema=schema_status(connection))
            if args.out:
                Path(args.out).write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            _emit(report)
            return EXIT_REFUSED if report["verdict"] != "OK" else EXIT_OK

        if args.command == "status":
            with _connect(_dsn(args.dsn)) as connection:
                _emit(run_status(connection, args.project))
            return EXIT_OK

        if args.command == "cutover-admit":
            previous = None
            if args.report:
                previous = json.loads(Path(args.report).read_text(encoding="utf-8"))
            record_path = _record_path(args)
            generation = int(args.expected_generation)
            # The whole switch runs inside one persisted maintenance window:
            # both providers block first (QUIESCING), the source snapshot is
            # frozen and verified, and only then does the admission switch the
            # writer. A crash at any step leaves a blocking, resumable phase
            # instead of two possible owners.
            with _connect(_dsn(args.dsn)) as connection:
                window = begin_maintenance_window(
                    connection,
                    project_id=args.project,
                    db_path=args.db,
                    record_path=record_path,
                    expected_generation=generation,
                    operator=args.operator,
                    reason=args.reason,
                )
                frozen = freeze_maintenance_source(
                    connection,
                    project_id=args.project,
                    db_path=args.db,
                    operation_id=window["operation_id"],
                )
                # Final import of the *frozen* source, then a real
                # reconciliation of source against target. The verification
                # digest is the reconciliation summary, never the frozen source
                # digest copied across: a shadow import that fell behind a
                # later legitimate SQLite write is caught here.
                final_snapshot = export_source_snapshot(args.db, args.project)
                # The frozen *content* is what must not move; snapshot_digest is
                # the snapshot contract digest and changes with every export.
                frozen_content = str(
                    frozen.get("content_digest") or frozen.get("snapshot_digest") or ""
                )
                if not frozen_content or content_digest(final_snapshot) != frozen_content:
                    raise AlgorithmCutoverError(
                        "ALGORITHM_MAINTENANCE_SOURCE_MOVED",
                        "the source changed after the final freeze",
                    )
                import_snapshot(
                    connection,
                    final_snapshot,
                    actor=args.operator or "cutover",
                    run_id=window["operation_id"],
                    maintenance_operation=window["operation_id"],
                )
                target_snapshot = export_target_snapshot(connection, args.project)
                reconciliation = build_report(
                    final_snapshot, target_snapshot, schema=schema_status(connection)
                )
                if reconciliation.get("verdict") != "OK":
                    raise AlgorithmCutoverError(
                        "ALGORITHM_MAINTENANCE_RECONCILIATION_FAILED",
                        "source and target do not reconcile; the window stays blocked",
                        detail=json.dumps(
                            reconciliation.get("conditions") or [],
                            ensure_ascii=False,
                        )[:800],
                    )
                verify_maintenance_window(
                    connection,
                    project_id=args.project,
                    operation_id=window["operation_id"],
                    verification_digest=str(reconciliation["summary_digest"]),
                )
                result = switch_maintenance_owner(
                    connection,
                    project_id=args.project,
                    db_path=args.db,
                    record_path=record_path,
                    operation_id=window["operation_id"],
                    expected_generation=generation,
                    operator=args.operator,
                    reason=args.reason,
                    acknowledge_unported=bool(args.acknowledge_unported),
                    previous_report=previous,
                )
            result.pop("report", None)
            _emit(result)
            return EXIT_OK

        if args.command == "maintenance-recover":
            # Explicitly authorised execution; without --apply it is a status read.
            with _connect(_dsn(args.dsn)) as connection:
                _emit(
                    recover_maintenance(
                        connection,
                        project_id=args.project,
                        db_path=args.db,
                        record_path=_record_path(args),
                        operation_id=args.operation_id or None,
                        operator=args.operator,
                        reason=args.reason,
                        acknowledge_unported=bool(args.acknowledge_unported),
                        apply=bool(args.apply),
                    )
                )
            return EXIT_OK

        if args.command == "maintenance-status":
            # Repeatable recovery entry: reports the persisted phase and the next
            # step, and settles only when the phase and the admission agree.
            with _connect(_dsn(args.dsn)) as connection:
                _emit(
                    resume_maintenance(
                        connection,
                        project_id=args.project,
                        record_path=_record_path(args),
                        operation_id=args.operation_id or None,
                    )
                )
            return EXIT_OK

        if args.command == "cutover-status":
            with _connect(_dsn(args.dsn)) as connection:
                _emit(cutover_status(connection, args.project))
            return EXIT_OK

        if args.command == "rollback-assess":
            admission = load_admission_record(_record_path(args))
            if admission is None:
                raise AlgorithmCutoverError(
                    "ALGORITHM_ROLLBACK_ADMISSION_MISSING",
                    "no admission record; reverse restoration stays blocked",
                )
            with _connect(_dsn(args.dsn)) as connection:
                assessment = assess_rollback(
                    connection, db_path=args.db, admission=admission
                )
            _emit(assessment)
            return EXIT_OK if assessment["allowed"] else EXIT_REFUSED

        if args.command == "rollback-execute":
            with _connect(_dsn(args.dsn)) as connection:
                result = rollback(
                    connection,
                    db_path=args.db,
                    admission_path=_record_path(args),
                    confirmed=bool(args.confirm),
                    operator=args.operator,
                    reason=args.reason,
                )
            _emit(result)
            return EXIT_OK if result.get("rolled_back") else EXIT_REFUSED

        return 2
    except AlgorithmCutoverRefused as error:
        # A policy refusal (stale generation, window already open, admission
        # gate not met) is the documented exit code 3, not an internal error.
        _emit({
            "refused": getattr(error, "code", type(error).__name__),
            "message": str(error),
            "detail": getattr(error, "detail", ""),
        }, stream=sys.stderr)
        return EXIT_REFUSED
    except (
        AlgorithmMigrationError,
        AlgorithmCutoverError,
        AlgorithmSchemaError,
        AlgorithmShadowError,
        AlgorithmRepositoryError,
        PlatformError,
    ) as error:
        _emit({
            "error": getattr(error, "code", type(error).__name__),
            "message": str(error),
            "detail": getattr(error, "detail", ""),
        }, stream=sys.stderr)
        return EXIT_ERROR
    except Exception as error:  # pragma: no cover - defensive CLI surface
        _emit({
            "error": type(error).__name__,
            "message": str(error),
        }, stream=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
