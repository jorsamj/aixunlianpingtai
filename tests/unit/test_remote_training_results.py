from __future__ import annotations

import json
import zipfile
import hashlib
import copy
import io
import pytest
from PIL import Image
from pathlib import Path

import platform_core.remote_training_results as remote_training_results_module
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
        "requested_precision": "fp16",
        "resolved_precision": "fp16",
        "runtime_precision": "fp32",
        "amp_check_method": "cuda_numeric",
        "amp_check_result": "failed",
        "precision_fallback_reason": "CUDA_FP16_PROBE_FAILED",
        "amp_preflight": {"enabled": False, "method": "cuda_numeric", "result": "failed", "reason": "CUDA_FP16_PROBE_FAILED"},
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
    assert verified.manifest["completion"]["requested_precision"] == "fp16"
    assert verified.manifest["completion"]["resolved_precision"] == "fp16"
    assert verified.manifest["completion"]["runtime_precision"] == "fp32"
    assert verified.manifest["completion"]["precision_fallback_reason"] == "CUDA_FP16_PROBE_FAILED"
    assert verified.manifest["completion"]["amp_preflight"]["enabled"] is False
    assert verified.manifest["training_report"]["metrics"]["metrics/mAP50(B)"] == 0.75
    assert {row["role"] for row in verified.models} == {"best", "last"}
    assert all((verified.root / row["ref"]).is_file() for row in verified.models)


def test_training_result_archive_preserves_frozen_dataset_evidence(tmp_path):
    project = tmp_path / "agent-project"
    job = _job(project)
    dataset = {"schema_version": 3, "snapshot_id": "snapshot-one",
               "dataset_revision_id": "a" * 64, "splits": {"test": []}}
    created = create_training_result_archive(
        project_dir=project, job=job, task_id="train-one",
        execution_generation=1, snapshot_id="snapshot-one",
        destination=tmp_path / "result.zip", dataset_manifest=dataset,
        input_freeze_id="b" * 64,
    )
    verified = verify_training_result_archive(
        created.path, tmp_path / "verified", expected_sha256=created.sha256,
        expected_size_bytes=created.size_bytes, expected_task_id="train-one",
        expected_execution_generation=1, expected_snapshot_id="snapshot-one",
    )
    assert verified.manifest["dataset_manifest"] == dataset
    assert verified.manifest["input_freeze_id"] == "b" * 64
    assert verified.manifest["dataset_revision_id"] == "a" * 64
    assert verified.manifest["diagnostic_images"] == []
    assert created.member_count == 3


def _dataset_evidence_fixture():
    snapshot = {"snapshot_id": "s", "dataset_revision_id": "a" * 64,
                "ids": {key: [key] for key in ("train", "validation", "test")},
                "label_schema": [{"code": "fire", "class_id": 0}]}
    rows = [{"id": key, "stored_name": key + ".jpg", "size_bytes": 12,
             "width": 10, "height": 10, "boxes": [],
             "content_sha256": "b" * 64} for key in snapshot["ids"]]
    manifest = {"schema_version": 3, "snapshot_id": "s", "dataset_revision_id": "a" * 64,
                "training_input_policy": "ultralytics_jpeg_repair_v1",
                "splits": {key: [{"image_id": key, "source_content_sha256": "b" * 64,
                    "image_ref": f"dataset/images/{key}/{key}.jpg",
                    "label_ref": (f"evaluation/ground_truth/test/{key}.txt" if key == "test"
                                  else f"dataset/labels/{key}/{key}.txt"),
                    "content_sha256": "b" * 64, "size_bytes": 12, "source_size_bytes": 12,
                    "label_sha256": hashlib.sha256(b"").hexdigest(), "normalized": False,
                    "training_input_policy": "ultralytics_jpeg_repair_v1"}]
                    for key in snapshot["ids"]}}
    return snapshot, rows, manifest


