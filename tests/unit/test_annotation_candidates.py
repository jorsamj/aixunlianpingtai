from pathlib import Path

import pytest

from platform_core.annotation_candidates import CandidateDecision, CandidateStore
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus


def test_generation_state_recovers_unordered_gaps_and_failed_selection(tmp_path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="unordered")
    store.initialize(labels=[], total_images=5)
    store.append_items([
        {"image_id": "d", "status": "empty", "boxes": []},
        {"image_id": "b", "status": "failed", "boxes": []},
        {"image_id": "a", "status": "success", "boxes": []},
    ])
    store.set_review_exclusion("d", "transferred", operation_id="op", actor="tester")
    state = store.generation_state(list("abcde"))
    assert state == dict(done_ids={"a", "d"}, failed_ids={"b"}, succeeded=2,
                         failed=1, total=3, next_index=2)
    assert [i for i in "abcde" if i not in state["done_ids"]] == list("bce")
    assert store.statistics()["gt_committed"] == 0
    assert store.get("d")["review_state"] == "transferred"
    store.append_items([{"image_id": "c", "status": "empty", "boxes": []}])
    assert store.generation_state(list("abcde"))["next_index"] == 4
    with pytest.raises(ValueError, match="scope"):
        store.generation_state(list("abced"))


@pytest.mark.parametrize("ids,status,match", [
    (["a", "a"], "empty", "duplicate"),
    (["b"], "empty", "immutable"),
    (["a"], "unexpected", "invalid generation status"),
])
def test_generation_state_fails_closed(tmp_path, ids, status, match):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="invalid-state")
    store.initialize(labels=[], total_images=1)
    store.append_items([{"image_id": "a", "status": "empty", "boxes": []}])
    with store._connect() as db:
        db.execute("UPDATE candidates SET status=?", (status,))
    with pytest.raises(ValueError, match=match):
        store.generation_state(ids)


def test_generation_state_scope_commit_is_fenced_and_resettable(tmp_path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="scope-guard")
    store.initialize(labels=[], total_images=2)
    def stale():
        raise RuntimeError("stale lease")
    with pytest.raises(RuntimeError, match="stale lease"):
        store.generation_state(["a", "b"], commit_guard=stale)
    # Rejected scope write must roll back entirely.
    assert store.generation_state(["b", "a"])["total"] == 0
    with pytest.raises(ValueError, match="scope"):
        store.generation_state(["a", "b"])
    store.initialize(labels=[], total_images=2)
    assert store.generation_state(["a", "b"])["total"] == 0


def test_generation_state_200k_reads_only_bounded_scalar_pages(tmp_path, monkeypatch):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="unordered-200k")
    total = 200_000
    ids = [f"image-{index}" for index in range(total)]
    store.initialize(labels=[], total_images=total)
    # Populate scalar recovery evidence without inflating the test with JSON
    # encoding/provider work. Reverse persistence order exercises unordered reads.
    with store._connect() as db:
        db.executemany(
            "INSERT INTO candidates(ordinal,image_id,status,boxes_count,item_json) VALUES (?,?,?,0,'{}')",
            ((index + 1, image_id, "failed" if index % 11 == 0 else "empty")
             for index, image_id in enumerate(reversed(ids))),
        )
    original_connect = store._connect
    reads = []
    class Connection:
        def __init__(self, inner):
            self.inner = inner
        def execute(self, sql, *args):
            if "FROM candidates" in sql:
                assert "SELECT ordinal,image_id,status" in sql
                assert "LIMIT 500" in sql
                reads.append(sql)
            return self.inner.execute(sql, *args)
        def __getattr__(self, name):
            return getattr(self.inner, name)
    monkeypatch.setattr(store, "_connect", lambda: Connection(original_connect()))
    monkeypatch.setattr(store, "get", lambda *_: pytest.fail("per-image recovery read"))
    state = store.generation_state(ids)
    assert state["total"] == state["next_index"] == total
    assert state["succeeded"] + state["failed"] == total
    assert state["done_ids"].isdisjoint(state["failed_ids"])
    assert len(reads) == 401  # Exact full pages plus one empty terminator.


