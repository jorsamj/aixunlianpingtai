"""Val-only error diagnostics must not privilege alphabetically first files."""
from pathlib import Path

from train_worker import _select_validation_error_images


def test_validation_error_sampling_covers_rare_classes_and_empty_labels(tmp_path: Path):
    images, labels = tmp_path / "images", tmp_path / "labels"
    images.mkdir()
    labels.mkdir()
    for number in range(40):
        (images / f"a_{number:03d}.jpg").write_bytes(b"image")
        (labels / f"a_{number:03d}.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    (images / "z_rare.jpg").write_bytes(b"image")
    (labels / "z_rare.txt").write_text("2 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    (images / "zz_empty.jpg").write_bytes(b"image")

    selected, evidence = _select_validation_error_images(images, labels, 8)
    assert len(selected) == 8
    assert {"z_rare.jpg", "zz_empty.jpg"}.issubset({file.name for file in selected})
    assert evidence["population_images"] == 42
    assert evidence["sampled_images"] == 8
    assert evidence["split"] == "val"
    assert evidence["strata_population"]["2"] == 1
    assert evidence["strata_population"]["__empty_label__"] == 1
    assert [file.name for file in selected] == [file.name for file in _select_validation_error_images(images, labels, 8)[0]]
    assert any(file.name.startswith("a_") and int(file.stem[2:]) >= 8 for file in selected)


def test_validation_error_sampling_no_overflow_on_multilabel_images(tmp_path: Path):
    images, labels = tmp_path / "images", tmp_path / "labels"
    images.mkdir()
    labels.mkdir()
    for number in range(20):
        (images / f"frame_{number}.png").write_bytes(b"image")
        (labels / f"frame_{number}.txt").write_text("0 0.5 0.5 0.2 0.2\n1 0.4 0.4 0.1 0.1\n", encoding="utf-8")
    selected, evidence = _select_validation_error_images(images, labels, 7)
    assert len(selected) == len({file.name for file in selected}) == 7
    assert evidence["strata_population"] == {"0": 20, "1": 20}
