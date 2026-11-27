"""U3 shadow schema: authentic v1/v2 -> v3 upgrades (data preserving)."""
from __future__ import annotations

import pathlib
import tempfile

import pytest


def _require_or_skip(module_name: str, reason: str):
    import importlib
    import os

    try:
        return importlib.import_module(module_name)
    except ImportError:
        if os.environ.get("MC_REQUIRE_POSTGRES", "").strip() == "1":
            raise RuntimeError(f"MC_REQUIRE_POSTGRES=1 but {module_name} is unavailable: {reason}")
        pytest.skip(reason, allow_module_level=True)


psycopg = _require_or_skip("psycopg", "psycopg 3 is required for PostgreSQL contracts")

from platform_core.u3_shadow import (
    CONTRACT_VERSION,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    U3MigrationError,
    _SCHEMA_V1,
    _SCHEMA_V2,
    ensure_schema,
    import_project_snapshot,
    read_target_snapshot,
    schema_checksum,
    schema_checksum_for,
)


class _ExternalPostgres:
    def __init__(self, dsn: str):
        self._dsn = dsn

    def get_uri(self) -> str:
        return self._dsn

    def cleanup(self) -> None:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")
                connection.commit()
        except Exception:
            pass


@pytest.fixture(scope="module")
def pg():
    import os

    external = os.environ.get("MC_TEST_POSTGRES_DSN", "").strip()
    if external:
        server = _ExternalPostgres(external)
        yield server
        server.cleanup()
        return
    pgserver = _require_or_skip("pgserver", "an isolated local PostgreSQL server is required")
    root = pathlib.Path(tempfile.mkdtemp(prefix="pgw3up-")) / "data"
    server = pgserver.get_server(root, cleanup_mode="delete")
    yield server
    server.cleanup()


def _exec(cursor, script: str) -> None:
    for part in [piece for piece in script.split(";") if piece.strip()]:
        cursor.execute(part)


def _seed(cursor, *, v1_refs: bool, conflict: bool = False, orphan: bool = False) -> None:
    cursor.execute(
        f"INSERT INTO {SCHEMA_NAME}.material(project_id,id,filename,payload) "
        "VALUES ('p1','m-old','old.jpg','{}'::jsonb)"
    )
    cursor.execute(
        f"INSERT INTO {SCHEMA_NAME}.material_label(project_id,material_id,label_code,box_count) "
        "VALUES ('p1','m-old','fire',2)"
    )
    cursor.execute(
        f"INSERT INTO {SCHEMA_NAME}.annotation(project_id,image_id,annotation_state,version,"
        "content_digest,boxes,scope) VALUES ('p1','m-old','annotated',4,'digest','[]'::jsonb,'[]'::jsonb)"
    )
    cursor.execute(
        f"INSERT INTO {SCHEMA_NAME}.negative_pool_category(project_id,id,name,enabled) "
        "VALUES ('p1','cat-1','FIRE',1)"
    )
    cursor.execute(
        f"INSERT INTO {SCHEMA_NAME}.negative_pool_member(project_id,material_id,joined_at) "
        "VALUES ('p1','m-old','2026-01-01')"
    )
    if v1_refs:
        # Two source kinds on different identities, plus (optionally) one identity
        # that v1 stored twice -- which cannot map to the v2 key.
        for image_id, label, kind in (("m-old", "fire", "sqlite"), ("m-old", "smoke", "legacy")):
            cursor.execute(
                f"INSERT INTO {SCHEMA_NAME}.annotation_label_reference"
                "(project_id,image_id,label_code,source_kind) VALUES ('p1',%s,%s,%s)",
                (image_id, label, kind),
            )
        if conflict:
            cursor.execute(
                f"INSERT INTO {SCHEMA_NAME}.annotation_label_reference"
                "(project_id,image_id,label_code,source_kind) VALUES ('p1','m-old','fire','legacy')"
            )
    else:
        for label in ("fire", "smoke"):
            cursor.execute(
                f"INSERT INTO {SCHEMA_NAME}.annotation_label_reference"
                "(project_id,image_id,label_code,box_count,scope_ref,annotation_state,source_kind) "
                "VALUES ('p1','m-old',%s,1,0,'annotated','sqlite')",
                (label,),
            )
    cursor.execute(
        f"INSERT INTO {SCHEMA_NAME}.negative_pool_link(project_id,material_id,category_id) "
        "VALUES ('p1','m-old',%s)",
        ("cat-missing" if orphan else "cat-1",),
    )


