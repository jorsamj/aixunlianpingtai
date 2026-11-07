"""Read-only independent-evaluation preview diagnostics.

Run this on the platform host so it uses the configured repositories and storage
providers. It never writes evaluation, Snapshot, Material, annotation, or label
records and never emits image bytes, object keys, credentials, or local paths.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter

from fastapi import HTTPException

import app as platform


def diagnose(project_id: str, algorithm_id: str, version_id: str) -> dict:
    _algorithm, version = platform._algorithm_version_for_action(
        project_id, algorithm_id, version_id,
    )
    evaluation = version.get("evaluation") or {}
    samples = [row for row in evaluation.get("error_samples") or [] if isinstance(row, dict)]
    snapshot_id = str(evaluation.get("snapshot_id") or "").lower()
    snapshot_path = platform.project_dir(project_id) / "snapshots" / f"{snapshot_id}.json"
    task_id = str(evaluation.get("task_id") or version.get("job_id") or "")
    bundle_manifest_exists = False
    if re.fullmatch(r"[A-Za-z0-9_-]{1,160}", task_id):
        bundle_manifest_exists = platform.shared_task_artifacts().artifact_path(
            task_id, "work/bundle/manifest.json",
        ).is_file()

    codes: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    results = []
    for sample in samples:
        image_name = str(sample.get("image") or "")
        row = {
            "image": image_name,
            "image_id": str(sample.get("image_id") or ""),
            "previewable": False,
            "retryable": False,
            "code": "PREVIEW_UNAVAILABLE",
        }
        try:
            response = platform.evaluation_diagnostic_image_v1(
                project_id, algorithm_id, version_id, image_name,
            )
            source = str(response.headers.get("x-evaluation-evidence-source") or "verified")
            row.update(previewable=True, code="OK", evidence_source=source)
            sources[source] += 1
            codes["OK"] += 1
            statuses['200'] += 1
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail, dict) else {}
            code = str(detail.get("code") or f"HTTP_{error.status_code}")
            row.update(code=code, retryable=detail.get("retryable") is True)
            codes[code] += 1
            statuses[str(error.status_code)] += 1
        results.append(row)

    previewable = codes.get("OK", 0)
    retryable = sum(1 for row in results if row["retryable"])
    return {
        "project_id": project_id,
        "algorithm_id": algorithm_id,
        "version_id": version_id,
        "evaluation_id": str(evaluation.get("evaluation_id") or ""),
        "snapshot_id": snapshot_id,
        "snapshot_exists": bool(re.fullmatch(r"[0-9a-f]{64}", snapshot_id) and snapshot_path.is_file()),
        "bundle_manifest_exists": bundle_manifest_exists,
        "problem_image_count": len(samples),
        "previewable_count": previewable,
        "retryable_count": retryable,
        "requires_evidence_recovery_count": len(samples) - previewable - retryable,
        "http_status_distribution": dict(sorted(statuses.items())),
        "error_code_distribution": dict(sorted(codes.items())),
        "verified_source_distribution": dict(sorted(sources.items())),
        "images": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="只读汇总独立评测问题图片的冻结身份、存储读取和预览错误码。",
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--algorithm-id", required=True)
    parser.add_argument("--version-id", required=True)
    args = parser.parse_args()
    print(json.dumps(
        diagnose(args.project_id, args.algorithm_id, args.version_id),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