def test_candidate_statistics_count_only_durable_unique_gt_journal(tmp_path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="statistics")
    store.initialize(labels=["fire"], total_images=3)
    store.append_items([
        {"image_id": "a", "status": "success", "boxes": [{"label": "fire"}]},
        {"image_id": "b", "status": "empty", "boxes": []},
        {"image_id": "c", "status": "failed", "boxes": []},
    ])
    assert store.statistics() == dict(total=3, success=1, empty=1, failed=1,
                                      accepted=0, rejected=0, unreviewed=2, boxes=1, gt_committed=0)
    store.apply_decisions([CandidateDecision("a", True), CandidateDecision("b", False)])
    assert store.statistics()["gt_committed"] == 0
    store.record_commit_summaries([{"image_id": "a", "box_count": 1}])
    store.record_commit_summaries([{"image_id": "a", "box_count": 1}])
    assert store.statistics()["gt_committed"] == 1




def test_committed_gt_is_visible_for_audit_but_never_frozen_for_reapproval(tmp_path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="gt-commit-scope")
    store.initialize(labels=["fire"], total_images=4)
    store.append_items([
        {"image_id": "a", "status": "success", "boxes": [{"label": "fire"}]},
        {"image_id": "b", "status": "empty", "boxes": []},
        {"image_id": "c", "status": "empty", "boxes": []},
        {"image_id": "d", "status": "success", "boxes": [{"label": "fire"}]},
    ])
    store.record_commit_summaries([
        {"image_id": "a", "box_count": 1},
        {"image_id": "b", "box_count": 0},
    ])
    all_page = store.read_page(cursor="0", limit=20, filter="all")
    assert all_page.total == 4
    assert {item["image_id"] for item in all_page.items if item["gt_committed"]} == {"a", "b"}
    committed_page = store.read_page(cursor="0", limit=20, filter="committed")
    assert committed_page.total == 2
    assert {item["image_id"] for item in committed_page.items} == {"a", "b"}
    assert store.review_counts()["committed"] == 2

    # Read-only audit can show committed records; action scopes never select them.
    assert list(store.iter_selected_ids(filter="all")) == ["c", "d"]
    assert list(store.iter_selected_ids(filter="empty")) == ["c"]
    assert list(store.iter_selected_ids(filter="committed")) == []
    assert list(store.iter_selected_ids(filter="clean_boxes")) == ["d"]





def test_automatic_ambiguity_draft_cannot_be_bulk_accepted_as_human_review(tmp_path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="auto-overlap")
    store.initialize(labels=["person", "tangzhe"], total_images=2)
    a = {"label": "person", "x1": 10, "y1": 10, "x2": 70, "y2": 80}
    b = {**a, "label": "tangzhe"}
    store.append_items([
        {"image_id": "auto", "status": "success", "boxes": [a, b], "manual_review_required": True},
        {"image_id": "manual", "status": "success", "boxes": [a, b], "manual_review_required": True},
    ])
    first = store.save_draft("auto", [a], expected_revision=0, actor="reviewer",
                             request_id="auto-request", automatic=True)
    assert first["auto_resolution"] is True
    assert store.save_draft("auto", [a], expected_revision=0, actor="reviewer",
                            request_id="auto-request", automatic=True) == first
    with pytest.raises(ValueError, match="request_id reused"):
        store.save_draft("auto", [a], expected_revision=0, actor="reviewer",
                         request_id="auto-request", automatic=False)
    store.save_draft("manual", [b], expected_revision=0, actor="reviewer",
                     request_id="manual-request")
    store.decide_unmentioned(True)
    assert store.get("auto")["accepted"] is None
    assert store.get("auto")["draft"]["auto_resolution"] is True
    assert store.get("manual")["accepted"] is True
    assert store.review_counts()["unreviewed_reviewable"] == 1
    store.apply_decisions([CandidateDecision("auto", True)])
    assert store.get("auto")["accepted"] is True
    assert store.statistics()["gt_committed"] == 0


def test_review_filters_separate_clean_boxes_from_ambiguous_candidates(tmp_path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="ambiguous-filter")
    store.initialize(labels=["person", "tangzhe"], total_images=4)
    a = {"label": "person", "x1": 10, "y1": 10, "x2": 70, "y2": 80}
    b = {**a, "label": "tangzhe"}
    store.append_items([
        {"image_id": "conflict", "status": "success", "boxes": [a, b],
         "manual_review_required": True},
        {"image_id": "clean", "status": "success", "boxes": [a]},
        {"image_id": "zero", "status": "empty", "boxes": []},
        {"image_id": "failed", "status": "failed", "boxes": []},
    ])
    assert [row["image_id"] for row in store.read_page(cursor=None, filter="clean_boxes").items] == ["clean"]
    assert [row["image_id"] for row in store.read_page(cursor=None, filter="ambiguous").items] == ["conflict"]
    counts = store.review_counts()
    assert counts["with_boxes"] == 2 and counts["clean_boxes"] == 1 and counts["ambiguous"] == 1 and counts["zero"] == 1
    assert list(store.iter_selected_ids(filter="ambiguous")) == ["conflict"]
    # A saved draft remains in the ambiguity review queue until a verified GT commit.
    store.save_draft("conflict", [a], expected_revision=0, actor="reviewer", request_id="filter-draft")
    assert store.review_counts()["ambiguous"] == 1
    store.apply_decisions([CandidateDecision("conflict", True)])
    store.record_commit_summaries([{"image_id": "conflict", "box_count": 1}])
    assert store.review_counts()["ambiguous"] == 0


