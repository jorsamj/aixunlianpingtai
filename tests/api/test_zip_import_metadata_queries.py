import io
import json
import subprocess
import sys

from PIL import Image
import pytest

from platform_core.material_repository import MaterialRepository
from tests.api.test_material_selection_atomicity import create_project_with_dataset


def source_files(tmp_path, count=3, format_name="yolo"):
    root = tmp_path / "source"
    (root / "images").mkdir(parents=True)
    (root / "labels").mkdir()
    raw = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(raw, format="PNG")
    for i in range(count):
        (root / "images" / f"image-{i}.png").write_bytes(raw.getvalue())
        if format_name == "yolo":
            (root / "labels" / f"image-{i}.txt").write_text("0 0.5 0.5 0.5 0.5\n", encoding="utf-8")
        elif format_name == "voc":
            (root / "labels" / f"image-{i}.xml").write_text(
                f"<annotation><filename>image-{i}.png</filename><size><width>32</width><height>32</height></size>"
                "<object><name>target</name><bndbox><xmin>8</xmin><ymin>8</ymin><xmax>24</xmax><ymax>24</ymax>"
                "</bndbox></object></annotation>", encoding="utf-8")
    if format_name == "coco":
        (root / "annotations.json").write_text(json.dumps({
            "images": [{"id": i, "file_name": f"image-{i}.png", "width": 32, "height": 32} for i in range(count)],
            "annotations": [{"id": i, "image_id": i, "category_id": 1, "bbox": [8, 8, 16, 16]} for i in range(count)],
            "categories": [{"id": 1, "name": "target"}],
        }), encoding="utf-8")
    (root / "data.yaml").write_text("names: [target]\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("format_name", ["yolo", "coco", "voc"])
def test_structured_import_never_reads_full_material_index_for_empty_delete_claims(client, tmp_path, monkeypatch, format_name):
    import app as api
    pid, dataset = create_project_with_dataset(client)
    repository = api.material_store(pid)
    repository.upsert_many({"id": str(i), "filename": str(i) + ".png", "dataset_id": "default"} for i in range(100))
    root = source_files(tmp_path, format_name=format_name)
    def forbidden(*args, **kwargs):
        raise AssertionError("normal per-image admission must not read the full material index")
    monkeypatch.setattr(MaterialRepository, "read", forbidden)
    monkeypatch.setattr(MaterialRepository, "mutate", forbidden)
    report = api.v19_build_report_base({"id": "query-contract", "file_name": "isolated.zip"})
    api._v50_begin_image_batch(pid)
    try:
        assert getattr(api, "_v18_import_" + format_name)(pid, root, dataset, report)
        api._v50_end_image_batch(save=True)
    finally:
        if api._v50_active_image_batch(pid):
            api._v50_end_image_batch(save=False)
    assert report["imported_images"] == report["boxes"] == 3
    assert repository.count() == 103
    for image_id in report["imported_image_ids"]:
        assert repository.get(image_id)["dataset_id"] == dataset
        annotation = api.AnnotationRepository(api.project_dir(pid)).get(image_id)
        assert annotation["version"] == 1
        assert annotation["boxes"][0]["label"] == "target"


@pytest.mark.parametrize("delete_after", [1, 3])
def test_concurrent_dataset_removal_blocks_image_or_final_commit_and_rolls_back(client, tmp_path, delete_after):
    import app as api
    pid, dataset = create_project_with_dataset(client)
    root = source_files(tmp_path)
    deletion = """import sys
import app as api
pid, dataset = sys.argv[1:]
with api._v50_dataset_locks(pid, [dataset]):
    rows = api._v50_read_datasets_strict(pid)
    api.write_json(api.datasets_file(pid), [row for row in rows if row['id'] != dataset])
"""
    def progress(done, total, message):
        if done == delete_after:
            subprocess.run([sys.executable, "-c", deletion, pid, dataset],
                           check=True, capture_output=True, timeout=30)
    report = api.v19_build_report_base({"id": "delete-race", "file_name": "isolated.zip"})
    api._v50_begin_image_batch(pid)
    try:
        with pytest.raises(api.HTTPException) as rejected:
            api._v18_import_yolo(pid, root, dataset, report, progress_cb=progress)
            api._v50_end_image_batch(save=True)
        assert rejected.value.status_code == 409
    finally:
        if api._v50_active_image_batch(pid):
            api._v50_end_image_batch(save=False)
    assert api.material_store(pid).count() == 0
    annotations = api.AnnotationRepository(api.project_dir(pid))
    assert all(not annotations.exists(image_id) for image_id in report.get("imported_image_ids", []))
