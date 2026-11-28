"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, List
from fastapi import HTTPException
from .project_management_contracts import ProjectCreate, ProjectUpdate

import shutil
import uuid
from platform_core.labels import normalize_label_aliases

@dataclass(frozen=True)
class ProjectManagementDependencies:
    ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: Callable[..., Any]
    DEFAULT_PROJECT_ID: Callable[..., Any]
    DEFAULT_PROJECT_NAME: Callable[..., Any]
    PROJECTS_FILE: Callable[..., Any]
    _prune_canonical_label_alias_conflicts: Callable[..., Any]
    default_label_color: Callable[..., Any]
    ensure_project_dirs: Callable[..., Any]
    get_project: Callable[..., Any]
    list_models_internal: Callable[..., Any]
    material_store: Callable[..., Any]
    normalize_label: Callable[..., Any]
    now_iso: Callable[..., Any]
    project_dir: Callable[..., Any]
    read_annotations_many: Callable[..., Any]
    read_json: Callable[..., Any]
    save_project: Callable[..., Any]
    sync_jobs_index: Callable[..., Any]
    write_json: Callable[..., Any]


class ProjectManagementService:
    def __init__(self, dependencies: ProjectManagementDependencies):
        self.dependencies = dependencies

    def list_projects(self, ):
        projects = self.dependencies.read_json(self.dependencies.PROJECTS_FILE(), [])
        projects = projects if isinstance(projects, list) else []
        if self.dependencies.ALLOW_MULTIPLE_PROJECTS_FOR_TESTS():
            return projects
        canonical = next(
            (item for item in projects if str(item.get("id") or "") == self.dependencies.DEFAULT_PROJECT_ID()),
            projects[0] if projects else None,
        )
        if not canonical:
            return []
        return [{**canonical, "name": self.dependencies.DEFAULT_PROJECT_NAME()}]

    def update_project(self, project_id: str, payload: ProjectUpdate):
        project = self.dependencies.get_project(project_id)
        if (
            not self.dependencies.ALLOW_MULTIPLE_PROJECTS_FOR_TESTS()
            and payload.name is not None
            and payload.name.strip() != self.dependencies.DEFAULT_PROJECT_NAME()
        ):
            raise HTTPException(status_code=409, detail="当前仅支持固定的默认空间")
        if payload.name is not None:
            if not payload.name.strip():
                raise HTTPException(status_code=400, detail="项目名称不能为空")
            project["name"] = payload.name.strip()
        if payload.description is not None:
            project["description"] = payload.description or ""
        self.dependencies.save_project(project)
        return project

    def delete_project(self, project_id: str):
        if not self.dependencies.ALLOW_MULTIPLE_PROJECTS_FOR_TESTS():
            raise HTTPException(status_code=409, detail="默认空间不允许删除")
        projects = self.dependencies.read_json(self.dependencies.PROJECTS_FILE(), [])
        if not any(p.get("id") == project_id for p in projects):
            raise HTTPException(status_code=404, detail="项目不存在")
        self.dependencies.write_json(self.dependencies.PROJECTS_FILE(), [p for p in projects if p.get("id") != project_id])
        shutil.rmtree(self.dependencies.project_dir(project_id), ignore_errors=True)
        return {"ok": True}

    def create_project(self, payload: ProjectCreate):
        existing_projects = self.dependencies.read_json(self.dependencies.PROJECTS_FILE(), [])
        existing_projects = existing_projects if isinstance(existing_projects, list) else []
        if not self.dependencies.ALLOW_MULTIPLE_PROJECTS_FOR_TESTS() and existing_projects:
            raise HTTPException(status_code=409, detail="系统仅支持一个默认空间")
        labels = []
        label_meta = []
        raw_label_meta = payload.label_meta or []
        for idx, x in enumerate(payload.labels or []):
            display_name = ""
            color = ""
            aliases: List[str] = []
            if isinstance(x, dict):
                code = self.dependencies.normalize_label(x.get("code") or x.get("name") or x.get("label") or "")
                display_name = str(x.get("display_name") or x.get("zh") or x.get("name") or code)
                color = str(x.get("color") or "")
                try:
                    aliases = normalize_label_aliases(x.get("aliases") or [])
                except ValueError as error:
                    raise HTTPException(status_code=400, detail=f"标签别名无效：{error}") from error
            else:
                code = self.dependencies.normalize_label(x)
                if idx < len(raw_label_meta) and isinstance(raw_label_meta[idx], dict):
                    display_name = str(raw_label_meta[idx].get("display_name") or raw_label_meta[idx].get("name") or code)
                    color = str(raw_label_meta[idx].get("color") or "")
                    try:
                        aliases = normalize_label_aliases(raw_label_meta[idx].get("aliases") or [])
                    except ValueError as error:
                        raise HTTPException(status_code=400, detail=f"标签别名无效：{error}") from error
                else:
                    display_name = code
            if code and code not in labels:
                labels.append(code)
                label_meta.append({
                    "code": code,
                    "display_name": display_name or code,
                    "color": color or self.dependencies.default_label_color(len(labels)-1),
                    "type": "bbox",
                    "hotkey": str(len(labels)) if len(labels) <= 9 else "",
                    "aliases": aliases,
                })
        if self.dependencies.ALLOW_MULTIPLE_PROJECTS_FOR_TESTS() and not payload.name.strip():
            raise HTTPException(status_code=400, detail="项目名称不能为空")
        # 项目创建不再强制填写标签；标签在数据集/标注环节维护。
        pid = uuid.uuid4().hex[:12] if self.dependencies.ALLOW_MULTIPLE_PROJECTS_FOR_TESTS() else self.dependencies.DEFAULT_PROJECT_ID()
        self.dependencies.ensure_project_dirs(pid)
        project = {
            "id": pid,
            "name": payload.name.strip() if self.dependencies.ALLOW_MULTIPLE_PROJECTS_FOR_TESTS() else self.dependencies.DEFAULT_PROJECT_NAME(),
            "description": payload.description or "",
            "labels": labels,
            "label_meta": label_meta,
            "created_at": self.dependencies.now_iso(),
            "updated_at": self.dependencies.now_iso(),
        }
        self.dependencies._prune_canonical_label_alias_conflicts(project)
        self.dependencies.save_project(project)
        self.dependencies.material_store(pid).mutate(lambda rows: rows.clear())
        return project

    def read_project(self, project_id: str):
        project = self.dependencies.get_project(project_id)
        # The legacy response only needs the image count plus GT totals; reading
        # ids (not every payload document) keeps the same response with far less
        # hydration on 100k+ projects.
        image_ids = self.dependencies.material_store(project_id).list_all_ids()
        jobs = self.dependencies.sync_jobs_index(project_id, read_only=True)
        models = self.dependencies.list_models_internal(project_id)
        annotated = 0
        boxes = 0
        # Batched formal-GT reads keep the legacy totals exactly, but replace the
        # previous one-connection-per-image N+1 with ceil(N/500) queries. The batch
        # reader keeps the same legacy JSON fallback as read_annotation().
        for offset in range(0, len(image_ids), 500):
            for ann in self.dependencies.read_annotations_many(project_id, image_ids[offset:offset + 500]).values():
                cnt = len(ann.get("boxes", []))
                boxes += cnt
                if cnt:
                    annotated += 1
        return {"project": project, "images": len(image_ids), "annotated_images": annotated, "boxes": boxes, "jobs": jobs, "models": models}
