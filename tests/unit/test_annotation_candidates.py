from pathlib import Path

import pytest

from platform_core.annotation_candidates import CandidateDecision, CandidateStore
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus


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

