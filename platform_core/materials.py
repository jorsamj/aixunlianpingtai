from pathlib import Path
from typing import Any, Mapping


def initial_processing_status(has_valid_boxes: bool) -> str:
    return "processed" if has_valid_boxes else "unprocessed"


def mark_ready(material: Mapping[str, Any], decided_at: str) -> dict:
    updated = dict(material)
    updated.update(
        {
            "processing_status": "processed",
            "clean_skipped": True,
            "clean_decision": "skipped",
            "clean_decision_at": decided_at,
            "updated_at": decided_at,
        }
    )
    return updated


def delete_material_files(project_path: Path, material: Mapping[str, Any]) -> list[str]:
    errors = []
    targets = [
        ("图片文件", project_path / "uploads" / str(material.get("stored_name") or "")),
        ("标注文件", project_path / "annotations" / f"{material.get('id')}.json"),
    ]
    for label, path in targets:
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            errors.append(f"{label}删除失败：{error}")
    return errors
