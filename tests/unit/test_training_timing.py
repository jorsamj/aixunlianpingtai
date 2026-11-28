from platform_core import training_job_projection as projection
from platform_core.training_timing import begin_attempt, record_update, timing_view


def test_wall_time_is_not_the_resumed_process_elapsed():
    job = {"status": "done", "first_started_at": "2026-10-26T20:00:00+00:00",
           "training_progress": {"elapsed_seconds": 10800},
           "training_attempts": [
               {"generation": 1, "worker_id": "initial", "started_at": "2026-10-26T20:00:00Z",
                "finished_at": "2026-10-26T22:00:00Z", "active_seconds": 7200, "training_closed": True},
               {"generation": 2, "worker_id": "recovered", "started_at": "2026-10-26T23:00:00Z",
                "finished_at": "2026-10-27T02:00:00Z", "active_seconds": 10800, "training_closed": True},
           ]}
    runtime = {"status": "SUCCEEDED", "finished_at": "2026-10-27T02:00:00Z"}
    display = projection.build_training_display_progress(job, runtime)
    assert display["wall_elapsed_seconds"] == 21600
    assert display["active_training_seconds"] == 18000
    assert display["attempt_elapsed_seconds"] == 10800
    assert display["elapsed_seconds"] == 21600


def test_missing_timezone_or_start_is_unknown_not_queue_age():
    display = projection.build_training_display_progress({"status": "done", "created_at": "2026-10-26T00:00:00Z",
        "first_batch_at": "2026-10-26 23:00:00", "training_progress": {"elapsed_seconds": 16380}},
        {"status": "SUCCEEDED", "finished_at": "2026-10-27T02:00:00Z"})
    assert display["wall_elapsed_seconds"] is None
    assert display["elapsed_seconds"] is None
    assert display["current_process_elapsed_seconds"] == 16380


def test_terminal_projection_retains_last_verified_worker():
    job = {"status": "done", "training_attempts": [{"generation": 1, "worker_id": "initial"},
                                                    {"generation": 2, "worker_id": "recovered"}]}
    projection.apply_training_task_truth(job, {"status": "SUCCEEDED", "worker_id": None}, legacy_status="done")
    assert job["task_worker_id"] == "recovered"


def test_training_intervals_exclude_pause_and_do_not_double_count_events():
    job = {}
    begin_attempt(job, 1, "worker", "2026-10-26T10:00:00Z")
    record_update(job, {"first_batch_at": "2026-10-26T10:01:00Z"}, "2026-10-26T10:01:00Z")
    # SQL acknowledgement may be delayed after the OS has actually suspended
    # the process. Count to the suspension event, not the later write time.
    record_update(job, {"status": "paused", "paused_at": "2026-10-26T11:01:00Z"}, "2026-10-26T11:02:00Z")
    record_update(job, {"status": "paused"}, "2026-10-26T11:02:00Z")
    record_update(job, {"resumed_at": "2026-10-26T12:01:00Z"}, "2026-10-26T12:01:00Z")
    record_update(job, {"training_segment_finished_at": "2026-10-26T13:01:00Z"}, "2026-10-26T13:01:00Z")
    view = timing_view(job, {"status": "SUCCEEDED", "finished_at": "2026-10-26T13:02:00Z"})
    assert view["active_training_seconds"] == 7200
    assert view["wall_elapsed_seconds"] == 10860
    assert view["active_training_seconds_complete"] is True


def test_interrupted_or_missing_generations_are_explicit_lower_bounds():
    job = {}
    begin_attempt(job, 2, "resume", "2026-10-26T12:00:00Z")
    record_update(job, {"resume_first_batch_at": "2026-10-26T12:00:00Z"}, "2026-10-26T12:00:00Z")
    record_update(job, {}, "2026-10-26T13:00:00Z")
    begin_attempt(job, 3, "resume2", "2026-10-26T14:00:00Z")
    view = timing_view(job, {"status": "RUNNING"}, now="2026-10-26T14:01:00Z")
    assert view["first_started_at"] is None
    assert view["active_training_seconds"] == 3600
    assert view["active_training_seconds_complete"] is False


def test_post_training_validation_remains_in_current_worker_execution():
    job = {"training_attempts": [{"generation": 1, "worker_id": "worker",
        "started_at": "2026-10-26T10:00:00Z", "finished_at": "2026-10-26T11:00:00Z"}]}
    view = timing_view(job, {"status": "RUNNING"}, now="2026-10-26T12:00:00Z")
    assert view["attempt_elapsed_seconds"] == 7200


def test_unrecorded_new_generation_does_not_inherit_previous_worker_or_attempt():
    job = {"training_attempts": [{"generation": 1, "worker_id": "old-worker",
        "started_at": "2026-10-26T10:00:00Z", "active_seconds": 100, "training_closed": True}]}
    view = timing_view(job, {"status": "FAILED", "attempt": 2, "finished_at": "2026-10-26T12:00:00Z"})
    assert view["last_training_worker_id"] is None
    assert view["attempt_elapsed_seconds"] is None
    assert view["active_training_seconds_complete"] is False