def _build(connection, schema: str, versions: tuple[int, ...], **seed) -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")
            _exec(cursor, schema)
            for version in versions:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.schema_migration(version,name,checksum,applied_by) "
                    "VALUES (%s,%s,%s,'test')",
                    (version, f"u3-material-gt-v{version}", schema_checksum_for(version)),
                )
            _seed(cursor, v1_refs=version_uses_v1_refs(schema), **seed)


def version_uses_v1_refs(schema: str) -> bool:
    return "label_code, source_kind" in schema


def _assert_upgraded(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT version,checksum FROM {SCHEMA_NAME}.schema_migration ORDER BY version"
        )
        rows = cursor.fetchall()
        assert [int(row[0]) for row in rows] == [1, 2, 3]
        for version, checksum in rows:
            assert str(checksum) == schema_checksum_for(int(version))
        cursor.execute(f"SELECT id,filename FROM {SCHEMA_NAME}.material WHERE project_id='p1'")
        assert cursor.fetchone() == ("m-old", "old.jpg")
        cursor.execute(
            f"SELECT label_code,box_count FROM {SCHEMA_NAME}.material_label WHERE project_id='p1'"
        )
        assert cursor.fetchone() == ("fire", 2)
        cursor.execute(f"SELECT version FROM {SCHEMA_NAME}.annotation WHERE project_id='p1'")
        assert cursor.fetchone() == (4,)
        cursor.execute(
            f"SELECT count(*) FROM {SCHEMA_NAME}.negative_pool_link WHERE project_id='p1'"
        )
        assert cursor.fetchone()[0] == 1
        # Both pool-link foreign keys exist after the upgrade.
        cursor.execute(
            "SELECT conname,confupdtype,confdeltype FROM pg_constraint "
            "WHERE conrelid = (%s)::regclass AND contype='f' ORDER BY conname",
            (f"{SCHEMA_NAME}.negative_pool_link",),
        )
        fks = cursor.fetchall()
        assert len(fks) == 2, fks
        assert all(str(fk[2]) == "c" for fk in fks), fks  # ON DELETE CASCADE
        # v3 uniqueness uses the locale-independent ASCII fold.
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname=%s "
            "AND indexname='uq_negative_pool_category_name'",
            (SCHEMA_NAME,),
        )
        indexdef = str(cursor.fetchone()[0])
        assert 'COLLATE "C"' in indexdef and "lower(" in indexdef, indexdef
        with pytest.raises(Exception):
            with connection.transaction():
                with connection.cursor() as inner:
                    inner.execute(
                        f"INSERT INTO {SCHEMA_NAME}.negative_pool_category"
                        "(project_id,id,name,enabled) VALUES ('p1','cat-2','fire',1)"
                    )
        with connection.transaction():
            with connection.cursor() as inner:
                inner.execute(
                    f"INSERT INTO {SCHEMA_NAME}.negative_pool_category"
                    "(project_id,id,name,enabled) VALUES ('p1','cat-3',%s,1),"
                    "('p1','cat-4',%s,1)",
                    ("\u00c4", "\u00e4"),
                )


def test_v1_upgrades_to_v3_preserving_reference_evidence(pg):
    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V1, (1,))
        assert ensure_schema(connection)["version"] == SCHEMA_VERSION
        _assert_upgraded(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT image_id,label_code,source_kind FROM {SCHEMA_NAME}."
                "annotation_label_reference_legacy ORDER BY label_code"
            )
            assert cursor.fetchall() == [("m-old", "fire", "sqlite"), ("m-old", "smoke", "legacy")]
            cursor.execute(
                f"SELECT image_id,label_code,box_count,scope_ref,annotation_state "
                f"FROM {SCHEMA_NAME}.annotation_label_reference ORDER BY label_code"
            )
            # Counters keep the documented v1 default (0); the state comes from GT.
            assert cursor.fetchall() == [
                ("m-old", "fire", 0, 0, "annotated"),
                ("m-old", "smoke", 0, 0, "annotated"),
            ]
        # Idempotent: a second run changes nothing.
        assert ensure_schema(connection)["version"] == SCHEMA_VERSION


