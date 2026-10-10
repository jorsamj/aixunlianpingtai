import io
import zipfile
from pathlib import Path

from PIL import Image

from platform_core.annotation_repository import AnnotationRepository


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _project(client) -> str:
    response = client.post(
        "/api/projects",
        json={"name": "v19-failure-rollback", "description": "", "labels": ["target"]},
    )
    response.raise_for_status()
    return response.json()["id"]


def _single_image_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("images/train/image.png", _png_bytes())
        archive.writestr("labels/train/image.txt", "0 0.5 0.5 0.5 0.5\n")
        archive.writestr(
            "data.yaml",
            "train: images/train\nnc: 1\nnames: [target]\n",
        )
    return buffer.getvalue()


def _local_stored_path(app_module, project_id: str, record):
    return app_module.project_dir(project_id) / "uploads" / record["stored_name"]


def test_v19_worker_failure_rolls_back_partial_durable_import(client, monkeypatch):
    import app as app_module

    project_id = _project(client)
    app_module.ensure_default_datasets(project_id)
    create = client.post(
        f"/api/v19/projects/{project_id}/datasets/default/import/jobs",
        files={"file": ("rollback.zip", _single_image_zip(), "application/zip")},
    )
    create.raise_for_status()
    job_id = create.json()["id"]
    captured = {}

    monkeypatch.setattr(app_module, "_v18_import_coco", lambda *args, **kwargs: False)
    monkeypatch.setattr(app_module, "_v18_import_voc", lambda *args, **kwargs: False)

    def fail_after_durable_image(
        project_id_arg,
        root,
        dataset_id,
        report,
        progress_cb=None,
        label_mapping=None,
        import_context=None,
    ):
        source = next(Path(root).rglob("image.png"))

        def final_annotation(record):
            return [
                {
                    "id": "box-rollback",
                    "class_id": 0,
                    "label": "target",
                    "x1": 4.0,
                    "y1": 4.0,
                    "x2": 20.0,
                    "y2": 20.0,
                }
            ]

        record = app_module.add_image_record(
            project_id_arg,
            source,
            source.name,
            "imported_yolo",
            dataset_id,
            annotation_builder=final_annotation,
        )
        assert record is not None
        app_module._v18_set_image_split(project_id_arg, record["id"], "train")
        captured["record"] = record
        report["imported_images"] += 1
        report["annotated_images"] += 1
        report["boxes"] += 1
        report.setdefault("imported_image_ids", []).append(record["id"])
        raise RuntimeError("forced import failure after durable image write")

    monkeypatch.setattr(app_module, "_v18_import_yolo", fail_after_durable_image)

    app_module.v19_import_worker(project_id, "default", job_id, [])

    job = app_module.v19_read_job(project_id, job_id)
    assert job["status"] == "failed"
    assert "forced import failure" in str(job.get("error") or "")
    record = captured["record"]
    image_id = record["id"]

    assert all(
        str(row.get("id")) != image_id
        for row in app_module.material_store(project_id).read().rows
    )
    assert not _local_stored_path(app_module, project_id, record).exists()
    assert not AnnotationRepository(app_module.project_dir(project_id)).exists(image_id)
    assert app_module._v50_active_image_batch(project_id) is None


def test_save_false_discards_new_batch_files_and_sqlite_annotation(client, tmp_path):
    import app as app_module

    project_id = _project(client)
    app_module.ensure_default_datasets(project_id)
    source = tmp_path / "discard.png"
    source.write_bytes(_png_bytes())

    app_module._v50_begin_image_batch(project_id)
    record = app_module.add_image_record(
        project_id,
        source,
        source.name,
        "imported_yolo",
        "default",
        annotation_builder=lambda row: [
            {
                "id": "box-discard",
                "class_id": 0,
                "label": "target",
                "x1": 2.0,
                "y1": 2.0,
                "x2": 18.0,
                "y2": 18.0,
            }
        ],
    )
    assert record is not None
    stored_path = _local_stored_path(app_module, project_id, record)
    repository = AnnotationRepository(app_module.project_dir(project_id))
    assert stored_path.exists()
    # The deferred formal annotation is not durable until Material commits.
    assert not repository.exists(record["id"])

    app_module._v50_end_image_batch(save=False)

    assert all(
        str(row.get("id")) != record["id"]
        for row in app_module.material_store(project_id).read().rows
    )
    assert not stored_path.exists()
    assert not repository.exists(record["id"])
    assert app_module._v50_active_image_batch(project_id) is None


def test_zip_stop_between_parse_and_db_commit_rolls_back_staged_material(client, monkeypatch):
    import app as app_module

    project_id = _project(client)
    app_module.ensure_default_datasets(project_id)
    created = client.post(
        f'/api/v19/projects/{project_id}/datasets/default/import/jobs',
        files={'file': ('stop.zip', _single_image_zip(), 'application/zip')},
    )
    created.raise_for_status()
    job_id = created.json()['id']
    captured = {}
    monkeypatch.setattr(app_module, '_v18_import_coco', lambda *args, **kwargs: False)
    monkeypatch.setattr(app_module, '_v18_import_voc', lambda *args, **kwargs: False)

    def import_then_request_stop(project_id_arg, root, dataset_id, report,
                                 progress_cb=None, label_mapping=None, import_context=None):
        source = next(Path(root).rglob('image.png'))
        record = app_module.add_image_record(
            project_id_arg, source, source.name, 'imported_yolo', dataset_id,
            annotation_builder=lambda _: [{
                'id': 'staged-only', 'class_id': 0, 'label': 'target',
                'x1': 1.0, 'y1': 1.0, 'x2': 20.0, 'y2': 20.0,
            }],
        )
        captured['record'] = record
        report['imported_images'] += 1
        report['annotated_images'] += 1
        report['boxes'] += 1
        report.setdefault('imported_image_ids', []).append(record['id'])
        stopped = client.post(f'/api/v19/projects/{project_id_arg}/import/jobs/{job_id}/stop')
        assert stopped.status_code == 200
        assert stopped.json()['cancel_requested'] is True
        return True

    monkeypatch.setattr(app_module, '_v18_import_yolo', import_then_request_stop)
    app_module.v19_import_worker(project_id, 'default', job_id, [])
    job = app_module.v19_read_job(project_id, job_id)
    assert job['status'] == 'cancelled'
    record = captured['record']
    assert app_module.material_store(project_id).get(record['id']) is None
    assert not AnnotationRepository(app_module.project_dir(project_id)).exists(record['id'])
    assert not _local_stored_path(app_module, project_id, record).exists()
    assert not (app_module.v19_job_dir(project_id, job_id) / 'source.zip').exists()


def test_zip_stop_rejects_commit_phase(client):
    import app as app_module

    project_id = _project(client)
    app_module.ensure_default_datasets(project_id)
    created = client.post(
        f'/api/v19/projects/{project_id}/datasets/default/import/jobs',
        files={'file': ('commit.zip', _single_image_zip(), 'application/zip')},
    )
    created.raise_for_status()
    job_id = created.json()['id']
    app_module.v19_update_job(project_id, job_id, status='running', phase='DB_COMMIT')
    response = client.post(f'/api/v19/projects/{project_id}/import/jobs/{job_id}/stop')
    assert response.status_code == 409
    assert not app_module.v19_read_job(project_id, job_id).get('cancel_requested')