def test_cross_label_candidate_requires_corrected_human_draft_before_accept(tmp_path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="overlap-review")
    store.initialize(labels=["person", "tangzhe"], total_images=2)
    person = {"label": "person", "x1": 10, "y1": 10, "x2": 70, "y2": 80}
    lying = {**person, "label": "tangzhe"}
    safe = {"label": "person", "x1": 100, "y1": 100, "x2": 130, "y2": 160}
    store.append_items([
        {"image_id": "conflict", "status": "success", "boxes": [person, lying, safe],
         "manual_review_required": True, "review_conflicts": [{"labels": ["person", "tangzhe"], "iou": 1.0}]},
        {"image_id": "clean", "status": "success", "boxes": [safe]},
    ])
    with pytest.raises(ValueError, match="人工消歧"):
        store.apply_decisions([CandidateDecision("conflict", True)])
    store.decide_unmentioned(True)
    assert store.get("clean")["accepted"] is True
    assert store.get("conflict")["accepted"] is None
    with pytest.raises(ValueError, match="跨标签"):
        store.save_draft("conflict", [person, lying, safe], expected_revision=0,
                         actor="reviewer", request_id="invalid-draft")
    saved = store.save_draft("conflict", [lying, safe], expected_revision=0,
                             actor="reviewer", request_id="corrected-draft")
    assert saved["revision"] == 1
    store.apply_decisions([CandidateDecision("conflict", True)])
    accepted = store.get("conflict")
    assert accepted["accepted"] is True
    assert [row["label"] for row in accepted["boxes"]] == ["tangzhe", "person"]
    assert store.statistics()["gt_committed"] == 0


def test_explicit_review_scope_is_durable_per_image_and_cleared_on_new_decision(tmp_path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="per-image-scope", page_size=1)
    store.initialize(labels=["fire", "smoke"], total_images=2)
    store.append_items([
        {"image_id": "first", "status": "empty", "boxes": []},
        {"image_id": "second", "status": "empty", "boxes": []},
    ])
    store.apply_decisions([
        CandidateDecision("first", True, review_scope=["fire"]),
        CandidateDecision("second", True, review_scope=["smoke"]),
    ], allowed_statuses={"empty"})
    assert store.read_page(cursor=None, limit=1).items[0]["review_scope"] == ["fire"]
    assert store.read_page(cursor="1", limit=1).items[0]["review_scope"] == ["smoke"]

    # A later edit must never inherit an unrelated, previously accepted scope.
    store.apply_decisions([CandidateDecision("first", False)], allowed_statuses={"empty"})
    assert "review_scope" not in store.get("first")
    store.apply_decisions([CandidateDecision("second", True)], allowed_statuses={"empty"})
    assert "review_scope" not in store.get("second")


@pytest.mark.parametrize("scope", [[], ["fire", "fire"], ["fire ", "smoke"]])
def test_invalid_per_image_scope_rolls_back_the_whole_decision_page(tmp_path, scope):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="invalid-image-scope")
    store.initialize(labels=["fire", "smoke"], total_images=2)
    store.append_items([
        {"image_id": "first", "status": "empty", "boxes": []},
        {"image_id": "second", "status": "empty", "boxes": []},
    ])
    with pytest.raises(ValueError, match="review scope"):
        store.apply_decisions([
            CandidateDecision("first", True, review_scope=["fire"]),
            CandidateDecision("second", True, review_scope=scope),
        ])
    assert store.summary()["unreviewed"] == 2
    assert "review_scope" not in store.get("first")


