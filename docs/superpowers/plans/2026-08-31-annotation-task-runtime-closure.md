# Annotation Task Runtime Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AI annotation and batch manual annotation durable, cancellable, recoverable, explicitly reviewable, bounded in payload/DOM size, and truthful under refresh, restart, rapid navigation, partial failure, and all-rejected review.

**Architecture:** Consume the shared persistent task runtime from `platform_core/task_runtime/` rather than maintaining `prelabel_tasks.json` or another annotation-only scheduler. Store AI request data and candidate pages as private task artifacts, expose only bounded public DTOs, and keep per-candidate `accepted: true | false | null` separate from the shared task execution status. Move browser concurrency, dirty-save navigation, virtual windows, and single-instance polling into small ES modules; retain `static/app.js` only as the final compatibility wiring layer.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, Pillow, the existing vision-provider adapters, shared `platform_core.task_runtime`, vanilla ES modules, Node test runner, pytest, Playwright.

---

## Shared Runtime Dependency and File Map

This plan starts after the video/training runtime plan has created these shared files:

- `platform_core/task_runtime/models.py`
- `platform_core/task_runtime/repository.py`
- `platform_core/task_runtime/scheduler.py`
- `platform_core/task_runtime/worker.py`
- `platform_core/task_runtime/process_control.py`
- `platform_core/task_runtime/artifacts.py`

The annotation implementation must import, not redefine:

```python
from platform_core.task_runtime import (
    ArtifactStore, Scheduler, TaskKind, TaskPage, TaskRecord,
    TaskRepository, TaskStatus, WorkerContext,
)
```

The shared enum values consumed here are:

```python
TaskStatus.QUEUED
TaskStatus.RUNNING
TaskStatus.AWAITING_CONFIRMATION
TaskStatus.PARTIAL_SUCCESS
TaskStatus.SUCCEEDED
TaskStatus.CANCEL_REQUESTED
TaskStatus.CANCELLED
TaskStatus.FAILED
TaskStatus.BLOCKED_BY_ENVIRONMENT
TaskStatus.BLOCKED_BY_HARDWARE
TaskKind.AI_ANNOTATION
```

The required repository contract is exact:

```python
TaskRepository.create(record) -> TaskRecord
TaskRepository.get(task_id) -> TaskRecord | None
TaskRepository.list(project_id=None, kinds=None, statuses=None, limit=50, cursor=None) -> TaskPage
TaskRepository.claim_next(worker_id, kinds, capabilities, lease_seconds=30) -> TaskLease | None
TaskRepository.heartbeat(task_id, lease_token, progress=None, stage=None, current_item=None) -> TaskRecord
TaskRepository.request_cancel(task_id) -> TaskRecord
TaskRepository.finish(task_id, lease_token, status, result_ref=None, error=None, accepted=None) -> TaskRecord
TaskRepository.complete_review(task_id, status, result_ref, accepted, error=None) -> TaskRecord
TaskRepository.retry(task_id) -> TaskRecord
TaskRepository.release_expired(now=None) -> int
```

`WorkerContext` provides `task`, `lease`, `repository`, `artifacts`, `cancel_requested()`, `load_checkpoint()`, and `save_checkpoint()`. `ArtifactStore` provides `atomic_write_json`, `read_json`, `append_log`, and `artifact_path`, using a task id plus a traversal-safe relative path.

Files created or modified by this plan:

- Create `platform_core/annotation_candidates.py`: paged candidate artifacts, tri-state review decisions, summaries, and idempotent decision persistence.
- Create `platform_core/annotation_task_service.py`: AI task creation, shared-worker handler, cancellation checkpoints, retry selection, recovery registration, and idempotent annotation commit.
- Create `static/modules/annotation-workbench.js`: one annotation session, dirty-save navigation, stale-request tokens, and queue virtualization.
- Create `static/modules/task-poller.js`: keyed single-instance polling with abort and single-flight behavior.
- Create `static/modules/annotation-task-view.js`: public task row projection, paged candidate review state, and bounded candidate windows.
- Modify `app.py:40`, `app.py:10474-10476`, `app.py:11742-12013`, `app.py:12245-12256`: replace v47 AI task persistence/API wiring with the shared runtime while keeping compatibility routes.
- Modify `static/main.mjs:1-49`: expose the new pure modules through `window.PlatformCore`.
- Modify `static/modules/annotation.js:3-20`: preserve true box counts above the preview limit.
- Modify `static/app.js:510-524`, `static/app.js:578`, `static/app.js:2840-2868`, `static/app.js:3113-3118`, `static/app.js:3535-3577`, `static/app.js:3784`: wire the final effective layer to the new modules without full-page/modal rebuilds.
- Create `tests/unit/test_annotation_candidates.py`.
- Create `tests/unit/test_annotation_task_service.py`.
- Create `tests/api/test_annotation_task_runtime.py`.
- Create `tests/frontend/annotation-workbench.test.mjs`.
- Create `tests/frontend/task-poller.test.mjs`.
- Create `tests/frontend/annotation-task-view.test.mjs`.
- Create `tests/browser/annotation-runtime.spec.mjs`.

### Task 1: Lock the Shared Runtime Contract and Add Paged Candidate Artifacts

**Files:**
- Create: `platform_core/annotation_candidates.py`
- Create: `tests/unit/test_annotation_candidates.py`
- Test: `tests/unit/test_annotation_task_service.py`

- [ ] **Step 1: Write the failing shared-contract and candidate-store tests**

```python
# tests/unit/test_annotation_candidates.py
from pathlib import Path

from platform_core.annotation_candidates import CandidateDecision, CandidateStore
from platform_core.task_runtime.artifacts import ArtifactStore
from platform_core.task_runtime.models import TaskKind, TaskRecord, TaskStatus
from platform_core.task_runtime.repository import TaskRepository


def test_shared_runtime_contract_exposes_annotation_dependencies(tmp_path: Path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    record = TaskRecord.new(
        task_id="task-contract", project_id="project-1",
        kind=TaskKind.AI_ANNOTATION, payload_ref="request.json",
        resource_key="vision:model-1", required_capabilities=("vision_provider",),
    )
    created = repository.create(record)
    page = repository.list(
        project_id="project-1",
        kinds={TaskKind.AI_ANNOTATION},
        statuses={TaskStatus.QUEUED},
        limit=50,
        cursor=None,
    )
    assert created.status is TaskStatus.QUEUED
    assert [item.task_id for item in page.items] == ["task-contract"]


def test_candidate_pages_default_to_unreviewed_and_keep_explicit_false(tmp_path: Path):
    artifacts = ArtifactStore(tmp_path)
    store = CandidateStore(artifacts, task_id="task-1", page_size=2)
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
    reviewed = store.read_page(cursor=None, limit=2)
    assert [item["accepted"] for item in reviewed.items] == [False, False]
    assert store.summary() == {
        "total": 3,
        "success": 1,
        "empty": 1,
        "failed": 1,
        "accepted": 0,
        "rejected": 2,
        "unreviewed": 1,
        "boxes": 1,
    }


def test_candidate_artifact_rejects_path_traversal(tmp_path: Path):
    artifacts = ArtifactStore(tmp_path)
    store = CandidateStore(artifacts, task_id="../outside", page_size=2)
    try:
        store.initialize(labels=["fire"], total_images=0)
    except ValueError as error:
        assert "task_id" in str(error) or "traversal" in str(error).lower()
    else:
        raise AssertionError("unsafe task id was accepted")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/unit/test_annotation_candidates.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'platform_core.annotation_candidates'`. If the shared runtime contract is incomplete, the first failure must name the missing shared class or method before annotation code is written.

- [ ] **Step 3: Implement the paged candidate store**

