from typing import Any, Dict, List, Optional


def _score(item: Dict[str, int]) -> int:
    return (
        item.get("images", 0) * 100
        + item.get("algorithms", 0) * 25
        + item.get("versions", 0) * 10
        + item.get("jobs", 0)
    )


def choose_project(
    projects: List[Dict[str, Any]],
    preferred_id: str,
    counts: Dict[str, Dict[str, int]],
) -> Optional[Dict[str, Any]]:
    if not projects:
        return None
    preferred = next(
        (item for item in projects if str(item.get("id")) == str(preferred_id)),
        None,
    )
    if preferred and _score(counts.get(str(preferred["id"]), {})) > 0:
        return preferred
    ranked = sorted(
        projects,
        key=lambda item: (
            _score(counts.get(str(item.get("id")), {})),
            str(item.get("updated_at") or item.get("created_at") or ""),
        ),
        reverse=True,
    )
    best = ranked[0]
    return best if _score(counts.get(str(best.get("id")), {})) > 0 else (preferred or projects[0])

