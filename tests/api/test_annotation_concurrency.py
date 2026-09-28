import pytest

from platform_core.annotation_repository import AnnotationConflictError, AnnotationRepository


def test_annotation_expected_version_rejects_stale_writer(tmp_path):
    repository = AnnotationRepository(tmp_path)
    initial = repository.get("image-1")
    assert initial["version"] == 0

    first = repository.upsert(
        "image-1",
        [{"label": "smoke", "x1": 1, "y1": 1, "x2": 10, "y2": 10}],
        "annotated",
        expected_version=0,
    )
    assert first["version"] == 1

    with pytest.raises(AnnotationConflictError) as captured:
        repository.upsert(
            "image-1",
            [],
            "confirmed_empty",
            expected_version=0,
        )
    assert captured.value.expected_version == 0
    assert captured.value.actual_version == 1

    current = repository.get("image-1")
    assert current["version"] == 1
    assert current["annotation_state"] == "annotated"
    assert current["content_digest"] == first["content_digest"]

    second = repository.upsert(
        "image-1",
        [],
        "confirmed_empty",
        expected_version=1,
    )
    assert second["version"] == 2
    assert second["annotation_state"] == "confirmed_empty"


def test_annotation_callers_without_expected_version_keep_existing_contract(tmp_path):
    repository = AnnotationRepository(tmp_path)
    first = repository.upsert(
        "image-2",
        [{"label": "fire", "x1": 2, "y1": 2, "x2": 20, "y2": 20}],
        "annotated",
    )
    second = repository.upsert("image-2", [], "confirmed_empty")

    assert first["version"] == 1
    assert second["version"] == 2