```python
# platform_core/annotation_candidates.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from pydantic import BaseModel

from .task_runtime.artifacts import ArtifactStore


class CandidateDecision(BaseModel):
    image_id: str
    accepted: bool


@dataclass(frozen=True)
class CandidatePage:
    items: list[dict[str, Any]]
    next_cursor: Optional[str]
    total: int


class CandidateStore:
    def __init__(self, artifacts: ArtifactStore, *, task_id: str, page_size: int = 50):
        if page_size < 1 or page_size > 200:
            raise ValueError("page_size must be between 1 and 200")
        self.artifacts = artifacts
        self.task_id = task_id
        self.page_size = page_size

    def initialize(self, *, labels: list[str], total_images: int) -> None:
        self.artifacts.atomic_write_json(self.task_id, "candidates/manifest.json", {
            "labels": list(labels),
            "total_images": int(total_images),
            "page_size": self.page_size,
            "pages": [],
            "items": 0,
        })

    def append_items(self, items: Iterable[dict[str, Any]]) -> None:
        manifest = self._manifest()
        pending = [self._normalize(item) for item in items]
        page_counts = list(manifest.get("pages") or [])
        if page_counts and page_counts[-1] < self.page_size and pending:
            page_number = len(page_counts) - 1
            relative = f"candidates/page-{page_number:06d}.json"
            page = list(self.artifacts.read_json(self.task_id, relative, default=[]))
            take = min(self.page_size - len(page), len(pending))
            page.extend(pending[:take])
            pending = pending[take:]
            self.artifacts.atomic_write_json(self.task_id, relative, page)
            page_counts[-1] = len(page)
            manifest["items"] = int(manifest["items"]) + take
            manifest["pages"] = page_counts
            self.artifacts.atomic_write_json(self.task_id, "candidates/manifest.json", manifest)
        while pending:
            page_number = len(page_counts)
            relative = f"candidates/page-{page_number:06d}.json"
            chunk = pending[: self.page_size]
            pending = pending[self.page_size :]
            self.artifacts.atomic_write_json(self.task_id, relative, chunk)
            page_counts.append(len(chunk))
            manifest["pages"] = page_counts
            manifest["items"] = int(manifest["items"]) + len(chunk)
            self.artifacts.atomic_write_json(self.task_id, "candidates/manifest.json", manifest)

    def read_page(self, *, cursor: Optional[str], limit: int = 50) -> CandidatePage:
        manifest = self._manifest()
        offset = int(cursor or 0)
        limit = max(1, min(200, int(limit)))
        all_items = self._read_range(offset, limit)
        next_offset = offset + len(all_items)
        total = int(manifest["items"])
        return CandidatePage(
            items=all_items,
            next_cursor=str(next_offset) if next_offset < total else None,
            total=total,
        )

    def apply_decisions(self, decisions: Iterable[CandidateDecision]) -> None:
        choice = {item.image_id: bool(item.accepted) for item in decisions}
        manifest = self._manifest()
        for page_number in range(len(manifest.get("pages") or [])):
            relative = f"candidates/page-{page_number:06d}.json"
            page = list(self.artifacts.read_json(self.task_id, relative, default=[]))
            changed = False
            for item in page:
                image_id = str(item.get("image_id") or "")
                if image_id in choice:
                    item["accepted"] = choice[image_id]
                    changed = True
            if changed:
                self.artifacts.atomic_write_json(self.task_id, relative, page)

    def summary(self) -> dict[str, int]:
        manifest = self._manifest()
        result = {"total": 0, "success": 0, "empty": 0, "failed": 0,
                  "accepted": 0, "rejected": 0, "unreviewed": 0, "boxes": 0}
        for item in self._read_range(0, int(manifest["items"])):
            result["total"] += 1
            status = str(item.get("status") or "failed")
            if status in {"success", "empty", "failed"}:
                result[status] += 1
            accepted = item.get("accepted")
            if accepted is True:
                result["accepted"] += 1
            elif accepted is False:
                result["rejected"] += 1
            else:
                result["unreviewed"] += 1
            result["boxes"] += len(item.get("boxes") or [])
        return result

    def all_items(self) -> list[dict[str, Any]]:
        manifest = self._manifest()
        return self._read_range(0, int(manifest["items"]))

    def _manifest(self) -> dict[str, Any]:
        return dict(self.artifacts.read_json(
            self.task_id, "candidates/manifest.json", default={"pages": [], "items": 0}
        ))

    def _read_range(self, offset: int, limit: int) -> list[dict[str, Any]]:
        manifest = self._manifest()
        result: list[dict[str, Any]] = []
        end = offset + limit
        page_start = 0
        for page_number, page_count in enumerate(manifest.get("pages") or []):
            page_end = page_start + int(page_count)
            if page_end <= offset or page_start >= end:
                page_start = page_end
                continue
            page = self.artifacts.read_json(
                self.task_id, f"candidates/page-{page_number:06d}.json", default=[]
            )
            left = max(0, offset - page_start)
            right = min(len(page), end - page_start)
            result.extend(dict(item) for item in page[left:right])
            page_start = page_end
        return result

    @staticmethod
    def _normalize(item: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(item)
        normalized["image_id"] = str(normalized.get("image_id") or "")
        normalized["accepted"] = None
        normalized["boxes"] = [dict(box) for box in normalized.get("boxes") or []]
        return normalized
```

- [ ] **Step 4: Run the candidate tests to verify they pass**

Run: `python -m pytest tests/unit/test_annotation_candidates.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit the candidate artifact boundary**

```bash
git add platform_core/annotation_candidates.py tests/unit/test_annotation_candidates.py
git commit -m "feat: add paged annotation candidate artifacts"
```

### Task 2: Add the AI Annotation Worker on the Shared Runtime

**Files:**
- Create: `platform_core/annotation_task_service.py`
- Create: `tests/unit/test_annotation_task_service.py`
- Modify: `app.py:40`

- [ ] **Step 1: Write failing worker outcome and cancellation tests**

```python
# tests/unit/test_annotation_task_service.py
from pathlib import Path

from platform_core.annotation_candidates import CandidateStore
from platform_core.annotation_task_service import run_ai_annotation
from platform_core.task_runtime.artifacts import ArtifactStore
from platform_core.task_runtime.models import TaskKind, TaskRecord, TaskStatus


class FakeContext:
    def __init__(self, tmp_path: Path, responses: dict[str, object]):
        self.artifacts = ArtifactStore(tmp_path)
        self.task = TaskRecord.new(
            task_id="ai-1", project_id="project-1", kind=TaskKind.AI_ANNOTATION,
            payload_ref="request.json", resource_key="vision:model-1",
            required_capabilities=("vision_provider",),
        )
        self.task = __import__("dataclasses").replace(self.task, status=TaskStatus.RUNNING)
        self.lease = type("Lease", (), {"lease_token": "lease-1"})()
        self.repository = type("Repository", (), {})()
        self.responses = responses
        self.finished = None
        self.heartbeats = []
        self._cancelled = False

    def cancel_requested(self):
        return self._cancelled

    def load_checkpoint(self):
        return self.artifacts.read_json("ai-1", "checkpoint.json", default={})

    def save_checkpoint(self, value):
        self.artifacts.atomic_write_json("ai-1", "checkpoint.json", value)


def test_worker_enters_review_with_partial_generation_summary(tmp_path, monkeypatch):
    context = FakeContext(tmp_path, {})
    context.artifacts.atomic_write_json("ai-1", "request.json", {
        "image_ids": ["one", "two"], "labels": ["fire"], "threshold": 0.45,
        "model_config_id": "model-1", "overwrite": False,
    })
    monkeypatch.setattr(
        "platform_core.annotation_task_service.load_task_images",
        lambda _project, _ids: [
            {"id": "one", "filename": "one.jpg", "width": 100, "height": 100, "path": "one.jpg"},
            {"id": "two", "filename": "two.jpg", "width": 100, "height": 100, "path": "two.jpg"},
        ],
    )
    monkeypatch.setattr(
        "platform_core.annotation_task_service.annotate_one",
        lambda _request, image: ({"boxes": [{"id": "box-1", "label": "fire"}]}
                                if image["id"] == "one" else (_ for _ in ()).throw(RuntimeError("timeout"))),
    )

    outcome = run_ai_annotation(context)

    assert outcome.status is TaskStatus.AWAITING_CONFIRMATION
    assert outcome.generation_partial is True
    assert context.load_checkpoint()["next_index"] == 2
    assert CandidateStore(context.artifacts, task_id="ai-1").summary()["failed"] == 1


