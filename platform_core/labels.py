from typing import Iterable, Mapping, Sequence


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
        for item in labels
        if str(item.get("status") or "active") == "active"
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
