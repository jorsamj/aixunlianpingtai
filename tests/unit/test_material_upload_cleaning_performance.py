from __future__ import annotations

from pathlib import Path

from PIL import Image

from platform_core.annotation_repository import AnnotationRepository
from platform_core.cleaning import MAX_ANALYSIS_PIXELS, image_metrics
from platform_core.material_repository import MaterialRepository
import platform_core.material_repository_batch  # noqa: F401 - installs runtime guards


def test_material_repository_repeated_constructor_skips_schema_reinitialization(tmp_path, monkeypatch):
    project = tmp_path / "project-material"
    first = MaterialRepository(project)
    assert first.path.is_file()

    def unexpected_connect(_self):
        raise AssertionError("same-project constructor must not rerun schema/migration initialization")

    monkeypatch.setattr(MaterialRepository, "_connect", unexpected_connect)
    repeated = MaterialRepository(project)
    assert repeated.path == first.path


def test_annotation_repository_repeated_constructor_skips_schema_reinitialization(tmp_path, monkeypatch):
    project = tmp_path / "project-annotation"
    first = AnnotationRepository(project)
    assert first.path.is_file()

    def unexpected_connect(_self):
        raise AssertionError("same-project annotation constructor must not rerun schema initialization")

    monkeypatch.setattr(AnnotationRepository, "_connect", unexpected_connect)
    repeated = AnnotationRepository(project)
    assert repeated.path == first.path


def test_material_repository_deleted_database_reinitializes(tmp_path):
    project = tmp_path / "project-recreate"
    first = MaterialRepository(project)
    database = first.path
    database.unlink()

    recreated = MaterialRepository(project)
    assert recreated.path.is_file()
    assert recreated.count() == 0


def test_cleaning_reuses_verified_material_hash(tmp_path, monkeypatch):
    path = tmp_path / "sample.png"
    Image.new("RGB", (400, 300), "gray").save(path)
    verified = "a" * 64

    import platform_core.cleaning as cleaning

    def unexpected_rehash(_path: Path):
        raise AssertionError("cleaning must reuse StorageManager.materialize verified SHA256")

    monkeypatch.setattr(cleaning, "file_sha256", unexpected_rehash)
    metrics = image_metrics(path, require_blur=False, content_sha256=verified)
    assert metrics["sha256"] == verified
    assert metrics["width"] == 400
    assert metrics["height"] == 300
    assert metrics["analysis_downsampled"] is False


def test_cleaning_has_bounded_large_image_analysis_contract():
    assert MAX_ANALYSIS_PIXELS == 16_000_000