def test_worker_stops_at_cancel_boundary_without_processing_more_images(tmp_path, monkeypatch):
    context = FakeContext(tmp_path, {})
    context._cancelled = True
    context.artifacts.atomic_write_json("ai-1", "request.json", {
        "image_ids": ["one"], "labels": ["fire"], "threshold": 0.45,
        "model_config_id": "model-1", "overwrite": False,
    })
    monkeypatch.setattr("platform_core.annotation_task_service.load_task_images", lambda *_: [{"id": "one"}])
    monkeypatch.setattr(
        "platform_core.annotation_task_service.annotate_one",
        lambda *_: (_ for _ in ()).throw(AssertionError("provider must not be called")),
    )

    outcome = run_ai_annotation(context)

    assert outcome.status is TaskStatus.CANCELLED
```

- [ ] **Step 2: Run the worker tests to verify they fail**

Run: `python -m pytest tests/unit/test_annotation_task_service.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'platform_core.annotation_task_service'`.

- [ ] **Step 3: Implement a checkpointed worker handler**

```python
# platform_core/annotation_task_service.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .annotation_candidates import CandidateStore
from .task_runtime.models import TaskStatus
from .task_runtime.worker import WorkerContext


@dataclass(frozen=True)
class WorkerOutcome:
    status: TaskStatus
    result_ref: str
    error: str | None = None
    generation_partial: bool = False


def load_task_images(project_id: str, image_ids: Iterable[str]) -> list[dict[str, Any]]:
    from app import load_images, project_dir
    wanted = {str(value) for value in image_ids}
    rows = []
    for image in load_images(project_id):
        if str(image.get("id")) not in wanted:
            continue
        row = dict(image)
        row["path"] = str(project_dir(project_id) / "uploads" / str(image.get("stored_name") or ""))
        rows.append(row)
    order = {str(image_id): index for index, image_id in enumerate(image_ids)}
    rows.sort(key=lambda image: order[str(image["id"])])
    return rows


def annotate_one(request: dict[str, Any], image: dict[str, Any]) -> dict[str, Any]:
    from app import _v47_build_annotation_prompt, _v47_runtime_provider
    from platform_core import auto_label as auto_label_core

    provider = request["_provider"]
    config = request["_provider_config"]
    prompt = _v47_build_annotation_prompt(
        config,
        request["label_catalog"],
        width=int(image["width"]),
        height=int(image["height"]),
        business_instruction=str(request.get("business_instruction") or ""),
        template=str(request.get("prompt_template") or ""),
    )
    response = provider.annotate(
        image_bytes=__import__("pathlib").Path(image["path"]).read_bytes(),
        prompt=prompt,
        output_schema=auto_label_core.CANDIDATE_OUTPUT_SCHEMA,
    )
    parsed = auto_label_core.parse_candidate_response(
        str(response.get("text") or ""),
        width=int(image["width"]),
        height=int(image["height"]),
        label_ids=request["label_ids"],
        label_aliases=request["label_aliases"],
    )
    threshold = float(request.get("threshold", 0.45))
    boxes = auto_label_core.nms_candidates(
        [box for box in parsed if float(box.get("confidence") or 0) >= threshold],
        iou_threshold=0.5,
    )
    return {"boxes": boxes, "response": response}


def run_ai_annotation(
    context: WorkerContext,
    *,
    annotate: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] = annotate_one,
) -> WorkerOutcome:
    request = dict(context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={}))
    images = load_task_images(context.task.project_id, request.get("image_ids") or [])
    checkpoint = dict(context.load_checkpoint() or {})
    start = int(checkpoint.get("next_index") or 0)
    store = CandidateStore(context.artifacts, task_id=context.task.task_id, page_size=50)
    if start == 0:
        store.initialize(labels=list(request.get("labels") or []), total_images=len(images))

    succeeded = int(checkpoint.get("succeeded") or 0)
    failed = int(checkpoint.get("failed") or 0)
    for index in range(start, len(images)):
        if context.cancel_requested():
            return WorkerOutcome(TaskStatus.CANCELLED, "candidates/manifest.json")
        image = images[index]
        try:
            generated = annotate(request, image)
            boxes = list(generated.get("boxes") or [])
            item = {
                "image_id": str(image["id"]), "filename": image.get("filename"),
                "url": image.get("url"), "status": "success" if boxes else "empty",
                "boxes": boxes,
            }
            succeeded += 1
        except Exception as error:
            item = {
                "image_id": str(image.get("id") or ""), "filename": image.get("filename"),
                "url": image.get("url"), "status": "failed", "boxes": [], "error": str(error),
            }
            failed += 1
        store.append_items([item])
        context.save_checkpoint({"next_index": index + 1, "succeeded": succeeded, "failed": failed})
        context.repository.heartbeat(
            context.task.task_id, context.lease.lease_token,
            progress=int((index + 1) / max(1, len(images)) * 100),
            stage="AI_ANNOTATION", current_item=str(image.get("id") or ""),
        )

    if failed and not succeeded:
        return WorkerOutcome(TaskStatus.FAILED, "candidates/manifest.json", "all images failed")
    return WorkerOutcome(
        TaskStatus.AWAITING_CONFIRMATION,
        "candidates/manifest.json",
        generation_partial=bool(failed),
    )
```

At the worker bootstrap boundary, construct one provider per claimed task, attach it to the in-memory request as `_provider` and `_provider_config`, and never serialize those two keys. The existing `app.py:11841-11843` behavior of one provider per task is retained; provider creation must not move inside the image loop.

- [ ] **Step 4: Run the worker tests to verify they pass**

Run: `python -m pytest tests/unit/test_annotation_task_service.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit the shared-runtime worker**

```bash
git add platform_core/annotation_task_service.py tests/unit/test_annotation_task_service.py app.py
git commit -m "feat: run AI annotation on persistent task runtime"
```

### Task 3: Persist Decisions and Commit Accepted Candidates Idempotently

**Files:**
- Modify: `platform_core/annotation_candidates.py`
- Modify: `platform_core/annotation_task_service.py`
- Modify: `tests/unit/test_annotation_candidates.py`
- Modify: `tests/unit/test_annotation_task_service.py`

- [ ] **Step 1: Write failing all-rejected and interrupted-commit tests**

```python
def test_all_rejected_is_not_interpreted_as_all_selected(tmp_path):
    artifacts = ArtifactStore(tmp_path)
    store = CandidateStore(artifacts, task_id="reject-all", page_size=50)
    store.initialize(labels=["fire"], total_images=2)
    store.append_items([
        {"image_id": "one", "status": "success", "boxes": [{"id": "a", "label": "fire"}]},
        {"image_id": "two", "status": "empty", "boxes": []},
    ])
    store.reject_all_reviewable()
    assert [item["accepted"] for item in store.all_items()] == [False, False]
    assert store.summary()["accepted"] == 0
    assert store.summary()["unreviewed"] == 0


def test_commit_replay_does_not_duplicate_candidate_boxes(tmp_path, monkeypatch):
    from platform_core.annotation_task_service import commit_candidate_decisions

    artifacts = ArtifactStore(tmp_path)
    store = CandidateStore(artifacts, task_id="commit-1", page_size=50)
    store.initialize(labels=["fire"], total_images=1)
    store.append_items([{  
        "image_id": "image-1", "status": "success", "accepted": None,
        "boxes": [{"id": "candidate-1", "class_id": 0, "label": "fire",
                   "x1": 1, "y1": 1, "x2": 20, "y2": 20}],
    }])
    store.apply_decisions([CandidateDecision(image_id="image-1", accepted=True)])
    written = []
    monkeypatch.setattr(
        "platform_core.annotation_task_service.read_formal_annotation",
        lambda _project, _image: {"boxes": list(written)},
    )
    monkeypatch.setattr(
        "platform_core.annotation_task_service.write_formal_annotation",
        lambda _project, _image, boxes: written.__setitem__(slice(None), boxes),
    )

    first = commit_candidate_decisions("project-1", "commit-1", store, overwrite=False)
    second = commit_candidate_decisions("project-1", "commit-1", store, overwrite=False)

    assert first["boxes_added"] == 1
    assert second["boxes_added"] == 0
    assert [box["candidate_id"] for box in written] == ["candidate-1"]
    assert written[0]["source_task_id"] == "commit-1"
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python -m pytest tests/unit/test_annotation_candidates.py tests/unit/test_annotation_task_service.py -q`

