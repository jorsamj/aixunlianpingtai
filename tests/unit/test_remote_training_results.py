from __future__ import annotations

import json
import zipfile
from pathlib import Path

from platform_core.remote_training_results import (
    RemoteTrainingResultError,
    create_training_result_archive,
    verify_training_result_archive,
)


def _job(project: Path):
    models = project / "models"
    models.mkdir(parents=True)
    best = models / "train_task_best.pt"
    last = models / "train_task_last.pt"
    best.write_bytes(b"best-model")
    last.write_bytes(b"last-model")
    return {
        "status": "done",
        "artifact_verified": True,
        "training_outcome": "completed",
        "completion_reason": "requested_epochs_completed",
        "completed_epochs": 3,
        "requested_epochs": 3,
        "runtime_stop_policy": "target_only",
        "quality_gate": {
            "runtime_stop_policy": "target_only",
            "stop_threshold": 0.9,
            "eval_interval": 10,
        },
        "best_path": str(best),
        "last_path": str(last),
        "verified_models": [str(best), str(last)],
        "training_report": {
            "metrics": {"metrics/mAP50(B)": 0.75},
            "test_result": {"status": "passed"},
        },
        "actual_device": "cuda:0",
        "requested_train_params": {"batch": 4, "workers": 0, "cache": False},
        "resolved_resources": {"resolved_batch": 11, "resolved_workers": 0, "resolved_cache": "ram"},
        "runtime_resources": {"runtime_batch": 11, "runtime_workers": 0, "runtime_cache": "ram"},
        "actual_train_params": {"batch": 11, "workers": 0, "cache": "ram"},
        "finished_at": "2026-09-18T02:00:00+00:00",
    }


def test_training_result_archive_round_trip_verifies_identity_and_models(tmp_path):
    project = tmp_path / "agent-project"
    job = _job(project)
    created = create_training_result_archive(
        project_dir=project,
        job=job,
        task_id="train-remote-one",
        execution_generation=4,
        snapshot_id="snapshot-one",
        destination=tmp_path / "result.zip",
    )

    assert created.size_bytes > 0
    assert created.member_count == 3
    assert {row["role"] for row in created.models} == {"best", "last"}

    verified = verify_training_result_archive(
        created.path,
        tmp_path / "verified",
        expected_sha256=created.sha256,
        expected_size_bytes=created.size_bytes,
        expected_task_id="train-remote-one",
        expected_execution_generation=4,
        expected_snapshot_id="snapshot-one",
    )
    assert verified.manifest["training_outcome"] == "completed"
    assert verified.manifest["completion"]["runtime_stop_policy"] == "target_only"
    assert verified.manifest["completion"]["quality_gate"]["runtime_stop_policy"] == "target_only"
    assert verified.manifest["completion"]["requested_train_params"]["batch"] == 4
    assert verified.manifest["completion"]["resolved_resources"]["resolved_batch"] == 11
    assert verified.manifest["completion"]["resolved_resources"]["resolved_workers"] == 0
    assert verified.manifest["completion"]["runtime_resources"]["runtime_batch"] == 11
    assert verified.manifest["completion"]["runtime_resources"]["runtime_workers"] == 0
    assert verified.manifest["completion"]["actual_train_params"]["batch"] == 11
    assert verified.manifest["training_report"]["metrics"]["metrics/mAP50(B)"] == 0.75
    assert {row["role"] for row in verified.models} == {"best", "last"}
    assert all((verified.root / row["ref"]).is_file() for row in verified.models)


def test_training_result_archive_rejects_model_outside_task_project(tmp_path):
    project = tmp_path / "agent-project"
    job = _job(project)
    outside = tmp_path / "outside.pt"
    outside.write_bytes(b"outside")
    job["verified_models"] = [str(outside)]
    job["best_path"] = str(outside)
    job["last_path"] = ""

    try:
        create_training_result_archive(
            project_dir=project,
            job=job,
            task_id="train-remote-one",
            execution_generation=1,
            snapshot_id="snapshot-one",
            destination=tmp_path / "result.zip",
        )
    except RemoteTrainingResultError as error:
        assert error.code == "TRAINING_RESULT_MODEL_OUTSIDE_WORKSPACE"
    else:
        raise AssertionError("outside-workspace model was accepted")


def test_training_result_archive_rejects_wrong_generation(tmp_path):
    project = tmp_path / "agent-project"
    created = create_training_result_archive(
        project_dir=project,
        job=_job(project),
        task_id="train-remote-one",
        execution_generation=2,
        snapshot_id="snapshot-one",
        destination=tmp_path / "result.zip",
    )
    try:
        verify_training_result_archive(
            created.path,
            tmp_path / "verified",
            expected_sha256=created.sha256,
            expected_size_bytes=created.size_bytes,
            expected_task_id="train-remote-one",
            expected_execution_generation=3,
            expected_snapshot_id="snapshot-one",
        )
    except RemoteTrainingResultError as error:
        assert error.code == "TRAINING_RESULT_IDENTITY_MISMATCH"
    else:
        raise AssertionError("stale training result generation was accepted")


