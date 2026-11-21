from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

from PIL import Image


def _image(color):
    raw = BytesIO()
    Image.new("RGB", (64, 48), color).save(raw, "JPEG")
    return raw.getvalue()


def _zip_with_opaque_class_names():
    raw = BytesIO()
    red, blue = _image("red"), _image("blue")
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("dataset/train/images/first.jpg", red)
        archive.writestr("dataset/train/images/second.jpg", blue)
        archive.writestr("dataset/train/labels/first.txt", "0 0.5 0.5 0.4 0.3\n")
        archive.writestr("dataset/train/labels/second.txt", "1 0.2 0.3 0.2 0.25\n")
    return raw.getvalue(), red, blue


def test_zip_label_mapping_can_preview_each_opaque_class_before_material_commit(client, seeded_project):
    import app as platform

    project_id, _seed = seeded_project
    archive, first_image, second_image = _zip_with_opaque_class_names()
    response = client.post(
        f"/api/v19/projects/{project_id}/datasets/default/import/jobs",
        files={"file": ("opaque-labels.zip", archive, "application/zip")},
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "selecting"
    assert {row["name"] for row in job["external_classes"]} == {"class_0", "class_1"}
    assert "class_samples" not in job  # bulk image refs never enter polling JSON

    for class_id, expected, expected_x in [
        ("0", first_image, 50.0),
        ("1", second_image, 20.0),
    ]:
        base = f"/api/v19/projects/{project_id}/import/jobs/{job['id']}/classes/{class_id}"
        result = client.get(base + "/samples")
        assert result.status_code == 200, result.text
        samples = result.json()["samples"]
        assert len(samples) == 1
        assert round(samples[0]["bbox"]["cx"] * 100) == expected_x
        assert samples[0]["preview_url"].startswith(base + "/sample-content?")
        preview = client.get(samples[0]["preview_url"])
        assert preview.status_code == 200
        assert preview.headers["content-type"].startswith("image/jpeg")
        assert preview.content == expected

    assert client.get(
        f"/api/v19/projects/{project_id}/import/jobs/{job['id']}/classes/77/samples"
    ).status_code == 404
    assert not (platform.v19_job_dir(project_id, job["id"]) / "extracted").exists()


def test_zip_pre_import_samples_do_not_guess_when_split_stems_are_ambiguous():
    from platform_core.zip_label_samples import build_zip_class_samples

    raw = BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("train/images/repeat.jpg", b"one")
        archive.writestr("val/images/repeat.jpg", b"two")
        archive.writestr("labels/repeat.txt", "0 0.5 0.5 0.3 0.3\n")
    raw.seek(0)
    with zipfile.ZipFile(raw) as archive:
        evidence = build_zip_class_samples(
            archive,
            [{"path": "train/images/repeat.jpg"}, {"path": "val/images/repeat.jpg"}],
            [{"class_id": "0", "name": "class_0"}],
            "YOLO",
        )
    assert evidence == {}


def test_zip_pre_import_samples_are_bounded_to_eight_and_do_not_choose_labels():
    from platform_core.zip_label_samples import build_zip_class_samples

    raw = BytesIO()
    images = []
    with zipfile.ZipFile(raw, "w") as archive:
        for index in range(25):
            path = f"dataset/images/img{index}.jpg"
            images.append({"path": path})
            archive.writestr(path, b"small-image")
            archive.writestr(
                f"dataset/labels/img{index}.txt", "0 0.5 0.5 0.3 0.3\n"
            )
    raw.seek(0)
    with zipfile.ZipFile(raw) as archive:
        evidence = build_zip_class_samples(
            archive, images, [{"class_id": "0", "name": "class_0"}],
            "YOLO", limit=8,
        )
    assert len(evidence["0"]) == 8
    assert all("target_label" not in row and "mapping" not in row for row in evidence["0"])



def test_same_image_preserves_multiple_original_boxes_for_its_class():
    from platform_core.zip_label_samples import build_zip_class_samples

    raw = BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("train/images/people.jpg", _image("white"))
        archive.writestr("train/labels/people.txt",
                         "0 0.2 0.2 0.2 0.2\n0 0.8 0.8 0.1 0.1\n1 0.5 0.5 0.3 0.3\n")
    raw.seek(0)
    with zipfile.ZipFile(raw) as archive:
        samples = build_zip_class_samples(
            archive, [{"path": "train/images/people.jpg"}],
            [{"class_id": "0"}, {"class_id": "1"}], "YOLO")
    assert len(samples["0"]) == 1
    assert [round(box["cx"], 2) for box in samples["0"][0]["bboxes"]] == [0.2, 0.8]
    assert len(samples["1"][0]["bboxes"]) == 1
    assert samples["0"][0]["image_path"] == samples["1"][0]["image_path"]


def test_coco_and_voc_source_boxes_use_original_class_ids_and_dimensions():
    import json
    from platform_core.zip_label_samples import build_zip_class_samples

    raw = BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("data/images/coco.jpg", _image("green"))
        archive.writestr("data/images/voc.jpg", _image("yellow"))
        archive.writestr("data/annotations.json", json.dumps({
            "images": [{"id": 41, "file_name": "coco.jpg", "width": 64, "height": 48}],
            "annotations": [{"image_id": 41, "category_id": 7, "bbox": [8, 12, 16, 24]},
                            {"image_id": 41, "category_id": 7, "bbox": [32, 12, 8, 12]}]
        }))
        archive.writestr("data/Annotations/voc.xml", """<annotation>
            <filename>voc.jpg</filename><size><width>64</width><height>48</height></size>
            <object><name>helmet</name><bndbox>
            <xmin>8</xmin><ymin>12</ymin><xmax>24</xmax><ymax>36</ymax>
            </bndbox></object></annotation>""")
    raw.seek(0)
    images = [{"path": "data/images/coco.jpg"}, {"path": "data/images/voc.jpg"}]
    with zipfile.ZipFile(raw) as archive:
        coco = build_zip_class_samples(archive, images, [{"class_id": "7"}], "COCO")
        voc = build_zip_class_samples(
            archive, images, [{"class_id": "helmet"}], "Pascal VOC",
            normalize_name=lambda value: value.strip().lower())
    assert coco["7"][0]["filename"] == "coco.jpg"
    assert len(coco["7"][0]["bboxes"]) == 2
    assert coco["7"][0]["bbox"] == {"cx": 0.25, "cy": 0.5, "w": 0.25, "h": 0.5}
    assert voc["helmet"][0]["filename"] == "voc.jpg"
    assert voc["helmet"][0]["bbox"] == coco["7"][0]["bbox"]


def test_large_image_inventory_uses_unambiguous_path_pairing():
    from platform_core.zip_label_samples import build_zip_class_samples

    paths = [{"path": f"dataset/train/images/other_{index}.jpg"} for index in range(20_000)]
    paths.extend([{"path": "dataset/train/images/same.jpg"},
                  {"path": "dataset/val/images/same.jpg"}])
    raw = BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("dataset/train/labels/same.txt", "0 0.4 0.5 0.2 0.3\n")
        archive.writestr("dataset/val/labels/same.txt", "1 0.6 0.5 0.2 0.3\n")
    raw.seek(0)
    with zipfile.ZipFile(raw) as archive:
        samples = build_zip_class_samples(archive, paths,
                     [{"class_id": "0"}, {"class_id": "1"}], "YOLO")
    assert samples["0"][0]["image_path"] == "dataset/train/images/same.jpg"
    assert samples["1"][0]["image_path"] == "dataset/val/images/same.jpg"