Expected: FAIL with missing `reject_all_reviewable` and `commit_candidate_decisions`.

- [ ] **Step 3: Add explicit reject-all and idempotent commit code**

Add to `CandidateStore`:

```python
def reject_all_reviewable(self) -> None:
    decisions = [
        CandidateDecision(image_id=str(item["image_id"]), accepted=False)
        for item in self.all_items()
        if item.get("status") in {"success", "empty"}
    ]
    self.apply_decisions(decisions)
```

Add to `platform_core/annotation_task_service.py`:

```python
def read_formal_annotation(project_id: str, image_id: str) -> dict[str, Any]:
    from app import read_annotation
    return read_annotation(project_id, image_id)


def write_formal_annotation(project_id: str, image_id: str, boxes: list[dict[str, Any]]) -> None:
    from app import write_annotation
    write_annotation(project_id, image_id, boxes)


def commit_candidate_decisions(
    project_id: str,
    task_id: str,
    store: CandidateStore,
    *,
    overwrite: bool,
) -> dict[str, Any]:
    applied_images: list[str] = []
    boxes_added = 0
    for item in store.all_items():
        if item.get("accepted") is not True:
            continue
        image_id = str(item["image_id"])
        previous = list(read_formal_annotation(project_id, image_id).get("boxes") or [])
        existing = {
            (str(box.get("source_task_id") or ""), str(box.get("candidate_id") or ""))
            for box in previous
        }
        incoming = []
        for box in item.get("boxes") or []:
            candidate_id = str(box.get("id") or "")
            key = (task_id, candidate_id)
            if key in existing:
                continue
            confirmed = dict(box)
            confirmed["candidate_id"] = candidate_id
            confirmed["source_task_id"] = task_id
            confirmed["source"] = "ai_candidate_confirmed"
            incoming.append(confirmed)
        if overwrite and incoming:
            replaced_classes = {box.get("class_id") for box in incoming}
            previous = [box for box in previous if box.get("class_id") not in replaced_classes]
        if incoming:
            write_formal_annotation(project_id, image_id, previous + incoming)
            boxes_added += len(incoming)
        applied_images.append(image_id)
    return {
        "applied_images": len(applied_images),
        "applied_image_ids": applied_images,
        "boxes_added": boxes_added,
        "review": store.summary(),
    }
```

Write `commit/result.json` through `ArtifactStore.atomic_write_json` after each image. On replay, use both that journal and `(source_task_id, candidate_id)` deduplication; never rely only on the shared task status.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `python -m pytest tests/unit/test_annotation_candidates.py tests/unit/test_annotation_task_service.py -q`

Expected: all focused tests PASS.

- [ ] **Step 5: Commit tri-state review and idempotent commit**

```bash
git add platform_core/annotation_candidates.py platform_core/annotation_task_service.py tests/unit/test_annotation_candidates.py tests/unit/test_annotation_task_service.py
git commit -m "fix: preserve rejected AI candidates and idempotent commits"
```

### Task 4: Replace v47 AI Endpoints with Bounded Public DTOs

**Files:**
- Modify: `app.py:11742-12013`
- Create: `tests/api/test_annotation_task_runtime.py`

- [ ] **Step 1: Write failing API tests for DTO secrecy, pagination, all rejection, cancel, and retry**

```python
# tests/api/test_annotation_task_runtime.py
def test_annotation_task_list_is_bounded_and_private_fields_are_absent(client, seeded_project):
    project_id, _image = seeded_project
    response = client.get(
        f"/api/v60/projects/{project_id}/annotation-tasks?limit=20&kind=AI_ANNOTATION"
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) <= 20
    forbidden = {"request_payload", "payload_ref", "candidate_file", "video_path", "api_key", "secret_ref"}
    for item in body["items"]:
        assert forbidden.isdisjoint(item)


def test_candidate_result_is_paged_and_all_rejected_remains_false(client, seeded_project, completed_ai_task):
    project_id, _image = seeded_project
    task_id = completed_ai_task(project_id, candidate_count=55)
    first = client.get(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates?limit=50"
    ).json()
    assert len(first["items"]) == 50
    assert first["next_cursor"] == "50"
    second = client.get(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates"
        f"?limit=50&cursor={first['next_cursor']}"
    ).json()
    assert len(second["items"]) == 5

    rejected = client.post(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/decisions",
        json={"decisions": [], "reject_unmentioned": True, "commit": True},
    )
    assert rejected.status_code == 200
    assert rejected.json()["review"]["accepted"] == 0
    assert rejected.json()["review"]["rejected"] == 55
    reloaded = client.get(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates?limit=50"
    ).json()
    assert all(item["accepted"] is False for item in reloaded["items"])


def test_cancel_and_retry_use_shared_runtime_states(client, seeded_project, queued_ai_task):
    project_id, _image = seeded_project
    task_id = queued_ai_task(project_id)
    cancelled = client.post(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/cancel"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] in {"CANCEL_REQUESTED", "CANCELLED"}
    retried = client.post(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/retry"
    )
    assert retried.status_code == 200
    assert retried.json()["id"] != task_id
    assert retried.json()["retry_of"] == task_id
    assert retried.json()["status"] == "QUEUED"
```

- [ ] **Step 2: Run the API tests to verify they fail**

Run: `python -m pytest tests/api/test_annotation_task_runtime.py -q`

Expected: FAIL with `404 Not Found` for `/api/v60/.../annotation-tasks`.

- [ ] **Step 3: Add exact request/public response models and routes**

Add models in `app.py` next to `V47AutoLabelReq`:

```python
class AnnotationTaskCreateReq(BaseModel):
    image_ids: List[str]
    labels_text: str = ""
    reference_image_ids: List[str] = []
    threshold: float = 0.45
    overwrite: bool = False
    task_name: str = "AI自动标注任务"
    model_config_id: Optional[str] = None
    prompt_template_id: Optional[str] = None
    business_instruction: str = ""


class AnnotationDecisionReq(BaseModel):
    decisions: List[CandidateDecision]
    reject_unmentioned: bool = True
    commit: bool = True


def public_annotation_task(task: TaskRecord, *, summary: Optional[dict] = None) -> dict:
    return {
        "id": task.task_id,
        "project_id": task.project_id,
        "kind": task.kind.value,
        "status": task.status.value,
        "progress": task.progress,
        "stage": task.stage,
        "current_item": task.current_item,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "finished_at": task.finished_at,
        "retry_of": task.retry_of,
        "accepted": task.accepted,
        "error": task.error,
        "summary": summary or {},
    }
```

Add v60 routes with these exact shapes:

