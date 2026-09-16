from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"{label}: expected source not found")
    return text.replace(old, new, 1)


def patch_public_py() -> None:
    path = "platform_core/task_runtime/public.py"
    text = read(path)
    text = replace_once(
        text,
        "def task_to_public(task: TaskRecord, repository: TaskRepository | None = None) -> dict[str, Any]:\n",
        """def task_to_public(
    task: TaskRecord,
    repository: TaskRepository | None = None,
    *,
    now=None,
    worker_runtime: list[dict[str, Any]] | None = None,
    queued_candidates: tuple[TaskRecord, ...] | None = None,
) -> dict[str, Any]:
""",
        "task_to_public signature",
    )
    text = replace_once(
        text,
        """    queue_position = None
    if repository is not None and task.status is TaskStatus.QUEUED:
        queue_position = repository.resource_queue_position(task.task_id)
    return {
""",
        """    queue_position = None
    queue_position_exact = False
    if repository is not None and task.status is TaskStatus.QUEUED:
        queue_position = repository.resource_queue_position(task.task_id)
        if task.kind is not TaskKind.TRAINING:
            queue_position_exact = _non_training_queue_position_exact(
                task,
                repository,
                queue_position=queue_position,
                now=now,
                worker_runtime=worker_runtime,
                queued_candidates=queued_candidates,
            )
    return {
""",
        "task_to_public queue truth",
    )
    text = replace_once(
        text,
        '        "resource_queue_position": queue_position,\n',
        '        "resource_queue_position": queue_position,\n        "resource_queue_position_exact": bool(queue_position_exact),\n',
        "public exact field",
    )
    helper = '''def _non_training_queue_position_exact(
    task: TaskRecord,
    repository: TaskRepository,
    *,
    queue_position: int | None,
    now=None,
    worker_runtime: list[dict[str, Any]] | None = None,
    queued_candidates: tuple[TaskRecord, ...] | None = None,
) -> bool:
    """Prove a resource queue rank matches one real Worker claim order.

    Resource-scoped SQL order alone is insufficient because a Worker may skip
    tasks by kind/capability or compete across resource keys. Exactness is
    fail-closed unless one compatible online Worker exists and every queued
    task that Worker could claim belongs to this same resource queue.
    """
    if (
        task.status is not TaskStatus.QUEUED
        or task.kind is TaskKind.TRAINING
        or queue_position is None
    ):
        return False
    runtime = (
        WorkerInstanceService(repository).list_runtime(now=now)
        if worker_runtime is None
        else worker_runtime
    )
    compatible = [
        worker
        for worker in runtime
        if worker.get("online") is True and _worker_can_claim(worker, task)
    ]
    if len(compatible) != 1:
        return False
    worker = compatible[0]
    candidates = repository.queued_candidates() if queued_candidates is None else queued_candidates
    claimable = [candidate for candidate in candidates if _worker_can_claim(worker, candidate)]
    if any(candidate.resource_key != task.resource_key for candidate in claimable):
        return False
    scan_position = next(
        (
            index
            for index, candidate in enumerate(claimable, start=1)
            if candidate.task_id == task.task_id
        ),
        None,
    )
    return scan_position is not None and scan_position == queue_position


'''
    marker = "def _waiting_training_truth(\n"
    if helper not in text:
        if marker not in text:
            raise RuntimeError("generic queue helper insertion marker missing")
        text = text.replace(marker, helper + marker, 1)
    write(path, text)


