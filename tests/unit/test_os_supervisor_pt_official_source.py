"""Exact official model pin admission only; no torch/pickle code execution."""
import hashlib
from pathlib import Path

import pytest

from platform_core.mother_model_assets import _OFFICIAL_YOLO11_DETECT
from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_pt_official_source import (
    pinned_official_pt_binding, verify_local_pinned_official_pt,
)


@pytest.mark.parametrize("model", ["yolo11n.pt", "yolo11s.pt", "yolo11m.pt"])
def test_existing_code_pinned_release_only(model):
    length, digest = _OFFICIAL_YOLO11_DETECT[model]
    result = pinned_official_pt_binding(
        source_name=model,
        source_sha256=digest,
        source_size_bytes=length,
    )
    assert result.source_name == model
    assert result.source_sha256 == digest
    assert result.origin == "ultralytics-assets-v8.4.0-pinned-sha256"
    assert result.launch_authorized is False
    assert result.result_publish_allowed is False
    assert result.trusted_stop_receipt_available is False


@pytest.mark.parametrize("model,sha,size", [
    ("yolo11n.pt", "a" * 64, 5613764),
    ("../yolo11n.pt", "a" * 64, 5613764),
    ("custom-trained.pt", "a" * 64, 100000),
    ("yolo11n.pt", "0" * 64, 5613764),
    ("yolo11n.pt", "0" * 64, -1),
    (None, "0" * 64, 5613764),
    ("yolo11n.pt", "0" * 64, True),
    ("YOLO11N.pt", "0" * 64, 5613764),
])
def test_no_self_attested_or_untrusted_pickle_pin(model, sha, size):
    with pytest.raises(GrantRejected, match="HOLD"):
        pinned_official_pt_binding(
            source_name=model, source_sha256=sha,
            source_size_bytes=size,
        )


def test_source_name_and_actual_content_both_required(tmp_path):
    model = "yolo11n.pt"
    length, digest = _OFFICIAL_YOLO11_DETECT[model]
    candidate = tmp_path / model
    candidate.write_bytes(b"x" * 1024)
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_local_pinned_official_pt(
            candidate, source_name=model,
            source_sha256=digest, source_size_bytes=length,
        )
    assert candidate.read_bytes() == b"x" * 1024


def test_hardlinked_or_symlinked_candidate_is_rejected(tmp_path):
    model = "yolo11n.pt"
    length, digest = _OFFICIAL_YOLO11_DETECT[model]
    candidate = tmp_path / model
    candidate.write_bytes(b"untrusted")
    hardlinked = tmp_path / "hardlinked.pt"
    hardlinked.hardlink_to(candidate)
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_local_pinned_official_pt(
            candidate, source_name=model,
            source_sha256=digest, source_size_bytes=length,
        )
    hardlinked.unlink()
    candidate.unlink()
    target = tmp_path / "other.pt"
    target.write_bytes(b"untrusted")
    try:
        candidate.symlink_to(target)
    except OSError:
        pytest.skip("platform does not permit creating symlinks")
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_local_pinned_official_pt(
            candidate, source_name=model,
            source_sha256=digest, source_size_bytes=length,
        )