```python
@app.get("/api/v60/projects/{project_id}/annotation-tasks")
def list_annotation_tasks(project_id: str, limit: int = 50, cursor: Optional[str] = None):
    page = annotation_task_repository().list(
        project_id=project_id,
        kinds={TaskKind.AI_ANNOTATION},
        limit=max(1, min(100, limit)),
        cursor=cursor,
    )
    return {
        "items": [public_annotation_task(task) for task in page.items],
        "next_cursor": page.next_cursor,
    }


@app.get("/api/v60/projects/{project_id}/annotation-tasks/{task_id}")
def get_annotation_task(project_id: str, task_id: str):
    task = require_project_task(project_id, task_id, TaskKind.AI_ANNOTATION)
    store = CandidateStore(annotation_artifacts(), task_id=task.task_id)
    return public_annotation_task(task, summary=store.summary() if task.result_ref else {})


@app.get("/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates")
def get_annotation_candidates(project_id: str, task_id: str, limit: int = 50, cursor: Optional[str] = None):
    task = require_project_task(project_id, task_id, TaskKind.AI_ANNOTATION)
    page = CandidateStore(annotation_artifacts(), task_id=task.task_id).read_page(
        cursor=cursor, limit=max(1, min(100, limit))
    )
    return {"items": page.items, "next_cursor": page.next_cursor, "total": page.total}


@app.post("/api/v60/projects/{project_id}/annotation-tasks/{task_id}/decisions")
def decide_annotation_candidates(project_id: str, task_id: str, payload: AnnotationDecisionReq):
    task = require_project_task(project_id, task_id, TaskKind.AI_ANNOTATION)
    if task.status is not TaskStatus.AWAITING_CONFIRMATION:
        raise HTTPException(status_code=409, detail="任务尚未生成可审核候选结果")
    store = CandidateStore(annotation_artifacts(), task_id=task.task_id)
    store.apply_decisions(payload.decisions)
    if payload.reject_unmentioned:
        decided = {item.image_id for item in payload.decisions}
        store.apply_decisions([
            CandidateDecision(image_id=str(item["image_id"]), accepted=False)
            for item in store.all_items()
            if item.get("status") in {"success", "empty"} and str(item["image_id"]) not in decided
        ])
    result = commit_candidate_decisions(
        project_id, task.task_id, store,
        overwrite=bool(annotation_artifacts().read_json(task.task_id, task.payload_ref, default={}).get("overwrite")),
    ) if payload.commit else {"review": store.summary()}
    annotation_artifacts().atomic_write_json(task.task_id, "review/result.json", result)
    summary = store.summary()
    final_status = TaskStatus.PARTIAL_SUCCESS if summary.get("failed") else TaskStatus.SUCCEEDED
    accepted = bool(summary.get("accepted"))
    updated = annotation_task_repository().complete_review(
        task.task_id, final_status, "review/result.json", accepted=accepted,
    )
    return {"ok": True, "task": public_annotation_task(updated, summary=summary), **result}


@app.post("/api/v60/projects/{project_id}/annotation-tasks/{task_id}/cancel")
def cancel_annotation_task(project_id: str, task_id: str):
    require_project_task(project_id, task_id, TaskKind.AI_ANNOTATION)
    return public_annotation_task(annotation_task_repository().request_cancel(task_id))


@app.post("/api/v60/projects/{project_id}/annotation-tasks/{task_id}/retry")
def retry_annotation_task(project_id: str, task_id: str):
    require_project_task(project_id, task_id, TaskKind.AI_ANNOTATION)
    return public_annotation_task(annotation_task_repository().retry(task_id))
```

Task creation must write a private `request.json` artifact before `TaskRepository.create(record)`. The public task record stores only `payload_ref="request.json"`; it must not embed `image_ids`, prompt snapshots, provider configuration, absolute file paths, `secret_ref`, or API keys. `complete_review` is a guarded atomic transition that accepts only `AWAITING_CONFIRMATION`; it is idempotent for an identical final result and rejects conflicting second decisions. `accepted=False` with zero committed candidates is a successful completed review, not a generation failure.

Keep `/api/v47/.../ai-label-tasks` as compatibility delegates for one release. The legacy confirm delegate must convert its selected ids to a full decision list; `image_ids=[]` becomes every reviewable candidate with `accepted=False`, while an omitted field preserves the old “select all” behavior only for legacy clients.

- [ ] **Step 4: Run the API tests to verify they pass**

Run: `python -m pytest tests/api/test_annotation_task_runtime.py tests/api/test_auto_label_candidates.py -q`

Expected: all tests PASS, including the legacy happy path and the new explicit all-rejected path.

- [ ] **Step 5: Commit the bounded API contract**

```bash
git add app.py tests/api/test_annotation_task_runtime.py tests/api/test_auto_label_candidates.py
git commit -m "feat: expose bounded annotation task APIs"
```

### Task 5: Register Recovery, Lease Expiry, Cancellation, and Retry

**Files:**
- Modify: `platform_core/annotation_task_service.py`
- Modify: `app.py:10474-10476`
- Modify: `app.py:12245-12256`
- Modify: `tests/api/test_annotation_task_runtime.py`

- [ ] **Step 1: Write failing restart-recovery tests**

```python
def test_startup_releases_expired_ai_lease_and_worker_reclaims_task(
    client, app_module, task_worker_harness, persisted_running_ai_task
):
    task_id = persisted_running_ai_task(lease_expired=True, checkpoint={"next_index": 1})
    released = app_module.recover_annotation_tasks()
    task = app_module.annotation_task_repository().get(task_id)
    assert released == 1
    assert task.status == TaskStatus.QUEUED
    task_worker_harness.run_once(kinds={TaskKind.AI_ANNOTATION})
    assert app_module.annotation_task_repository().get(task_id).status != TaskStatus.QUEUED


def test_cancel_requested_task_recovers_as_cancelled_without_provider_call(
    client, app_module, task_worker_harness, persisted_running_ai_task, monkeypatch
):
    task_id = persisted_running_ai_task(status=TaskStatus.CANCEL_REQUESTED, checkpoint={"next_index": 1})
    monkeypatch.setattr(
        "platform_core.annotation_task_service.annotate_one",
        lambda *_: (_ for _ in ()).throw(AssertionError("provider must not run")),
    )
    app_module.recover_annotation_tasks()
    task_worker_harness.run_once(kinds={TaskKind.AI_ANNOTATION})
    assert app_module.annotation_task_repository().get(task_id).status is TaskStatus.CANCELLED
```

- [ ] **Step 2: Run the restart tests to verify they fail**

Run: `python -m pytest tests/api/test_annotation_task_runtime.py -k "startup or recover" -q`

Expected: FAIL with missing `recover_annotation_tasks` or a persisted task remaining `RUNNING`.

- [ ] **Step 3: Wire the shared worker and startup recovery**

Add to `platform_core/annotation_task_service.py`:

```python
def finish_ai_annotation(context: WorkerContext) -> None:
    outcome = run_ai_annotation(context)
    context.repository.finish(
        context.task.task_id,
        context.lease.lease_token,
        status=outcome.status,
        result_ref=outcome.result_ref,
        error=outcome.error,
        accepted=None,
    )
```

Add process singletons in `app.py`:

```python
_ANNOTATION_TASK_REPOSITORY = TaskRepository(DATA_DIR / "tasks.sqlite3")


def annotation_task_repository() -> TaskRepository:
    return _ANNOTATION_TASK_REPOSITORY


def recover_annotation_tasks() -> int:
    return _ANNOTATION_TASK_REPOSITORY.release_expired()
```

Call `recover_annotation_tasks()` once during API startup; it only repairs expired leases and never starts work. Register `TaskKind.AI_ANNOTATION: finish_ai_annotation` in the standalone `task_worker.py` handler registry. The supervised worker process, not FastAPI startup or a browser refresh, owns the scheduler loop.

Retry uses `TaskRepository.retry(task_id)`. The shared repository copies the original private `payload_ref`, sets `retry_of`, resets progress/checkpoint references, and creates a new `QUEUED` record; the annotation API does not hand-copy secret-bearing request data into its response.

- [ ] **Step 4: Run restart, cancel, and retry tests**

Run: `python -m pytest tests/api/test_annotation_task_runtime.py -k "startup or recover or cancel or retry" -q`

Expected: all selected tests PASS; no test waits on an orphaned `RUNNING` task.

- [ ] **Step 5: Commit runtime recovery wiring**

```bash
git add platform_core/annotation_task_service.py app.py tests/api/test_annotation_task_runtime.py
git commit -m "fix: recover and cancel persistent annotation tasks"
```

### Task 6: Make Manual Batch Annotation a Single Dirty-Safe Session

**Files:**
- Create: `static/modules/annotation-workbench.js`
- Create: `tests/frontend/annotation-workbench.test.mjs`
- Modify: `static/main.mjs:1-49`
- Modify: `static/app.js:510-524`
- Modify: `static/app.js:3535-3545`

