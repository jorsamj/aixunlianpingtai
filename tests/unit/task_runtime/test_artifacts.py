import pytest

from platform_core.task_runtime import ArtifactStore


def test_artifacts_are_atomic_and_task_relative(tmp_path):
    store = ArtifactStore(tmp_path)
    store.atomic_write_json("task-1", "checkpoints/video.json", {"next_index": 31})
    assert store.read_json("task-1", "checkpoints/video.json") == {"next_index": 31}

    store.append_log("task-1", "logs/task.log", "frame batch committed\n")
    assert store.artifact_path("task-1", "logs/task.log").read_text(encoding="utf-8") == (
        "frame batch committed\n"
    )


@pytest.mark.parametrize(
    "value",
    [
        "../escape.json",
        "/tmp/escape.json",
        r"C:\escape.json",
        r"folder\..\escape.json",
    ],
)
def test_artifact_store_rejects_escape(tmp_path, value):
    with pytest.raises(ValueError, match="relative task artifact"):
        ArtifactStore(tmp_path).artifact_path("task-1", value)


def test_task_id_is_also_a_single_safe_path_component(tmp_path):
    store = ArtifactStore(tmp_path)
    for task_id in ("../task", "nested/task", r"nested\task", "C:"):
        with pytest.raises(ValueError, match="task id"):
            store.artifact_path(task_id, "payload.json")