def test_21163_distinct_per_image_attestations_remain_indexed_and_page_bounded(tmp_path):
    total = 21_163
    store = CandidateStore(ArtifactStore(tmp_path), task_id="supplemental-review-scale")
    store.initialize(labels=["fire", "smoke"], total_images=total)
    store.append_items({
        "image_id": f"image-{index:05d}", "status": "empty", "boxes": [],
    } for index in range(total))
    store.apply_decisions((
        CandidateDecision(f"image-{index:05d}", True,
            review_scope=["fire"] if index % 2 else ["smoke"])
        for index in range(total)
    ), allowed_statuses={"empty"})
    first = store.read_page(cursor=None, limit=50)
    last = store.read_page(cursor=str(total - 13), limit=50)
    assert first.total == last.total == total
    assert len(first.items) == 50 and len(last.items) == 13
    assert first.items[0]["review_scope"] == ["smoke"]
    assert first.items[1]["review_scope"] == ["fire"]
    assert last.items[-1]["review_scope"] == ["smoke"]
    assert store.summary()["accepted"] == total


def test_gt_journal_audit_pages_by_stable_image_id_without_loading_all(tmp_path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="audit-pages")
    store.initialize(labels=["fire"], total_images=0)
    store.record_commit_summaries([{"image_id": value, "box_count": 0} for value in ("z", "a", "b")])
    first = store.read_commit_page(limit=2)
    assert [row["image_id"] for row in first.items] == ["a", "b"]
    assert first.total == 3 and first.next_cursor == "b"
    second = store.read_commit_page(cursor=first.next_cursor, limit=2)
    assert [row["image_id"] for row in second.items] == ["z"]
    assert second.next_cursor is None
    with pytest.raises(ValueError, match="page size"):
        store.read_commit_page(limit=101)
    with pytest.raises(ValueError, match="cursor"):
        store.read_commit_page(cursor="x" * 201)