- [ ] **Step 1: Write failing request-token, dirty-save, and 50-image virtual-window tests**

```javascript
// tests/frontend/annotation-workbench.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {createAnnotationWorkbench, queueWindow} from '../../static/modules/annotation-workbench.js';

test('stale annotation response cannot replace the newest image', async () => {
  const pending = new Map();
  const load = id => new Promise(resolve => pending.set(id, resolve));
  const applied = [];
  const workbench = createAnnotationWorkbench({load, save: async () => true, apply: value => applied.push(value)});
  const first = workbench.open('one');
  const second = workbench.open('two');
  pending.get('two')({image_id: 'two'});
  await second;
  pending.get('one')({image_id: 'one'});
  await first;
  assert.deepEqual(applied, [{image_id: 'two'}]);
});

test('dirty navigation waits for save and blocks when save fails', async () => {
  const events = [];
  const workbench = createAnnotationWorkbench({
    load: async id => ({image_id: id}),
    save: async () => { events.push('save'); return false; },
    apply: value => events.push(`open:${value.image_id}`),
  });
  await workbench.open('one');
  workbench.markDirty();
  const moved = await workbench.open('two');
  assert.equal(moved, false);
  assert.deepEqual(events, ['open:one', 'save']);
});

test('fifty-image queue renders a bounded window around the active image', () => {
  const ids = Array.from({length: 50}, (_, index) => `image-${index}`);
  const visible = queueWindow(ids, 'image-25', 9);
  assert.equal(visible.length, 9);
  assert.equal(visible.includes('image-25'), true);
  assert.equal(visible[0], 'image-21');
  assert.equal(visible.at(-1), 'image-29');
});
```

- [ ] **Step 2: Run the frontend test to verify it fails**

Run: `node --test tests/frontend/annotation-workbench.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `static/modules/annotation-workbench.js`.

- [ ] **Step 3: Implement the annotation workbench module**

```javascript
// static/modules/annotation-workbench.js
export function queueWindow(ids, activeId, windowSize = 9) {
  const rows = [...ids];
  if (rows.length <= windowSize) return rows;
  const active = Math.max(0, rows.indexOf(activeId));
  const half = Math.floor(windowSize / 2);
  const start = Math.max(0, Math.min(rows.length - windowSize, active - half));
  return rows.slice(start, start + windowSize);
}

export function createAnnotationWorkbench({load, save, apply}) {
  let requestToken = 0;
  let dirty = false;
  let activeId = null;
  return {
    get activeId() { return activeId; },
    get dirty() { return dirty; },
    markDirty() { dirty = true; },
    markSaved() { dirty = false; },
    async open(id) {
      if (activeId && activeId !== id && dirty) {
        const saved = await save();
        if (!saved) return false;
        dirty = false;
      }
      const token = ++requestToken;
      const result = await load(id, token);
      if (token !== requestToken) return false;
      activeId = id;
      apply(result, token);
      return true;
    },
    invalidate() { requestToken += 1; },
  };
}
```

Expose it in `static/main.mjs`:

```javascript
import {createAnnotationWorkbench, queueWindow} from './modules/annotation-workbench.js?v=422000';

// inside window.PlatformCore
annotationWorkbench: {createAnnotationWorkbench, queueWindow},
```

Create exactly one `state.annotationWorkbench` during final app initialization. Replace `goAnnotation417` with an async call to `workbench.open(id)`; do not close the modal before save completes. Replace the full queue map at `static/app.js:516` with `queueWindow(queueIds, img.id, 9)`, while retaining `at + 1 / total` outside the virtual window.

`openAnnotation` must call the workbench loader and apply the response only when its token is current. `markDirty()` and successful `saveAnn()` must call `state.annotationWorkbench.markDirty()` and `.markSaved()` respectively. Closing an annotation modal with dirty state must invoke the same save boundary; if save fails, keep the modal open and display `保存失败`.

- [ ] **Step 4: Run unit and browser-focused tests**

Run: `node --test tests/frontend/annotation-workbench.test.mjs`

Expected: `3 passed`.

Run: `npx playwright test tests/browser/material-workflows.spec.mjs --grep "batch annotation"`

Expected: the batch test PASS, with one dialog node retained while moving from image 1 to image 2.

- [ ] **Step 5: Commit the stable annotation session**

```bash
git add static/modules/annotation-workbench.js static/main.mjs static/app.js tests/frontend/annotation-workbench.test.mjs tests/browser/material-workflows.spec.mjs
git commit -m "fix: keep batch annotation dirty-safe and single-instance"
```

### Task 7: Preserve True Box Counts and Patch Only the Active Material

**Files:**
- Modify: `static/modules/annotation.js:3-20`
- Modify: `tests/frontend/materials.test.mjs`
- Modify: `static/app.js:3559-3577`
- Modify: `tests/browser/material-workflows.spec.mjs`

- [ ] **Step 1: Write failing tests for more than 64 boxes and stable gallery DOM**

```javascript
test('annotation response preserves the true count above the preview limit', () => {
  const boxes = Array.from({length: 80}, (_, index) => ({
    class_id: 0, label: 'person', x1: index, y1: 1, x2: index + 1, y2: 2,
  }));
  const result = applyAnnotationResult(
    [{id: 'image-1', filename: 'one.jpg'}],
    {image: {id: 'image-1', box_count: 80}},
    boxes,
  );
  assert.equal(result[0].box_count, 80);
  assert.equal(result[0].annotation_preview.length, 64);
});
```

Add a Playwright assertion after save:

```javascript
const galleryNodeStable = await page.evaluate(() => {
  const card = document.querySelector('.data412-card');
  window.__cardBeforeAnnotationSave = card;
  return Boolean(card);
});
expect(galleryNodeStable).toBe(true);
await dialog.getByRole('button', {name: '保存并继续'}).click();
expect(await page.evaluate(() => document.querySelector('.data412-card') === window.__cardBeforeAnnotationSave)).toBe(true);
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test tests/frontend/materials.test.mjs`

Expected: FAIL because `box_count` is 64 rather than 80.

Run: `npx playwright test tests/browser/material-workflows.spec.mjs --grep "manual annotation"`

Expected: FAIL because `static/app.js:3572` rebuilds the gallery.

- [ ] **Step 3: Correct the projection and remove full gallery rendering from save**

Change `static/modules/annotation.js` to:

```javascript
export function applyAnnotationResult(materials, response, boxes) {
  const allBoxes = boxes || [];
  const preview = allBoxes.slice(0, 64).map(box => ({
    class_id: box.class_id, label: box.label,
    x1: box.x1, y1: box.y1, x2: box.x2, y2: box.y2,
  }));
  const summary = response?.image || {};
  return replaceMaterial(materials, {
    ...summary,
    id: summary.id,
    annotated: allBoxes.length > 0,
    box_count: Number(summary.box_count ?? allBoxes.length),
    labels: [...new Set(allBoxes.map(box => box.label).filter(Boolean))],
    annotation_preview: preview,
  });
}
```

Replace the `renderDatasets424()` call at `static/app.js:3572` with a targeted `patchMaterialCard412(state.activeImage)` that updates only the matching count, labels, and overlay container. It must not assign `#view.innerHTML`, replace the grid, or recreate unrelated `<img>` elements.

- [ ] **Step 4: Run the unit and browser tests to verify they pass**

Run: `node --test tests/frontend/materials.test.mjs`

Expected: all material tests PASS.

Run: `npx playwright test tests/browser/material-workflows.spec.mjs --grep "manual annotation"`

Expected: the manual annotation test PASS and the gallery card identity assertion remain true.

- [ ] **Step 5: Commit accurate annotation projection**

```bash
git add static/modules/annotation.js static/app.js tests/frontend/materials.test.mjs tests/browser/material-workflows.spec.mjs
git commit -m "fix: preserve full annotation counts without gallery rebuild"
```

### Task 8: Add Single-Instance Polling and Paged Candidate Review UI