def patch_app_py() -> None:
    path = "app.py"
    text = read(path)

    # Unified durable-task list snapshots queue proof inputs once per response.
    text = replace_once(
        text,
        '''    return {
        "items": [task_to_public(task, repository) for task in page.items],
        "next_cursor": page.next_cursor,
    }
''',
        '''    worker_runtime = WorkerInstanceService(repository).list_runtime()
    queued_candidates = repository.queued_candidates()
    return {
        "items": [
            task_to_public(
                task, repository,
                worker_runtime=worker_runtime,
                queued_candidates=queued_candidates,
            )
            for task in page.items
        ],
        "next_cursor": page.next_cursor,
    }
''',
        "unified task list snapshot",
    )

    old_public = '''def _public_task(task: TaskRecord) -> Dict[str, Any]:
    return {
        "id": task.task_id,
        "project_id": task.project_id,
        "kind": task.kind.value,
        "status": task.status.value,
        "priority": task.priority,
        "progress": task.progress,
        "stage": task.stage,
        "resource_wait_reason": task.resource_wait_reason,
        "current_item": task.current_item,
        "attempt": task.attempt,
        "accepted": task.accepted,
        "error": task.error,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "finished_at": task.finished_at,
        "result_ref": task.result_ref,
    }
'''
    new_public = '''def _public_task(
    task: TaskRecord,
    *,
    worker_runtime=None,
    queued_candidates=None,
) -> Dict[str, Any]:
    repository = shared_task_repository()
    truth = task_to_public(
        task,
        repository,
        worker_runtime=worker_runtime,
        queued_candidates=queued_candidates,
    )
    return {
        **truth,
        "id": task.task_id,
        "task_id": task.task_id,
        "task_status": truth["status"],
        "progress": truth["progress_percent"],
        "stage": truth["phase"],
    }
'''
    text = replace_once(text, old_public, new_public, "v33 public task projection")

    text = replace_once(
        text,
        '''def _public_video_task(task: TaskRecord) -> Dict[str, Any]:
    response = _public_task(task)
''',
        '''def _public_video_task(task: TaskRecord, *, worker_runtime=None, queued_candidates=None) -> Dict[str, Any]:
    response = _public_task(
        task,
        worker_runtime=worker_runtime,
        queued_candidates=queued_candidates,
    )
''',
        "video public projection",
    )
    text = replace_once(
        text,
        '''    page = shared_task_repository().list(
        project_id=project_id,
        kinds={TaskKind.VIDEO_FRAMES},
        limit=max(1, min(100, int(limit))),
        cursor=cursor,
    )
    return {"items": [_public_video_task(task) for task in page.items], "next_cursor": page.next_cursor}
''',
        '''    repository = shared_task_repository()
    page = repository.list(
        project_id=project_id,
        kinds={TaskKind.VIDEO_FRAMES},
        limit=max(1, min(100, int(limit))),
        cursor=cursor,
    )
    worker_runtime = WorkerInstanceService(repository).list_runtime()
    queued_candidates = repository.queued_candidates()
    return {
        "items": [
            _public_video_task(
                task,
                worker_runtime=worker_runtime,
                queued_candidates=queued_candidates,
            )
            for task in page.items
        ],
        "next_cursor": page.next_cursor,
    }
''',
        "video list snapshot",
    )

    ann_start = text.index("def public_annotation_task(task: TaskRecord, *, summary: Optional[dict] = None) -> Dict[str, Any]:")
    ann_end = text.index("\n\ndef _require_annotation_review_task", ann_start)
    ann = text[ann_start:ann_end]
    ann = replace_once(
        ann,
        "def public_annotation_task(task: TaskRecord, *, summary: Optional[dict] = None) -> Dict[str, Any]:\n",
        """def public_annotation_task(
    task: TaskRecord,
    *,
    summary: Optional[dict] = None,
    worker_runtime=None,
    queued_candidates=None,
) -> Dict[str, Any]:
""",
        "annotation public signature",
    )
    ann = replace_once(
        ann,
        "    truth = task_to_public(task, repository)\n",
        """    truth = task_to_public(
        task,
        repository,
        worker_runtime=worker_runtime,
        queued_candidates=queued_candidates,
    )
""",
        "annotation shared truth",
    )
    ann = replace_once(
        ann,
        '''    page = shared_task_repository().list(
        project_id=project_id,
        kinds={TaskKind.AI_ANNOTATION},
        limit=max(1, min(100, int(limit))),
        cursor=cursor,
    )
    return {"items": [public_annotation_task(task) for task in page.items], "next_cursor": page.next_cursor}
''',
        '''    repository = shared_task_repository()
    page = repository.list(
        project_id=project_id,
        kinds={TaskKind.AI_ANNOTATION},
        limit=max(1, min(100, int(limit))),
        cursor=cursor,
    )
    worker_runtime = WorkerInstanceService(repository).list_runtime()
    queued_candidates = repository.queued_candidates()
    return {
        "items": [
            public_annotation_task(
                task,
                worker_runtime=worker_runtime,
                queued_candidates=queued_candidates,
            )
            for task in page.items
        ],
        "next_cursor": page.next_cursor,
    }
''',
        "annotation list snapshot",
    )
    text = text[:ann_start] + ann + text[ann_end:]
    write(path, text)


def patch_material_batches_py() -> None:
    path = "platform_core/material_batches.py"
    text = read(path)
    text = replace_once(
        text,
        '            "resource_queue_position": truth["resource_queue_position"] if truth else None,\n',
        '            "resource_queue_position": truth["resource_queue_position"] if truth else None,\n            "resource_queue_position_exact": truth["resource_queue_position_exact"] if truth else False,\n',
        "material batch exact projection",
    )
    write(path, text)


