import io
from pathlib import Path

from PIL import Image

from platform_core.annotation_repository import AnnotationRepository


def _write_png(path: Path, color: str = "white") -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())


def _box():
    return {
        "id": "box-final",
        "class_id": 0,
        "label": "target",
        "x1": 4.0,
        "y1": 4.0,
        "x2": 24.0,
        "y2": 24.0,
    }


def test_add_image_record_can_persist_final_annotation_before_return(client, tmp_path, monkeypatch):
    import app as app_module

    project = client.post(
        "/api/projects", json={"name": "p2b-final-builder", "labels": ["target"]}
    ).json()
    project_id = project["id"]
    app_module.ensure_default_datasets(project_id)
    source = tmp_path / "final.png"
    _write_png(source)

    calls = 0
    original = AnnotationRepository.upsert_many

    def counted(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AnnotationRepository, "upsert_many", counted)
    app_module._v50_begin_image_batch(project_id)
    committed = False
    try:
        record = app_module.add_image_record(
            project_id,
            source,
            source.name,
            "imported_yolo",
            "default",
            annotation_builder=lambda _record: [_box()],
        )
        repository = AnnotationRepository(app_module.project_dir(project_id))
        assert repository.exists(record["id"])
        annotation = repository.get(record["id"])
        assert annotation["annotation_state"] == "annotated"
        assert annotation["boxes"] == [{**_box(), "source": "imported"}]
        assert annotation["version"] == 1
        assert calls == 1
        app_module._v50_end_image_batch(save=True)
        committed = True
    finally:
        if not committed and app_module._v50_active_image_batch(project_id):
            app_module._v50_end_image_batch(save=False)

    material = app_module.material_store(project_id).get(record["id"])
    assert material["box_count"] == 1
    assert material["annotated"] is True
    assert material["annotation_origin"] == "imported"


def test_final_empty_annotation_keeps_confirmed_empty_semantics(client, tmp_path):
    import app as app_module

    project = client.post(
        "/api/projects", json={"name": "p2b-final-empty", "labels": ["target"]}
    ).json()
    project_id = project["id"]
    app_module.ensure_default_datasets(project_id)
    source = tmp_path / "empty.png"
    _write_png(source, "gray")

    record = app_module.add_image_record(
        project_id,
        source,
        source.name,
        "imported_yolo",
        "default",
        annotation_builder=lambda _record: [],
    )
    annotation = AnnotationRepository(app_module.project_dir(project_id)).get(record["id"])
    assert annotation["annotation_state"] == "confirmed_empty"
    assert annotation["boxes"] == []
    assert annotation["version"] == 1


def test_plain_add_image_record_still_creates_unannotated_truth(client, tmp_path):
    import app as app_module

    project = client.post(
        "/api/projects", json={"name": "p2b-plain", "labels": ["target"]}
    ).json()
    project_id = project["id"]
    app_module.ensure_default_datasets(project_id)
    source = tmp_path / "plain.png"
    _write_png(source, "blue")

    record = app_module.add_image_record(project_id, source, source.name, "raw", "default")
    annotation = AnnotationRepository(app_module.project_dir(project_id)).get(record["id"])
    assert annotation["annotation_state"] == "unannotated"
    assert annotation["boxes"] == []
    assert annotation["version"] == 1


def test_yolo_batch_uses_one_durable_annotation_write_per_image(client, tmp_path, monkeypatch):
    import app as app_module

    project = client.post(
        "/api/projects", json={"name": "p2b-yolo", "labels": []}
    ).json()
    project_id = project["id"]
    app_module.ensure_default_datasets(project_id)
    root = tmp_path / "source"
    images = root / "images" / "train"
    labels = root / "labels" / "train"
    images.mkdir(parents=True, exist_ok=True)
    labels.mkdir(parents=True, exist_ok=True)
    count = 20
    for index in range(count):
        stem = f"image_{index:04d}"
        _write_png(images / f"{stem}.png")
        (labels / f"{stem}.txt").write_text(
            "0 0.5 0.5 0.5 0.5\n", encoding="utf-8"
        )
    (root / "data.yaml").write_text(
        "train: images/train\nnames: [target]\n", encoding="utf-8"
    )

    writes = 0
    original = AnnotationRepository.upsert_many

    def counted(self, *args, **kwargs):
        nonlocal writes
        writes += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AnnotationRepository, "upsert_many", counted)
    report = app_module.v19_build_report_base({"id": "p2b", "file_name": "p2b.zip"})
    app_module._v50_begin_image_batch(project_id)
    try:
        assert app_module._v18_import_yolo(project_id, root, "default", report) is True
        app_module._v50_end_image_batch(save=True)
    except BaseException:
        app_module._v50_end_image_batch(save=False)
        raise

    assert report["imported_images"] == count
    assert report["boxes"] == count
    assert writes == count
    summary = app_module.material_store(project_id).summary()
    assert summary["total"] == count
    assert summary["annotated"] == count
    assert summary["boxes"] == count
