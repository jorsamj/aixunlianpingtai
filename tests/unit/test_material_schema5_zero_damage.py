"""Whole-fixture upgrade checks over genuine historical DDL, never production."""
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from PIL import Image
import pytest

from platform_core.annotation_repository import AnnotationRepository
import platform_core.material_repository as materials_module
from platform_core.material_repository import MaterialRepository, existing_sqlite_reader
from platform_core.model_artifacts import ModelArtifactRepository
from platform_core.snapshots import build_snapshot, persist_snapshot
from platform_core.task_runtime.artifacts import ArtifactStore
from platform_core.task_runtime.models import TaskKind, TaskRecord, TaskStatus
from platform_core.task_runtime.repository import TaskRepository


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def business_state(root):
    databases, files = {}, {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.endswith(("-wal", "-shm", ".lock")):
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix != ".sqlite3":
            files[relative] = sha(path)
            continue
        with closing(existing_sqlite_reader(path)) as db:
            tables = {}
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                name = row[0]
                quoted = '"' + name.replace('"', '""') + '"'
                tables[name] = sorted(json.dumps(tuple(value), ensure_ascii=False) for value in db.execute("SELECT * FROM " + quoted))
            databases[relative] = tables
    return {"databases": databases, "files": files}


def clone_fixture(source, target):
    assert not target.exists()
    target.mkdir()
    for path in source.rglob("*"):
        if not path.is_file() or path.name.endswith(("-wal", "-shm", ".lock")):
            continue
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".sqlite3":
            with closing(existing_sqlite_reader(path)) as reader, closing(sqlite3.connect(destination)) as writer:
                reader.backup(writer)
        else:
            shutil.copy2(path, destination)


def make_historical_fixture(root):
    project = root / "projects/p"
    (project / "uploads").mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({"id": "p", "labels": ["target"]}), encoding="utf-8")
    annotations = AnnotationRepository(project)
    rows = []
    for index, color in enumerate(("red", "blue", "green")):
        image_id = f"historical-{index}"
        path = project / "uploads" / (image_id + ".png")
        Image.new("RGB", (16, 12), color).save(path)
        box = {"id": f"box-{index}", "class_id": 0, "label": "target", "x1": 1, "y1": 2, "x2": 8, "y2": 9}
        gt = annotations.upsert(image_id, [box], annotation_scope=["target"],
                                source_content_sha256=sha(path), project_material=False)
        row = {"id": image_id, "filename": path.name, "stored_name": path.name,
               "object_key": "uploads/" + path.name, "content_sha256": sha(path),
               "size_bytes": path.stat().st_size, "width": 16, "height": 12,
               "dataset_id": "default" if index < 2 else "historical-other",
               "processing_status": "processed", "annotation_state": "annotated",
               "annotation_scope": ["target"], "annotation_version": gt["version"],
               "annotation_hash": gt["content_digest"], "box_count": 1, "labels": ["target"],
               "annotation_preview": gt["boxes"], "created_at": "2020-01-01T00:00:00"}
        rows.append(row)
    rows[0].pop("dataset_id")  # A normal historical default image remains a training input.
    snapshot = build_snapshot([{**row, "boxes": annotations.get(row["id"])["boxes"]} for row in rows],
                              [rows[0]["id"]], [rows[2]["id"]], [{"code": "target"}], seed=42)
    persist_snapshot(project / "snapshots", snapshot)
    # Exercise real legacy JSON semantics: missing dataset_id and an existing
    # delete claim, without manufacturing a v6 database and downgrading its tag.
    rows[1].pop("dataset_id")
    rows[1]["_dataset_delete_claim"] = "1" * 32
    (project / "images.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    ddl = (Path(__file__).parents[1] / "fixtures/material_repository_schema5.sql").read_text(encoding="utf-8")
    assert "ix_materials_dataset_delete_claim" not in ddl
    with closing(sqlite3.connect(project / "materials.sqlite3", isolation_level=None)) as db:
        db.row_factory = sqlite3.Row
        db.executescript(ddl)
        # This writer is unchanged from the schema5 implementation; no
        # constructor runs until after the old database has been backed up.
        db.execute("BEGIN IMMEDIATE")
        for row in rows:
            MaterialRepository._write_row(db, row)
        db.execute("UPDATE material_meta SET value='17' WHERE key='revision'")
        db.execute("COMMIT")
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='ix_materials_dataset_delete_claim'").fetchone()
    artifacts = ArtifactStore(root / "task_runtime/artifacts")
    artifacts.atomic_write_json("historical-training", "payload.json", {
        "snapshot_id": snapshot["snapshot_id"], "image_ids": snapshot["train_image_ids"],
        "source_sha256": rows[0]["content_sha256"], "automatic_execution": False,
    })
    checkpoint = artifacts.artifact_path("historical-training", "checkpoint.pt")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_bytes(b"isolated preservation fixture; not an inference-valid model")
    artifacts.atomic_write_json("historical-training", "result.json", {"checkpoint_ref": "checkpoint.pt", "sha256": sha(checkpoint)})
    tasks = TaskRepository(root / "task_runtime/tasks.sqlite3")
    task = TaskRecord.new("historical-training", "p", TaskKind.TRAINING, "payload.json", "training")
    tasks.create(replace(task, status=TaskStatus.SUCCEEDED, result_ref="result.json"), artifacts=artifacts)
    ModelArtifactRepository(root).upsert({
        "artifact_id": "historical-artifact", "project_id": "p", "algorithm_id": "historical-algorithm",
        "version_id": "historical-version", "artifact_kind": "training", "target": "original",
        "file_name": checkpoint.name, "source_path": str(checkpoint), "sha256": sha(checkpoint),
        "size_bytes": checkpoint.stat().st_size,
        "metadata": {"task_id": task.task_id, "snapshot_id": snapshot["snapshot_id"], "fixture_only": True},
    })
    return rows, snapshot


@pytest.mark.parametrize("interrupt", [False, True])
def test_genuine_schema5_backup_preserves_all_historical_business_evidence(tmp_path, monkeypatch, interrupt):
    source = tmp_path / "historical-source"
    rows, snapshot = make_historical_fixture(source)
    target, restored = tmp_path / "upgrade-copy", tmp_path / "restore-copy"
    clone_fixture(source, target)
    before = business_state(source)
    assert business_state(target) == before
    project = target / "projects/p"
    if interrupt:
        with monkeypatch.context() as fault:
            fault.setattr(materials_module, "_SCHEMA", materials_module._SCHEMA + "\nINVALID INTERRUPTION;")
            with pytest.raises(sqlite3.OperationalError):
                MaterialRepository(project)
        assert business_state(target) == before
        with closing(existing_sqlite_reader(project / "materials.sqlite3")) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        clone_fixture(source, restored)
        assert business_state(restored) == before
        with closing(existing_sqlite_reader(restored / "projects/p/materials.sqlite3")) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 5
    repository = MaterialRepository(project)
    assert repository.count() == 3
    assert repository.current_revision() == 17
    assert "dataset_id" not in repository.get(rows[0]["id"])
    claim = repository.list_dataset_delete_claims("default")
    assert len(claim) == 1 and claim[0]["id"] == rows[1]["id"]
    assert "dataset_id" not in claim[0]
    assert claim[0]["_dataset_delete_claim"] == "1" * 32
    assert business_state(target) == before == business_state(source)
    with closing(repository._connect()) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
        plan = " ".join(row[3] for row in db.execute(
            "EXPLAIN QUERY PLAN SELECT payload_json FROM materials INDEXED BY ix_materials_dataset_delete_claim "
            "WHERE json_extract(payload_json,'$._dataset_delete_claim') IS NOT NULL "
            "AND COALESCE(CAST(json_extract(payload_json,'$.dataset_id') AS TEXT),'default')='default'"))
        assert "SEARCH materials USING INDEX ix_materials_dataset_delete_claim" in plan
    current_gt = AnnotationRepository(project)
    rebuilt = build_snapshot([{**repository.get(row["id"]), "boxes": current_gt.get(row["id"])["boxes"]} for row in rows],
                             snapshot["train_image_ids"], snapshot["val_image_ids"], [{"code": "target"}], seed=42)
    assert rebuilt["snapshot_id"] == snapshot["snapshot_id"]
    assert business_state(target) == before