def patch_frontend() -> None:
    path = "static/modules/annotation-task-view.js"
    text = read(path)
    if "exactTaskQueuePosition" not in text:
        text = "import {exactTaskQueuePosition} from './task-runtime-truth.js';\n" + text
    text = replace_once(
        text,
        "  const queuePosition = Math.max(0, Number(task.resource_queue_position) || 0);\n",
        "  const queuePosition = exactTaskQueuePosition(task) || 0;\n",
        "annotation exact queue",
    )
    write(path, text)

    path = "static/modules/material-batches.js"
    text = read(path)
    text = replace_once(
        text,
        "import {canonicalTaskStatus, isCanonicalTaskActive} from './task-runtime-truth.js';\n",
        "import {canonicalTaskStatus, exactTaskQueuePosition, isCanonicalTaskActive} from './task-runtime-truth.js';\n",
        "material batch truth import",
    )
    text = replace_once(
        text,
        "  const queuePosition = Math.max(0, Number(task.resource_queue_position) || 0);\n",
        "  const queuePosition = exactTaskQueuePosition(task) || 0;\n",
        "material batch exact queue",
    )
    write(path, text)


def patch_backend_tests() -> None:
    path = "tests/unit/task_runtime/test_public_projection.py"
    text = read(path)
    addition = '''

def add_video(repository, task_id, priority=50, resource="cpu:video"):
    return repository.create(TaskRecord.new(
        task_id, "project-1", TaskKind.VIDEO_FRAMES, "request.json", resource,
        priority=priority, required_capabilities=("opencv",),
    ))


def test_generic_queue_position_is_exact_for_one_dedicated_worker(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    first = add_video(repository, "video-first", priority=5)
    second = add_video(repository, "video-second", priority=50)
    register_worker(
        repository, "video-worker",
        task_kinds=(TaskKind.VIDEO_FRAMES.value,), capabilities=("opencv",),
    )

    public = task_to_public(second, repository)

    assert public["resource_queue_position"] == 2
    assert public["resource_queue_position_exact"] is True
    assert repository.resource_queue_position(first.task_id) == 1


def test_generic_queue_position_is_inexact_without_compatible_worker(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    task = add_video(repository, "video-no-worker")

    public = task_to_public(task, repository)

    assert public["resource_queue_position"] == 1
    assert public["resource_queue_position_exact"] is False


def test_generic_queue_position_is_inexact_with_multiple_compatible_workers(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    task = add_video(repository, "video-many-workers")
    for worker_id in ("video-worker-a", "video-worker-b"):
        register_worker(
            repository, worker_id,
            task_kinds=(TaskKind.VIDEO_FRAMES.value,), capabilities=("opencv",),
        )

    public = task_to_public(task, repository)

    assert public["resource_queue_position"] == 1
    assert public["resource_queue_position_exact"] is False


def test_generic_queue_position_is_inexact_when_worker_competes_across_resources(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    target = add_video(repository, "video-target", priority=50, resource="cpu:video")
    add_video(repository, "video-other-resource", priority=5, resource="cpu:video-secondary")
    register_worker(
        repository, "video-worker",
        task_kinds=(TaskKind.VIDEO_FRAMES.value,), capabilities=("opencv",),
    )

    public = task_to_public(target, repository)

    assert public["resource_queue_position"] == 1
    assert public["resource_queue_position_exact"] is False


def test_running_generic_task_never_exposes_queue_position(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    add_video(repository, "video-running")
    register_worker(
        repository, "video-worker",
        task_kinds=(TaskKind.VIDEO_FRAMES.value,), capabilities=("opencv",),
    )
    lease = repository.claim_next("video-worker", [TaskKind.VIDEO_FRAMES], {"opencv"})
    assert lease is not None

    public = task_to_public(repository.get("video-running"), repository)

    assert public["status"] == "RUNNING"
    assert public["resource_queue_position"] is None
    assert public["resource_queue_position_exact"] is False
'''
    if "test_generic_queue_position_is_exact_for_one_dedicated_worker" not in text:
        text += addition
    write(path, text)


