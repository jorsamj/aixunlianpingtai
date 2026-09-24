from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from filelock import FileLock

from .algorithms import list_algorithms, update_algorithm_version
from .model_artifacts import SUCCESSFUL_CONVERSION_STATUSES


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _external_auto_publish_enabled(data_dir: Path) -> bool:
    root = Path(data_dir) / "external_algorithm_platform"
    config_path = root / "config.json"
    if not config_path.is_file():
        return False
    try:
        with FileLock(str(root / ".lock"), timeout=30):
            body = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    # ExternalPlatformRepository canonically forces auto publishing on whenever
    # external mode is enabled. Read only that durable mode flag here so this
    # marker stays usable by lightweight Agent runtimes without the FastAPI router.
    return isinstance(body, dict) and str(body.get("mode") or "local") == "external"


def request_external_auto_publish_if_enabled(
    *,
    data_dir: Path,
    algorithms_path: Path,
    algorithm_id: str,
    version_id: str,
    now: str,
) -> bool:
    try:
        if not _external_auto_publish_enabled(Path(data_dir)):
            return False
        algorithms = list_algorithms(Path(algorithms_path))
        algorithm = next(
            (row for row in algorithms if str(row.get("id") or "") == str(algorithm_id)),
            None,
        )
        if not algorithm or str(algorithm.get("source_type") or "").upper() != "EXTERNAL":
            return False
        update_algorithm_version(
            Path(algorithms_path),
            str(algorithm_id),
            str(version_id),
            {"external_publish_requested_at": str(now)},
            now=str(now),
        )
        return True
    except Exception:
        return False


def request_external_auto_publish_for_conversion_if_enabled(
    *,
    data_dir: Path,
    project_id: str,
    conversion_job: Mapping[str, Any],
    now: str | None = None,
) -> bool:
    """Mark a deliverable conversion for the existing external-publish owner."""
    status = str(conversion_job.get("status") or "").strip().lower()
    if status not in SUCCESSFUL_CONVERSION_STATUSES:
        return False

    algorithm_id = ""
    version_id = ""
    for source in (
        conversion_job.get("source_trace"),
        conversion_job.get("source_meta"),
    ):
        if not isinstance(source, Mapping):
            continue
        candidate_algorithm_id = str(source.get("algorithm_id") or "").strip()
        candidate_version_id = str(source.get("version_id") or "").strip()
        if candidate_algorithm_id and candidate_version_id:
            algorithm_id = candidate_algorithm_id
            version_id = candidate_version_id
            break

    if not algorithm_id or not version_id:
        source_id = str(conversion_job.get("source_id") or "").strip()
        match = re.fullmatch(r"version::([^:]+)::([^:]+)", source_id)
        if match:
            algorithm_id, version_id = match.group(1), match.group(2)

    project_id = str(project_id or "").strip()
    if not project_id or not algorithm_id or not version_id:
        return False

    return request_external_auto_publish_if_enabled(
        data_dir=Path(data_dir),
        algorithms_path=Path(data_dir) / "projects" / project_id / "algorithms.json",
        algorithm_id=algorithm_id,
        version_id=version_id,
        now=str(now or utc_now()),
    )
