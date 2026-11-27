"""U3-P2 business read contract: history, roles, usage, confirmations, paging.

Real PostgreSQL 16 projection + real SQLite Task/Annotation owners. Usage rows
are recorded through the public ``TrainingMaterialUsage`` APIs, never by
hand-editing the index.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
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

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.negative_pool import _DDL as POOL_DDL
from platform_core.task_runtime import TaskRepository
from platform_core.training_label_tasks import task_negative_context, task_negative_identity
from platform_core.training_material_business_read import (
    BusinessFilter,
    BusinessHistoryChanged,
    BusinessHistoryUnavailable,
    BusinessQuery,
    BusinessReadProvider,
    compare_candidate_sets,
    selection_digest,
)
from platform_core.training_material_picker_read import (
    PickerCursorContextMismatch,
    PickerFilter,
    PickerNegativeReceipt,
    PickerNegativeReceipts,
    PickerProjectMismatch,
    PickerUnsupportedFilter,
    SQLitePickerReadProvider,
    sqlite_owner_revision_source,
)
from platform_core.training_material_usage import TrainingMaterialUsage
from platform_core.u3_shadow import (
    SCHEMA_NAME,
    ensure_schema,
    export_project_snapshot,
    import_project_snapshot,
)

ALGORITHM = "algo-fire"


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
    root = pathlib.Path(tempfile.mkdtemp(prefix="pgp2-")) / "data"
    server = pgserver.get_server(root, cleanup_mode="delete")
    yield server
    server.cleanup()


def _material(index: int, *, source: str, created_at: str, sha: str | None = None) -> dict:
    return {
        "id": f"m{index:03d}",
        "filename": f"Business-{index:03d}.jpg",
        "storage_source_id": source,
        "storage_type": "local",
        "object_key": f"uploads/m{index:03d}.jpg",
        "content_sha256": sha or f"{index + 1:064x}"[-64:],
        "size_bytes": 1024 + index,
        "processing_status": "processed",
        "box_count": 1,
        "annotated": True,
        "created_at": created_at,
        "updated_at": "2026-09-15T12:00:00+00:00",
    }


#: created_at is intentionally shared by m000..m003 so ties fall back to id.
def _created(index: int) -> str:
    if index < 4:
        return "2026-09-15T12:00:00+00:00"
    minutes, seconds = divmod(index - 3, 60)
    return f"2026-09-15T12:{minutes:02d}:{seconds:02d}+00:00"


def _box(label: str, index: int) -> dict:
    return {"id": f"b{index}", "label": label, "x1": 10, "y1": 10, "x2": 40, "y2": 40}


def _business_project(tmp_path, project_id: str = "p1"):
    """One project with every history/role state the P2 contract must classify."""
    data_dir = tmp_path / "data"
    project = data_dir / "projects" / project_id
    project.mkdir(parents=True)
    repository = MaterialRepository(project)
    repository.upsert_many([
        _material(index, source="nas-1" if index in {0, 3, 6, 9} else "default_local",
                  created_at=_created(index))
        for index in range(12)
    ])
    with sqlite3.connect(repository.path) as database:
        for statement in POOL_DDL:
            database.execute(statement)
        database.execute("INSERT INTO negative_pool_members VALUES ('m000','2026-09-16T00:00:00+00:00')")
        database.execute("INSERT INTO negative_pool_members VALUES ('m004','2026-09-16T00:00:00+00:00')")
        database.execute("INSERT INTO negative_pool_categories VALUES ('cat-fire','fire',1)")
        database.execute("INSERT INTO negative_pool_links VALUES ('m000','cat-fire')")
        database.execute("INSERT INTO negative_pool_algorithm_members VALUES ('algo-fire','m004','2026-09-16T00:00:00+00:00')")
    annotations = AnnotationRepository(project)
    # m000 positive, m001 smoke-only scope (needs a receipt to be negative),
    # m002 positive + current used, m003 positive + other used, m004 positive +
    # possible, m005 positive + selected, m006 confirmed empty, m007 untouched,
    # m008 stale source, m009 positive + test reserved, m010 positive + eval only,
    # m011 positive + no history.
    payload = []
    for index in (0, 2, 3, 4, 5, 9, 10, 11):
        payload.append({
            "image_id": f"m{index:03d}", "annotation_state": "annotated",
            "boxes": [_box("fire", index)], "annotation_scope": ["fire"],
        })
    payload.append({
        "image_id": "m001", "annotation_state": "annotated",
        "boxes": [_box("smoke", 1)], "annotation_scope": ["smoke"],
    })
    payload.append({
        "image_id": "m006", "annotation_state": "confirmed_empty",
        "boxes": [], "annotation_scope": ["fire"],
    })
    annotations.upsert_many(payload)
    # m008: annotate first, then change the material content hash -> stale GT.
    annotations.upsert_many([{
        "image_id": "m008", "annotation_state": "annotated",
        "boxes": [_box("fire", 8)], "annotation_scope": ["fire"],
    }])
    repository.upsert(_material(8, source="default_local", created_at=_created(8), sha="f" * 64))

    tasks_path = data_dir / "task_runtime" / "tasks.sqlite3"
    TaskRepository(tasks_path)
    usage = TrainingMaterialUsage(tasks_path)
    rows = {str(row["id"]): row for row in repository.get_many([f"m{i:03d}" for i in range(12)])}

    def record(task_id: str, image_ids: list[str], role: str = "train") -> None:
        images = [{
            "image_id": image_id, "role": role,
            "content_sha256": rows[image_id]["content_sha256"],
        } for image_id in image_ids]
        usage.record_selected(
            project_id, ALGORITHM, task_id,
            {"snapshot_id": f"snap-{task_id}", "images": images},
        )

    record("t-used", ["m002"])
    usage.record_execution("t-used", completed_epoch=True)
    record("t-possible", ["m004"])
    usage.record_execution("t-possible", first_batch=True)
    record("t-selected", ["m005"])
    record("t-other", ["m003"])
    usage.record_execution("t-other", completed_epoch=True)
    # The other-algorithm evidence must carry another algorithm id.
    with sqlite3.connect(tasks_path) as database:
        database.execute(
            "UPDATE training_material_usage SET algorithm_id='algo-other' WHERE task_id='t-other'"
        )
    record("t-test", ["m009"], role="test")
    usage.record_execution("t-test", test_observed=True)
    record("t-eval", ["m010"], role="validation")
    usage.record_execution("t-eval", validation_observed=True)
    usage.mark_coverage(project_id, ALGORITHM, complete=True)
    return project, usage


def _reset(pg, project_id: str) -> None:
    tables = (
        "negative_pool_link", "negative_pool_algorithm_member", "negative_pool_member",
        "negative_pool_category", "material_label", "material_annotation_scope",
        "annotation_label_reference", "annotation", "material", "evidence_row",
        "table_state", "store_revision", "picker_snapshot_state",
        "u3_projection_cursor", "task_negative_confirmation", "u3_shadow_import",
    )
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection)
        with connection.transaction():
            with connection.cursor() as cursor:
                for table in tables:
                    cursor.execute(f"DELETE FROM {SCHEMA_NAME}.{table} WHERE project_id=%s", (project_id,))


def _publish(pg, project, project_id: str = "p1"):
    snapshot = export_project_snapshot(project, project_id)
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
    return snapshot


def _providers(pg, project, project_id: str = "p1"):
    _reset(pg, project_id)
    _publish(pg, project, project_id)
    sqlite_picker = SQLitePickerReadProvider(project, project_id=project_id)
    postgres_picker = __import__(
        "platform_core.training_material_picker_read", fromlist=["PostgresPickerReadProvider"],
    ).PostgresPickerReadProvider.from_dsn(
        pg.get_uri(), owner_revisions=sqlite_owner_revision_source(project, project_id),
    )
    return (
        BusinessReadProvider(sqlite_picker, project, project_id=project_id),
        BusinessReadProvider(postgres_picker, project, project_id=project_id),
    )


def _query(*, filters: BusinessFilter | None = None, **kwargs) -> BusinessQuery:
    return BusinessQuery(project_id="p1", filters=filters or BusinessFilter(), **kwargs)


FIRE = ("fire",)


def _filter(**kwargs) -> BusinessFilter:
    base = kwargs.pop("base", PickerFilter())
    kwargs.setdefault("algorithm_asset_id", ALGORITHM)
    return BusinessFilter(base=base, label_codes=FIRE, **kwargs)


def _ids(page) -> list[str]:
    return [item.material.id for item in page.items]


def _stream(provider, *, filters: BusinessFilter) -> list[str]:
    return [
        item.material.id
        for batch in provider.iter_candidates(_query(filters=filters))
        for item in batch
    ]


# ---------------------------------------------------------------------------
# A. history policies and usage states
# ---------------------------------------------------------------------------
def test_history_policies_match_the_owner_and_sqlite_pickers(pg, tmp_path):
    project, _usage = _business_project(tmp_path)
    sqlite_business, postgres_business = _providers(pg, project)
    cases = {
        "default": _filter(),
        "include_history": _filter(history_policy="include_history"),
        "current_only": _filter(history_scope="current_only", browse_only=True),
        "other_only": _filter(history_scope="other_only", browse_only=True),
        "used": _filter(usage_state="used", browse_only=True),
        "possible": _filter(usage_state="possible", browse_only=True),
        "selected": _filter(usage_state="selected", browse_only=True),
        "unused": _filter(usage_state="unused"),
        "unknown": _filter(usage_state="unknown"),
        "test_reserved": _filter(usage_state="test_reserved", browse_only=True),
        "eval_only": _filter(usage_state="eval_only", browse_only=True),
        "browse": _filter(browse_only=True),
    }
    for name, filters in cases.items():
        baseline = _stream(sqlite_business, filters=filters)
        candidate = _stream(postgres_business, filters=filters)
        assert candidate == baseline, name
    default = set(_stream(postgres_business, filters=_filter()))
    # used + possible + test-reserved are excluded for a new training selection.
    assert not ({"m002", "m004", "m009"} & default)
    include = set(_stream(postgres_business, filters=_filter(history_policy="include_history")))
    assert {"m002", "m004"} <= include and "m009" not in include
    # current_algorithm_trained uses evidence>0, so a "possible" row counts too.
    assert set(_stream(postgres_business, filters=_filter(history_scope="current_only", browse_only=True))) == {"m002", "m004"}
    assert set(_stream(postgres_business, filters=_filter(history_scope="other_only", browse_only=True))) == {"m003"}
    assert set(_stream(postgres_business, filters=_filter(usage_state="used", browse_only=True))) == {"m002"}
    assert set(_stream(postgres_business, filters=_filter(usage_state="possible", browse_only=True))) == {"m004"}
    assert set(_stream(postgres_business, filters=_filter(usage_state="selected", browse_only=True))) == {"m005"}
    assert set(_stream(postgres_business, filters=_filter(usage_state="test_reserved", browse_only=True))) == {"m009"}
    assert set(_stream(postgres_business, filters=_filter(usage_state="eval_only", browse_only=True))) == {"m010"}
    unused = set(_stream(postgres_business, filters=_filter(usage_state="unused")))
    assert {"m000", "m011"} <= unused and not ({"m002", "m004", "m009"} & unused)


# ---------------------------------------------------------------------------
# B. sample roles
# ---------------------------------------------------------------------------
def test_sample_roles_reuse_the_existing_classifier(pg, tmp_path):
    project, _usage = _business_project(tmp_path)
    _sqlite_business, postgres_business = _providers(pg, project)
    roles = {
        "positive": set(_stream(
            postgres_business,
            filters=_filter(sample_role="positive", history_policy="include_history"),
        )),
        "confirmed_negative": set(_stream(
            postgres_business,
            filters=_filter(sample_role="confirmed_negative", history_policy="include_history"),
        )),
        "pending_negative": set(_stream(
            postgres_business,
            filters=_filter(sample_role="pending_negative", history_policy="include_history"),
        )),
        "pending_review": set(_stream(
            postgres_business,
            filters=_filter(sample_role="pending_review", history_policy="include_history"),
        )),
    }
    assert {"m000", "m002", "m011"} <= roles["positive"]
    assert "m006" in roles["confirmed_negative"]
    assert "m001" not in roles["confirmed_negative"]  # smoke-only scope needs a receipt
    assert "m007" in roles["pending_negative"]
    # A smoke-only scope is confirmable but not yet confirmed: pending_negative.
    assert "m001" in roles["pending_negative"]
    assert "m008" in roles["pending_review"]  # stale GT
    assert roles["pending_review"] == {"m008"}
    assert "m002" in roles["positive"]  # include_history keeps the used positive
    # The default policy still excludes it before role filtering.
    assert "m002" not in set(_stream(postgres_business, filters=_filter(sample_role="positive")))


# ---------------------------------------------------------------------------
# C. confirmation receipts: strict consumer validation (no receipt is created)
# ---------------------------------------------------------------------------
def test_confirmation_receipt_validation_is_strict(tmp_path):
    project, _usage = _business_project(tmp_path)
    provider = BusinessReadProvider(
        SQLitePickerReadProvider(project, project_id="p1"), project, project_id="p1",
    )
    contract = provider._contract(_filter())
    context_key = __import__(
        "platform_core.training_label_tasks", fromlist=["task_negative_context"],
    ).task_negative_context(contract)
    annotation = provider.annotations.get_many(["m000"])["m000"]
    material = {str(row["id"]): row for row in provider.materials.get_many(["m000"])}["m000"]
    identity = task_negative_identity({
        "id": "m000", "content_sha256": material["content_sha256"],
        "annotation_version": annotation["version"],
        "annotation_hash": annotation["content_digest"],
    }, contract)

    def receipts(authoritative: bool, **overrides):
        evidence = {**identity, **overrides}
        return PickerNegativeReceipts(
            context_key=context_key, generation=1, state="present",
            authoritative=authoritative, owner_equivalent=True,
            receipts=(PickerNegativeReceipt(
                receipt_id=str(identity["receipt_id"]), context_key=context_key,
                image_id="m000", evidence=evidence,
            ),),
        )

    provider.picker.get_task_negative_receipts = lambda *a, **k: receipts(True)
    valid = provider._valid_receipts(
        _query(filters=_filter()), contract,
        {str(material["id"]): material}, {"m000": annotation}, receipts(True),
    )
    assert [item["receipt_id"] for item in valid] == [identity["receipt_id"]]
    for scenario, expected in (
        ("stale_hash", 0), ("wrong_context", 0), ("wrong_source", 0),
        ("stale_version", 0), ("not_authoritative", 0),
    ):
        if scenario == "stale_hash":
            payload = receipts(True, annotation_hash="0" * 64)
        elif scenario == "wrong_context":
            payload = receipts(True, context_key="other")
        elif scenario == "wrong_source":
            payload = receipts(True, source_content_sha256="0" * 64)
        elif scenario == "stale_version":
            payload = receipts(True, annotation_version=int(annotation["version"]) + 1)
        else:
            payload = receipts(False)
        provider.picker.get_task_negative_receipts = lambda *a, **k: payload
        kept = provider._valid_receipts(
            _query(filters=_filter()), contract,
            {str(material["id"]): material}, {"m000": annotation}, payload,
        )
        assert len(kept) == expected, scenario


# ---------------------------------------------------------------------------
# D. composite filters, pagination and counts
# ---------------------------------------------------------------------------
def test_composite_filters_page_after_every_business_predicate(pg, tmp_path):
    project, _usage = _business_project(tmp_path)
    sqlite_business, postgres_business = _providers(pg, project)
    filters = _filter(
        base=PickerFilter(query="Business", storage_source_ids=()),
        sample_role="positive", history_policy="include_history",
    )
    full = _stream(postgres_business, filters=filters)
    assert full == _stream(sqlite_business, filters=filters)
    # The first candidates in created_at order are m000 (kept), m001 (pending),
    # m002 (used), m003 (other) ...: the page must not stop at the excluded ones.
    page = postgres_business.read_page(_query(filters=filters, page=1, page_size=3, count_mode="exact"))
    assert _ids(page) == full[:3]
    assert page.total == len(full)
    assert page.has_more is True
    second = postgres_business.read_page(_query(filters=filters, page=2, page_size=3, count_mode="exact"))
    assert _ids(second) == full[3:6]
    # Deferred count never runs the full count.
    deferred = postgres_business.read_page(_query(
        filters=filters, page=1, page_size=3, count_mode="deferred",
    ))
    assert deferred.total is None
    assert deferred.has_more is True
    # Cursor traversal covers the set exactly once.
    collected: list[str] = []
    cursor = None
    while True:
        page = postgres_business.read_page(_query(
            filters=filters, page_size=4, cursor=cursor,
        ))
        collected.extend(_ids(page))
        if not page.has_more:
            break
        cursor = page.next_cursor
        assert cursor
    assert collected == full


def test_cursor_is_bound_to_history_and_snapshot(pg, tmp_path):
    project, usage = _business_project(tmp_path)
    _sqlite_business, postgres_business = _providers(pg, project)
    first = postgres_business.read_page(_query(filters=_filter(), page_size=2))
    cursor = first.next_cursor
    assert cursor
    # Any usage write bumps the history revision: the old cursor is refused.
    usage.record_execution("t-selected", completed_epoch=True)
    with pytest.raises(BusinessHistoryChanged):
        postgres_business.read_page(_query(filters=_filter(), page_size=2, cursor=cursor))
    # A changed projection snapshot is refused too.
    snapshot = postgres_business.read_page(_query(filters=_filter(), page_size=2))
    cursor = snapshot.next_cursor
    MaterialRepository(project).upsert(
        _material(90, source="default_local", created_at="2026-09-16T00:00:00+00:00")
    )
    _publish(pg, project)
    with pytest.raises(PickerCursorContextMismatch):
        postgres_business.read_page(_query(filters=_filter(), page_size=2, cursor=cursor))
    with pytest.raises(PickerUnsupportedFilter):
        postgres_business.read_page(_query(
            filters=_filter(), page_size=2, cursor=cursor, count_mode="exact",
        ))


def test_incomplete_or_unavailable_history_never_becomes_unused(tmp_path):
    project, usage = _business_project(tmp_path)
    # Coverage for a different algorithm is NOT complete: "unused" stays unknown.
    usage.mark_coverage("p1", "algo-unseen", complete=False)
    provider = BusinessReadProvider(
        SQLitePickerReadProvider(project, project_id="p1"), project, project_id="p1",
    )
    unseen = _filter(algorithm_asset_id="algo-unseen")
    assert _stream(provider, filters=_filter(
        algorithm_asset_id="algo-unseen", usage_state="unused", browse_only=True,
    )) == []
    assert len(_stream(provider, filters=_filter(
        algorithm_asset_id="algo-unseen", usage_state="unknown", browse_only=True,
    ))) == 12

    broken = BusinessReadProvider(
        SQLitePickerReadProvider(project, project_id="p1"), project, project_id="p1",
    )
    broken.usage = _UnavailableUsage()
    with pytest.raises(BusinessHistoryUnavailable):
        _stream(broken, filters=_filter())


class _UnavailableUsage:
    def read_revision(self):
        raise sqlite3.OperationalError("history store unavailable")

    def query_filter(self, *args, **kwargs):
        raise sqlite3.OperationalError("history store unavailable")


# ---------------------------------------------------------------------------
# E. freeze-set equivalence (read-only, no production selection is created)
# ---------------------------------------------------------------------------
def test_candidate_sets_and_selection_digest_are_equivalent(pg, tmp_path):
    project, _usage = _business_project(tmp_path)
    sqlite_business, postgres_business = _providers(pg, project)
    filters = _filter(sample_role="positive", history_policy="include_history")
    result = compare_candidate_sets(
        sqlite_business, postgres_business, _query(filters=filters),
    )
    assert result["count"] == len(result["ids"])
    assert result["digest"] == selection_digest(result["ids"])
    assert result["ids"] == _stream(postgres_business, filters=filters)
    # A different query is not equivalent: the comparison refuses to publish.
    other = compare_candidate_sets(
        sqlite_business, postgres_business,
        _query(filters=_filter(sample_role="pending_review")),
    )
    assert other["ids"] != result["ids"]


# ---------------------------------------------------------------------------
# G. Audit remediation regressions
# ---------------------------------------------------------------------------
class _MutatingPicker:
    """Delegates to the real SQLite picker and mutates history mid-stream."""

    def __init__(self, inner, usage):
        self._inner = inner
        self._usage = usage
        self.project_id = inner.project_id
        self.name = inner.name

    def __getattr__(self, item):
        return getattr(self._inner, item)

    def iter_candidates(self, query, *, batch_size=500):
        first = True
        for batch in self._inner.iter_candidates(query, batch_size=batch_size):
            if first:
                first = False
                # The write lands after the session captured its history revision
                # and before the (early-stopped) page is published.
                self._usage.record_execution("t-selected", completed_epoch=True)
            yield batch


def test_deferred_early_exit_still_verifies_history(tmp_path):
    project, usage = _business_project(tmp_path)
    provider = BusinessReadProvider(
        _MutatingPicker(SQLitePickerReadProvider(project, project_id="p1"), usage),
        project, project_id="p1",
    )
    # One page needs a single match, so the stream stops after the first candidates;
    # the session must still detect the usage write that happened mid-stream.
    with pytest.raises(BusinessHistoryChanged):
        provider.read_page(_query(filters=_filter(), page=1, page_size=1))


def _insert_task(tasks_path, task_id, status, project_id="p1"):
    with sqlite3.connect(tasks_path) as database:
        database.execute(
            "INSERT INTO tasks(task_id,project_id,kind,status,priority,resource_key,"
            "required_capabilities,payload_ref,log_ref,progress,stage,attempt,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, project_id, "TRAINING", status, 5, "gpu", "[]", "payload",
             "task.log", 0.0, "queued", 0,
             "2026-09-15T12:00:00+00:00", "2026-09-15T12:00:00+00:00"),
        )


def test_real_task_status_change_rejects_cursor_without_usage_revision_change(tmp_path):
    project, usage = _business_project(tmp_path)
    tasks_path = project.parent.parent / "task_runtime" / "tasks.sqlite3"
    _insert_task(tasks_path, "t-live", "RUNNING")
    provider = BusinessReadProvider(
        SQLitePickerReadProvider(project, project_id="p1"), project, project_id="p1",
    )
    first = provider.read_page(_query(filters=_filter(), page_size=2))
    revision = usage.read_revision()
    with sqlite3.connect(tasks_path) as database:
        database.execute(
            "UPDATE tasks SET status='CANCELLED', updated_at='2026-09-15T13:00:00+00:00' "
            "WHERE task_id='t-live'"
        )
    assert usage.read_revision() == revision  # the usage revision did not move
    with pytest.raises(BusinessHistoryChanged):
        provider.read_page(_query(filters=_filter(), page_size=2, cursor=first.next_cursor))


def test_swapped_active_task_statuses_are_detected_even_with_equal_counts(tmp_path):
    project, _usage = _business_project(tmp_path)
    tasks_path = project.parent.parent / "task_runtime" / "tasks.sqlite3"
    _insert_task(tasks_path, "t-a", "RUNNING")
    _insert_task(tasks_path, "t-b", "CANCEL_REQUESTED")
    provider = BusinessReadProvider(
        SQLitePickerReadProvider(project, project_id="p1"), project, project_id="p1",
    )
    first = provider.read_page(_query(filters=_filter(), page_size=2))
    with sqlite3.connect(tasks_path) as database:
        database.execute("UPDATE tasks SET status='CANCEL_REQUESTED' WHERE task_id='t-a'")
        database.execute("UPDATE tasks SET status='RUNNING' WHERE task_id='t-b'")
    with pytest.raises(BusinessHistoryChanged):
        provider.read_page(_query(filters=_filter(), page_size=2, cursor=first.next_cursor))


def test_central_task_owner_path_and_cross_project_guard(tmp_path):
    project, usage = _business_project(tmp_path)
    data_dir = project.parent.parent
    provider = BusinessReadProvider(
        SQLitePickerReadProvider(project, project_id="p1"), project, project_id="p1",
    )
    assert provider.tasks_path == data_dir / "task_runtime" / "tasks.sqlite3"
    assert provider.usage.path == provider.tasks_path
    # A project-local decoy task store is never consulted.
    with sqlite3.connect(project / "tasks.sqlite3") as database:
        database.execute("CREATE TABLE IF NOT EXISTS training_usage_meta(id INTEGER PRIMARY KEY, revision INTEGER)")
        database.execute("INSERT OR REPLACE INTO training_usage_meta VALUES(1, 999)")
    assert provider.usage.path != project / "tasks.sqlite3"
    other = tmp_path / "other" / "projects" / "p2"
    other.mkdir(parents=True)
    foreign = MaterialRepository(other)
    with pytest.raises(PickerProjectMismatch):
        BusinessReadProvider(
            SQLitePickerReadProvider(project, project_id="p1"), project,
            project_id="p1", materials=foreign,
        )


def test_formal_selection_keeps_history_and_test_protection(tmp_path):
    project, _usage = _business_project(tmp_path)
    provider = BusinessReadProvider(
        SQLitePickerReadProvider(project, project_id="p1"), project, project_id="p1",
    )
    browse = set(_stream(provider, filters=_filter(usage_state="test_reserved", browse_only=True)))
    assert browse == {"m009"}
    assert _stream(provider, filters=_filter(usage_state="test_reserved")) == []
    assert _stream(provider, filters=_filter(usage_state="used")) == []
    assert "m002" in set(_stream(provider, filters=_filter(history_policy="include_history")))


def test_real_confirmation_receipt_chain(tmp_path):
    project, _usage = _business_project(tmp_path)
    annotations = AnnotationRepository(project)
    material = {str(row["id"]): row for row in MaterialRepository(project).get_many(["m001"])}["m001"]
    record = annotations.get("m001")
    contract = {"algorithm_id": ALGORITHM, "effective_label_codes": ["fire"],
                "task_negative_confirmations": []}
    row = {**record, "content_sha256": material["content_sha256"], "id": "m001"}
    identity = task_negative_identity(row, contract)
    annotations.confirm_task_negatives(
        task_negative_context(contract), [identity], {"actor_id": "tester"},
    )
    provider = BusinessReadProvider(
        SQLitePickerReadProvider(project, project_id="p1"), project, project_id="p1",
    )
    page = provider.read_page(_query(
        filters=_filter(sample_role="confirmed_negative", history_policy="include_history"),
        page=1, page_size=100, count_mode="exact",
    ))
    matched = {item.material.id: item for item in page.items}
    assert "m001" in matched
    assert matched["m001"].confirmation_receipt
    # A new GT version invalidates the receipt: no longer a confirmed negative.
    annotations.upsert_many([{
        "image_id": "m001", "annotation_state": "annotated",
        "boxes": [_box("fire", 1)], "annotation_scope": ["fire"],
    }])
    provider = BusinessReadProvider(
        SQLitePickerReadProvider(project, project_id="p1"), project, project_id="p1",
    )
    page = provider.read_page(_query(
        filters=_filter(sample_role="confirmed_negative", history_policy="include_history"),
        page=1, page_size=100, count_mode="exact",
    ))
    assert "m001" not in {item.material.id for item in page.items}


def test_pg_session_keeps_candidates_gt_and_receipts_in_one_snapshot(pg, tmp_path):
    project, _usage = _business_project(tmp_path)
    _sqlite_business, postgres_business = _providers(pg, project)
    query = _query(filters=_filter(history_policy="include_history"))
    with postgres_business.read_session(query) as session:
        first = [item.material.id for batch in session.batches() for item in batch]
        assert first
        with psycopg.connect(pg.get_uri()) as writer:
            with writer.transaction():
                with writer.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO {SCHEMA_NAME}.material"
                        "(project_id,id,filename,processing_status,created_at,payload) "
                        "VALUES ('p1','m999','late.jpg','processed',"
                        "'2026-09-30T00:00:00+00:00','{}'::jsonb)"
                    )
        again = [item.material.id for batch in session.batches() for item in batch]
        assert again == first
        assert session.annotations(["m000"]).annotations
    # The late PG-only row is not an owner material, so a new session must not
    # invent it; the owner remains the only material authority.
    with postgres_business.read_session(query) as session:
        assert "m999" not in [item.material.id for batch in session.batches() for item in batch]


def test_frozen_selection_reference_matches_the_business_set(pg, tmp_path):
    import uuid

    from platform_core.training_selection_reference import (
        freeze_selection, read_selection, selection_context,
    )

    project, _usage = _business_project(tmp_path)
    _sqlite_business, postgres_business = _providers(pg, project)
    filters = _filter(history_policy="include_history", sample_role="positive")
    ids = _stream(postgres_business, filters=filters)
    data_dir = str(project.parent.parent)
    context = selection_context(
        data_dir, "p1", {"algorithm_asset_id": ALGORITHM}, role="train",
    )
    frozen = freeze_selection(data_dir, context, ids, request_id=str(uuid.uuid4()))
    read = read_selection(data_dir, frozen["selection_ref"], context)
    assert read == sorted(ids)
    assert frozen["count"] == len(ids)
    assert selection_digest(read) == selection_digest(ids)
    excluded = ids[0]
    remaining = [image_id for image_id in ids if image_id != excluded]
    frozen2 = freeze_selection(
        data_dir, context, remaining, request_id=str(uuid.uuid4()),
    )
    read2 = read_selection(data_dir, frozen2["selection_ref"], context)
    assert excluded not in read2 and read2 == sorted(remaining)


def test_bounded_batches_do_not_accumulate_or_recheck_everything(tmp_path):
    project, _usage = _business_project(tmp_path)
    provider = BusinessReadProvider(
        SQLitePickerReadProvider(project, project_id="p1"), project, project_id="p1",
    )
    calls = {"count": 0}
    real = provider.usage.query_filter

    def counting(*args, **kwargs):
        calls["count"] += 1
        return real(*args, **kwargs)

    provider.usage.query_filter = counting
    with provider.read_session(_query(filters=_filter(), count_mode="deferred")) as session:
        assert not hasattr(session, "_facts")
        batches = list(session.batches(batch_size=4))
    assert len(batches) == 3
    # One bounded history read per batch; verify() adds no full-candidate re-read.
    assert calls["count"] == 3


def test_candidate_stream_consumes_a_business_cursor(tmp_path):
    project, _usage = _business_project(tmp_path)
    provider = BusinessReadProvider(
        SQLitePickerReadProvider(project, project_id="p1"), project, project_id="p1",
    )
    expected = [item.material.id for batch in provider.iter_candidates(
        _query(filters=_filter()), batch_size=5,
    ) for item in batch]
    first = provider.read_page(_query(filters=_filter(), page_size=4))
    tail = [item.material.id for batch in provider.iter_candidates(
        _query(filters=_filter(), cursor=first.next_cursor), batch_size=5,
    ) for item in batch]
    assert tail == expected[4:]
    with pytest.raises(PickerUnsupportedFilter):
        provider.read_page(_query(filters=_filter(), page_size=2, verify_owner=False))


def test_roles_match_the_original_role_page(tmp_path):
    from platform_core.training_material_picker_api import _role_material_page

    project, _usage = _business_project(tmp_path)
    repository = MaterialRepository(project)
    annotations = AnnotationRepository(project)
    provider = BusinessReadProvider(
        SQLitePickerReadProvider(project, project_id="p1"), project, project_id="p1",
    )
    ids = [f"m{index:03d}" for index in range(12)]
    contract = {"algorithm_id": ALGORITHM, "effective_label_codes": ["fire"],
                "task_negative_confirmations": []}
    baseline = _role_material_page(
        repository, annotations, contract, image_ids=ids, page=1, limit=60,
        filters={"label_mode": "any", "browse_only": True},
        sort_order="oldest", count_mode="exact",
    )
    expected = {str(item["id"]): item["sample_role"] for item in baseline["items"]}
    page = provider.read_page(_query(
        filters=_filter(history_policy="include_history", browse_only=True),
        page=1, page_size=100, count_mode="exact",
    ))
    assert {item.material.id: item.sample_role for item in page.items} == expected


def test_browse_mode_keeps_the_real_confirmation_role(tmp_path):
    project, _usage = _business_project(tmp_path)
    annotations = AnnotationRepository(project)
    material = {str(row["id"]): row for row in MaterialRepository(project).get_many(["m001"])}["m001"]
    record = annotations.get("m001")
    contract = {"algorithm_id": ALGORITHM, "effective_label_codes": ["fire"],
                "task_negative_confirmations": []}
    identity = task_negative_identity(
        {**record, "content_sha256": material["content_sha256"], "id": "m001"}, contract,
    )
    annotations.confirm_task_negatives(
        task_negative_context(contract), [identity], {"actor_id": "tester"},
    )
    provider = BusinessReadProvider(
        SQLitePickerReadProvider(project, project_id="p1"), project, project_id="p1",
    )
    browse = provider.read_page(_query(
        filters=_filter(history_policy="include_history", browse_only=True,
                        sample_role="confirmed_negative"),
        page=1, page_size=100, count_mode="exact",
    ))
    matched = {item.material.id: item for item in browse.items}
    assert "m001" in matched and matched["m001"].confirmation_receipt
