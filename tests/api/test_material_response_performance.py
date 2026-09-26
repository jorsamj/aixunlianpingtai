import json

from starlette.responses import Response

import app as app_module


def test_material_list_is_pre_serialized_without_changing_json(monkeypatch):
    rows = [
        {
            "id": "image-1",
            "filename": "测试图片.jpg",
            "box_count": 1,
            "labels": ["helmet"],
            "annotation_preview": [{"label": "helmet", "x1": 1, "y1": 2}],
            "size_bytes": 12,
            "split": "train",
            "processing_status": "processed",
            "annotation_summary_at": "2026-08-30T00:00:00Z",
        }
    ]
    monkeypatch.setattr(app_module, "get_project", lambda _project_id: {"id": "project-1"})
    monkeypatch.setattr(app_module, "load_images", lambda _project_id: rows)

    response = app_module.list_images("project-1")

    assert isinstance(response, Response)
    assert response.media_type == "application/json"
    assert json.loads(response.body) == rows


def test_bootstrap_snapshot_is_pre_serialized_without_changing_json(monkeypatch):
    snapshot = {"project": {"id": "project-1"}, "images": [{"id": "image-1"}]}
    monkeypatch.setattr(app_module, "_V53_BOOTSTRAP_STATUS", {"status": "ready"})
    monkeypatch.setattr(app_module, "_V53_BOOTSTRAP_SNAPSHOT", snapshot)
    monkeypatch.setattr(app_module, "read_json", lambda *_args, **_kwargs: [{"id": "project-1"}])
    monkeypatch.setattr(
        app_module,
        "_v53_project_counts",
        lambda _project: (_ for _ in ()).throw(AssertionError("cached snapshot must not recalculate project counts")),
    )
    monkeypatch.setattr(app_module, "_v53_choose_project", lambda projects, _preferred: projects[0])

    response = app_module.v53_bootstrap_snapshot("")

    assert isinstance(response, Response)
    payload = json.loads(response.body)
    assert payload["ok"] is True
    assert payload["bootstrap"] == {"status": "ready"}
    assert payload["project"] == snapshot["project"]
    assert payload["images"] == snapshot["images"]


def test_refreshed_bootstrap_counts_each_project_once_and_replaces_cache(monkeypatch):
    projects = [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]
    calls = []
    monkeypatch.setattr(app_module, "_V53_BOOTSTRAP_STATUS", {"status": "ready"})
    monkeypatch.setattr(app_module, "_V53_BOOTSTRAP_SNAPSHOT", {"project": {"id": "p1"}})
    monkeypatch.setattr(app_module, "read_json", lambda *_args, **_kwargs: projects)
    monkeypatch.setattr(
        app_module,
        "_v53_project_counts",
        lambda project: calls.append(project["id"]) or {
            "images": 1, "algorithms": 2, "versions": 3, "jobs": 4,
        },
    )
    monkeypatch.setattr(
        app_module,
        "_v53_build_snapshot",
        lambda project_id: {"project": {"id": project_id}, "generated_at": "fresh"},
    )

    response = app_module.v53_bootstrap_snapshot("p2", refresh=True)
    payload = json.loads(response.body)

    assert calls == ["p1", "p2", "p3"]
    assert payload["project"]["id"] == "p2"
    assert [row["bootstrap_counts"]["jobs"] for row in payload["projects"]] == [4, 4, 4]
    assert app_module._V53_BOOTSTRAP_SNAPSHOT["project"]["id"] == "p2"


