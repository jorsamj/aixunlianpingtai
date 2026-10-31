import pytest

from platform_core.annotations import annotation_summary, normalize_boxes, restore_box_provenance


def test_atomic_json_concurrent_writers_own_distinct_temporary_files(tmp_path, monkeypatch):
    import json
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from threading import Barrier
    from platform_core.annotations import atomic_write_json

    target = tmp_path / "job.json"
    barrier = Barrier(2)
    temporaries = []
    original_replace = Path.replace

    def simultaneous_replace(source, destination):
        if source not in temporaries:
            temporaries.append(source)
            barrier.wait(timeout=5)
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", simultaneous_replace)
    errors = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(atomic_write_json, target, {"writer": i, "data": "x" * 2000}) for i in range(2)]
        for future in futures:
            try:
                future.result()
            except Exception as error:
                errors.append(error)
    assert len(set(temporaries)) == 2, "Concurrent writers must not share job.json.tmp"
    assert not errors
    assert json.loads(target.read_text(encoding="utf-8"))["writer"] in (0, 1)
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("winerror", [None, 5])
def test_atomic_json_failed_replace_preserves_original_and_cleans_owned_temp(tmp_path, monkeypatch, winerror):
    from pathlib import Path
    from platform_core.annotations import atomic_write_json

    target = tmp_path / "job.json"
    target.write_text('{"original": true}', encoding="utf-8")
    attempts = []

    def refuse_replace(source, destination):
        attempts.append(source)
        error = PermissionError("target still open")
        error.winerror = winerror
        raise error

    monkeypatch.setattr(Path, "replace", refuse_replace)
    with pytest.raises(PermissionError, match="target still open"):
        atomic_write_json(target, {"replacement": True})
    assert len(attempts) == (4 if winerror == 5 else 1)
    assert target.read_text(encoding="utf-8") == '{"original": true}'
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_json_retries_transient_windows_replace_contention(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from platform_core.annotations import atomic_write_json

    original_replace = Path.replace
    attempts = []

    def contended_replace(source, destination):
        attempts.append(source)
        if len(attempts) == 1:
            error = PermissionError("simultaneous Windows rename")
            error.winerror = 5
            raise error
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "replace", contended_replace)
    target = tmp_path / "job.json"
    atomic_write_json(target, {"complete": True})
    assert len(attempts) == 2
    assert attempts[0] == attempts[1]
    assert json.loads(target.read_text(encoding="utf-8")) == {"complete": True}
    assert list(tmp_path.iterdir()) == [target]


def test_invalid_coordinates_are_rejected():
    with pytest.raises(ValueError, match="坐标"):
        normalize_boxes(
            [{"label": "fire", "x1": 20, "y1": 10, "x2": 10, "y2": 30}],
            100,
            100,
            {"fire": 0},
        )


def test_summary_contains_preview_and_status():
    boxes = normalize_boxes(
        [
            {"label": "fire", "x1": 1, "y1": 2, "x2": 20, "y2": 30},
            {"label": "fire", "x1": 30, "y1": 2, "x2": 50, "y2": 30},
            {"label": "smoke", "x1": 2, "y1": 40, "x2": 40, "y2": 70},
        ],
        100,
        100,
        {"fire": 0, "smoke": 1},
    )
    summary = annotation_summary(boxes)
    assert summary["labels"] == ["fire", "smoke"]
    assert summary["label_counts"] == {"fire": 2, "smoke": 1}
    assert summary["box_count"] == 3
    assert summary["annotation_status"] == "annotated"
    assert summary["annotation_preview"][0]["label"] == "fire"



def test_restore_box_provenance_preserves_server_truth_and_marks_new_boxes_manual():
    existing = [{
        "id": "ai-box",
        "class_id": 0,
        "label": "fire",
        "x1": 1,
        "y1": 2,
        "x2": 20,
        "y2": 30,
        "source": "ai_candidate_confirmed",
        "source_task_id": "task-1",
        "candidate_id": "candidate-1",
        "confidence": 0.91,
    }]
    normalized = normalize_boxes(
        [
            {"id": "ai-box", "label": "fire", "x1": 2, "y1": 3, "x2": 22, "y2": 32},
            {"id": "manual-box", "label": "smoke", "x1": 30, "y1": 10, "x2": 60, "y2": 40,
             "source": "ai_candidate_confirmed"},
        ],
        100,
        100,
        {"fire": 0, "smoke": 1},
    )

    restored = restore_box_provenance(normalized, existing)

    assert restored[0]["source"] == "ai_candidate_confirmed"
    assert restored[0]["source_task_id"] == "task-1"
    assert restored[0]["candidate_id"] == "candidate-1"
    assert restored[0]["confidence"] == 0.91
    assert restored[1]["source"] == "manual"
    assert annotation_summary(restored)["annotation_origin"] == "mixed"
