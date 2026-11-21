from __future__ import annotations

import errno
import hashlib
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from unittest.mock import Mock

from platform_core.task_runtime.payload_publications import PayloadPublicationError, PayloadPublicationIdentity
from platform_core.task_runtime.worker import FencedArtifactStore

import sys
from datetime import datetime, timedelta, timezone

import psutil
import pytest

from platform_core.task_runtime import (
    ArtifactStore,
    ExecutionFencedError,
    FencedTaskRepository,
    ProcessIdentity,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskStatus,
    WorkerContext,
    hash_command,
    launch_process,
)


def _add(repository, task_id="task-1"):
    return repository.create(
        TaskRecord.new(
            task_id,
            "project-1",
            TaskKind.VIDEO_FRAMES,
            "payload.json",
            "cpu:video",
        )
    )


def _expire(repository, task_id: str) -> None:
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with repository._connect() as database:
        database.execute(
            "UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
            (past, task_id),
        )


def test_expired_heartbeat_cannot_resurrect_execution(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    _add(repository)
    lease = repository.claim_next("worker-a", [TaskKind.VIDEO_FRAMES], set(), lease_seconds=30)
    assert lease is not None
    _expire(repository, "task-1")

    with pytest.raises(PermissionError, match="execution"):
        repository.heartbeat(
            "task-1",
            lease.lease_token,
            progress=25,
            execution_generation=lease.task.attempt,
        )

    current = repository.get("task-1")
    assert current is not None
    assert current.status is TaskStatus.RUNNING
    assert current.progress == 0


def test_live_process_blocks_requeue_until_exact_tree_is_reaped(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    _add(repository)
    lease = repository.claim_next("worker-a", [TaskKind.VIDEO_FRAMES], set(), lease_seconds=30)
    assert lease is not None
    launched = launch_process(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
    )
    try:
        repository.bind_process(
            "task-1",
            lease.lease_token,
            launched.identity,
            execution_generation=lease.task.attempt,
        )
        _expire(repository, "task-1")

        assert repository.release_expired() == 0
        blocked = repository.get("task-1")
        assert blocked is not None
        assert blocked.status is TaskStatus.RUNNING
        assert blocked.stage == "lease_expired_process_alive"
        assert psutil.pid_exists(launched.identity.pid)
        assert repository.claim_next("worker-b", [TaskKind.VIDEO_FRAMES], set()) is None

        assert repository.reap_expired_processes(timeout=1.0) == 1
        assert launched.process.wait(timeout=5) is not None
        assert repository.release_expired() == 1
        recovered = repository.get("task-1")
        assert recovered is not None
        assert recovered.status is TaskStatus.QUEUED
        assert recovered.stage == "recovered"
        assert recovered.process_pid is None
    finally:
        if launched.process.poll() is None:
            launched.process.terminate()
            launched.process.wait(timeout=5)


def test_gpu_reservation_is_retained_while_expired_process_is_still_alive(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    _add(repository)
    lease = repository.claim_next("worker-a", [TaskKind.VIDEO_FRAMES], set(), lease_seconds=30)
    assert lease is not None
    launched = launch_process(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
    )
    try:
        repository.bind_process(
            "task-1",
            lease.lease_token,
            launched.identity,
            execution_generation=lease.task.attempt,
        )
        old = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        with repository._connect() as database:
            database.execute(
                """
                INSERT INTO gpu_reservations
                (task_id, gpu_uuid, gpu_index, reserved_bytes, estimated_bytes,
                 worker_id, worker_slot, lease_token, policy, share_eligible,
                 sharing_evidence_at, created_at, heartbeat_at, expires_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    "task-1", "GPU-test", 0, 1024, 1024,
                    "worker-a", "slot-a", lease.lease_token, "exclusive", 0,
                    None, old, old, old,
                ),
            )
            database.execute(
                "UPDATE tasks SET lease_expires_at=? WHERE task_id='task-1'",
                (old,),
            )

        assert repository.release_expired() == 0
        with repository._connect() as database:
            reservation = database.execute(
                "SELECT task_id FROM gpu_reservations WHERE task_id='task-1'"
            ).fetchone()
        assert reservation is not None

        assert repository.reap_expired_processes(timeout=1.0) == 1
        launched.process.wait(timeout=5)
        assert repository.release_expired() == 1
        with repository._connect() as database:
            reservation = database.execute(
                "SELECT task_id FROM gpu_reservations WHERE task_id='task-1'"
            ).fetchone()
        assert reservation is None
    finally:
        if launched.process.poll() is None:
            launched.process.terminate()
            launched.process.wait(timeout=5)


def test_pid_identity_mismatch_never_kills_unrelated_process_and_allows_recovery(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    _add(repository)
    lease = repository.claim_next("worker-a", [TaskKind.VIDEO_FRAMES], set())
    assert lease is not None
    launched = launch_process(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
    )
    try:
        wrong_identity = ProcessIdentity(
            launched.identity.pid,
            launched.identity.create_time,
            hash_command([sys.executable, "-c", "print('different command')"]),
        )
        repository.bind_process(
            "task-1",
            lease.lease_token,
            wrong_identity,
            execution_generation=lease.task.attempt,
        )
        _expire(repository, "task-1")

        assert repository.reap_expired_processes(timeout=0.2) == 0
        assert launched.process.poll() is None
        assert repository.release_expired() == 1
        assert repository.get("task-1").status is TaskStatus.QUEUED
        assert launched.process.poll() is None
    finally:
        launched.process.terminate()
        launched.process.wait(timeout=5)


def test_execution_generation_fences_old_attempt_even_if_token_matches(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    _add(repository)
    first = repository.claim_next("worker-a", [TaskKind.VIDEO_FRAMES], set())
    assert first is not None
    _expire(repository, "task-1")
    assert repository.release_expired() == 1
    second = repository.claim_next("worker-b", [TaskKind.VIDEO_FRAMES], set())
    assert second is not None
    assert second.task.attempt == first.task.attempt + 1

    # Simulate an impossible token collision to prove attempt/generation is a
    # separate fence rather than relying on UUID uniqueness alone.
    with repository._connect() as database:
        database.execute(
            "UPDATE tasks SET lease_token=? WHERE task_id=?",
            (first.lease_token, "task-1"),
        )

    with pytest.raises(PermissionError, match="execution"):
        repository.finish(
            "task-1",
            first.lease_token,
            TaskStatus.SUCCEEDED,
            execution_generation=first.task.attempt,
        )

    finished = repository.finish(
        "task-1",
        first.lease_token,
        TaskStatus.SUCCEEDED,
        execution_generation=second.task.attempt,
    )
    assert finished.status is TaskStatus.SUCCEEDED


def test_parent_training_mutations_require_current_prepare_generation(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(TaskRecord.new(
        "train-parent",
        "project-1",
        TaskKind.TRAINING,
        "payload.json",
        "training:pending",
        required_capabilities=("training.input.ready",),
    ))
    repository.create(TaskRecord.new(
        "trainprep-parent",
        "project-1",
        TaskKind.TRAINING_PREPARE,
        "payload.json",
        "training-prepare:project-1",
        required_capabilities=("training.prepare",),
    ))
    first = repository.claim_next(
        "worker-a", [TaskKind.TRAINING_PREPARE], {"training.prepare"}, lease_seconds=30,
    )
    assert first is not None
    _expire(repository, "trainprep-parent")
    assert repository.release_expired() == 1
    second = repository.claim_next(
        "worker-b", [TaskKind.TRAINING_PREPARE], {"training.prepare"}, lease_seconds=30,
    )
    assert second is not None

    owner = {
        "preparation_task_id": first.task.task_id,
        "preparation_lease_token": first.lease_token,
        "preparation_execution_generation": first.task.attempt,
    }
    with pytest.raises(PermissionError, match="preparation execution"):
        repository.activate_prepared_training(
            "train-parent",
            resource_key="training:remote:scheduler",
            required_capabilities=("training.ultralytics",),
            **owner,
        )
    with pytest.raises(PermissionError, match="preparation execution"):
        repository.fail_queued_precondition(
            "train-parent",
            "must-not-publish",
            status=TaskStatus.FAILED,
            **owner,
        )
    parent = repository.get("train-parent")
    assert parent is not None and parent.status is TaskStatus.QUEUED
    assert parent.required_capabilities == ("training.input.ready",)
    assert parent.error is None

    activated = repository.activate_prepared_training(
        "train-parent",
        resource_key="training:remote:scheduler",
        required_capabilities=("training.ultralytics",),
        preparation_task_id=second.task.task_id,
        preparation_lease_token=second.lease_token,
        preparation_execution_generation=second.task.attempt,
    )
    assert activated.status is TaskStatus.QUEUED
    assert activated.required_capabilities == ("training.ultralytics",)


def test_fenced_context_refuses_artifact_publication(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    _add(repository)
    lease = repository.claim_next("worker-a", [TaskKind.VIDEO_FRAMES], set())
    assert lease is not None
    context = WorkerContext(lease.task, lease, repository, artifacts)
    context.mark_lease_lost()

    with pytest.raises(ExecutionFencedError):
        context.artifacts.atomic_write_json("task-1", "result.json", {"stale": True})
    assert not artifacts.artifact_path("task-1", "result.json").exists()


def test_scheduler_does_not_publish_success_after_execution_expires(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    _add(repository)

    class ExpiringHandler:
        def run(self, context):
            _expire(repository, context.task.task_id)
            return TaskStatus.SUCCEEDED, "result.json"

        recover = run

    scheduler = Scheduler(
        repository,
        artifacts,
        "worker-a",
        {TaskKind.VIDEO_FRAMES: ExpiringHandler()},
        set(),
        lease_seconds=30,
    )
    assert scheduler.run_once() is True
    stale = repository.get("task-1")
    assert stale is not None
    assert stale.status is TaskStatus.RUNNING
    assert stale.finished_at is None

    # On the next scheduling pass the expired process-less attempt is safely
    # recovered before another execution can be claimed.
    assert repository.release_expired() == 1
    recovered = repository.get("task-1")
    assert recovered.status is TaskStatus.QUEUED
    assert recovered.stage == "recovered"


def test_unverified_remote_agent_expiry_holds_resource_and_gpu_reservation(tmp_path):
    # Unlike a local worker, the controller has no way to inspect an Agent's
    # remote OS process. An expired lease must never silently requeue the job.
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    for task_id in ("remote-owner", "same-resource-waiter"):
        repository.create(TaskRecord.new(
            task_id, "project-1", TaskKind.MODEL_CONVERSION,
            "payload.json", "model-conversion:shared",
        ))
    first = repository.claim_next("agent:node-remote", [TaskKind.MODEL_CONVERSION], set())
    assert first is not None
    assert first.task.task_id == "remote-owner"
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with repository._connect() as db:
        db.execute(
            """INSERT INTO gpu_reservations
                (task_id,gpu_uuid,gpu_index,reserved_bytes,estimated_bytes,
                 worker_id,worker_slot,lease_token,policy,share_eligible,
                 sharing_evidence_at,created_at,heartbeat_at,expires_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("remote-owner", "GPU-unverified", 0, 1024, 1024,
             "agent:node-remote", "slot-0", first.lease_token, "exclusive", 0,
             None, past, past, past),
        )
        db.execute("UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
                   (past, "remote-owner"))

    assert repository.release_expired() == 0
    held = repository.get("remote-owner")
    assert held.status is TaskStatus.RUNNING
    assert held.stage == "recovery_blocked_remote_agent_unverified"
    assert "REMOTE_AGENT_STOP_UNVERIFIED" in str(held.resource_wait_reason)
    assert held.worker_id == "agent:node-remote"
    assert held.attempt == 1
    with pytest.raises(PermissionError, match="execution"):
        repository.heartbeat(
            "remote-owner", first.lease_token,
            execution_generation=first.task.attempt,
        )
    assert repository.claim_next(
        "worker-b", [TaskKind.MODEL_CONVERSION], set(),
    ) is None
    waiting = repository.get("same-resource-waiter")
    # The initial queue prefilter skips a resource still owned by an
    # unverified remote process, before emitting an admission wait reason.
    assert waiting.status is TaskStatus.QUEUED

    with repository._connect() as db:
        reservation = db.execute(
            "SELECT policy,share_eligible,expires_at FROM gpu_reservations WHERE task_id=?",
            ("remote-owner",),
        ).fetchone()
    assert reservation is not None
    assert reservation["policy"] == "exclusive"
    assert reservation["share_eligible"] == 0
    assert datetime.fromisoformat(reservation["expires_at"]) > datetime.now(timezone.utc)
    assert repository.release_expired() == 0
    assert repository.get("remote-owner").stage == "recovery_blocked_remote_agent_unverified"


def test_unverified_remote_agent_cancel_does_not_claim_process_has_stopped(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(TaskRecord.new(
        "remote-cancel", "project-1", TaskKind.DEPLOYMENT_TEST,
        "request.json", "deployment:remote-cancel",
    ))
    lease = repository.claim_next(
        "agent:node-remote", [TaskKind.DEPLOYMENT_TEST], set(),
    )
    assert lease is not None
    current = repository.request_cancel("remote-cancel")
    assert current.status is TaskStatus.CANCEL_REQUESTED
    _expire(repository, "remote-cancel")
    assert repository.release_expired() == 0
    held = repository.get("remote-cancel")
    assert held.status is TaskStatus.CANCEL_REQUESTED
    assert held.stage == "recovery_blocked_remote_agent_unverified"
    assert held.worker_id == "agent:node-remote"
    assert held.finished_at is None


def test_cancelling_held_remote_execution_keeps_stop_unverified_fence(tmp_path):
    """Cancel must not temporarily erase the safety hold before next reap."""
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    for task_id in ("agent-holder", "waiting-contender"):
        repository.create(TaskRecord.new(
            task_id, "project-1", TaskKind.MODEL_CONVERSION,
            "request.json", "conversion:shared-unverified-stop",
        ))
    first = repository.claim_next(
        "agent:unreachable-node", [TaskKind.MODEL_CONVERSION], set(),
    )
    assert first is not None and first.task.task_id == "agent-holder"
    _expire(repository, "agent-holder")
    assert repository.release_expired() == 0
    held = repository.get("agent-holder")
    assert held.stage == "recovery_blocked_remote_agent_unverified"

    cancelled = repository.request_cancel("agent-holder")
    assert cancelled.status is TaskStatus.CANCEL_REQUESTED
    assert cancelled.stage == "recovery_blocked_remote_agent_unverified"
    assert cancelled.worker_id == "agent:unreachable-node"
    assert cancelled.finished_at is None

    # The queue must remain fenced even *before* another recovery sweep.
    assert repository.claim_next(
        "ordinary-worker", [TaskKind.MODEL_CONVERSION], set(),
    ) is None
    assert repository.get("waiting-contender").status is TaskStatus.QUEUED
    assert repository.get("agent-holder").attempt == 1


def test_generic_stage_mutation_cannot_erase_remote_agent_stop_hold(tmp_path):
    """Even internal stage updates cannot weaken an unresolved remote hold."""
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(TaskRecord.new(
        "remote-stage-owner", "project-1", TaskKind.MODEL_CONVERSION,
        "request.json", "conversion:remote-stage-hold",
    ))
    first = repository.claim_next(
        "agent:offline-node", [TaskKind.MODEL_CONVERSION], set(),
    )
    assert first is not None
    _expire(repository, "remote-stage-owner")
    assert repository.release_expired() == 0
    held = repository.get("remote-stage-owner")
    assert held.stage == "recovery_blocked_remote_agent_unverified"

    with pytest.raises(ValueError, match="running tasks"):
        repository.set_stage("remote-stage-owner", "running")
    after = repository.get("remote-stage-owner")
    assert after.stage == "recovery_blocked_remote_agent_unverified"
    assert after.status is TaskStatus.RUNNING
    assert after.worker_id == "agent:offline-node"
    assert after.attempt == 1


def test_generic_stage_mutation_still_works_for_ordinary_running_task(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(TaskRecord.new(
        "ordinary-stage-owner", "project-1", TaskKind.MODEL_CONVERSION,
        "request.json", "conversion:ordinary-stage",
    ))
    first = repository.claim_next(
        "local-worker", [TaskKind.MODEL_CONVERSION], set(),
    )
    assert first is not None
    assert repository.set_stage(
        "ordinary-stage-owner", "preparing",
    ).stage == "preparing"


# P1 immutable storage contracts; no Claim/Task publication integration.
def identity(**changes):
    values = dict(task_id="parent", project_id="project", kind="TRAINING",
                  phase="training.ready", expected_ref="payload.json",
                  expected_parent_attempt=0, intent={"request_id": "request", "target": "local"})
    values.update(changes)
    return PayloadPublicationIdentity(**values)


def native(path):
    # Raw corruption probes must also work on Windows with long paths disabled.
    return Path("\\\\?\\" + str(path)) if os.name == "nt" else path


def publish(root, payload=None):
    return ArtifactStore(root).prepare_payload_publication(
        identity(), {"中文": [1, 2], "a": True} if payload is None else payload,
        activation={"stage": "queued", "required_capabilities": ["training.runtime"]})


def test_payload_p1_digest_canonical_bytes_and_restart(tmp_path):
    prepared = publish(tmp_path)
    version = prepared.version
    assert version.raw == '{"a":true,"中文":[1,2]}'.encode()
    assert hashlib.sha256(version.raw).hexdigest() in version.payload_ref
    reread = ArtifactStore(tmp_path).read_payload_version("parent", version.payload_ref)
    assert reread == version
    receipt = ArtifactStore(tmp_path).read_payload_publication_receipt(
        "parent", prepared.operation_id, identity=identity())
    assert receipt == prepared
    assert receipt.metadata["size"] == len(version.raw)
    assert publish(tmp_path) == prepared
    path = native(tmp_path / "parent" / version.payload_ref)
    original = path.stat().st_mtime_ns
    assert publish(tmp_path) == prepared
    assert path.stat().st_mtime_ns == original
    script = "from platform_core.task_runtime.artifacts import ArtifactStore; import sys; v=ArtifactStore(sys.argv[1]).read_payload_version('parent',sys.argv[2]); print(v.digest)"
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), version.payload_ref],
                            check=True, capture_output=True, text=True)
    assert result.stdout.strip() == version.digest


def test_payload_p1_operation_identity_is_detached_stable_and_rejects_unallowed_fields(tmp_path):
    intent = {"target": "local", "request_id": "request"}
    first = identity(intent=intent)
    intent["target"] = "changed"
    assert first.operation_id == identity().operation_id
    assert first.operation_id != identity(expected_parent_attempt=1).operation_id
    assert first.operation_id != identity(expected_ref="other.json").operation_id
    with pytest.raises(PayloadPublicationError, match="ACTIVATION"):
        ArtifactStore(tmp_path).prepare_payload_publication(first, {}, activation={"attempt": 5})
    with pytest.raises(PayloadPublicationError):
        identity(intent={"nonfinite": float("nan")})


def test_payload_p1_conflict_and_receipt_identity_validation(tmp_path):
    prepared = publish(tmp_path, {"value": 1})
    with pytest.raises(PayloadPublicationError, match="OPERATION_CONFLICT"):
        publish(tmp_path, {"value": 2})
    assert ArtifactStore(tmp_path).read_payload_version("parent", prepared.version.payload_ref).data == {"value": 1}
    with pytest.raises(PayloadPublicationError, match="IDENTITY"):
        ArtifactStore(tmp_path).read_payload_publication_receipt(
            "parent", prepared.operation_id, identity=identity(project_id="foreign"))


def test_payload_p1_tampering_and_missing_never_fall_back(tmp_path):
    prepared = publish(tmp_path)
    path = native(tmp_path / "parent" / prepared.version.payload_ref)
    path.write_bytes(b"{}")  # deliberate out-of-protocol corruption
    with pytest.raises(PayloadPublicationError, match="INTEGRITY"):
        ArtifactStore(tmp_path).read_payload_version("parent", prepared.version.payload_ref)
    path.unlink()
    with pytest.raises(PayloadPublicationError, match="MISSING"):
        ArtifactStore(tmp_path).read_payload_version("parent", prepared.version.payload_ref)


@pytest.mark.parametrize("ref", ["../escape", "/escape", "C:/escape", "payload-versions/v1/not-a-hash/file.json", "scenario/../payload.json"])
def test_payload_p1_invalid_refs(tmp_path, ref):
    with pytest.raises(PayloadPublicationError):
        ArtifactStore(tmp_path).read_payload_version("parent", ref)


def test_payload_p1_symlink_escape_and_alias(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    prepared = publish(store.root)
    alias = store.root / "parent" / "alias"
    try:
        alias.symlink_to(store.root / "parent" / "payload-versions", target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink capability unavailable: {error}")
    with pytest.raises(ValueError):
        store.atomic_write_json("parent", "alias/overwrite.json", {})
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.root / "other").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PayloadPublicationError, match="UNSAFE"):
        store.prepare_payload_publication(identity(task_id="other"), {})
    assert not list(outside.iterdir())


@pytest.mark.parametrize("scenario", [False, True])
def test_payload_p1_reserved_legacy_interfaces_and_delete_are_all_or_nothing(tmp_path, scenario):
    store = ArtifactStore(tmp_path)
    ident = identity(kind="DEPLOYMENT_TEST", phase="deployment.ready") if scenario else identity()
    prepared = store.prepare_payload_publication(ident, {})
    store.atomic_write_json("parent", "result.json", {"keep": True})
    for ref in (prepared.version.payload_ref,
                ("scenario/" if scenario else "") + "payload-publications/v1/other.json"):
        for operation in (lambda: store.artifact_path("parent", ref),
                          lambda: store.atomic_write_json("parent", ref, {}),
                          lambda: store.append_log("parent", ref, "bad")):
            with pytest.raises(ValueError, match="RESERVED"):
                operation()
    with pytest.raises(PayloadPublicationError, match="RETENTION"):
        store.delete_task("parent")
    assert store.read_json("parent", "result.json") == {"keep": True}
    assert store.read_payload_version("parent", prepared.version.payload_ref).data == {}
    store.atomic_write_json("legacy", "payload.json", {})
    assert store.delete_task("legacy")
    assert not (tmp_path / "legacy").exists()


def test_payload_p1_fenced_preparation_rechecks_and_legacy_cannot_bypass(tmp_path):
    context = Mock(assert_current_execution=Mock())
    fenced = FencedArtifactStore(context, ArtifactStore(tmp_path))
    prepared = fenced.prepare_payload_publication(identity(), {})
    assert fenced.read_payload_version("parent", prepared.version.payload_ref).data == {}
    assert fenced.read_payload_publication_receipt("parent", prepared.operation_id) == prepared
    with pytest.raises(ValueError):
        fenced.atomic_write_json("parent", prepared.version.payload_ref, {})
    with pytest.raises(ValueError):
        fenced.artifact_path("parent", prepared.version.payload_ref)
    with pytest.raises(ValueError):
        fenced.append_log("parent", prepared.version.payload_ref, "bad")
    context.assert_current_execution.side_effect = [None, ExecutionFencedError("lost")]
    with pytest.raises(ExecutionFencedError):
        fenced.prepare_payload_publication(identity(task_id="other"), {})
    assert not list((tmp_path / "other").glob("payload-publications/v1/*.json"))


@pytest.mark.parametrize("which", ["version", "receipt"])
def test_payload_p1_link_failure_leaves_no_partial_final_and_is_retryable(tmp_path, monkeypatch, which):
    real_link = os.link
    def failing_link(source, destination, **kwargs):
        if ("payload-publications" in str(destination)) == (which == "receipt"):
            raise OSError(errno.ENOTSUP, "injected link failure")
        return real_link(source, destination, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(os, "link", failing_link)
        patch.setattr(os, "replace", Mock(side_effect=AssertionError("no covering fallback allowed")))
        with pytest.raises(PayloadPublicationError, match="BACKEND"):
            publish(tmp_path)
    assert not list((tmp_path / "parent").glob("payload-publications/v1/*.json"))
    assert publish(tmp_path).version.data["a"] is True


def test_payload_p1_fsync_failure_does_not_publish(tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", Mock(side_effect=OSError("disk failure")))
        with pytest.raises(PayloadPublicationError):
            publish(tmp_path)
    assert not list((tmp_path / "parent").glob("**/sha256-*.json"))
    assert publish(tmp_path)


def test_payload_p1_process_concurrency_and_orphan_version_recovery(tmp_path):
    script = '''
import json, sys, time
from pathlib import Path
from platform_core.task_runtime.artifacts import ArtifactStore
from platform_core.task_runtime.payload_publications import PayloadPublicationIdentity, PayloadPublicationError
root, value = Path(sys.argv[1]), int(sys.argv[2])
(root / ('ready-' + str(value))).touch()
deadline = time.monotonic() + 15
while not (root / 'start').exists():
    if time.monotonic() > deadline: raise RuntimeError('start barrier timeout')
    time.sleep(.01)
identity = PayloadPublicationIdentity(task_id='parent', project_id='project', kind='TRAINING', phase='training.ready', expected_ref='payload.json', expected_parent_attempt=0, intent={'request_id':'request', 'target':'local'})
try:
    prepared = ArtifactStore(root).prepare_payload_publication(identity, {'value':value})
    print(json.dumps(['ok', prepared.version.payload_ref]))
except PayloadPublicationError as error:
    print(json.dumps([error.code, '']))
'''
    processes = [subprocess.Popen([sys.executable, "-c", script, str(tmp_path), str(value)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for value in (1, 2)]
    try:
        deadline = time.monotonic() + 15
        while not all((tmp_path / f"ready-{value}").exists() for value in (1, 2)):
            assert time.monotonic() < deadline, "publish processes failed to reach barrier"
            time.sleep(.01)
        (tmp_path / "start").touch()
        results = []
        for process in processes:
            output, error = process.communicate(timeout=15)
            assert process.returncode == 0, error
            results.append(json.loads(output))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert sorted(row[0] for row in results) == ["PUBLICATION_OPERATION_CONFLICT", "ok"]
    winner = next(row[1] for row in results if row[0] == "ok")
    store = ArtifactStore(tmp_path)
    assert store.read_payload_publication_receipt("parent", identity().operation_id).version.payload_ref == winner
    # A separate operation with only a version left behind is NOT Task publication.
    other = store.prepare_payload_publication(identity(task_id="orphan"), {})
    receipt = tmp_path / "orphan" / "payload-publications/v1" / (other.operation_id + ".json")
    receipt.unlink()  # simulate loss before receipt publication
    with pytest.raises(PayloadPublicationError, match="MISSING"):
        store.read_payload_publication_receipt("orphan", other.operation_id)
    assert ArtifactStore(tmp_path).prepare_payload_publication(identity(task_id="orphan"), {}) == other


def test_payload_p1_storage_io_does_not_hold_sqlite_writer(tmp_path, monkeypatch):
    database = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE marker (value INTEGER)")
    real_fsync = os.fsync
    calls = []
    def probe(descriptor):
        with sqlite3.connect(database, timeout=0) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO marker VALUES (1)")
        calls.append(descriptor)
        return real_fsync(descriptor)
    monkeypatch.setattr(os, "fsync", probe)
    assert publish(tmp_path / "artifacts")
    assert len(calls) >= 2

@pytest.mark.parametrize('field,value', [
    ('operation_id', '0' * 64), ('digest', '0' * 64), ('size', 100),
    ('activation', {'status': 'RUNNING'}), ('new_ref', '../payload.json'),
])
def test_payload_p1_receipt_revalidates_every_binding(tmp_path, field, value):
    prepared = publish(tmp_path)
    path = native(tmp_path / 'parent' / 'payload-publications/v1' / (prepared.operation_id + '.json'))
    receipt = prepared.metadata
    receipt[field] = value
    path.write_text(json.dumps(receipt, sort_keys=True, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    with pytest.raises(PayloadPublicationError):
        ArtifactStore(tmp_path).read_payload_publication_receipt('parent', prepared.operation_id)


def test_payload_p1_size_limit_and_actual_explicit_training_request_scale(tmp_path):
    # app.py:8272 caps each explicit train/test ID list at 50,000.
    ids = [f'{index:08x}-0000-0000-0000-{index:012x}' for index in range(50000)]
    prepared = ArtifactStore(tmp_path).prepare_payload_publication(
        identity(), {'train_image_ids': ids, 'test_image_ids': ids})
    assert len(prepared.version.data['test_image_ids']) == 50000
    assert len(prepared.version.raw) > 3_000_000
    with pytest.raises(PayloadPublicationError, match='SIZE_LIMIT'):
        ArtifactStore(tmp_path, max_payload_bytes=100).read_payload_version('parent', prepared.version.payload_ref)
    with pytest.raises(PayloadPublicationError, match='SIZE_LIMIT'):
        ArtifactStore(tmp_path / 'small', max_payload_bytes=5).prepare_payload_publication(identity(), {'too': 'large'})


def test_payload_p1_write_failure_does_not_publish(tmp_path, monkeypatch):
    real_fdopen = os.fdopen
    class FailedWrite:
        def __init__(self, descriptor):
            self.stream = real_fdopen(descriptor, 'wb')
        def __enter__(self):
            return self
        def write(self, raw):
            raise OSError('injected write failure')
        def __exit__(self, *args):
            self.stream.close()
    with monkeypatch.context() as patch:
        patch.setattr(os, 'fdopen', lambda descriptor, mode: FailedWrite(descriptor))
        with pytest.raises(PayloadPublicationError, match='IO_ERROR'):
            publish(tmp_path)
    assert not list((tmp_path / 'parent').glob('**/sha256-*.json'))
    assert publish(tmp_path)


def test_payload_p1_fenced_receipt_not_published_after_lease_loss(tmp_path):
    context = Mock(assert_current_execution=Mock(side_effect=[None, None, ExecutionFencedError('lost before receipt')]))
    store = ArtifactStore(tmp_path)
    with pytest.raises(ExecutionFencedError):
        FencedArtifactStore(context, store).prepare_payload_publication(identity(), {})
    with pytest.raises(PayloadPublicationError, match='MISSING'):
        store.read_payload_publication_receipt('parent', identity().operation_id)
    assert list((tmp_path / 'parent' / 'payload-versions').glob('**/sha256-*.json'))


def test_payload_p1_hash_and_serialization_also_run_outside_writer(tmp_path, monkeypatch):
    from platform_core.task_runtime import payload_publications as module
    database = tmp_path / 'tasks.sqlite3'
    sqlite3.connect(database).close()
    def probe():
        with sqlite3.connect(database, timeout=0) as connection:
            connection.execute('BEGIN IMMEDIATE')
    real_json, real_sha = module._json_bytes, hashlib.sha256
    def encode(value):
        probe()
        return real_json(value)
    def sha(*args, **kwargs):
        probe()
        return real_sha(*args, **kwargs)
    monkeypatch.setattr(module, '_json_bytes', encode)
    monkeypatch.setattr(hashlib, 'sha256', sha)
    assert publish(tmp_path / 'artifacts')


def test_payload_p1_payload_and_receipt_limits_are_independent(tmp_path):
    store = ArtifactStore(tmp_path, max_payload_bytes=2)
    publication = store.prepare_payload_publication(identity(), {})
    assert store.read_payload_publication_receipt('parent', publication.operation_id) == publication
    small_receipt = ArtifactStore(tmp_path / 'other', max_receipt_bytes=2)
    with pytest.raises(PayloadPublicationError, match='SIZE_LIMIT'):
        small_receipt.prepare_payload_publication(identity(), {})
    assert not (small_receipt.root / 'parent').exists()


def test_payload_p1_process_crash_between_version_and_receipt_is_not_task_publication(tmp_path):
    script = '''
import os, sys
from platform_core.task_runtime.artifacts import ArtifactStore
from platform_core.task_runtime.payload_publications import PayloadVersionStore, PayloadPublicationIdentity
original = PayloadVersionStore._publish
def crash(self, task_id, ref, *args, **kwargs):
    if 'payload-publications' in ref: os._exit(23)
    return original(self, task_id, ref, *args, **kwargs)
PayloadVersionStore._publish = crash
identity = PayloadPublicationIdentity(task_id='parent', project_id='project', kind='TRAINING', phase='training.ready', expected_ref='payload.json', expected_parent_attempt=0, intent={'request_id':'request', 'target':'local'})
ArtifactStore(sys.argv[1]).prepare_payload_publication(identity, {})
'''
    process = subprocess.run([sys.executable, '-c', script, str(tmp_path)], timeout=15,
                             capture_output=True, text=True)
    assert process.returncode == 23, process.stderr
    store = ArtifactStore(tmp_path)
    with pytest.raises(PayloadPublicationError, match='MISSING'):
        store.read_payload_publication_receipt('parent', identity().operation_id)
    orphan = list((tmp_path / 'parent' / 'payload-versions').glob('**/sha256-*.json'))
    assert len(orphan) == 1
    original_time = native(orphan[0]).stat().st_mtime_ns
    recovered = store.prepare_payload_publication(identity(), {})
    assert recovered.version.data == {}
    assert native(orphan[0]).stat().st_mtime_ns == original_time
