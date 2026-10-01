import json
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from filelock import FileLock


def normalize_label_aliases(values) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    result: list[str] = []
    seen = set()
    for value in values:
        alias = str(value or "").strip()
        if not alias or alias in seen:
            continue
        if len(alias) > 128:
            raise ValueError("label alias is too long")
        seen.add(alias)
        result.append(alias)
    return result


def label_identity_values(item: Mapping) -> set[str]:
    return {
        value
        for value in (
            str(item.get("code") or "").strip(),
            str(item.get("display_name") or "").strip(),
            str(item.get("display_name_zh") or "").strip(),
        )
        if value
    }


def confirmed_alias_updates(
    classes: Sequence[Mapping],
    mapping: Mapping[str, str],
    labels: Sequence[Mapping],
) -> dict[str, list[str]]:
    active = {
        str(item.get("code")): item
        for item in active_label_options(labels)
    }
    resolved_rows: list[tuple[str, str]] = []
    source_targets: dict[str, set[str]] = {}
    for item in classes:
        source_id = str(item.get("class_id"))
        source_name = str(item.get("name") or "").strip()
        target = str(mapping.get(source_id) or mapping.get(source_name) or "").strip()
        if not source_name or target not in active:
            continue
        resolved_rows.append((source_name, target))
        source_targets.setdefault(source_name, set()).add(target)

    ambiguous_sources = {
        source_name
        for source_name, targets in source_targets.items()
        if len(targets) > 1
    }
    updates: dict[str, list[str]] = {}
    for source_name, target in resolved_rows:
        if source_name in ambiguous_sources:
            continue
        if source_name in label_identity_values(active[target]):
            continue
        bucket = updates.setdefault(target, [])
        if source_name not in bucket:
            bucket.append(source_name)
    return updates


def active_label_options(items: Sequence[Mapping]) -> list[dict]:
    return [
        dict(item)
        for item in items
        if str(item.get("status") or "active").strip().lower() == "active"
        and item.get("active") is not False
    ]


def active_project_label_ids(project_path) -> dict[str, int] | None:
    """Read active canonical labels from current and legacy project metadata.

    Production projects normally persist parallel labels and label_meta arrays.
    Older durable snapshots and focused runtimes may persist only label_meta.
    Both shapes describe the same project label governance and must resolve
    identically.
    """
    path = Path(project_path) / "meta.json"
    if not path.is_file():
        return None
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise ValueError("project label catalog is unreadable") from error

    labels = list(meta.get("labels") or [])
    metadata = list(meta.get("label_meta") or [])
    result: dict[str, int] = {}
    for index in range(max(len(labels), len(metadata))):
        raw_label = labels[index] if index < len(labels) else ""
        raw_meta = metadata[index] if index < len(metadata) else {}
        info = dict(raw_meta) if isinstance(raw_meta, Mapping) else {}
        if isinstance(raw_label, Mapping):
            fallback = str(
                raw_label.get("code") or raw_label.get("name") or ""
            ).strip()
            info = {**dict(raw_label), **info}
        else:
            fallback = str(raw_label or "").strip()
        code = str(info.get("code") or fallback).strip()
        if (
            not code
            or code in result
            or str(info.get("status") or "active").strip().lower() != "active"
            or info.get("active") is False
        ):
            continue
        try:
            class_id = int(info.get("class_id", index))
        except (TypeError, ValueError):
            class_id = index
        result[code] = class_id
    return result


def label_governance_lock_path(project_path) -> Path:
    """Cross-process fence for project label-schema read/check/write decisions."""
    return Path(project_path) / ".label-governance.lock"


_LABEL_GOVERNANCE_HELD: ContextVar[frozenset[str]] = ContextVar(
    "label_governance_held",
    default=frozenset(),
)


@contextmanager
def label_governance_fence(project_path, *, timeout: float = 60):
    """Serialize label-governance decisions and allow same-context re-entry."""
    lock_path = str(label_governance_lock_path(project_path).resolve())
    held = _LABEL_GOVERNANCE_HELD.get()
    if lock_path in held:
        yield
        return
    with FileLock(lock_path, timeout=timeout):
        token = _LABEL_GOVERNANCE_HELD.set(held | {lock_path})
        try:
            yield
        finally:
            _LABEL_GOVERNANCE_HELD.reset(token)


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
