from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact match, got {count}")
    write(path, text.replace(old, new, 1))


# 1) Task projection: selected image stays in task; selected labels define positives.
path = "platform_core/training_label_tasks.py"
old = '''        if state == "annotated" and not selected_boxes:\n            present = sorted({\n                str(box.get("label") or box.get("code") or "").strip()\n                for box in boxes\n                if str(box.get("label") or box.get("code") or "").strip()\n            })\n            raise ValueError(\n                f"训练素材 {image_id} 不包含本次训练标签；当前标注为 "\n                f"{', '.join(present[:8]) or '无'}。"\n                "如果它应作为负样本，请先明确执行“确认无目标”，不能通过过滤其他标签制造负样本。"\n            )\n        row["annotation_state"] = state\n        row["annotated"] = state in {"annotated", "confirmed_empty"}\n        row["boxes"] = selected_boxes if state == "annotated" else []\n        if state == "annotated":\n            explicit = {value for value in raw_scope if value and value != "*"}\n            row["annotation_scope"] = sorted((explicit & allowed) | {\n                str(box.get("label") or box.get("code") or "").strip()\n                for box in selected_boxes\n            })\n        else:\n            row["annotation_scope"] = raw_scope\n'''
new = '''        present = sorted({\n            str(box.get("label") or box.get("code") or "").strip()\n            for box in boxes\n            if str(box.get("label") or box.get("code") or "").strip()\n        })\n        task_filtered_negative = state == "annotated" and not selected_boxes\n        row["source_annotation_state"] = state\n        row["source_labels"] = present\n        if task_filtered_negative:\n            # Material selection decides whether the image participates in this task;\n            # the task label contract decides which classes are positive. If all\n            # source boxes belong to unselected classes, keep the image and project\n            # it to an intentional task-local background sample. Source Ground Truth\n            # in AnnotationRepository is never mutated.\n            row["annotation_state"] = "confirmed_empty"\n            row["annotated"] = True\n            row["boxes"] = []\n            row["annotation_scope"] = sorted(allowed)\n            row["negative_origin"] = "filtered_by_training_labels"\n        else:\n            row["annotation_state"] = state\n            row["annotated"] = state in {"annotated", "confirmed_empty"}\n            row["boxes"] = selected_boxes if state == "annotated" else []\n            if state == "annotated":\n                explicit = {value for value in raw_scope if value and value != "*"}\n                row["annotation_scope"] = sorted((explicit & allowed) | {\n                    str(box.get("label") or box.get("code") or "").strip()\n                    for box in selected_boxes\n                })\n            else:\n                row["annotation_scope"] = raw_scope\n                if state == "confirmed_empty":\n                    row["negative_origin"] = str(row.get("negative_origin") or "explicit_confirmed_empty")\n'''
replace_once(path, old, new)

# 2) Snapshot keeps provenance so an empty target is auditable instead of silent.
path = "platform_core/snapshots.py"
text = read(path)
pattern = re.compile(r'(?m)^(\s*)"annotation_hash": annotation_hash,$')
replacement = (
    r'\1"annotation_hash": annotation_hash,\n'
    r'\1"negative_origin": str(image.get("negative_origin") or ""),\n'
    r'\1"source_annotation_state": str(image.get("source_annotation_state") or ""),\n'
    r'\1"source_labels": sorted({str(value) for value in (image.get("source_labels") or []) if str(value)}),'
)
text, count = pattern.subn(replacement, text)
if count != 2:
    raise SystemExit(f"{path}: expected 2 snapshot record insertion points, got {count}")
text = text.replace(
    '    negative_scope_counts: dict[str, int] = {}\n',
    '    negative_scope_counts: dict[str, int] = {}\n    negative_origin_counts: dict[str, int] = {}\n',
    1,
)
old_negative = '''            if state == "confirmed_empty":\n                for label in scope:\n                    negative_scope_counts[label] = negative_scope_counts.get(label, 0) + 1\n'''
new_negative = '''            if state == "confirmed_empty":\n                origin = str(image.get("negative_origin") or "explicit_confirmed_empty")\n                negative_origin_counts[origin] = negative_origin_counts.get(origin, 0) + 1\n                for label in scope:\n                    negative_scope_counts[label] = negative_scope_counts.get(label, 0) + 1\n'''
if text.count(old_negative) != 1:
    raise SystemExit(f"{path}: negative counter block mismatch")