def test_annotation_summary_migration_batches_repository_reads_and_projection_writes(monkeypatch):
    project_id = "project-scale"
    rows = [
        {"id": f"image-{index:04d}", "filename": f"image-{index:04d}.jpg"}
        for index in range(1201)
    ]
    read_batches = []
    patch_batches = []

    class FakeAnnotations:
        def get_many(self, image_ids):
            batch = list(image_ids)
            read_batches.append(batch)
            assert len(batch) <= app_module._ANNOTATION_INDEX_BATCH_SIZE
            return {
                image_id: {
                    "image_id": image_id,
                    "annotation_state": "annotated",
                    "boxes": [{"label": "fire", "class_id": 0}],
                    "updated_at": "2026-09-26T00:00:00Z",
                }
                for image_id in batch
            }

    class FakeMaterials:
        def patch(self, patches):
            patch_batches.append(dict(patches))
            assert len(patches) <= app_module._ANNOTATION_INDEX_BATCH_SIZE
            return list(patches.values())

    monkeypatch.setattr(app_module, "load_images", lambda _project_id: rows)
    monkeypatch.setattr(app_module, "_v50_annotation_repository", lambda _project_id: FakeAnnotations())
    monkeypatch.setattr(app_module, "material_store", lambda _project_id: FakeMaterials())
    monkeypatch.setattr(
        app_module,
        "read_annotation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("annotation summary migration must not issue per-image reads")
        ),
    )

    app_module._v52_annotation_index_worker(project_id)

    assert [len(batch) for batch in read_batches] == [500, 500, 201]
    assert [len(batch) for batch in patch_batches] == [500, 500, 201]
    assert app_module._ANNOTATION_INDEX_STATUS[project_id]["running"] is False
    assert app_module._ANNOTATION_INDEX_STATUS[project_id]["processed"] == 1201


def test_selected_batch_split_uses_indexed_patch_without_full_table_mutate(monkeypatch):
    import inspect
    import app as app_module

    class FakeMaterials:
        def __init__(self):
            self.patches = []

        def patch(self, patches):
            self.patches.append(dict(patches))
            return [{"id": image_id, **dict(patch)} for image_id, patch in patches.items()]

        def mutate(self, _callback):
            raise AssertionError("selected batch split must not read/mutate the full material table")

    materials = FakeMaterials()
    monkeypatch.setattr(app_module, "get_project", lambda _project_id: {"id": "project-1"})
    monkeypatch.setattr(app_module, "material_store", lambda _project_id: materials)

    result = app_module.v20_batch_image_split(
        "project-1",
        app_module.BatchImageSplitReq(
            image_ids=["a", "b", "a"],
            split="train",
            scope="selected",
        ),
    )

    assert result["changed"] == 2
    assert set(materials.patches[0]) == {"a", "b"}
    assert all(patch["split"] == "train" for patch in materials.patches[0].values())

    source = inspect.getsource(app_module.v20_batch_image_split)
    filtered = source[source.index('if scope == "filtered"'):]
    assert "read_annotation(project_id" not in filtered
    assert "annotations.get_many(batch_ids)" in filtered


def test_mark_ready_uses_bounded_indexed_patch_without_full_table_mutate(monkeypatch):
    class FakeMaterials:
        def __init__(self):
            self.patch_calls = []

        def get_many(self, image_ids):
            return [
                {"id": image_id, "filename": f"{image_id}.jpg", "processing_status": "pending_decision"}
                for image_id in image_ids
                if image_id != "missing"
            ]

        def patch_many(self, image_ids, patch, batch_size=0):
            self.patch_calls.append((list(image_ids), dict(patch), batch_size))
            return len(list(image_ids))

        def mutate(self, _callback):
            raise AssertionError("mark-ready must never scan/mutate the full material table")

    materials = FakeMaterials()
    monkeypatch.setattr(app_module, "get_project", lambda _project_id: {"id": "project-1"})
    monkeypatch.setattr(app_module, "material_store", lambda _project_id: materials)

    result = app_module.v52_mark_ready(
        "project-1",
        app_module.V52ReadyReq(image_ids=["a", "b", "missing", "a"]),
    )

    assert result["changed"] == 2
    assert result["image_ids"] == ["a", "b"]
    assert len(materials.patch_calls) == 1
    ids, patch, batch_size = materials.patch_calls[0]
    assert ids == ["a", "b"]
    assert batch_size == 500
    assert patch["processing_status"] == "processed"
    assert patch["clean_skipped"] is True
    assert patch["clean_decision"] == "skipped"