def test_shared_runtime_contract_exposes_annotation_dependencies(tmp_path: Path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    record = TaskRecord.new(
        "task-contract", "project-1", TaskKind.AI_ANNOTATION, "request.json",
        "vision:model-1", required_capabilities=("vision_provider",),
    )
    created = repository.create(record)
    page = repository.list(
        project_id="project-1", kinds={TaskKind.AI_ANNOTATION},
        statuses={TaskStatus.QUEUED}, limit=50,
    )
    assert artifacts.root.is_dir()
    assert created.status is TaskStatus.QUEUED
    assert [item.task_id for item in page.items] == ["task-contract"]


def test_candidate_pages_default_to_unreviewed_and_keep_explicit_false(tmp_path: Path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="task-1", page_size=2)
    store.initialize(labels=["fire"], total_images=3)
    store.append_items([
        {"image_id": "a", "status": "success", "boxes": [{"id": "box-a", "label": "fire"}]},
        {"image_id": "b", "status": "empty", "boxes": []},
        {"image_id": "c", "status": "failed", "boxes": [], "error": "provider timeout"},
    ])
    first = store.read_page(cursor=None, limit=2)
    assert [item["accepted"] for item in first.items] == [None, None]
    assert first.next_cursor == "2"
    store.apply_decisions([
        CandidateDecision(image_id="a", accepted=False),
        CandidateDecision(image_id="b", accepted=False),
    ])
    assert [item["accepted"] for item in store.read_page(cursor=None, limit=2).items] == [False, False]
    # Failed provider generations have no candidate decision for a human to make,
    # so they must not inflate the public pending-review count.
    assert store.summary() == {
        "total": 3, "success": 1, "empty": 1, "failed": 1,
        "accepted": 0, "rejected": 2, "unreviewed": 0, "boxes": 1,
    }


def test_generation_prefix_uses_candidate_sqlite_as_durable_recovery_truth(tmp_path: Path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="recovery-prefix", page_size=50)
    store.initialize(labels=["fire"], total_images=3)
    store.append_items([
        {"image_id": "one", "status": "success", "boxes": [{"id": "a", "label": "fire"}]},
        {"image_id": "two", "status": "failed", "boxes": [], "error": "timeout"},
    ])
    assert store.generation_prefix(["one", "two", "three"]) == {
        "next_index": 2,
        "succeeded": 1,
        "failed": 1,
    }


def test_generation_prefix_fails_closed_when_candidate_order_differs_from_request(tmp_path: Path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="recovery-order", page_size=50)
    store.initialize(labels=["fire"], total_images=2)
    store.append_items([
        {"image_id": "two", "status": "success", "boxes": []},
    ])
    with pytest.raises(ValueError, match="recovery order"):
        store.generation_prefix(["one", "two"])


def test_candidate_artifact_rejects_path_traversal(tmp_path: Path):
    # ArtifactStore now rejects an unsafe task id before CandidateStore can even
    # create a database path; keep the guard at the earliest security boundary.
    with pytest.raises(ValueError, match="task id"):
        CandidateStore(ArtifactStore(tmp_path), task_id="../outside", page_size=2)


def test_all_rejected_is_not_interpreted_as_all_selected(tmp_path: Path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="reject-all", page_size=50)
    store.initialize(labels=["fire"], total_images=2)
    store.append_items([
        {"image_id": "one", "status": "success", "boxes": [{"id": "a", "label": "fire"}]},
        {"image_id": "two", "status": "empty", "boxes": []},
    ])
    store.reject_all_reviewable()
    assert [item["accepted"] for item in store.all_items()] == [False, False]
    assert store.summary()["accepted"] == 0
    assert store.summary()["unreviewed"] == 0


def test_review_can_replace_candidate_boxes_before_acceptance(tmp_path: Path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="edit-candidate", page_size=50)
    store.initialize(labels=["fire", "smoke"], total_images=1)
    store.append_items([{"image_id": "one", "status": "success", "boxes": [{"label": "fire"}]}])
    store.apply_decisions([CandidateDecision(
        image_id="one", accepted=True,
        boxes=[{"label": "smoke", "class_id": 1, "x1": 1, "y1": 2, "x2": 30, "y2": 40}],
    )])
    item = store.all_items()[0]
    assert item["accepted"] is True
    assert item["boxes"] == [{"label": "smoke", "class_id": 1, "x1": 1, "y1": 2, "x2": 30, "y2": 40}]
    assert store.summary()["boxes"] == 1


def test_candidate_get_many_is_bounded_and_preserves_review_truth(tmp_path: Path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="batch-lookup", page_size=50)
    store.initialize(labels=["fire"], total_images=3)
    store.append_items([
        {"image_id": "one", "status": "success", "boxes": [{"label": "fire"}]},
        {"image_id": "two", "status": "empty", "boxes": []},
        {"image_id": "three", "status": "failed", "boxes": [], "error": "timeout"},
    ])
    store.apply_decisions([CandidateDecision(image_id="two", accepted=True)])
    rows = store.get_many(["two", "missing", "one"])
    assert list(rows) == ["one", "two"] or set(rows) == {"one", "two"}
    assert rows["one"]["accepted"] is None
    assert rows["two"]["accepted"] is True
    with pytest.raises(ValueError, match="limited to 200"):
        store.get_many([f"image-{index}" for index in range(201)])

def test_large_review_decisions_batch_candidate_reads_and_fail_closed(tmp_path: Path, monkeypatch):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="large-review", page_size=50)
    total = 1001
    store.initialize(labels=["fire"], total_images=total)
    store.append_items([
        {
            "image_id": f"image-{index:04d}",
            "status": "success",
            "boxes": [{"label": "fire", "class_id": 0}],
        }
        for index in range(total)
    ])

    original_connect = store._connect
    candidate_selects: list[str] = []

    class CountingConnection:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args):
            normalized = " ".join(str(sql).split())
            if "SELECT * FROM candidates WHERE image_id IN (" in normalized:
                candidate_selects.append(normalized)
            if "SELECT * FROM candidates WHERE image_id=?" in normalized:
                raise AssertionError("large review decisions must not issue one SELECT per image")
            return self._inner.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(store, "_connect", lambda: CountingConnection(original_connect()))
    store.apply_decisions(
        [
            CandidateDecision(image_id=f"image-{index:04d}", accepted=True)
            for index in range(total)
        ],
        allowed_statuses={"success", "empty"},
    )
    assert len(candidate_selects) == 6

    with pytest.raises(ValueError, match="missing or unavailable"):
        store.apply_decisions(
            [
                CandidateDecision(image_id="image-0000", accepted=False),
                CandidateDecision(image_id="missing-image", accepted=True),
            ],
            allowed_statuses={"success", "empty"},
        )

    # The invalid second decision rolls back the whole transaction.
    assert store.get_many(["image-0000"])["image-0000"]["accepted"] is True


def test_label_revalidation_pages_large_candidate_store(tmp_path: Path, monkeypatch):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="large-remap", page_size=50)
    total = 1001
    store.initialize(labels=["fire"], total_images=total)
    store.append_items([
        {
            "image_id": f"image-{index:04d}",
            "status": "success",
            "boxes": [{"label": "fire", "class_id": 0}],
        }
        for index in range(total)
    ])

    original_connect = store._connect
    page_reads: list[str] = []

    class CountingConnection:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args):
            normalized = " ".join(str(sql).split())
            if (
                "WHERE status IN ('success','empty') AND ordinal>?" in normalized
                and "LIMIT 200" in normalized
            ):
                page_reads.append(normalized)
            return self._inner.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(store, "_connect", lambda: CountingConnection(original_connect()))
    store.remap_labels({}, {"fire": 0})
    assert len(page_reads) == 6