text = text.replace(old_negative, new_negative, 1)
text = text.replace(
    '        "negative_scope_counts": dict(sorted(negative_scope_counts.items())),\n',
    '        "negative_scope_counts": dict(sorted(negative_scope_counts.items())),\n        "negative_origin_counts": dict(sorted(negative_origin_counts.items())),\n',
    1,
)
write(path, text)

# 3) Replace the old rejection contract with the new task-local negative contract.
path = "tests/unit/test_training_label_contract.py"
text = read(path)
pattern = re.compile(
    r'def test_projection_rejects_positive_material_with_only_unselected_labels\(tmp_path: Path\):.*?\n\n\ndef test_portable_data_yaml_contains_only_effective_task_schema',
    re.S,
)
new_test = '''def test_projection_turns_only_unselected_labels_into_task_negative_without_mutating_source(tmp_path: Path):\n    _, project = _project(tmp_path)\n    annotations = AnnotationRepository(project)\n    annotations.upsert("a", [_box("person")], annotation_state="annotated")\n\n    class Materials:\n        def get_many(self, _ids):\n            return [{"id": "a", "width": 100, "height": 100}]\n\n    contract = {\n        "project_path": str(project.resolve()),\n        "effective_label_codes": ["fire"],\n        "effective_label_schema": [{"code": "fire", "class_id": 0}],\n    }\n    token = _LABEL_CONTRACT.set(contract)\n    try:\n        rows = _scoped_selected_project_images(Materials(), project, ["a"])\n    finally:\n        _LABEL_CONTRACT.reset(token)\n\n    projected = rows[0]\n    assert projected["annotation_state"] == "confirmed_empty"\n    assert projected["annotated"] is True\n    assert projected["boxes"] == []\n    assert projected["annotation_scope"] == ["fire"]\n    assert projected["negative_origin"] == "filtered_by_training_labels"\n    assert projected["source_annotation_state"] == "annotated"\n    assert projected["source_labels"] == ["person"]\n\n    # The task projection must never rewrite material-library Ground Truth.\n    source = annotations.get("a")\n    assert source["annotation_state"] == "annotated"\n    assert [box["label"] for box in source["boxes"]] == ["person"]\n\n\ndef test_portable_data_yaml_contains_only_effective_task_schema'''
text, count = pattern.subn(new_test, text)
if count != 1:
    raise SystemExit(f"{path}: old rejection test not found exactly once ({count})")
needle = '''    assert rows[0]["annotation_scope"] == ["fire"]\n    assert "annotation_hash" not in rows[0]\n'''
replacement = '''    assert rows[0]["annotation_scope"] == ["fire"]\n    assert rows[0]["source_annotation_state"] == "annotated"\n    assert rows[0]["source_labels"] == ["fire", "person"]\n    assert "negative_origin" not in rows[0]\n    assert "annotation_hash" not in rows[0]\n'''
if text.count(needle) != 1:
    raise SystemExit(f"{path}: mixed-label assertion anchor mismatch")
text = text.replace(needle, replacement, 1)
append = '''\n\ndef test_task_filtered_negative_materializes_as_empty_yolo_label(tmp_path: Path):\n    _, project = _project(tmp_path)\n    AnnotationRepository(project).upsert("a", [_box("person")], annotation_state="annotated")\n    image_file = tmp_path / "task-negative.jpg"\n    image_file.write_bytes(b"task-negative-source")\n    content_hash = hashlib.sha256(image_file.read_bytes()).hexdigest()\n\n    class Materials:\n        def get_many(self, _ids):\n            return [{\n                "id": "a", "filename": image_file.name, "width": 100, "height": 100\n            }]\n\n    contract = {\n        "project_path": str(project.resolve()),\n        "effective_label_codes": ["fire"],\n        "effective_label_schema": [{"code": "fire", "class_id": 0}],\n    }\n    token = _LABEL_CONTRACT.set(contract)\n    try:\n        rows = _scoped_selected_project_images(Materials(), project, ["a"])\n    finally:\n        _LABEL_CONTRACT.reset(token)\n    rows[0]["content_sha256"] = content_hash\n    snapshot = {\n        "snapshot_id": "filtered-negative",\n        "label_schema": contract["effective_label_schema"],\n        "ids": {"train": ["a"], "validation": [], "test": []},\n        "images": [{"image_id": "a", "content_sha256": content_hash}],\n    }\n    bundle = materialize_portable_dataset(\n        tmp_path / "work-negative", snapshot, rows, lambda _row: image_file, safety_reserve_bytes=0\n    )\n    label = bundle / "dataset" / "labels" / "train" / "a.txt"\n    assert label.is_file()\n    assert label.read_text(encoding="utf-8") == ""\n'''
if "test_task_filtered_negative_materializes_as_empty_yolo_label" not in text:
    text += append
