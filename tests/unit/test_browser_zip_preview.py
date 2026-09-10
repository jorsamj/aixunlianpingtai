from __future__ import annotations

import zipfile

import app


def test_v19_zip_scan_counts_all_images_but_bounds_preview(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_BROWSER_ZIP_PREVIEW_IMAGES", "100")
    archive = tmp_path / "large-yolo.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as stream:
        stream.writestr("dataset/data.yaml", "names: [cat]\ntrain: images\n")
        for index in range(5000):
            stream.writestr(f"dataset/images/{index:06d}.jpg", b"")
            stream.writestr(f"dataset/labels/{index:06d}.txt", b"")

    result = app.v19_scan_zip(archive)

    assert result["image_count"] == 5000
    assert result["file_count"] == 10001
    assert result["images_preview_count"] == 100
    assert len(result["images"]) == 100
    assert result["images_truncated"] is True
    assert "YOLO" in result["format_hints"]


def test_v19_zip_scan_preview_limit_is_capped(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_BROWSER_ZIP_PREVIEW_IMAGES", "999999")
    archive = tmp_path / "cap.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as stream:
        for index in range(2100):
            stream.writestr(f"images/{index:06d}.jpg", b"")

    result = app.v19_scan_zip(archive)
    assert result["image_count"] == 2100
    assert result["images_preview_count"] == 2000
    assert result["images_truncated"] is True
