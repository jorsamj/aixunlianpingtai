from __future__ import annotations

import json
from pathlib import Path

import pytest

from platform_core.hard_sample_mining import (
    HardSampleSafetyError, assert_not_frozen_test, difficulty_signals, sha256_file,
)


def test_frozen_test_ids_and_duplicate_hashes_are_never_mining_inputs(tmp_path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / ("a" * 64 + ".json")).write_text(json.dumps({
        "test_image_ids": ["frozen-test"],
        "images": [{"image_id": "frozen-test", "content_sha256": "b" * 64}],
    }))
    assert_not_frozen_test(tmp_path, ["train-1"], {"train-1": "c" * 64})
    with pytest.raises(HardSampleSafetyError, match="FROZEN_TEST_FORBIDDEN"):
        assert_not_frozen_test(tmp_path, ["frozen-test"])
    with pytest.raises(HardSampleSafetyError, match="DUPLICATE_FORBIDDEN"):
        assert_not_frozen_test(tmp_path, ["new-copy"], {"new-copy": "b" * 64})


def test_unreadable_snapshot_fails_closed_without_mutating_truth(tmp_path):
    directory = tmp_path / "snapshots"
    directory.mkdir()
    (directory / "corrupt.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(HardSampleSafetyError, match="SNAPSHOT_UNREADABLE"):
        assert_not_frozen_test(tmp_path, ["sample"])
    assert (directory / "corrupt.json").read_text() == "{broken"


def test_no_gt_never_fabricates_false_positive_or_false_negative():
    empty = difficulty_signals([], width=640, height=480)
    assert empty["signals"] == ["no_detection_unverified"]
    assert empty["ground_truth_compared"] is False
    assert empty["root_cause_confirmed"] is False
    rows = [{"confidence": 0.31, "box": [10, 10, 20, 20]}]
    analysis = difficulty_signals(rows, width=640, height=480)
    assert "low_confidence" in analysis["signals"]
    assert "small_target" in analysis["signals"]
    assert "false_negative" not in str(analysis)


def test_source_file_hash_is_reproducible(tmp_path):
    file = tmp_path / "model.pt"
    file.write_bytes(b"frozen-model")
    assert sha256_file(file) == __import__("hashlib").sha256(b"frozen-model").hexdigest()