def patch_frontend_tests() -> None:
    path = "tests/frontend/phase2-task-truth.test.mjs"
    text = read(path)
    text = text.replace(
        "resource_queue_position: 2, resource_wait_reason: 'VISION_CAPACITY_BUSY',",
        "resource_queue_position: 2, resource_queue_position_exact: true, resource_wait_reason: 'VISION_CAPACITY_BUSY',",
        1,
    )
    text = text.replace(
        "materialBatchTaskText({status:'WAITING_RESOURCE', resource_queue_position:3, resource_wait_reason:'MATERIAL_WORKER_BUSY'}),",
        "materialBatchTaskText({status:'WAITING_RESOURCE', resource_queue_position:3, resource_queue_position_exact:true, resource_wait_reason:'MATERIAL_WORKER_BUSY'}),",
        1,
    )
    addition = '''

test('annotation and material batch never promote inexact candidate ranks', () => {
  const annotation = annotationTaskView({
    status: 'WAITING_RESOURCE', resource_queue_position: 7, resource_queue_position_exact: false,
    resource_wait_reason: 'VISION_CAPACITY_BUSY',
  });
  assert.equal(annotation.runtimeText, '等待资源 · VISION_CAPACITY_BUSY');
  assert.equal(annotation.runtimeText.includes('第 7 位'), false);
  const material = materialBatchTaskText({
    status: 'WAITING_RESOURCE', resource_queue_position: 9, resource_queue_position_exact: false,
    resource_wait_reason: 'MATERIAL_WORKER_BUSY',
  });
  assert.equal(material, '等待资源 · MATERIAL_WORKER_BUSY');
  assert.equal(material.includes('第 9 位'), false);
});
'''
    if "never promote inexact candidate ranks" not in text:
        text += addition
    write(path, text)

    path = "tests/frontend/annotation-task-view.test.mjs"
    text = read(path)
    addition = '''

test('annotation queue number is visible only when backend proves exactness', () => {
  const exact = annotationTaskView({
    task_status: 'WAITING_RESOURCE', status: 'completed',
    resource_queue_position: 2, resource_queue_position_exact: true,
    resource_wait_reason: 'VISION_CAPACITY_BUSY',
  });
  assert.equal(exact.status, 'WAITING_RESOURCE');
  assert.equal(exact.runtimeText, '资源队列第 2 位 · VISION_CAPACITY_BUSY');

  const inexact = annotationTaskView({
    status: 'QUEUED', resource_queue_position: 2, resource_queue_position_exact: false,
  });
  assert.equal(inexact.runtimeText, '');
});
'''
    if "backend proves exactness" not in text:
        text += addition
    write(path, text)


def write_handoff() -> None:
    path = ROOT / "docs" / "CODEX_HANDOFF_2026-09-16_GENERIC_QUEUE_EXACTNESS.md"
    path.write_text('''# Generic Durable Queue Exactness Closure

Date: 2026-09-16
Branch: `refactor/frontend-runtime-stabilization`
Formal version remains `42.24.0`.

## Scope

This closure completes the backend half of Task Runtime Truth v2 for non-training durable tasks. A numeric resource-scoped queue position is not automatically an executable Worker rank. The backend now emits `resource_queue_position_exact` only when it can prove the resource order and the unique compatible Worker claim order are the same.

## Proof rule

For a queued non-training task, exactness is true only when all of the following hold:

- exactly one online Worker can claim the task kind and all required capabilities;
- every queued task that Worker could claim belongs to the same `resource_key`;
- the task position in that Worker's claimable durable scan equals `resource_queue_position`.

No compatible Worker, multiple compatible Workers, cross-resource competition, and non-queued tasks fail closed to `resource_queue_position_exact=false`. Training keeps its specialized CPU/GPU/remote queue truth and GPU admission semantics. Scheduler claim order itself is unchanged.

## Frontend contract

AI annotation and material-batch views now use the same `exactTaskQueuePosition()` helper as storage import, resource discovery, video, deployment tests, and training UI. They may show “资源队列第 N 位” only when the backend exact flag is true. Wait reasons remain visible when rank is inexact.

## Performance

Unified task, video-task, and annotation-task list endpoints snapshot Worker runtime and queued candidates once per response and reuse those snapshots for every item, avoiding an N+1 Worker/candidate query pattern.

## Boundaries

This batch does not change Scheduler selection, priority, promotion, Worker capabilities, leases, GPU admission, or the already-closed v47 cleaning compatibility projection. Genuine 10k validation and A800 RC remain deferred.
''', encoding="utf-8")


def main() -> None:
    patch_public_py()
    patch_app_py()
    patch_material_batches_py()
    patch_frontend()
    patch_backend_tests()
    patch_frontend_tests()
    write_handoff()


if __name__ == "__main__":
    main()
