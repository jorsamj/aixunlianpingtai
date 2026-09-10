from platform_core.annotation_repository import AnnotationRepository


def test_empty_boxes_default_to_unannotated(tmp_path):
    repository = AnnotationRepository(tmp_path)

    saved = repository.upsert("image-a", [])

    assert saved["annotation_state"] == "unannotated"
    assert saved["annotation_scope"] == []


def test_confirmed_empty_requires_explicit_state_and_scope(tmp_path):
    repository = AnnotationRepository(tmp_path)

    saved = repository.upsert(
        "image-b",
        [],
        annotation_state="confirmed_empty",
        annotation_scope=["lbl_fire"],
    )

    assert saved["annotation_state"] == "confirmed_empty"
    assert saved["annotation_scope"] == ["lbl_fire"]
    assert saved["confirmed_empty_scope"] == ["lbl_fire"]
