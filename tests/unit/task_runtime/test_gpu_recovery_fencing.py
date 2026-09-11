from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from platform_core.task_runtime import (
    FencedTaskRepository,
    TaskKind,
    TaskRecord,
    launch_process,
)


def test_recovery_hold_forces_gpu_reservation_exclusive(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(
        TaskRecord.new(
            "train-held",
            "project-1",
            TaskKind.TRAINING,
            "payload.json",
            "training:local",
            required_capabilities=("cuda",),
        )
    )
    lease = repository.claim_next(
        "worker-a",
        [TaskKind.TRAINING],
        {"cuda"},
        lease_seconds=30,
    )
    assert lease is not None
    launched = launch_process(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
    )
    try:
        repository.bind_process(
            "train-held",
            lease.lease_token,
            launched.identity,
            execution_generation=lease.task.attempt,
        )
        past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
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
                    "train-held", "GPU-test", 0, 1024, 1024,
                    "worker-a", "slot-held", lease.lease_token, "shared", 1,
                    past, past, past, past,
                ),
            )
            database.execute(
                "UPDATE tasks SET lease_expires_at=? WHERE task_id='train-held'",
                (past,),
            )

        assert repository.release_expired() == 0
        with repository._connect() as database:
            reservation = database.execute(
                "SELECT * FROM gpu_reservations WHERE task_id='train-held'"
            ).fetchone()
        assert reservation is not None
        assert reservation["policy"] == "exclusive"
        assert reservation["share_eligible"] == 0
        assert reservation["sharing_evidence_at"] is None
        assert datetime.fromisoformat(reservation["expires_at"]) > datetime.now(timezone.utc)
    finally:
        repository.reap_expired_processes(timeout=1.0)
        if launched.process.poll() is None:
            launched.process.terminate()
        launched.process.wait(timeout=5)
