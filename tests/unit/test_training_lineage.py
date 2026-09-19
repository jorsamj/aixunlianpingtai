import pytest

from platform_core.training_lineage import build_training_lineage


def test_training_lineage_is_public_safe_and_derives_agent_node():
    lineage = build_training_lineage(
        task_id="train-1",
        snapshot_id="snapshot-1",
        dataset_revision_id="a" * 64,
        framework="Ultralytics",
        base_version_id="v0",
        base_version_name="20260918090000",
        base_model=r"C:\\models\\best.pt",
        base_selection_reason="current_verified_version",
        execution={
            "mode": "agent",
            "worker_id": "agent:node-7",
            "execution_generation": 4,
            "requested_device": "cuda:0",
            "assigned_device": "cuda:0",
            "secret_url": "https://forbidden.example/signed",
        },
        requested_params={"epochs": 30, "batch": 4, "unknown": "drop"},
        actual_params={"epochs": 28, "batch": 4, "imgsz": 640},
        artifacts=[{
            "role": "best",
            "artifact_id": "art-1",
            "file_name": "best.pt",
            "sha256": "b" * 64,
            "size_bytes": 1234,
            "storage_source_id": "models",
            "object_key": "models/a/best.pt",
            "signed_url": "https://forbidden.example/object",
        }],
        training_status="SUCCEEDED",
    )
    assert lineage["schema_version"] == 1
    assert lineage["base"]["model"] == "best.pt"
    assert lineage["execution"]["node_id"] == "node-7"
    assert "secret_url" not in str(lineage)
    assert "signed_url" not in str(lineage)
    assert lineage["parameters"]["requested"] == {"batch": 4, "epochs": 30}
    assert lineage["parameters"]["actual"]["epochs"] == 28


def test_training_lineage_rejects_invalid_dataset_revision():
    with pytest.raises(ValueError, match="dataset_revision_id"):
        build_training_lineage(task_id="train-2", dataset_revision_id="not-a-sha")
