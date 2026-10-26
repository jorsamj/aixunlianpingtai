"""Bounded, read-only input contract for the external engine."""
from __future__ import annotations

import re
from pathlib import Path


FEATURE = "hog-color-v1"
MAX_IMAGES = 2000


def validate_manifest(value):
    if not isinstance(value, dict) or value.get("feature") != FEATURE:
        raise ValueError("unsupported smart audit feature")
    for key in ("project_id", "task_id"):
        if not isinstance(value.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value[key]):
            raise ValueError(f"invalid {key}")
    images = value.get("images")
    if not isinstance(images, list) or not 1 <= len(images) <= MAX_IMAGES:
        raise ValueError(f"analysis requires 1..{MAX_IMAGES} images")
    identities = set()
    for row in images:
        if not isinstance(row, dict) or not isinstance(row.get("image_id"), str) or not row["image_id"]:
            raise ValueError("invalid image identity")
        if row["image_id"] in identities:
            raise ValueError("duplicate image identity")
        identities.add(row["image_id"])
        if not isinstance(row.get("content_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["content_sha256"]):
            raise ValueError("verified content_sha256 required")
        if not isinstance(row.get("path"), str) or not Path(row["path"]).is_absolute():
            raise ValueError("absolute read-only image path required")
    threshold = value.get("threshold", .4)
    if isinstance(threshold, bool) or not isinstance(threshold, (float, int)) or not 0 < threshold < 2:
        raise ValueError("invalid similarity distance threshold")
    return value