def test_v1_reference_conflict_is_refused_not_deduplicated(pg):
    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V1, (1,), conflict=True)
        with pytest.raises(U3MigrationError) as conflict:
            ensure_schema(connection)
        assert conflict.value.code == "U3_UPGRADE_REFERENCE_CONFLICT"
        # Rolled back: the v1 table and both original rows are still there.
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT count(*) FROM {SCHEMA_NAME}.annotation_label_reference"
            )
            assert cursor.fetchone()[0] == 3
            cursor.execute(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema=%s "
                "AND table_name='annotation_label_reference' AND column_name='box_count'",
                (SCHEMA_NAME,),
            )
            assert cursor.fetchone()[0] == 0


def test_v1_pool_link_with_missing_category_is_refused(pg):
    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V1, (1,), orphan=True)
        with pytest.raises(U3MigrationError) as orphan:
            ensure_schema(connection)
        assert orphan.value.code == "U3_UPGRADE_LINK_ORPHAN"


def test_real_v2_upgrades_to_v3_with_both_foreign_keys(pg):
    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V2, (1, 2))
        assert ensure_schema(connection)["version"] == SCHEMA_VERSION
        _assert_upgraded(connection)
        with connection.cursor() as cursor:
            # Category deletion cascades the link...
            with connection.transaction():
                cursor.execute(
                    f"DELETE FROM {SCHEMA_NAME}.negative_pool_category "
                    "WHERE project_id='p1' AND id='cat-1'"
                )
            cursor.execute(
                f"SELECT count(*) FROM {SCHEMA_NAME}.negative_pool_link WHERE project_id='p1'"
            )
            assert cursor.fetchone()[0] == 0
            # ...and so does the material (member, link, algorithm membership).
            with connection.transaction():
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.negative_pool_category"
                    "(project_id,id,name,enabled) VALUES ('p1','cat-9','nine',1)"
                )
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.negative_pool_link"
                    "(project_id,material_id,category_id) VALUES ('p1','m-old','cat-9')"
                )
                cursor.execute(
                    f"DELETE FROM {SCHEMA_NAME}.material WHERE project_id='p1' AND id='m-old'"
                )
            for table in ("negative_pool_member", "negative_pool_link", "material_label"):
                cursor.execute(f"SELECT count(*) FROM {SCHEMA_NAME}.{table} WHERE project_id='p1'")
                assert cursor.fetchone()[0] == 0, table


def test_tampered_or_unknown_versions_are_refused(pg):
    for version in (1, 2, 3):
        with psycopg.connect(pg.get_uri()) as connection:
            _build(connection, _SCHEMA_V1, (1,))
            ensure_schema(connection)
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"UPDATE {SCHEMA_NAME}.schema_migration SET checksum=%s WHERE version=%s",
                        ("0" * 64, version),
                    )
            with pytest.raises(U3MigrationError) as tampered:
                ensure_schema(connection)
            assert tampered.value.code == "U3_SCHEMA_CHECKSUM_MISMATCH"

    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V1, (1,))
        ensure_schema(connection)
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.schema_migration"
                    "(version,name,checksum,applied_by) VALUES (99,'future',%s,'test')",
                    ("1" * 64,),
                )
        with pytest.raises(U3MigrationError) as newer:
            ensure_schema(connection)
        assert newer.value.code == "U3_SCHEMA_NEWER_THAN_TOOL"

def _snapshot(references, *, materials=None):
    """Minimal authoritative snapshot (as exported from a SQLite project)."""
    return {
        "contract_version": CONTRACT_VERSION,
        "project_id": "p1",
        "stores": {
            "materials": {
                "materials": materials or [],
                "material_labels": [{"material_id": "m-old", "label_code": "fire", "box_count": 2}],
                "material_annotation_scopes": [{"material_id": "m-old", "label_code": "fire"}],
                "negative_pool_members": [{"material_id": "m-old", "joined_at": "2026-01-01"}],
                "negative_pool_categories": [{"id": "cat-1", "name": "FIRE", "enabled": 1}],
                "negative_pool_links": [{"material_id": "m-old", "category_id": "cat-1"}],
                "negative_pool_algorithm_members": [],
                "evidence": {},
            },
            "annotations": {
                "annotations": [
                    {"image_id": "m-old", "annotation_state": "annotated", "version": 4,
                     "content_digest": "digest", "boxes": [], "scope": []},
                ],
                "annotation_label_references": references,
                "evidence": {},
            },
        },
        "revisions": {"materials": 1, "annotations": 1, "negative_pool": 0},
    }


