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
        requested_params={
            "epochs": 30, "batch": 4, "resource_strategy": "auto",
            "resource_profile": "performance", "gpu_policy": "exclusive",
            "precision": "bf16", "time": 2.5, "unknown": "drop",
        },
        actual_params={
            "epochs": 28, "batch": 4, "imgsz": 640,
            "resource_strategy": "auto", "resource_profile": "performance",
            "gpu_policy": "exclusive", "precision": "bf16", "time": 2.5,
        },
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
    assert lineage["parameters"]["requested"] == {
        "batch": 4,
        "epochs": 30,
        "gpu_policy": "exclusive",
        "precision": "bf16",
        "resource_profile": "performance",
        "resource_strategy": "auto",
        "time": 2.5,
    }
    assert lineage["parameters"]["actual"]["epochs"] == 28
    assert lineage["parameters"]["actual"]["resource_profile"] == "performance"
    assert lineage["parameters"]["actual"]["precision"] == "bf16"
    assert lineage["parameters"]["actual"]["time"] == 2.5


def test_training_lineage_rejects_invalid_dataset_revision():
    with pytest.raises(ValueError, match="dataset_revision_id"):
        build_training_lineage(task_id="train-2", dataset_revision_id="not-a-sha")


def test_training_lineage_carries_public_confirmed_iteration_action():
    lineage = build_training_lineage(
        task_id="train-action-lineage",
        dataset_revision_id="a" * 64,
        iteration_action={
            "action_id": "b" * 64,
            "action": "continue_training",
            "source": {
                "decision_id": "c" * 64,
                "evaluation_id": "d" * 64,
                "version_id": "version-prev",
                "dataset_revision_id": "a" * 64,
                "snapshot_id": "snapshot-prev",
                "private_note": "must-not-leak",
            },
            "data_draft": {"problem_samples": ["private.jpg"]},
        },
    )
    assert lineage["iteration_action"] == {
        "action": "continue_training",
        "action_id": "b" * 64,
        "decision_id": "c" * 64,
        "evaluation_id": "d" * 64,
        "dataset_revision_id": "a" * 64,
        "version_id": "version-prev",
        "snapshot_id": "snapshot-prev",
    }
    assert "private" not in str(lineage)


def test_training_lineage_carries_bounded_supplement_feedback_provenance():
    provenance = {
        "schema_version": 1, "candidate_set_id": "a" * 64,
        "adoption_id": "b" * 64, "action_id": "c" * 64,
        "algorithm_id": "alg-prev", "version_id": "ver-prev",
        "source_candidate_count": 2, "adopted_candidate_count": 1,
        "adopted_material_count": 1, "adopted_feedback_ids": ["feedback-1"],
        "adopted_material_ids": ["material-1"], "automatic_execution": False,
        "adopted_candidates": [{
            "feedback_id": "feedback-1", "feedback_type": "needs_correction",
            "material_id": "material-1", "candidate_digest": "d" * 64,
            "annotation_hash": "e" * 64, "annotation_state": "annotated",
            "model_sha256": "f" * 64, "input_sha256": "1" * 64,
        }],
        "private_note": "do-not-leak",
    }
    lineage = build_training_lineage(
        task_id="train-feedback",
        dataset_revision_id="2" * 64,
        supplement_provenance=provenance,
    )
    assert lineage["supplement_provenance"]["candidate_set_id"] == "a" * 64
    assert lineage["supplement_provenance"]["adopted_feedback_ids"] == ["feedback-1"]
    assert lineage["supplement_provenance"]["automatic_execution"] is False
    assert "private_note" not in str(lineage)
