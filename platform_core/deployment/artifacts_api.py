"""Model artifact queries over the existing conversion/deployment job projection.

Read-only: the conversion job projection stays the single owner of job state and
the host application's existing business-file authorization stays the single
owner of file access. This module only lists already-produced artifacts and
serves one artifact file; it never writes job state.
"""
from __future__ import annotations

from pathlib import Path

import requests
from fastapi import APIRouter, HTTPException

# Artifact types the existing UI can display/download as model deliverables.
_ARTIFACT_EXTENSIONS = frozenset({
    "onnx", "engine", "bmodel", "om", "rknn", "pdmodel", "pdiparams",
    "json", "yml", "yaml",
})


def create_deploy_artifact_router(
    *,
    list_jobs,
    resolve_business_file,
    business_file_response,
) -> APIRouter:
    """Build the deploy-artifact router with host-owned dependencies.

    ``list_jobs(project_id)`` returns the existing conversion/deployment job
    records; ``resolve_business_file``/``business_file_response`` are the
    host's existing authorization-aware business-file accessors.
    """
    router = APIRouter()

    @router.get("/api/v39/projects/{project_id}/deploy/artifacts")
    def v39_list_deploy_artifacts(project_id: str):
        rows = []
        for j in list_jobs(project_id):
            if j.get("status") not in {"done", "blocked_by_hardware"}:
                continue
            for o in j.get("outputs", []) or []:
                p = Path(str(o.get("path") or ""))
                if not p.exists():
                    continue
                ext = p.suffix.lower().lstrip('.')
                if ext not in _ARTIFACT_EXTENSIONS:
                    continue
                try:
                    resolve_business_file(project_id, 'deployment', f"jobs/{j.get('id')}/{o.get('rel') or ''}")
                except HTTPException:
                    continue
                rows.append({**o, "job_id": j.get("id"), "target": j.get("target"), "resource_name": j.get("resource", {}).get("name"), "source_name": j.get("source_name"), "params": j.get("params", {}), "created_at": j.get("finished_at") or j.get("created_at"), "download_url": f"/api/v39/projects/{project_id}/deploy/jobs/{j.get('id')}/artifact?rel={requests.utils.quote(str(o.get('rel') or ''))}"})
        return {"ok": True, "items": rows}

    @router.get("/api/v39/projects/{project_id}/deploy/jobs/{job_id}/artifact")
    def v39_download_deploy_artifact(project_id: str, job_id: str, rel: str):
        return business_file_response(project_id, 'deployment', f'jobs/{job_id}/{rel}', download=True)

    return router
