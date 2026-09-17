import hashlib
import json
from pathlib import Path

import yaml
from PIL import Image

from platform_core.training_tasks import materialize_portable_dataset, verify_portable_dataset


def _fixture(tmp_path: Path):
    project = tmp_path / "project"
    uploads = project / "uploads"
    uploads.mkdir(parents=True)
    rows = []
    ids = {"train": ["train-1", "train-2"], "validation": ["val-1"], "test": ["test-1"]}
    for index, image_id in enumerate(("train-1", "train-2", "val-1", "test-1")):
        path = uploads / f"{image_id}.jpg"
        Image.new("RGB", (64, 48), (30 + index, 40, 50)).save(path, format="JPEG")
        rows.append(
            {
                "id": image_id,
                "stored_name": path.name,
                "width": 64,
                "height": 48,
                "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "boxes": [{"label": "smoke", "x1": 8, "y1": 6, "x2": 32, "y2": 24}],
            }
        )
    snapshot = {
        "schema_version": 2,
        "snapshot_id": "blind-test-contract",
        "ids": ids,
        "label_schema": [{"code": "smoke", "class_id": 0}],
        "images": [
            {
                "image_id": row["id"],
                "role": next(role for role, values in ids.items() if row["id"] in values),
                "stored_name": row["stored_name"],
                "content_sha256": row["content_sha256"],
            }
            for row in rows
        ],
    }
    return project, rows, snapshot


def test_independent_test_ground_truth_is_hidden_from_training_runtime(tmp_path: Path):
    project, rows, snapshot = _fixture(tmp_path)
    bundle = materialize_portable_dataset(
        tmp_path / "task",
        snapshot,
        rows,
        lambda row: project / "uploads" / row["stored_name"],
    )

    data = yaml.safe_load((bundle / "dataset" / "data.yaml").read_text(encoding="utf-8"))
    assert data["train"] == "images/train"
    assert data["val"] == "images/validation"
    assert "test" not in data, "训练运行时 data.yaml 不得暴露独立试验集答案入口"

    assert (bundle / "dataset" / "images" / "test" / "test-1.jpg").is_file()
    assert not (bundle / "dataset" / "labels" / "test").exists(), "试验 GT 不得放在 Ultralytics 自动发现的 labels/test"

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    test_member = manifest["splits"]["test"][0]
    assert test_member["label_ref"].startswith("evaluation/ground_truth/test/")
    assert (bundle / test_member["label_ref"]).is_file()
    assert verify_portable_dataset(bundle / "manifest.json")["verified_files"] == 4
