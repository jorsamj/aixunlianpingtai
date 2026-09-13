import io
import json
from pathlib import Path

from PIL import Image

from platform_core.annotation_repository import AnnotationRepository


def _write_png(path: Path, color: str = "white") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())


def _material_by_filename(app_module, project_id: str):
    return {
        str(row.get("filename") or ""): row
        for row in app_module.material_store(project_id).read().rows
    }


def _count_annotation_upserts(monkeypatch):
    calls = {"value": 0}
    original = AnnotationRepository.upsert_many

    def counted(self, *args, **kwargs):
        calls["value"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AnnotationRepository, "upsert_many", counted)
    return calls


def test_coco_structured_import_writes_final_truth_once_per_image(
    client, tmp_path, monkeypatch
):
    import app as app_module

    project = client.post(
        "/api/projects", json={"name": "p2c-coco", "labels": []}
    ).json()
    project_id = project["id"]
    app_module.ensure_default_datasets(project_id)

    root = tmp_path / "coco"
    images_dir = root / "images" / "train"
    annotations_dir = root / "annotations" / "train"
    annotations_dir.mkdir(parents=True, exist_ok=True)

    image_count = 6
    annotated_indexes = {0, 2, 4}
    images = []
    annotations = []
    for index in range(image_count):
        filename = f"image_{index:03d}.png"
        _write_png(images_dir / filename, "white" if index % 2 == 0 else "gray")
        images.append(
            {
                "id": index + 1,
                "file_name": f"images/train/{filename}",
                "width": 32,
                "height": 32,
            }
        )
        if index in annotated_indexes:
            annotations.append(
                {
                    "id": index + 1,
                    "image_id": index + 1,
                    "category_id": 7,
                    "bbox": [4, 5, 12, 14],
                    "area": 168,
                    "iscrowd": 0,
                }
            )

    (annotations_dir / "instances.json").write_text(
        json.dumps(
            {
                "images": images,
                "annotations": annotations,
                "categories": [{"id": 7, "name": "target"}],
            }
        ),
        encoding="utf-8",
    )

    upserts = _count_annotation_upserts(monkeypatch)
    report = app_module.v19_build_report_base(
        {"id": "p2c-coco", "file_name": "p2c-coco.zip"}
    )
    app_module._v50_begin_image_batch(project_id)
    committed = False
    try:
        assert app_module._v18_import_coco(
            project_id, root, "default", report
        ) is True
        app_module._v50_end_image_batch(save=True)
        committed = True
    finally:
        if not committed and app_module._v50_active_image_batch(project_id):
            app_module._v50_end_image_batch(save=False)

    assert report["detected_format"] == "COCO"
    assert report["imported_images"] == image_count
    assert report["boxes"] == len(annotated_indexes)
    assert report["annotated_images"] == len(annotated_indexes)
    assert upserts["value"] == image_count

    rows = _material_by_filename(app_module, project_id)
    repository = AnnotationRepository(app_module.project_dir(project_id))
    assert len(rows) == image_count
    for index in range(image_count):
        filename = f"image_{index:03d}.png"
        record = rows[filename]
        annotation = repository.get(record["id"])
        assert annotation["version"] == 1
        if index in annotated_indexes:
            assert annotation["annotation_state"] == "annotated"
            assert len(annotation["boxes"]) == 1
            box = annotation["boxes"][0]
            assert box["label"] == "target"
            assert box["x1"] == 4.0
            assert box["y1"] == 5.0
            assert box["x2"] == 16.0
            assert box["y2"] == 19.0
            assert record["box_count"] == 1
            assert record["annotated"] is True
        else:
            assert annotation["annotation_state"] == "confirmed_empty"
            assert annotation["boxes"] == []
            assert record["box_count"] == 0
            assert record["annotated"] is True


def _voc_xml(filename: str, annotated: bool) -> str:
    object_xml = ""
    if annotated:
        object_xml = """
  <object>
    <name>target</name>
    <bndbox>
      <xmin>3</xmin><ymin>4</ymin><xmax>20</xmax><ymax>22</ymax>
    </bndbox>
  </object>"""
    return f"""<annotation>
  <filename>{filename}</filename>
  <size><width>32</width><height>32</height><depth>3</depth></size>{object_xml}
</annotation>
"""


def test_voc_structured_import_writes_final_truth_once_per_image(
    client, tmp_path, monkeypatch
):
    import app as app_module

    project = client.post(
        "/api/projects", json={"name": "p2c-voc", "labels": []}
    ).json()
    project_id = project["id"]
    app_module.ensure_default_datasets(project_id)

    root = tmp_path / "voc"
    images_dir = root / "JPEGImages"
    annotations_dir = root / "Annotations" / "train"
    annotations_dir.mkdir(parents=True, exist_ok=True)

    image_count = 6
    annotated_indexes = {1, 3, 5}
    for index in range(image_count):
        filename = f"image_{index:03d}.png"
        _write_png(images_dir / filename, "blue" if index % 2 == 0 else "green")
        (annotations_dir / f"image_{index:03d}.xml").write_text(
            _voc_xml(filename, index in annotated_indexes), encoding="utf-8"
        )

    upserts = _count_annotation_upserts(monkeypatch)
    report = app_module.v19_build_report_base(
        {"id": "p2c-voc", "file_name": "p2c-voc.zip"}
    )
    app_module._v50_begin_image_batch(project_id)
    committed = False
    try:
        assert app_module._v18_import_voc(
            project_id, root, "default", report
        ) is True
        app_module._v50_end_image_batch(save=True)
        committed = True
    finally:
        if not committed and app_module._v50_active_image_batch(project_id):
            app_module._v50_end_image_batch(save=False)

    assert report["detected_format"] == "Pascal VOC"
    assert report["imported_images"] == image_count
    assert report["boxes"] == len(annotated_indexes)
    assert report["annotated_images"] == len(annotated_indexes)
    assert upserts["value"] == image_count

    rows = _material_by_filename(app_module, project_id)
    repository = AnnotationRepository(app_module.project_dir(project_id))
    assert len(rows) == image_count
    for index in range(image_count):
        filename = f"image_{index:03d}.png"
        record = rows[filename]
        annotation = repository.get(record["id"])
        assert annotation["version"] == 1
        if index in annotated_indexes:
            assert annotation["annotation_state"] == "annotated"
            assert len(annotation["boxes"]) == 1
            box = annotation["boxes"][0]
            assert box["label"] == "target"
            assert box["x1"] == 3.0
            assert box["y1"] == 4.0
            assert box["x2"] == 20.0
            assert box["y2"] == 22.0
            assert record["box_count"] == 1
            assert record["annotated"] is True
        else:
            assert annotation["annotation_state"] == "confirmed_empty"
            assert annotation["boxes"] == []
            assert record["box_count"] == 0
            assert record["annotated"] is True
