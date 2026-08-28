from typing import Iterable, Mapping, Sequence


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