def test_candidate_write_session_reuses_connection_but_commits_every_image(
    tmp_path: Path, monkeypatch,
):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="generation-writer", page_size=50)
    total = 1001
    store.initialize(labels=["fire"], total_images=total)

    original_connect = store._connect
    connection_count = 0
    commit_count = 0
    guard_count = 0

    class CountingConnection:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, *args, **kwargs):
            return self._inner.execute(*args, **kwargs)

        def commit(self):
            nonlocal commit_count
            commit_count += 1
            return self._inner.commit()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def counted_connect():
        nonlocal connection_count
        connection_count += 1
        return CountingConnection(original_connect())

    def guard():
        nonlocal guard_count
        guard_count += 1

    monkeypatch.setattr(store, "_connect", counted_connect)
    with store.write_session(commit_guard=guard) as append_candidate:
        for index in range(total):
            append_candidate([{
                "image_id": f"image-{index:05d}",
                "status": "empty",
                "boxes": [],
            }])

    assert connection_count == 2
    assert commit_count == total
    assert guard_count == total
    assert store.summary()["total"] == total

def test_generation_prefix_20k_reads_bounded_pages(tmp_path: Path, monkeypatch):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="recovery-20k", page_size=50)
    total = 20_000
    image_ids = [f"image-{index:05d}" for index in range(total)]
    store.initialize(labels=["fire"], total_images=total)
    store.append_items(
        {
            "image_id": image_id,
            "status": "failed" if index % 11 == 0 else "empty",
            "boxes": [],
        }
        for index, image_id in enumerate(image_ids)
    )

    original_connect = store._connect
    page_reads = []

    class CountingConnection:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args):
            normalized = " ".join(str(sql).split())
            if "SELECT image_id,status FROM candidates ORDER BY ordinal" in normalized:
                raise AssertionError("recovery must not fetch the full candidate table")
            if (
                "SELECT ordinal,image_id,status FROM candidates" in normalized
                and "WHERE ordinal>?" in normalized
                and "LIMIT 500" in normalized
            ):
                page_reads.append(normalized)
            return self._inner.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(
        store,
        "_connect",
        lambda: CountingConnection(original_connect()),
    )
    result = store.generation_prefix(image_ids)

    assert result["next_index"] == total
    assert result["failed"] == sum(1 for index in range(total) if index % 11 == 0)
    assert result["succeeded"] + result["failed"] == total
    assert len(page_reads) == 40

def test_generation_prefix_rejects_more_rows_than_immutable_input(tmp_path: Path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="recovery-overrun", page_size=50)
    store.initialize(labels=["fire"], total_images=2)
    store.append_items([
        {"image_id": "one", "status": "empty", "boxes": []},
        {"image_id": "two", "status": "empty", "boxes": []},
    ])
    with pytest.raises(ValueError, match="more rows than task input"):
        store.generation_prefix(["one"])

def test_large_candidate_iterators_reuse_one_read_connection(
    tmp_path: Path, monkeypatch,
):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="iterator-scale", page_size=50)
    total = 10_001
    store.initialize(labels=["fire"], total_images=total)
    store.append_items(
        {
            "image_id": f"image-{index:05d}",
            "status": "success",
            "boxes": [{"label": "fire", "class_id": 0}],
        }
        for index in range(total)
    )
    store.decide_unmentioned(True)

    original_connect = store._connect
    connection_count = 0
    item_reads = 0
    accepted_reads = 0

    class CountingConnection:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args):
            nonlocal item_reads, accepted_reads
            normalized = " ".join(str(sql).split())
            if (
                "SELECT * FROM candidates WHERE ordinal>? AND accepted=1" in normalized
                and "LIMIT 200" in normalized
            ):
                accepted_reads += 1
            elif (
                "SELECT * FROM candidates WHERE ordinal>? ORDER BY ordinal LIMIT 200"
                in normalized
            ):
                item_reads += 1
            return self._inner.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def counted_connect():
        nonlocal connection_count
        connection_count += 1
        return CountingConnection(original_connect())

    monkeypatch.setattr(store, "_connect", counted_connect)

    assert sum(1 for _ in store.iter_items()) == total
    assert connection_count == 2
    assert item_reads == 51

    connection_count = 0
    assert sum(1 for _ in store.iter_accepted_items()) == total
    assert connection_count == 2
    assert accepted_reads == 51