def test_v1_upgrade_keeps_source_kind_and_supports_real_read_write(pg):
    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V1, (1,))
        ensure_schema(connection)
        with connection.cursor() as cursor:
            # The upgraded table really has the business column ...
            cursor.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema=%s "
                "AND table_name='annotation_label_reference' ORDER BY column_name",
                (SCHEMA_NAME,),
            )
            columns = [str(row[0]) for row in cursor.fetchall()]
            for required in ("project_id", "image_id", "label_code", "box_count",
                             "scope_ref", "annotation_state", "source_kind"):
                assert required in columns, (required, columns)
            # ... and it carries the legacy value, not a fabricated one.
            cursor.execute(
                f"SELECT label_code,source_kind FROM {SCHEMA_NAME}.annotation_label_reference "
                "ORDER BY label_code"
            )
            assert cursor.fetchall() == [("fire", "sqlite"), ("smoke", "legacy")]

        connection.rollback()  # leave the implicit read transaction
        # Before the authoritative import the target is explicitly incomplete.
        before = read_target_snapshot(connection, "p1")
        assert before["legacy_reference_pending_import"] is True
        assert any(row["source_kind"] == "sqlite" for row in
                   before["stores"]["annotations"]["annotation_label_references"])

        references = [
            {"image_id": "m-old", "label_code": "fire", "box_count": 3, "scope_ref": 1,
             "annotation_state": "annotated", "source_kind": "sqlite"},
            {"image_id": "m-old", "label_code": "smoke", "box_count": 0, "scope_ref": 0,
             "annotation_state": "unannotated", "source_kind": "legacy"},
        ]
        import_project_snapshot(connection, _snapshot(references), mode="incremental")
        after = read_target_snapshot(connection, "p1")
        stored = {
            row["label_code"]: (row["source_kind"], row["box_count"], row["scope_ref"],
                                row["annotation_state"])
            for row in after["stores"]["annotations"]["annotation_label_references"]
        }
        assert stored == {
            "fire": ("sqlite", 3, 1, "annotated"),
            "smoke": ("legacy", 0, 0, "unannotated"),
        }
        assert after["legacy_reference_pending_import"] is True

        # A hand-built mapping cannot prove completeness: a full import into a
        # pending project is refused before touching anything.
        before = read_target_snapshot(connection, "p1")
        snapshot = _snapshot(references, materials=[{"id": "m-old", "filename": "old.jpg"}])
        with pytest.raises(U3MigrationError) as incomplete:
            import_project_snapshot(connection, snapshot, mode="full")
        assert incomplete.value.code == "U3_PENDING_IMPORT_INCOMPLETE"
        after_refusal = read_target_snapshot(connection, "p1")
        assert after_refusal["stores"] == before["stores"]
        assert after_refusal["table_state"] == before["table_state"]
        assert after_refusal["revisions"] == before["revisions"]
        assert after_refusal["legacy_reference_pending_import"] is True
        # Re-running the migration is a no-op and keeps the marker.
        ensure_schema(connection)
        assert read_target_snapshot(connection, "p1")["legacy_reference_pending_import"] is True

def test_recorded_v3_with_missing_structure_is_refused(pg):
    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V1, (1,))
        ensure_schema(connection)
        # Simulate the earlier defect: v3 recorded, source_kind missing.
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"ALTER TABLE {SCHEMA_NAME}.annotation_label_reference DROP COLUMN source_kind"
                )
        with pytest.raises(U3MigrationError) as missing_column:
            ensure_schema(connection)
        assert missing_column.value.code == "U3_SCHEMA_STRUCTURE_INVALID"
        assert "source_kind" in missing_column.value.detail


