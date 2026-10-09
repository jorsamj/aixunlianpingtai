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
