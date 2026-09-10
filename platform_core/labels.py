import uuid
from pathlib import Path
from typing import Iterable, Mapping, MutableMapping, Sequence

from filelock import FileLock


def project_label_file_lock(meta_path: str | Path, *, timeout: float = 30) -> FileLock:
    """Return the cross-process lock shared by all project-label metadata writers."""
    path = Path(meta_path).resolve()
    return FileLock(str(path) + ".labels.lock", timeout=timeout)


def new_label_id() -> str:
    return "lbl_" + uuid.uuid4().hex


def _legacy_label_id(project_id: object, index: int, code: object) -> str:
    seed = f"platform-label:{project_id}:{index}:{code}"
    return "lbl_" + uuid.uuid5(uuid.NAMESPACE_URL, seed).hex


def ensure_stable_label_ids(project: MutableMapping) -> bool:
    """Backfill immutable IDs while preserving the legacy parallel label arrays."""
    labels = project.setdefault("labels", [])
    meta = project.setdefault("label_meta", [])
    changed = False
    while len(meta) < len(labels):
        meta.append({})
        changed = True
    seen_ids = set()
    for index, code in enumerate(labels):
        if not isinstance(meta[index], dict):
            meta[index] = {}
            changed = True
        item = meta[index]
        current_id = str(item.get("label_id") or "").strip()
        if not current_id or current_id in seen_ids:
            item["label_id"] = _legacy_label_id(project.get("id", ""), index, code)
            changed = True
        seen_ids.add(item["label_id"])
        if item.get("code") != code:
            item["code"] = code
            changed = True
    return changed


def active_label_options(items: Sequence[Mapping]) -> list[dict]:
    return [
        dict(item)
        for item in items
        if str(item.get("status") or "active") == "active"
    ]


def labels_match_any(image_labels: Iterable[str], selected: set[str]) -> bool:
    return not selected or bool({str(item) for item in image_labels} & selected)


def label_by_code(items: Sequence[Mapping], code: str) -> dict:
    match = next(
        (dict(item) for item in items if str(item.get("code")) == str(code)),
        None,
    )
    if not match:
        raise KeyError(code)
    return match