def test_recorded_v3_without_category_foreign_key_is_refused(pg):
    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V1, (1,))
        ensure_schema(connection)
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT conname FROM pg_constraint WHERE conrelid = (%s)::regclass "
                    "AND contype='f'",
                    (f"{SCHEMA_NAME}.negative_pool_link",),
                )
                names = [str(row[0]) for row in cursor.fetchall()]
                for name in names:
                    cursor.execute(
                        f"ALTER TABLE {SCHEMA_NAME}.negative_pool_link "
                        f"DROP CONSTRAINT {name}"
                    )
        with pytest.raises(U3MigrationError) as missing_fk:
            ensure_schema(connection)
        assert missing_fk.value.code == "U3_SCHEMA_STRUCTURE_INVALID"
        assert "negative_pool_category" in missing_fk.value.detail

def test_wrong_primary_key_or_column_mapping_is_refused(pg):
    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V1, (1,))
        ensure_schema(connection)
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT conname FROM pg_constraint WHERE conrelid = (%s)::regclass "
                    "AND contype='p'",
                    (f"{SCHEMA_NAME}.annotation_label_reference",),
                )
                primary = str(cursor.fetchone()[0])
                cursor.execute(
                    f"ALTER TABLE {SCHEMA_NAME}.annotation_label_reference "
                    f"DROP CONSTRAINT {primary}"
                )
        with pytest.raises(U3MigrationError) as no_primary:
            ensure_schema(connection)
        assert no_primary.value.code == "U3_SCHEMA_STRUCTURE_INVALID"
        assert "primary_key" in no_primary.value.detail

    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V1, (1,))
        ensure_schema(connection)
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT conname FROM pg_constraint WHERE conrelid = (%s)::regclass "
                    "AND contype='f' AND confrelid = (%s)::regclass",
                    (f"{SCHEMA_NAME}.negative_pool_link",
                     f"{SCHEMA_NAME}.negative_pool_category"),
                )
                category_fk = str(cursor.fetchone()[0])
                cursor.execute(
                    f"ALTER TABLE {SCHEMA_NAME}.negative_pool_link "
                    f"DROP CONSTRAINT {category_fk}"
                )
                # A foreign key that exists but maps the wrong columns must fail:
                # the category FK is replaced by a second member FK.
                cursor.execute(
                    f"ALTER TABLE {SCHEMA_NAME}.negative_pool_link "
                    "ADD CONSTRAINT negative_pool_link_wrong_fk "
                    "FOREIGN KEY (project_id, category_id) "
                    f"REFERENCES {SCHEMA_NAME}.negative_pool_member"
                    "(project_id, material_id) ON DELETE CASCADE NOT VALID"
                )
        with pytest.raises(U3MigrationError) as wrong_mapping:
            ensure_schema(connection)
        assert wrong_mapping.value.code == "U3_SCHEMA_STRUCTURE_INVALID"
        assert "negative_pool_category" in wrong_mapping.value.detail

def test_not_valid_foreign_key_is_refused(pg):
    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V1, (1,))
        ensure_schema(connection)
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT conname FROM pg_constraint WHERE conrelid = (%s)::regclass "
                    "AND contype='f' AND confrelid = (%s)::regclass",
                    (f"{SCHEMA_NAME}.negative_pool_link",
                     f"{SCHEMA_NAME}.negative_pool_category"),
                )
                category_fk = str(cursor.fetchone()[0])
                cursor.execute(
                    f"ALTER TABLE {SCHEMA_NAME}.negative_pool_link "
                    f"DROP CONSTRAINT {category_fk}"
                )
                # Correct mapping and CASCADE, but not validated: still refused.
                cursor.execute(
                    f"ALTER TABLE {SCHEMA_NAME}.negative_pool_link "
                    "ADD CONSTRAINT negative_pool_link_unvalidated "
                    "FOREIGN KEY (project_id, category_id) "
                    f"REFERENCES {SCHEMA_NAME}.negative_pool_category(project_id, id) "
                    "ON DELETE CASCADE NOT VALID"
                )
        with pytest.raises(U3MigrationError) as unvalidated:
            ensure_schema(connection)
        assert unvalidated.value.code == "U3_SCHEMA_STRUCTURE_INVALID"
        assert "negative_pool_category" in unvalidated.value.detail