def test_draft_cas_and_original_evidence(tmp_path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id='draft')
    store.initialize(labels=['fire'], total_images=1)
    store.append_items([{'image_id':'a','status':'success','boxes':[{'label':'fire','x':1}]}])
    result=store.save_draft('a',[{'label':'fire','x':2}],expected_revision=0,actor='reviewer',request_id='r1')
    assert result['revision']==1
    assert store.get('a')['boxes'][0]['x']==2
    assert store.get('a')['original_boxes'][0]['x']==1
    assert store.save_draft('a',[{'label':'fire','x':2}],expected_revision=0,actor='reviewer',request_id='r1')==result
    with pytest.raises(ValueError,match='revision'):
        store.save_draft('a',[],expected_revision=0,actor='other',request_id='r2')
    assert CandidateStore(ArtifactStore(tmp_path),task_id='draft').get('a')['draft_revision']==1


def test_transfer_cannot_be_accepted_by_explicit_or_implicit_decision(tmp_path):
    store=CandidateStore(ArtifactStore(tmp_path),task_id='transfer')
    store.initialize(labels=['fire'],total_images=3)
    store.append_items([{'image_id':i,'status':'empty','boxes':[]} for i in ['a','b','c']])
    store.set_review_exclusion('a','transferred',operation_id='op',actor='reviewer')
    store.apply_decisions([CandidateDecision('b',False)])
    store.decide_unmentioned(True)
    assert [i['image_id'] for i in store.iter_accepted_items()]==['c']
    with pytest.raises(ValueError,match='unavailable'):
        store.apply_decisions([CandidateDecision('a',True)])
    assert store.review_counts()['remaining_reviewable']==1
    assert store.read_page(cursor=None,filter='transferred').items[0]['image_id']=='a'
    assert list(store.iter_selected_ids(filter='zero'))==['b','c']

def test_draft_retry_and_pending_transfer_preserve_human_work(tmp_path):
    store=CandidateStore(ArtifactStore(tmp_path),task_id='retry-safe')
    store.initialize(labels=['fire'],total_images=2)
    store.append_items([{'image_id':i,'status':'success','boxes':[{'label':'fire'}]} for i in ['a','b']])
    store.save_draft('a',[],expected_revision=0,actor='reviewer',request_id='save')
    store.set_review_exclusion('b','pending_transfer',operation_id='op',actor='reviewer')
    revision=store.review_revision()
    store.append_items([{'image_id':i,'status':'failed','boxes':[]} for i in ['a','b']])
    assert store.review_revision()==revision
    assert store.get('a')['status']=='success'
    assert store.get('a')['boxes']==[]
    assert store.get('a')['original_boxes']==[{'label':'fire'}]
    store.decide_unmentioned(True)
    assert [i['image_id'] for i in store.iter_accepted_items()]==['a']
    assert store.get('b')['review_operation_id']=='op'
    store.set_review_exclusion('b','transferred',operation_id='op',actor='reviewer')
    revision=store.review_revision()
    store.set_review_exclusion('b','transferred',operation_id='op',actor='reviewer')
    assert store.review_revision()==revision


def test_finalized_rows_are_unavailable_but_worker_can_replay_journal(tmp_path):
    store=CandidateStore(ArtifactStore(tmp_path),task_id='finalized')
    store.initialize(labels=['fire'],total_images=1)
    store.append_items([{'image_id':'a','status':'empty','boxes':[]}])
    store.decide_unmentioned(True)
    store.record_commit_summaries([{'image_id':'a','box_count':0}])
    assert list(store.iter_accepted_items())==[]
    assert len(list(store.iter_accepted_items(include_committed=True)))==1
    assert store.review_counts()['remaining_reviewable']==0
    with pytest.raises(ValueError,match='finalized'):
        store.set_review_exclusion('a','transferred',operation_id='op',actor='reviewer')
    with pytest.raises(ValueError,match='unavailable'):
        store.save_draft('a',[],expected_revision=0,actor='reviewer',request_id='save')