**Files:**
- Create: `static/modules/task-poller.js`
- Create: `static/modules/annotation-task-view.js`
- Create: `tests/frontend/task-poller.test.mjs`
- Create: `tests/frontend/annotation-task-view.test.mjs`
- Modify: `static/main.mjs:1-49`
- Modify: `static/app.js:578`
- Modify: `static/app.js:2840-2868`
- Modify: `static/app.js:3116-3118`

- [ ] **Step 1: Write failing poll-singleton, no-duplicate-fetch, and bounded-review tests**

```javascript
// tests/frontend/task-poller.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {createTaskPoller} from '../../static/modules/task-poller.js';

test('starting the same poll key twice leaves one active request chain', async () => {
  let calls = 0;
  const poller = createTaskPoller({setTimer: fn => fn(), clearTimer: () => {}});
  const fetcher = async () => { calls += 1; return {items: []}; };
  await poller.start('annotation-list', fetcher, () => {}, {repeat: false});
  await poller.start('annotation-list', fetcher, () => {}, {repeat: false});
  assert.equal(calls, 1);
  assert.equal(poller.activeKeys().length, 1);
  poller.stop('annotation-list');
  assert.deepEqual(poller.activeKeys(), []);
});
```

```javascript
// tests/frontend/annotation-task-view.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {createCandidateReviewState} from '../../static/modules/annotation-task-view.js';

test('candidate review loads each page once and renders at most twelve cards', async () => {
  let calls = 0;
  const loadPage = async cursor => {
    calls += 1;
    const start = Number(cursor || 0);
    return {
      items: Array.from({length: Math.min(50, 55 - start)}, (_, i) => ({
        image_id: `image-${start + i}`, accepted: null, boxes: [],
      })),
      next_cursor: start + 50 < 55 ? String(start + 50) : null,
      total: 55,
    };
  };
  const review = createCandidateReviewState({loadPage, windowSize: 12});
  await review.loadNext();
  await review.loadNext();
  await review.loadNext();
  assert.equal(calls, 2);
  assert.equal(review.items.length, 55);
  assert.equal(review.visible().length, 12);
});
```

- [ ] **Step 2: Run the frontend tests to verify they fail**

Run: `node --test tests/frontend/task-poller.test.mjs tests/frontend/annotation-task-view.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for both modules.

- [ ] **Step 3: Implement the poller and paged review state**

```javascript
// static/modules/task-poller.js
export function createTaskPoller({setTimer = setTimeout, clearTimer = clearTimeout} = {}) {
  const entries = new Map();
  return {
    activeKeys: () => [...entries.keys()],
    async start(key, fetcher, apply, {interval = 2000, repeat = true} = {}) {
      if (entries.has(key)) return entries.get(key).promise;
      const entry = {stopped: false, timer: null, inFlight: false, promise: null};
      const tick = async () => {
        if (entry.stopped || entry.inFlight) return;
        entry.inFlight = true;
        try { apply(await fetcher()); }
        finally {
          entry.inFlight = false;
          if (repeat && !entry.stopped) entry.timer = setTimer(tick, interval);
        }
      };
      entry.promise = tick();
      entries.set(key, entry);
      return entry.promise;
    },
    stop(key) {
      const entry = entries.get(key);
      if (!entry) return;
      entry.stopped = true;
      if (entry.timer !== null) clearTimer(entry.timer);
      entries.delete(key);
    },
    stopAll() { [...entries.keys()].forEach(key => this.stop(key)); },
  };
}
```

```javascript
// static/modules/annotation-task-view.js
export function createCandidateReviewState({loadPage, windowSize = 12}) {
  let cursor = null;
  let exhausted = false;
  let loading = null;
  let offset = 0;
  const items = [];
  return {
    items,
    async loadNext() {
      if (exhausted) return items;
      if (loading) return loading;
      loading = (async () => {
        const page = await loadPage(cursor);
        items.push(...page.items);
        cursor = page.next_cursor;
        exhausted = cursor === null;
        return items;
      })().finally(() => { loading = null; });
      return loading;
    },
    visible() { return items.slice(offset, offset + windowSize); },
    moveWindow(nextOffset) {
      offset = Math.max(0, Math.min(Math.max(0, items.length - windowSize), nextOffset));
      return this.visible();
    },
    setAccepted(imageId, accepted) {
      const item = items.find(row => String(row.image_id) === String(imageId));
      if (item) item.accepted = accepted;
    },
    decisions() {
      return items
        .filter(item => item.accepted !== null)
        .map(item => ({image_id: String(item.image_id), accepted: Boolean(item.accepted)}));
    },
  };
}
```

Expose both modules from `static/main.mjs`. Create one `state.annotationTaskPoller`; stop its list key when leaving `自动标注及清洗`. Render the task page shell once, then update only `<tbody>` and progress cells. Do not call `document.getElementById('view').innerHTML` from a poll tick.

Replace the `static/app.js:3116-3117` wrapper so candidate review performs one request per page. Remove the first full result request and the second call through `oldReviewAi429`. Candidate cards must come from `review.visible()` and provide previous/next window controls; loading the next virtual window may fetch the next 50-item backend page.

Submit a complete decision array with both checked and unchecked reviewable items. If every card is unchecked, send `accepted:false` for every reviewable item; never send an empty selected-id array to represent rejection.

- [ ] **Step 4: Run frontend tests and the mocked browser review test**

Run: `node --test tests/frontend/task-poller.test.mjs tests/frontend/annotation-task-view.test.mjs`

Expected: `3 passed` across the two files.

Run: `npx playwright test tests/browser/model-and-conversion.spec.mjs --grep "candidate review"`

Expected: PASS, with exactly one intercepted request for the first candidate page.

- [ ] **Step 5: Commit bounded polling and candidate review**

```bash
git add static/modules/task-poller.js static/modules/annotation-task-view.js static/main.mjs static/app.js tests/frontend/task-poller.test.mjs tests/frontend/annotation-task-view.test.mjs tests/browser/model-and-conversion.spec.mjs
git commit -m "perf: bound annotation polling and candidate review"
```

### Task 9: Add 50-Image Pressure, Secret Redaction, and Payload Budget Acceptance

**Files:**
- Modify: `tests/api/test_annotation_task_runtime.py`
- Create: `tests/browser/annotation-runtime.spec.mjs`
- Modify: `tests/frontend/annotation-workbench.test.mjs`
- Modify: `tests/frontend/annotation-task-view.test.mjs`

- [ ] **Step 1: Add failing API payload-budget and secret-redaction tests**

```python
import json


def test_public_task_payload_stays_bounded_with_five_thousand_image_ids(
    client, seeded_project, queued_ai_task
):
    project_id, _image = seeded_project
    queued_ai_task(
        project_id,
        image_ids=[f"image-{index}" for index in range(5000)],
        provider_config={"api_key": "secret-value", "secret_ref": "vault-key"},
    )
    response = client.get(
        f"/api/v60/projects/{project_id}/annotation-tasks?limit=50"
    )
    raw = response.content
    assert len(raw) < 64 * 1024
    assert b"secret-value" not in raw
    assert b"vault-key" not in raw
    assert b"image-4999" not in raw
    assert all("payload_ref" not in item for item in response.json()["items"])