write(path, text)

# 4) Snapshot audit test.
path = "tests/unit/test_negative_sample_contract.py"
text = read(path)
if "test_snapshot_preserves_task_filtered_negative_origin" not in text:
    text += '''\n\ndef test_snapshot_preserves_task_filtered_negative_origin():\n    row = {\n        "id": "task-negative",\n        "content_sha256": "hash-task-negative",\n        "stored_name": "task-negative.jpg",\n        "annotation_state": "confirmed_empty",\n        "annotation_scope": ["fire"],\n        "annotated": True,\n        "processing_status": "processed",\n        "boxes": [],\n        "negative_origin": "filtered_by_training_labels",\n        "source_annotation_state": "annotated",\n        "source_labels": ["people"],\n    }\n    snapshot = build_snapshot(\n        [row],\n        _manifest("task-negative", "hash-task-negative"),\n        [{"code": "fire", "class_id": 0}],\n    )\n    locked = snapshot["images"][0]\n    assert locked["negative_origin"] == "filtered_by_training_labels"\n    assert locked["source_annotation_state"] == "annotated"\n    assert locked["source_labels"] == ["people"]\n    assert snapshot["negative_origin_counts"] == {"filtered_by_training_labels": 1}\n'''
write(path, text)

# 5) Documentation: supersede only the task-projection rule; explicit negative workflow remains valid.
path = "docs/superpowers/specs/2026-09-11-negative-sample-contract.md"
text = read(path)
marker = "## 11. 2026-09-17 Task-derived negative addendum"
if marker not in text:
    text += '''\n\n## 11. 2026-09-17 Task-derived negative addendum\n\nThe product contract now distinguishes **material Ground Truth** from a **training-task projection**.\n\n- Selecting material decides whether the image participates in the training task.\n- Selecting training labels decides which classes are positive for that task.\n- If an already-annotated selected image contains only classes that the user deselects for this task, the image remains in the task and is projected as `confirmed_empty` with `negative_origin=filtered_by_training_labels`.\n- The source AnnotationRepository row is immutable: its original boxes and `annotation_state=annotated` remain unchanged.\n- If a selected image contains both selected and deselected classes, only deselected boxes are filtered; the image stays positive.\n- Explicit material-level `确认无目标` remains a separate state and is recorded as `negative_origin=explicit_confirmed_empty` in the task projection.\n- Snapshot v3 persists `negative_origin`, `source_annotation_state`, `source_labels`, and `negative_origin_counts` so task-derived backgrounds are auditable.\n\nThis deliberately permits a YOLO empty target for the locked task schema, while preventing task label filtering from rewriting source Ground Truth.\n'''
write(path, text)

for path in ("docs/PROJECT_HANDOFF_CURRENT.md", "docs/BUG_AUDIT_2026-09-17.md"):
    text = read(path)
    marker = "CLOSED — Training label filter task-derived negatives"
    if marker not in text:
        text += '''\n\n## CLOSED — Training label filter task-derived negatives\n\n2026-09-17 product rule: selected materials stay in the training task. The training label checkbox defines the positive schema. If all source boxes are excluded by that schema, the task projection becomes an auditable background sample (`negative_origin=filtered_by_training_labels`) without mutating source annotations. Mixed-label images retain selected boxes. Explicit `确认无目标` remains distinct.\n'''
    write(path, text)

print("task-filtered negative migration applied")