def test_draft_cas_has_one_winner_for_concurrent_reviewers(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store=CandidateStore(ArtifactStore(tmp_path),task_id='concurrent')
    store.initialize(labels=['fire'],total_images=1)
    store.append_items([{'image_id':'a','status':'empty','boxes':[]}])
    def save(actor):
        try:
            return store.save_draft('a',[],expected_revision=0,actor=actor,request_id=actor)['revision']
        except ValueError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(map(str,executor.map(save,['first','second'])))==['1','conflict']


def test_review_counts_and_ids_never_materialize_large_box_payloads(tmp_path, monkeypatch):
    store=CandidateStore(ArtifactStore(tmp_path),task_id='large-review')
    store.initialize(labels=['fire'],total_images=20000)
    store.append_items({'image_id':str(i),'status':'empty','boxes':[]} for i in range(20000))
    monkeypatch.setattr(store,'_decode',lambda *_:pytest.fail('count/id scan decoded boxes'))
    assert store.review_counts()['unreviewed_reviewable']==20000
    assert len(list(store.iter_selected_ids('empty')))==20000

def test_transfer_retry_restores_pending_and_cannot_steal_another_operation(tmp_path):
    store=CandidateStore(ArtifactStore(tmp_path),task_id='transfer-recovery')
    store.initialize(labels=['fire'],total_images=1)
    store.append_items([{'image_id':'a','status':'empty','boxes':[]}])
    store.set_review_exclusion('a','pending_transfer',operation_id='op',actor='reviewer')
    store.set_review_exclusion('a','blocked',operation_id='op',actor='reviewer')
    with pytest.raises(ValueError,match='operation'):
        store.set_review_exclusion('a','pending_transfer',operation_id='other',actor='reviewer')
    store.set_review_exclusion('a','pending_transfer',operation_id='op',actor='reviewer')
    assert store.get('a')['review_state']=='pending_transfer'
    store.set_review_exclusion('a','transferred',operation_id='op',actor='reviewer')
    store.set_review_exclusion('a','active',operation_id='op',actor='reviewer')
    with pytest.raises(ValueError,match='undone'):
        store.set_review_exclusion('a','transferred',operation_id='op',actor='reviewer')


def test_final_decision_uses_updated_draft_and_retains_original_evidence(tmp_path):
    store=CandidateStore(ArtifactStore(tmp_path),task_id='mapped-draft')
    store.initialize(labels=['fire','smoke'],total_images=1)
    store.append_items([{'image_id':'a','status':'success','boxes':[{'label':'fire','x1':1,'y1':2,'x2':3,'y2':4}]}])
    store.save_draft('a',[{'label':'fire','x1':5,'y1':6,'x2':8,'y2':9}],expected_revision=0,actor='r',request_id='save')
    store.apply_decisions([CandidateDecision('a',True,[{'label':'smoke','x1':5,'y1':6,'x2':8,'y2':9}])])
    assert next(store.iter_accepted_items())['boxes'][0]['label']=='smoke'
    assert store.get('a')['original_boxes'][0]['label']=='fire'


def test_transfer_outbox_reads_are_bounded_and_never_decode_candidate_boxes(tmp_path, monkeypatch):
    store=CandidateStore(ArtifactStore(tmp_path),task_id='outbox-paging')
    store.initialize(labels=['fire'],total_images=500)
    for start in range(0,500,200):
        store.write_transfer_receipts('operation',{str(i):{'image_id':str(i),'status':'transferred'} for i in range(start,min(500,start+200))})
    monkeypatch.setattr(store,'_decode',lambda *_:pytest.fail('receipt query decoded candidate boxes'))
    assert len(store.read_transfer_receipts('operation'))==200
    assert len(store.read_transfer_receipts('operation',offset=400))==100
    assert store.transfer_receipt_counts('operation')=={'transferred':500,'total':500}
    assert len(store.transfer_receipt_statuses('operation'))==500

def test_undo_state_and_outbox_receipt_rollback_together(tmp_path):
    import sqlite3
    store=CandidateStore(ArtifactStore(tmp_path),task_id='atomic-undo')
    store.initialize(labels=['fire'],total_images=1)
    store.append_items([{'image_id':'a','status':'empty','boxes':[]}])
    store.set_review_exclusion('a','transferred',operation_id='operation',actor='reviewer')
    store.write_transfer_receipts('operation',{'a':{'image_id':'a','status':'transferred'}})
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER fail_undo_receipt BEFORE UPDATE ON review_transfer_receipts WHEN NEW.status='undone' BEGIN SELECT RAISE(ABORT,'isolated outbox commit failure');END")
    with pytest.raises(sqlite3.IntegrityError,match='isolated outbox'):
        store.set_review_exclusion('a','active',operation_id='operation',actor='reviewer',transfer_receipt={'image_id':'a','status':'undone'})
    assert store.get('a')['review_state']=='transferred'
    assert store.read_transfer_receipts('operation')['a']['status']=='transferred'