@pytest.mark.parametrize("role", ["train", "validation", "test"])
def test_dataset_evidence_validates_every_split_label_hash(role):
    from platform_core.remote_training_results import verify_dataset_manifest_evidence
    snapshot, rows, manifest = _dataset_evidence_fixture()
    assert verify_dataset_manifest_evidence(manifest, snapshot, rows) == manifest
    forged = copy.deepcopy(manifest)
    forged["splits"][role][0]["label_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="label"):
        verify_dataset_manifest_evidence(forged, snapshot, rows)
    forged = copy.deepcopy(manifest)
    forged["splits"][role][0]["source_content_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="source hash"):
        verify_dataset_manifest_evidence(forged, snapshot, rows)
    forged = copy.deepcopy(manifest)
    forged["splits"][role].append(copy.deepcopy(forged["splits"][role][0]))
    with pytest.raises(ValueError, match="cohort"):
        verify_dataset_manifest_evidence(forged, snapshot, rows)


@pytest.mark.parametrize("role", ["train", "validation", "test"])
@pytest.mark.parametrize("field,value", [
    ("source_size_bytes", 13),
    ("image_ref", "dataset/images/train/other.jpg"),
    ("label_ref", "dataset/labels/test/test.txt"),
])
def test_dataset_evidence_rejects_wrong_source_size_or_noncanonical_role_path(role, field, value):
    from platform_core.remote_training_results import verify_dataset_manifest_evidence
    snapshot, rows, manifest = _dataset_evidence_fixture()
    manifest["splits"][role][0][field] = value
    with pytest.raises(ValueError, match="source size|canonical"):
        verify_dataset_manifest_evidence(manifest, snapshot, rows)


def _diagnostic_archive(tmp_path, *, sample=None, member_ref="dataset/images/test/test-one.jpg", corrupt=False):
    project = tmp_path / "agent-project"
    job = _job(project)
    pixels = io.BytesIO()
    Image.new("RGB", (12, 8), (40, 90, 120)).save(pixels, format="JPEG")
    data = pixels.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    job["training_report"]["test_result"]["error_samples"] = [sample or {
        "image": "test-one.jpg", "image_id": "test-one", "image_content_sha256": digest,
    }]
    root = tmp_path / "dataset"
    path = root / "dataset/images/test/test-one.jpg"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"corrupted" if corrupt else data)
    manifest = {"schema_version": 3, "snapshot_id": "snapshot-one", "dataset_revision_id": "a" * 64,
                "splits": {"test": [{"image_id": "test-one", "image_ref": member_ref,
                    "content_sha256": digest, "size_bytes": len(data)}]}}
    created = create_training_result_archive(
        project_dir=project, job=job, task_id="train-one", execution_generation=1,
        snapshot_id="snapshot-one", destination=tmp_path / "result.zip",
        dataset_manifest=manifest, dataset_root=root, input_freeze_id="b" * 64,
    )
    return created, data


def test_training_result_retains_only_actual_error_sample_image(tmp_path):
    created, data = _diagnostic_archive(tmp_path)
    verified = verify_training_result_archive(
        created.path, tmp_path / "verified", expected_sha256=created.sha256,
        expected_size_bytes=created.size_bytes, expected_task_id="train-one",
        expected_execution_generation=1, expected_snapshot_id="snapshot-one",
    )
    images = verified.manifest["diagnostic_images"]
    assert len(images) == 1
    assert images[0]["ref"] == "evidence/bundle/dataset/images/test/test-one.jpg"
    assert (verified.root / images[0]["ref"]).read_bytes() == data
    assert created.member_count == 4


def test_training_result_extraction_rejects_tampered_diagnostic_bytes(tmp_path):
    created, _data = _diagnostic_archive(tmp_path)
    altered = tmp_path / "altered.zip"
    with zipfile.ZipFile(created.path) as source, zipfile.ZipFile(altered, "w") as target:
        for name in source.namelist():
            target.writestr(name, b"tampered" if name.startswith("evidence/") else source.read(name))
    with pytest.raises(RemoteTrainingResultError, match="diagnostic image bytes"):
        verify_training_result_archive(
            altered, tmp_path / "verified", expected_sha256=hashlib.sha256(altered.read_bytes()).hexdigest(),
            expected_size_bytes=altered.stat().st_size, expected_task_id="train-one",
            expected_execution_generation=1, expected_snapshot_id="snapshot-one",
        )


@pytest.mark.parametrize("kwargs", [
    {"corrupt": True},
    {"member_ref": "../outside.jpg"},
    {"member_ref": "dataset/images/train/test-one.jpg"},
    {"sample": {"image": "other.jpg", "image_id": "train-one"}},
])
def test_training_result_rejects_unbound_diagnostic_image(tmp_path, kwargs):
    with pytest.raises(RemoteTrainingResultError):
        _diagnostic_archive(tmp_path, **kwargs)


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

def test_training_result_verifier_hashes_embedded_models_during_extract(tmp_path, monkeypatch):
    project = tmp_path / "agent-project"
    created = create_training_result_archive(
        project_dir=project,
        job=_job(project),
        task_id="train-remote-one",
        execution_generation=7,
        snapshot_id="snapshot-one",
        destination=tmp_path / "result.zip",
    )

    original_sha256 = remote_training_results_module._sha256

    def forbid_model_rehash(path):
        value = Path(path)
        if value.suffix.lower() == ".pt":
            raise AssertionError("embedded model must use extraction-pass SHA256 evidence")
        return original_sha256(value)

    monkeypatch.setattr(
        remote_training_results_module,
        "_sha256",
        forbid_model_rehash,
    )
    verified = verify_training_result_archive(
        created.path,
        tmp_path / "verified",
        expected_sha256=created.sha256,
        expected_size_bytes=created.size_bytes,
        expected_task_id="train-remote-one",
        expected_execution_generation=7,
        expected_snapshot_id="snapshot-one",
    )

    assert {item["role"] for item in verified.models} == {"best", "last"}

