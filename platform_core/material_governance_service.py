"""Existing governance orchestration. Persistence, locks and receipts retain their original owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Mapping, Tuple
from fastapi import HTTPException
from .material_governance_contracts import BatchImageSplitReq, BatchSplitReq, ImagePatchReq, V46BatchDeleteImagesReq, V52ReadyReq

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import material_dataset_matches
from platform_core.materials import mark_ready

@dataclass(frozen=True)
class MaterialGovernanceDependencies:
    _V50DatasetSourceChanged: Any
    _require_material_delete_preview: Callable[..., Any]
    _v50_assert_dataset_writable_locked: Callable[..., Any]
    _v50_dataset_locks: Callable[..., Any]
    get_project: Callable[..., Any]
    load_images: Callable[..., Any]
    material_store: Callable[..., Any]
    now_iso: Callable[..., Any]
    project_dir: Callable[..., Any]
    read_annotation: Callable[..., Any]


class MaterialGovernanceService:
    def __init__(self, dependencies: MaterialGovernanceDependencies):
        self.dependencies = dependencies

    def delete_dataset(self, project_id: str, dataset_id: str):
        self.dependencies.get_project(project_id)
        self.dependencies._require_material_delete_preview(project_id)

    def delete_image(self,
        project_id: str, image_id: str,
        delete_source: Optional[bool] = None, confirmation: str = "",
    ):
        self.dependencies.get_project(project_id)
        self.dependencies._require_material_delete_preview(project_id)

    def v46_batch_delete_images(self, project_id: str, payload: V46BatchDeleteImagesReq):
        self.dependencies.get_project(project_id)
        self.dependencies._require_material_delete_preview(project_id)

    def v12_patch_image(self, project_id: str, image_id: str, payload: ImagePatchReq):
        self.dependencies.get_project(project_id)
        patch = {"updated_at": self.dependencies.now_iso()}
        if payload.split is not None:
            split = (payload.split or "unassigned").lower()
            if split not in {"train", "val", "test", "unassigned"}:
                raise HTTPException(status_code=400, detail="数据用途只能是未处理、训练集、试验集或评测集")
            patch["split"] = split
        if payload.dataset_id is not None:
            target_dataset_id = payload.dataset_id or "default"
            patch["dataset_id"] = target_dataset_id
            for _attempt in range(16):
                current = self.dependencies.material_store(project_id).get(image_id)
                if current is None:
                    raise HTTPException(status_code=404, detail="图片不存在")
                source_dataset_id = str(current.get("dataset_id") or "default")
                try:
                    with self.dependencies._v50_dataset_locks(
                        project_id, [source_dataset_id, target_dataset_id]
                    ):
                        self.dependencies._v50_assert_dataset_writable_locked(
                            project_id, source_dataset_id
                        )
                        if target_dataset_id != source_dataset_id:
                            self.dependencies._v50_assert_dataset_writable_locked(
                                project_id, target_dataset_id
                            )

                        def apply_dataset_patch(rows):
                            for row in rows:
                                if str(row.get("id")) != str(image_id):
                                    continue
                                latest_source = str(
                                    row.get("dataset_id") or "default"
                                )
                                if latest_source != source_dataset_id:
                                    raise self.dependencies._V50DatasetSourceChanged()
                                row.update(patch)
                                return dict(row)
                            raise HTTPException(status_code=404, detail="图片不存在")

                        changed = self.dependencies.material_store(project_id).mutate_ids(
                            [image_id], apply_dataset_patch
                        )
                    break
                except self.dependencies._V50DatasetSourceChanged:
                    continue
            else:
                raise HTTPException(
                    status_code=409,
                    detail="图片所属数据集频繁变化，请重试",
                )
        else:
            changed = self.dependencies.material_store(project_id).patch({image_id: patch})
        if not changed:
            raise HTTPException(status_code=404, detail="图片不存在")
        return {"ok": True}

    def v20_batch_image_split(self, project_id: str, payload: BatchImageSplitReq):
        self.dependencies.get_project(project_id)
        split = (payload.split or "unassigned").lower()
        if split not in {"train", "val", "test", "unassigned"}:
            raise HTTPException(status_code=400, detail="数据用途只能是未处理、训练集、试验集或评测集")
        target_ids = {str(image_id) for image_id in (payload.image_ids or [])}
        scope = (payload.scope or "selected").lower()
        dataset_id = payload.dataset_id or None
        filt = (payload.filter or "all").lower()
        updated = self.dependencies.now_iso()
        materials = self.dependencies.material_store(project_id)

        if scope == "selected":
            if not target_ids:
                raise HTTPException(status_code=400, detail="请先选择要移动的素材")
            changed_rows = materials.patch({
                image_id: {"split": split, "updated_at": updated}
                for image_id in target_ids
            })
            if not changed_rows:
                raise HTTPException(status_code=400, detail="没有匹配到可移动的素材")
            return {"ok": True, "changed": len(changed_rows), "split": split}

        annotation_box_counts = {}
        if scope == "filtered" and filt in {"marked", "unmarked"}:
            images = self.dependencies.load_images(project_id)
            image_ids = [str(img.get("id") or "") for img in images if str(img.get("id") or "")]
            annotations = AnnotationRepository(self.dependencies.project_dir(project_id))
            for offset in range(0, len(image_ids), 500):
                batch_ids = image_ids[offset:offset + 500]
                for image_id, annotation in annotations.get_many(batch_ids).items():
                    annotation_box_counts[str(image_id)] = len(annotation.get("boxes", []))

        def match_latest(img: Dict[str, Any]) -> bool:
            if not material_dataset_matches(img, dataset_id):
                return False
            if scope == "dataset":
                return True
            if scope == "filtered":
                image_id = str(img.get("id"))
                cur_split = (img.get("split") or "unassigned").lower()
                if filt == "marked":
                    box_count = annotation_box_counts.get(image_id)
                    return box_count is not None and box_count > 0
                if filt == "unmarked":
                    # A row appearing after annotation facts were read is unknown,
                    # not proven empty, so both annotation filters exclude it.
                    box_count = annotation_box_counts.get(image_id)
                    return box_count is not None and box_count == 0
                if filt in {"train", "val", "test", "unassigned"}:
                    return cur_split == filt
                return True
            return str(img.get("id")) in target_ids

        def apply_split(rows):
            changed = 0
            for img in rows:
                if not match_latest(img):
                    continue
                img["split"] = split
                img["updated_at"] = updated
                changed += 1
            if not changed:
                raise HTTPException(status_code=400, detail="没有匹配到可移动的素材")
            return changed

        if scope == "dataset":
            changed = materials.mutate_dataset(dataset_id, apply_split)
        else:
            changed = materials.mutate(apply_split)
        return {"ok": True, "changed": changed, "split": split}

    def v12_auto_split(self, project_id: str, dataset_id: str, payload: BatchSplitReq):
        self.dependencies.get_project(project_id)
        annotation_presence = {}
        if not payload.include_unannotated:
            for img in self.dependencies.load_images(project_id):
                image_id = str(img.get("id"))
                annotation_presence[image_id] = bool(
                    self.dependencies.read_annotation(project_id, image_id).get("boxes")
                )

        def apply_auto_split(rows):
            images = [
                img
                for img in rows
                if img.get("dataset_id", "default") == dataset_id
                and (
                    payload.include_unannotated
                    or annotation_presence.get(str(img.get("id")), False)
                )
            ]
            if not images:
                raise HTTPException(status_code=400, detail="该数据集暂无图片")
            images.sort(key=lambda img: str(img.get("id", "")))
            total = len(images)
            train_n = max(1, int(total * payload.train))
            val_n = max(0, int(total * payload.val))
            if train_n + val_n > total:
                val_n = max(0, total - train_n)
            counts = {"train": 0, "val": 0, "test": 0}
            for index, img in enumerate(images):
                if index < train_n:
                    split = "train"
                elif index < train_n + val_n:
                    split = "val"
                else:
                    split = "test"
                img["split"] = split
                counts[split] += 1
            return counts

        counts = self.dependencies.material_store(project_id).mutate(apply_auto_split)
        return {"ok": True, "counts": counts}

    def v52_mark_ready(self, project_id: str, payload: V52ReadyReq):
        self.dependencies.get_project(project_id)
        ids = list(dict.fromkeys(
            str(value).strip() for value in (payload.image_ids or []) if str(value).strip()
        ))
        if not ids:
            return {'ok': True, 'changed': 0, 'image_ids': [], 'images': []}
        now = self.dependencies.now_iso()
        materials = self.dependencies.material_store(project_id)
        current = materials.get_many(ids)
        existing_ids = [str(row.get('id')) for row in current if str(row.get('id') or '')]
        patch = {
            'processing_status': 'processed',
            'clean_skipped': True,
            'clean_decision': 'skipped',
            'clean_decision_at': now,
            'updated_at': now,
        }
        materials.patch_many(existing_ids, patch, batch_size=500)
        changed_images = [mark_ready(row, now) for row in current]
        return {
            'ok': True,
            'changed': len(existing_ids),
            'image_ids': existing_ids,
            'images': changed_images,
        }

    def v49_mark_processed(self, project_id: str, payload: V46BatchDeleteImagesReq):
        ids={str(x) for x in payload.image_ids or []}; cleaned_at=self.dependencies.now_iso()
        def apply_processed(rows):
            changed=0
            for img in rows:
                if str(img.get('id')) in ids:
                    img['processing_status']='processed';img['cleaned_at']=cleaned_at;changed+=1
            return changed
        # Measured crossover on 50k rows: 5k explicit IDs is faster through
        # mutate_ids (1.33s vs 2.17s); 10k is already slower (3.45s vs 2.94s).
        # Keep the one full-table transaction above the measured boundary.
        if len(ids)<=5000:
            changed=self.dependencies.material_store(project_id).mutate_ids(ids,apply_processed)
        else:
            changed=self.dependencies.material_store(project_id).mutate(apply_processed)
        return {'ok':True,'changed':changed}
