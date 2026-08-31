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
    assert store.summary() == {
        "total": 3, "success": 1, "empty": 1, "failed": 1,
        "accepted": 0, "rejected": 2, "unreviewed": 1, "boxes": 1,
    }


def test_candidate_artifact_rejects_path_traversal(tmp_path: Path):
    store = CandidateStore(ArtifactStore(tmp_path), task_id="../outside", page_size=2)
    with pytest.raises(ValueError, match="task id"):
        store.initialize(labels=["fire"], total_images=0)


def test_all_rejected_is_not_interpreted_as_all_selected(tmp_path):
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


def test_review_can_replace_candidate_boxes_before_acceptance(tmp_path):
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