def test_candidate_page_has_hard_limit(client, seeded_project, completed_ai_task):
    project_id, _image = seeded_project
    task_id = completed_ai_task(project_id, candidate_count=500)
    response = client.get(
        f"/api/v60/projects/{project_id}/annotation-tasks/{task_id}/candidates?limit=1000"
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 100
    assert len(response.content) < 512 * 1024
```

- [ ] **Step 2: Add the failing 50-image browser pressure test**

```javascript
// tests/browser/annotation-runtime.spec.mjs
import {test, expect} from '@playwright/test';

test('fifty-image batch annotation keeps one dialog and a bounded queue', async ({page, request}) => {
  const project = await createProjectWithImages(request, {count: 50, ready: true});
  await selectProject(page, project.id);
  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  await page.getByRole('button', {name: /已处理/}).click();
  await page.getByRole('button', {name: '批量操作'}).click();
  await page.locator('.data412-card input[type="checkbox"]').evaluateAll(nodes => {
    for (const node of nodes) {
      node.checked = true;
      node.dispatchEvent(new Event('change', {bubbles: true}));
    }
  });
  await page.getByRole('button', {name: '批量标注'}).click();
  const dialog = page.getByRole('dialog', {name: '图片标注'});
  const identity = await dialog.evaluate(node => {
    window.__annotationDialogIdentity = node;
    return true;
  });
  expect(identity).toBe(true);
  await expect(dialog.locator('.ann417-queue img')).toHaveCount(9);
  await dialog.getByRole('button', {name: '下一张'}).click();
  expect(await page.evaluate(() => document.querySelector('[role="dialog"][aria-label="图片标注"]') === window.__annotationDialogIdentity || document.querySelector('[role="dialog"]') === window.__annotationDialogIdentity)).toBe(true);
  await expect(dialog.getByText('2 / 50', {exact: true})).toBeVisible();
});

test('rapid next navigation applies only the final annotation response', async ({page, request}) => {
  const project = await createProjectWithImages(request, {count: 3, ready: true});
  await selectProject(page, project.id);
  const responseOrder = [];
  await page.route('**/annotations/**', async route => {
    const id = route.request().url().split('/').at(-1);
    responseOrder.push(id);
    await new Promise(resolve => setTimeout(resolve, id.endsWith('1') ? 250 : 20));
    await route.continue();
  });
  await page.goto('/');
  await openBatchAnnotation(page, 3);
  await page.getByRole('button', {name: '下一张'}).click();
  await page.getByRole('button', {name: '下一张'}).click();
  await expect(page.locator('.ann414-state')).toContainText(project.images[2].filename);
  await expect(page.locator('.ann414-state')).not.toContainText(project.images[0].filename);
});
```

Implement the named local helpers in the same test file with concrete API calls copied from `tests/browser/material-workflows.spec.mjs:8-60`; the helper must upload exactly the requested count and mark every returned id ready before navigation.

- [ ] **Step 3: Run the new acceptance tests to observe their first failure**

Run: `python -m pytest tests/api/test_annotation_task_runtime.py -k "bounded or hard_limit" -q`

Expected before final DTO cleanup: FAIL because the list contains private fields or exceeds 64 KiB.

Run: `npx playwright test tests/browser/annotation-runtime.spec.mjs`

Expected before final DOM cleanup: FAIL because more than nine queue thumbnails exist or the dialog node is replaced.

- [ ] **Step 4: Apply the final bounded-output and stable-DOM corrections**

Ensure the task list serializer calls only `public_annotation_task()`, clamps list limit to 100, and never serializes the private `TaskRecord.payload_ref`. Ensure candidate pages clamp to 100. Keep API keys only in the existing secret store and provider runtime object; task artifacts store only `model_config_id` and a prompt-template snapshot that contains no credential fields.

Update the workbench renderer in place:

```javascript
function patchAnnotationWorkbench(next) {
  document.querySelector('.ann417-queue header span').textContent = `${next.index + 1} / ${next.total}`;
  document.querySelector('.ann417-queue > div').replaceChildren(...next.queueNodes);
  const image = document.getElementById('annImg');
  image.src = next.image.url;
  document.querySelector('.ann414-state').firstChild.textContent = `${next.image.filename} · `;
}
```

The modal root and `.ann-layout` remain mounted for the entire batch. Only the queue window, active image source, boxes, labels, and counters are patched.

- [ ] **Step 5: Run the pressure and security tests to verify they pass**

Run: `python -m pytest tests/api/test_annotation_task_runtime.py -q`

Expected: all annotation-runtime API tests PASS.

Run: `npx playwright test tests/browser/annotation-runtime.spec.mjs`

Expected: `2 passed`, with nine queue thumbnails for a 50-image batch and one dialog identity.

- [ ] **Step 6: Commit pressure and security acceptance**

```bash
git add tests/api/test_annotation_task_runtime.py tests/browser/annotation-runtime.spec.mjs tests/frontend/annotation-workbench.test.mjs tests/frontend/annotation-task-view.test.mjs static/app.js app.py
git commit -m "test: lock annotation runtime pressure and privacy contracts"
```

### Task 10: Run the Full Annotation Regression and Record the Runtime Contract

**Files:**
- Modify: `README.md`
- Test: `tests/api/test_annotation_flow.py`
- Test: `tests/api/test_auto_label_candidates.py`
- Test: `tests/api/test_annotation_task_runtime.py`
- Test: `tests/frontend`
- Test: `tests/browser/material-workflows.spec.mjs`
- Test: `tests/browser/model-and-conversion.spec.mjs`
- Test: `tests/browser/annotation-runtime.spec.mjs`

- [ ] **Step 1: Document the public behavior and private-data boundary**

Add this concise section to `README.md`:

```markdown
## 标注任务运行约定

- AI 标注任务使用持久任务运行时；刷新页面不会创建重复任务，服务重启后会释放过期租约并继续未完成任务。
- 公共状态来自统一任务枚举。候选结果按页读取；单条候选的 `accepted` 为 `null`（未审核）、`true`（接受）或 `false`（拒绝）。
- 全部拒绝会保存为每条候选 `accepted=false`，不会写入正式标注。
- 任务列表不返回图片 id 全集、提示词快照、文件绝对路径、密钥引用或 API Key。
- 批量人工标注在切图前保存 dirty 修改；50 张队列仅渲染当前窗口，不重建整页或标注弹窗。
```

- [ ] **Step 2: Run Python annotation tests**

Run:

```bash
python -m pytest tests/unit/test_annotation_candidates.py tests/unit/test_annotation_task_service.py tests/api/test_annotation_flow.py tests/api/test_auto_label_candidates.py tests/api/test_annotation_task_runtime.py -q
```

Expected: all selected Python tests PASS with zero failures.

- [ ] **Step 3: Run all frontend unit tests**

Run: `npm test`

Expected: all Node tests PASS with zero failures.

- [ ] **Step 4: Run browser annotation regressions**

Run:

```bash
npx playwright test tests/browser/material-workflows.spec.mjs tests/browser/model-and-conversion.spec.mjs tests/browser/annotation-runtime.spec.mjs
```

Expected: all selected Playwright tests PASS with zero failures.

- [ ] **Step 5: Run repository status and forbidden-field scans**

Run:

```bash
rg -n "request_payload|candidate_file|video_path|api_key|secret_ref" platform_core/annotation_task_service.py static/modules/annotation-task-view.js tests/api/test_annotation_task_runtime.py
```

Expected: matches exist only in negative assertions or private artifact construction; none occur in `public_annotation_task()` output.

Run:

```bash
rg -n "setInterval|setTimeout\(.*renderOps427|oldReviewAi429|renderDatasets424\(\)" static/app.js static/modules/task-poller.js
```

Expected: no `oldReviewAi429`, no task-page recursive render timer, and no annotation-save call that redraws the full dataset.

- [ ] **Step 6: Commit documentation and final verification state**

```bash
git add README.md
git commit -m "docs: document persistent annotation task behavior"
```

## Completion Criteria

- Shared `TaskStatus` and `TaskKind.AI_ANNOTATION` are the only execution-state definitions used by annotation tasks.
- AI tasks survive refresh and restart, use leases/checkpoints, support cancel and retry, and expose `SUCCEEDED`, `PARTIAL_SUCCESS`, `FAILED`, or `CANCELLED` truthfully.
- Candidate pages are capped at 100 items; task lists exclude private request data, secrets, and absolute paths.
- Every reviewable candidate persists `accepted` as `null`, `true`, or `false`; all-rejected confirmation writes no formal annotations.
- Confirmation is replay-safe through `source_task_id + candidate_id` and a commit artifact journal.
- Manual batch annotation maintains one session and one modal, saves dirty edits before navigation, ignores stale requests, and renders at most nine queue thumbnails for 50 images.
- One image with more than 64 boxes retains its true `box_count` while preview overlays remain bounded.
- Each task page has one poll key and one in-flight request; candidate review does not fetch the same page twice.
- All commands in Task 10 pass before the branch is offered for integration.