def test_training_result_archive_rejects_tampered_model_with_valid_outer_zip_hash(tmp_path):
    project = tmp_path / "agent-project"
    created = create_training_result_archive(
        project_dir=project,
        job=_job(project),
        task_id="train-remote-one",
        execution_generation=2,
        snapshot_id="snapshot-one",
        destination=tmp_path / "result.zip",
    )

    with zipfile.ZipFile(created.path, "r") as reader:
        manifest = json.loads(reader.read("manifest.json"))
        entries = {name: reader.read(name) for name in reader.namelist()}
    model_ref = manifest["models"][0]["ref"]
    entries[model_ref] = b"tampered-model"
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_STORED) as writer:
        for name, data in entries.items():
            writer.writestr(name, data)

    import hashlib
    digest = hashlib.sha256(tampered.read_bytes()).hexdigest()
    try:
        verify_training_result_archive(
            tampered,
            tmp_path / "verified",
            expected_sha256=digest,
            expected_size_bytes=tampered.stat().st_size,
            expected_task_id="train-remote-one",
            expected_execution_generation=2,
            expected_snapshot_id="snapshot-one",
        )
    except RemoteTrainingResultError as error:
        assert error.code == "TRAINING_RESULT_MODEL_EVIDENCE_MISMATCH"
    else:
        raise AssertionError("tampered model was accepted")


def test_training_result_archive_rejects_undeclared_file(tmp_path):
    project = tmp_path / "agent-project"
    created = create_training_result_archive(
        project_dir=project,
        job=_job(project),
        task_id="train-remote-one",
        execution_generation=2,
        snapshot_id="snapshot-one",
        destination=tmp_path / "result.zip",
    )
    with zipfile.ZipFile(created.path, "r") as reader:
        entries = {name: reader.read(name) for name in reader.namelist()}
    extra = tmp_path / "extra.zip"
    with zipfile.ZipFile(extra, "w", compression=zipfile.ZIP_STORED) as writer:
        for name, data in entries.items():
            writer.writestr(name, data)
        writer.writestr("secret.txt", b"should-not-be-here")

    import hashlib
    digest = hashlib.sha256(extra.read_bytes()).hexdigest()
    try:
        verify_training_result_archive(
            extra,
            tmp_path / "verified",
            expected_sha256=digest,
            expected_size_bytes=extra.stat().st_size,
            expected_task_id="train-remote-one",
            expected_execution_generation=2,
            expected_snapshot_id="snapshot-one",
        )
    except RemoteTrainingResultError as error:
        assert error.code == "TRAINING_RESULT_UNDECLARED_MEMBER"
    else:
        raise AssertionError("undeclared result file was accepted")


def test_training_result_manifest_only_requires_confirmed_separate_model_protocol(tmp_path):
    project = tmp_path / "agent-project"
    created = create_training_result_archive(
        project_dir=project,
        job=_job(project),
        task_id="train-remote-one",
        execution_generation=5,
        snapshot_id="snapshot-one",
        destination=tmp_path / "result-manifest.zip",
        include_model_bytes=False,
    )

    with zipfile.ZipFile(created.path, "r") as archive:
        assert archive.namelist() == ["manifest.json"]
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["model_transport"] == "separate-object-v1"
        assert len(manifest["models"]) == 2

    try:
        verify_training_result_archive(
            created.path,
            tmp_path / "rejected",
            expected_sha256=created.sha256,
            expected_size_bytes=created.size_bytes,
            expected_task_id="train-remote-one",
            expected_execution_generation=5,
            expected_snapshot_id="snapshot-one",
        )
    except RemoteTrainingResultError as error:
        assert error.code == "TRAINING_RESULT_MODEL_TRANSPORT_INVALID"
    else:
        raise AssertionError("manifest-only training result was accepted without model-object protocol")

    verified = verify_training_result_archive(
        created.path,
        tmp_path / "verified-separate",
        expected_sha256=created.sha256,
        expected_size_bytes=created.size_bytes,
        expected_task_id="train-remote-one",
        expected_execution_generation=5,
        expected_snapshot_id="snapshot-one",
        allow_separate_model_objects=True,
    )
    assert verified.manifest["model_transport"] == "separate-object-v1"
    assert {item["role"] for item in verified.models} == {"best", "last"}
    assert not (verified.root / "models").exists()
