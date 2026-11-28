"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from fastapi import HTTPException
from .dataset_export_contracts import BuildDatasetReq, BuildPaddleDatasetReq

import json
import shutil
import uuid
import random
from datetime import datetime
from pathlib import Path
import yaml
from fastapi.responses import FileResponse
from platform_core.snapshots import is_training_ground_truth
from platform_core.training_create_api import TrainReq

@dataclass(frozen=True)
class DatasetExportDependencies:
    _authorize_business_file_project: Callable[..., Any]
    box_to_yolo_line: Callable[..., Any]
    dataset_quality_report: Callable[..., Any]
    get_project: Callable[..., Any]
    load_images: Callable[..., Any]
    normalize_box_for_project: Callable[..., Any]
    normalize_label: Callable[..., Any]
    project_dir: Callable[..., Any]
    read_annotation: Callable[..., Any]
    resolve_material_path: Callable[..., Any]
    zip_dir: Callable[..., Any]


class DatasetExportService:
    def __init__(self, dependencies: DatasetExportDependencies):
        self.dependencies = dependencies

    def build_dataset(self, project_id: str, payload: BuildDatasetReq):
        project = self.dependencies.get_project(project_id)
        p = self.dependencies.project_dir(project_id)
        images = self.dependencies.load_images(project_id)
        if payload.dataset_id:
            images = [img for img in images if img.get("dataset_id", "default") == payload.dataset_id]
        selected = []
        empty_count = 0
        for img in images:
            ann = self.dependencies.read_annotation(project_id, img["id"])
            if is_training_ground_truth(ann.get("annotation_state"), ann.get("boxes") or []):
                selected.append((img, ann))
                if ann.get("annotation_state") == "confirmed_empty":
                    empty_count += 1
        if not selected:
            raise HTTPException(status_code=400, detail="没有可生成的数据。请先完成标注；无目标图片请先明确“确认无目标”。")
        ratio = max(0.5, min(float(payload.train_ratio), 0.95))
        selected = sorted(selected, key=lambda x: x[0]["id"])
        if len(selected) == 1:
            train_items = selected
            val_items = selected
        else:
            split = max(1, min(len(selected) - 1, int(len(selected) * ratio)))
            train_items = selected[:split]
            val_items = selected[split:]
        dataset = p / "dataset"
        if dataset.exists():
            shutil.rmtree(dataset)
        for sub in ["images/train", "images/val", "labels/train", "labels/val"]:
            (dataset / sub).mkdir(parents=True, exist_ok=True)
        counts = {"train": 0, "val": 0, "boxes": 0, "empty_images": empty_count}

        def copy_items(items: List[Tuple[Dict[str, Any], Dict[str, Any]]], part: str):
            for img, ann in items:
                src = self.dependencies.resolve_material_path(project_id, img)
                dst_img = dataset / "images" / part / img["stored_name"]
                shutil.copy2(src, dst_img)
                label_path = dataset / "labels" / part / f"{Path(img['stored_name']).stem}.txt"
                lines = []
                for b in ann.get("boxes", []):
                    if int(b.get("class_id", -1)) < 0 or int(b.get("class_id", -1)) >= len(project["labels"]):
                        continue
                    lines.append(self.dependencies.box_to_yolo_line(b, img["width"], img["height"]))
                    counts["boxes"] += 1
                label_path.write_text("\n".join(lines), encoding="utf-8")
                counts[part] += 1

        copy_items(train_items, "train")
        copy_items(val_items, "val")
        data_yaml = {
            "path": str(dataset).replace("\\", "/"),
            "train": "images/train",
            "val": "images/val",
            "names": {i: label for i, label in enumerate(project["labels"])},
        }
        yaml_path = dataset / "data.yaml"
        yaml_path.write_text(yaml.safe_dump(data_yaml, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return {"ok": True, "dataset": str(dataset), "data_yaml": str(yaml_path), "counts": counts, "labels": project["labels"]}

    def download_dataset(self, project_id: str):
        self.dependencies._authorize_business_file_project(project_id)
        dataset = self.dependencies.project_dir(project_id) / "dataset"
        yaml_path = dataset / "data.yaml"
        if not yaml_path.exists():
            raise HTTPException(status_code=404, detail="请先生成数据集")
        zip_path = self.dependencies.project_dir(project_id) / "exports" / "yolo_dataset.zip"
        self.dependencies.zip_dir(dataset, zip_path)
        return FileResponse(zip_path, filename=f"{project_id}_yolo_dataset.zip")

    def _coco_image_item(self, img: Dict[str, Any], idx: int, file_name: str) -> Dict[str, Any]:
        return {
            "id": idx,
            "file_name": file_name,
            "width": int(img["width"]),
            "height": int(img["height"]),
        }

    def _coco_ann_item(self, ann_id: int, img_id: int, b: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            x1 = float(b["x1"]); y1 = float(b["y1"]); x2 = float(b["x2"]); y2 = float(b["y2"])
            w = max(0.0, x2 - x1); h = max(0.0, y2 - y1)
            if w < 1 or h < 1:
                return None
            return {
                "id": ann_id,
                "image_id": img_id,
                "category_id": int(b["class_id"]) + 1,
                "bbox": [round(x1, 2), round(y1, 2), round(w, 2), round(h, 2)],
                "area": round(w * h, 2),
                "iscrowd": 0,
                "segmentation": [],
            }
        except Exception:
            return None

    def build_paddle_dataset_internal(self, project_id: str, train_ratio: float = 0.8, include_empty: bool = False, dataset_id: Optional[str] = None) -> Dict[str, Any]:
        """Export internal annotations to a COCO-style dataset usable by PaddleX/PaddleDetection."""
        project = self.dependencies.get_project(project_id)
        p = self.dependencies.project_dir(project_id)
        images = self.dependencies.load_images(project_id)
        if dataset_id:
            images = [img for img in images if img.get("dataset_id", "default") == dataset_id]
        selected: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        empty_count = 0
        for img in images:
            ann = self.dependencies.read_annotation(project_id, img["id"])
            if is_training_ground_truth(ann.get("annotation_state"), ann.get("boxes") or []):
                selected.append((img, ann))
                if ann.get("annotation_state") == "confirmed_empty":
                    empty_count += 1
        if not selected:
            raise HTTPException(status_code=400, detail="没有可生成的飞桨数据。请先完成标注；无目标图片请先明确“确认无目标”。")
        ratio = max(0.5, min(float(train_ratio), 0.95))
        selected = sorted(selected, key=lambda x: x[0]["id"])
        if len(selected) == 1:
            train_items = selected
            val_items = selected
        else:
            split = max(1, min(len(selected) - 1, int(len(selected) * ratio)))
            train_items = selected[:split]
            val_items = selected[split:]

        dataset = p / "paddle_dataset"
        if dataset.exists():
            shutil.rmtree(dataset)
        for sub in ["images/train", "images/val", "annotations"]:
            (dataset / sub).mkdir(parents=True, exist_ok=True)

        labels = [str(x) for x in project.get("labels", []) if str(x).strip()]
        if not labels:
            raise HTTPException(status_code=400, detail="当前项目没有标签，无法生成飞桨数据集。请先在标签库中添加类别。")
        # PaddleDetection + COCO：categories 使用 1-based id；模型输出 class index 是 0-based，
        # PaddleDetection 会按 categories 顺序建立 label_to_cat_id_map。
        # 关键是：annotation.category_id 必须只出现在 categories 里，同时训练配置 num_classes 必须等于 len(labels)。
        categories = [{"id": i + 1, "name": label, "supercategory": "object"} for i, label in enumerate(labels)]
        counts = {"train": 0, "val": 0, "boxes": 0, "train_boxes": 0, "val_boxes": 0, "empty_images": empty_count, "class_count": len(labels)}

        def write_part(items: List[Tuple[Dict[str, Any], Dict[str, Any]]], part: str, json_name: str):
            coco_images = []
            coco_anns = []
            ann_id = 1
            for idx, (img, ann) in enumerate(items, start=1):
                src = self.dependencies.resolve_material_path(project_id, img)
                dst_name = img["stored_name"]
                dst = dataset / "images" / part / dst_name
                shutil.copy2(src, dst)
                coco_images.append(self._coco_image_item(img, idx, f"images/{part}/{dst_name}"))
                for b in ann.get("boxes", []):
                    cid = int(b.get("class_id", -1))
                    if cid < 0 or cid >= len(labels):
                        continue
                    item = self._coco_ann_item(ann_id, idx, b)
                    if item:
                        # 再次兜底：确保 COCO category_id 落在 categories 里，避免评估阶段 KeyError。
                        if int(item.get("category_id", -1)) not in {c["id"] for c in categories}:
                            continue
                        coco_anns.append(item)
                        ann_id += 1
                        counts["boxes"] += 1
                        counts[f"{part}_boxes"] += 1
                counts[part] += 1
            payload = {"images": coco_images, "annotations": coco_anns, "categories": categories}
            out = dataset / "annotations" / json_name
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return str(out)

        train_json = write_part(train_items, "train", "instance_train.json")
        val_json = write_part(val_items, "val", "instance_val.json")
        label_list = dataset / "label_list.txt"
        label_list.write_text("\n".join(project.get("labels", [])), encoding="utf-8")
        readme = dataset / "README.txt"
        readme.write_text(
            "这是平台导出的 COCO/Paddle 数据集。\n"
        "常见用途：PaddleX/PaddleDetection 训练。\n"
        "训练集标注：annotations/instance_train.json\n"
        "验证集标注：annotations/instance_val.json\n"
        "图片目录：images/train、images/val\n",
            encoding="utf-8",
        )
        return {
            "ok": True,
            "dataset": str(dataset),
            "train_json": train_json,
            "val_json": val_json,
            "label_list": str(label_list),
            "counts": counts,
            "labels": labels,
            "message": "已生成飞桨/COCO格式数据集。可用于 PaddleX/PaddleDetection 训练命令。",
        }

    def build_paddle_dataset(self, project_id: str, payload: BuildPaddleDatasetReq):
        return self.build_paddle_dataset_internal(project_id, payload.train_ratio, payload.include_empty, getattr(payload, "dataset_id", None))

    def download_paddle_dataset(self, project_id: str):
        self.dependencies._authorize_business_file_project(project_id)
        dataset = self.dependencies.project_dir(project_id) / "paddle_dataset"
        if not (dataset / "annotations" / "instance_train.json").exists():
            raise HTTPException(status_code=404, detail="请先生成飞桨/COCO数据集")
        zip_path = self.dependencies.project_dir(project_id) / "exports" / "paddle_coco_dataset.zip"
        self.dependencies.zip_dir(dataset, zip_path)
        return FileResponse(zip_path, filename=f"{project_id}_paddle_coco_dataset.zip")

    def dataset_items_by_split(self, project_id: str, dataset_id: Optional[str], include_empty: bool = False) -> Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]]:
        images = self.dependencies.load_images(project_id)
        if dataset_id:
            images = [img for img in images if img.get("dataset_id", "default") == dataset_id]
        result = {"train": [], "val": [], "test": []}
        for img in sorted(images, key=lambda x: x.get("id", "")):
            ann = self.dependencies.read_annotation(project_id, img["id"])
            if not is_training_ground_truth(ann.get("annotation_state"), ann.get("boxes") or []):
                continue
            split = (img.get("split") or "train").lower()
            if split not in result:
                split = "train"
            result[split].append((img, ann))
        # 若用户只传了训练集，自动给评测集兜底，避免 YOLO val 为空
        if not result["val"] and result["train"]:
            result["val"] = result["train"][-max(1, min(len(result["train"]), max(1, len(result["train"]) // 5))):]
        if not result["test"]:
            result["test"] = []
        return result

    def build_yolo_dataset_v12(self, project_id: str, dataset_id: Optional[str] = None, include_empty: bool = False) -> Dict[str, Any]:
        project = self.dependencies.get_project(project_id)
        p = self.dependencies.project_dir(project_id)
        parts = self.dataset_items_by_split(project_id, dataset_id, include_empty)
        if not any(parts.values()):
            raise HTTPException(status_code=400, detail="没有可训练数据。请先上传并标注图片。")
        # 训练前质检：有图片不等于有训练目标，必须有有效标注框。
        report = self.dependencies.dataset_quality_report(project_id, dataset_id, include_empty)
        if not report.get("can_train"):
            raise HTTPException(status_code=400, detail="当前数据集没有有效训练框：" + "；".join(report.get("warnings", [])))
        dataset = p / "dataset"
        if dataset.exists():
            shutil.rmtree(dataset)
        for sub in ["images/train", "images/val", "images/test", "labels/train", "labels/val", "labels/test"]:
            (dataset / sub).mkdir(parents=True, exist_ok=True)
        counts = {"train": 0, "val": 0, "test": 0, "boxes": 0, "train_boxes": 0, "val_boxes": 0, "test_boxes": 0, "invalid_boxes": 0}
        for part, items in parts.items():
            for img, ann in items:
                src = self.dependencies.resolve_material_path(project_id, img)
                clean = []
                for b in ann.get("boxes", []):
                    nb = self.dependencies.normalize_box_for_project(project_id, img, b, create_label=False)
                    if nb:
                        clean.append(nb)
                    else:
                        counts["invalid_boxes"] += 1
                if not is_training_ground_truth(ann.get("annotation_state"), clean):
                    continue
                shutil.copy2(src, dataset / "images" / part / img["stored_name"])
                lines = []
                for b in clean:
                    lines.append(self.dependencies.box_to_yolo_line(b, img["width"], img["height"]))
                (dataset / "labels" / part / f"{Path(img['stored_name']).stem}.txt").write_text("\n".join(lines), encoding="utf-8")
                counts[part] += 1
                counts["boxes"] += len(lines)
                counts[f"{part}_boxes"] += len(lines)
        if counts["train_boxes"] == 0:
            raise HTTPException(status_code=400, detail="训练集没有有效标注框，请先在数据集里保存标注并重新生成训练文件。")
        if counts["val_boxes"] == 0 and counts["train_boxes"] > 0:
            # 兜底：若评测集为空，用训练集副本做 val，保证 Ultralytics 不会出现 no labels found。
            for f in (dataset / "images" / "train").glob("*"):
                shutil.copy2(f, dataset / "images" / "val" / f.name)
            for f in (dataset / "labels" / "train").glob("*.txt"):
                shutil.copy2(f, dataset / "labels" / "val" / f.name)
            counts["val"] = counts["train"]
            counts["val_boxes"] = counts["train_boxes"]
        data_yaml = {
            "path": str(dataset).replace("\\", "/"),
            "train": "images/train",
            "val": "images/val",
            "test": "images/test",
            "names": {i: label for i, label in enumerate(self.dependencies.get_project(project_id).get("labels", []))},
        }
        yaml_path = dataset / "data.yaml"
        yaml_path.write_text(yaml.safe_dump(data_yaml, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return {"ok": True, "dataset": str(dataset), "data_yaml": str(yaml_path), "counts": counts, "labels": self.dependencies.get_project(project_id).get("labels", []), "quality": report}

    def v12_build_dataset(self, project_id: str, payload: BuildDatasetReq):
        return self.build_yolo_dataset_v12(project_id, payload.dataset_id, payload.include_empty)

    def build_coco_dataset_v12(self, project_id: str, dataset_id: Optional[str] = None, include_empty: bool = False) -> Dict[str, Any]:
        project = self.dependencies.get_project(project_id)
        p = self.dependencies.project_dir(project_id)
        parts = self.dataset_items_by_split(project_id, dataset_id, include_empty)
        if not any(parts.values()):
            raise HTTPException(status_code=400, detail="没有可导出的数据")
        dataset = p / "paddle_dataset"
        if dataset.exists():
            shutil.rmtree(dataset)
        for sub in ["images/train", "images/val", "images/test", "annotations"]:
            (dataset / sub).mkdir(parents=True, exist_ok=True)
        categories = [{"id": i + 1, "name": label, "supercategory": "object"} for i, label in enumerate(project.get("labels", []))]
        counts = {"train": 0, "val": 0, "test": 0, "boxes": 0}
        def write_part(part: str, json_name: str):
            coco_images = []; coco_anns = []; ann_id = 1
            for idx, (img, ann) in enumerate(parts[part], start=1):
                src = self.dependencies.resolve_material_path(project_id, img)
                shutil.copy2(src, dataset / "images" / part / img["stored_name"])
                coco_images.append(self._coco_image_item(img, idx, f"images/{part}/{img['stored_name']}"))
                for b in ann.get("boxes", []):
                    item = self._coco_ann_item(ann_id, idx, b)
                    if item:
                        coco_anns.append(item); ann_id += 1; counts["boxes"] += 1
                counts[part] += 1
            out = dataset / "annotations" / json_name
            out.write_text(json.dumps({"images": coco_images, "annotations": coco_anns, "categories": categories}, ensure_ascii=False, indent=2), encoding="utf-8")
            return str(out)
        train_json = write_part("train", "instance_train.json")
        val_json = write_part("val", "instance_val.json")
        test_json = write_part("test", "instance_test.json")
        label_list = dataset / "label_list.txt"
        label_list.write_text("\n".join(project.get("labels", [])), encoding="utf-8")
        return {"ok": True, "dataset": str(dataset), "train_json": train_json, "val_json": val_json, "test_json": test_json, "label_list": str(label_list), "counts": counts, "labels": project.get("labels", [])}

    def v12_export_dataset(self, project_id: str, dataset_id: str, fmt: str):
        self.dependencies._authorize_business_file_project(project_id)
        fmt = fmt.lower()
        if fmt in {"yolo", "ultralytics"}:
            build = self.build_yolo_dataset_v12(project_id, dataset_id, include_empty=True)
            src = Path(build["dataset"])
            filename = f"{project_id}_{dataset_id}_YOLO数据集.zip"
        elif fmt in {"coco", "paddle"}:
            build = self.build_coco_dataset_v12(project_id, dataset_id, include_empty=True)
            src = Path(build["dataset"])
            filename = f"{project_id}_{dataset_id}_COCO数据集.zip"
        else:
            raise HTTPException(status_code=400, detail="导出格式只支持 YOLO 或 COCO")
        zip_path = self.dependencies.project_dir(project_id) / "exports" / filename
        self.dependencies.zip_dir(src, zip_path)
        return FileResponse(zip_path, filename=filename)

    def build_yolo_dataset_v44(self, project_id: str, payload: TrainReq) -> Dict[str, Any]:
        """Build one immutable training snapshot from the project's single logical data pool.
    train uses split=train, validation/试验集 uses split=val, final evaluation uses split=test.
    Optional label filters only select samples; source annotations are never modified.
    """
        project = self.dependencies.get_project(project_id)
        p = self.dependencies.project_dir(project_id)
        train_filter = {self.dependencies.normalize_label(x) for x in (payload.train_labels or []) if self.dependencies.normalize_label(x)}
        val_filter = {self.dependencies.normalize_label(x) for x in (payload.val_labels or []) if self.dependencies.normalize_label(x)}
        train_ids = set(payload.train_image_ids or [])
        val_ids = set(payload.val_image_ids or [])
        groups = {"train": [], "val": [], "test": []}
        requested_ids = {str(value) for value in (payload.selected_image_ids or []) if str(value).strip()}
        split_seed = int(payload.seed or 0)
        # The product training flow sends one candidate pool and asks the backend
        # to draw a fresh experiment set for this run.  A non-zero seed keeps the
        # run reproducible; the default seed deliberately uses secure entropy so
        # repeated runs do not reuse the same holdout by accident.
        random_pool = bool(payload.random_experiment_split and requested_ids)
        if random_pool:
            if not split_seed:
                split_seed = random.SystemRandom().randrange(1, 2**31 - 1)
            candidates = []
            combined_filter = train_filter | val_filter
            for img in sorted(self.dependencies.load_images(project_id), key=lambda x: x.get("id", "")):
                if str(img.get("id")) not in requested_ids:
                    continue
                source_split = (img.get("split") or "unassigned").lower()
                # Only persisted training/experiment roles can enter a run; test
                # and unassigned materials stay available for later assignment.
                if source_split not in {"train", "val", "unassigned"}:
                    continue
                ann = self.dependencies.read_annotation(project_id, img["id"])
                clean = []
                for b in ann.get("boxes", []):
                    nb = self.dependencies.normalize_box_for_project(project_id, img, b, create_label=False)
                    if nb:
                        clean.append(nb)
                if not is_training_ground_truth(ann.get("annotation_state"), clean):
                    continue
                labs = {str(b.get("label") or "") for b in clean}
                if combined_filter and not labs.intersection(combined_filter):
                    continue
                candidates.append((img, {"boxes": clean}))
            random.Random(split_seed).shuffle(candidates)
            if len(candidates) >= 2:
                val_count = max(1, min(len(candidates) - 1, round(len(candidates) * float(payload.experiment_percent) / 100.0)))
                groups["val"] = candidates[:val_count]
                groups["train"] = candidates[val_count:]
        else:
            for img in sorted(self.dependencies.load_images(project_id), key=lambda x: x.get("id", "")):
                split = (img.get("split") or "unassigned").lower()
                if split not in groups:
                    continue
                if split == "train" and train_ids and img.get("id") not in train_ids:
                    continue
                if split == "val" and val_ids and img.get("id") not in val_ids:
                    continue
                ann = self.dependencies.read_annotation(project_id, img["id"])
                clean=[]
                for b in ann.get("boxes", []):
                    nb=self.dependencies.normalize_box_for_project(project_id,img,b,create_label=False)
                    if nb: clean.append(nb)
                if not is_training_ground_truth(ann.get("annotation_state"), clean):
                    continue
                labs={str(b.get("label") or "") for b in clean}
                filt=train_filter if split=="train" else val_filter if split=="val" else set()
                if filt and not labs.intersection(filt):
                    continue
                groups[split].append((img,{"boxes":clean}))
        if payload.train_max_samples and payload.train_max_samples>0:
            groups["train"]=groups["train"][:int(payload.train_max_samples)]
        # v42.8：试验集快照保留全部所选数据。val_max_samples 只控制“每隔 N 轮门禁检查”时的随机抽样数量；
        # 0 表示每次检查使用全部试验集，避免把抽样数量错误地固化成整个训练任务的试验集大小。
        if not groups["train"]:
            raise HTTPException(status_code=400,detail="训练集没有符合条件的已标注素材")
        if not groups["val"]:
            raise HTTPException(status_code=400,detail="试验集没有符合条件的已标注素材。请先把素材划入试验集。")
        dataset = p / "dataset_snapshots" / f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
        for sub in ["images/train","images/val","images/test","labels/train","labels/val","labels/test"]:
            (dataset/sub).mkdir(parents=True,exist_ok=True)
        counts={"train":0,"val":0,"test":0,"boxes":0,"train_boxes":0,"val_boxes":0,"test_boxes":0}
        selected_ids={"train":[],"val":[],"test":[]}
        for part,items in groups.items():
            for img,ann in items:
                src=self.dependencies.resolve_material_path(project_id,img)
                shutil.copy2(src,dataset/"images"/part/img["stored_name"])
                lines=[self.dependencies.box_to_yolo_line(b,img["width"],img["height"]) for b in ann.get("boxes",[])]
                (dataset/"labels"/part/f"{Path(img['stored_name']).stem}.txt").write_text("\n".join(lines),encoding="utf-8")
                counts[part]+=1;counts["boxes"]+=len(lines);counts[f"{part}_boxes"]+=len(lines);selected_ids[part].append(img["id"])
        data_yaml={"path":str(dataset).replace("\\\\","/"),"train":"images/train","val":"images/val","test":"images/test","names":{i:l for i,l in enumerate(project.get("labels",[]))}}
        yaml_path=dataset/"data.yaml";yaml_path.write_text(yaml.safe_dump(data_yaml,allow_unicode=True,sort_keys=False),encoding="utf-8")
        return {"ok":True,"dataset":str(dataset),"data_yaml":str(yaml_path),"counts":counts,"labels":project.get("labels",[]),"selected_ids":selected_ids,"split_seed":split_seed,"experiment_percent":float(payload.experiment_percent),"filters":{"train_labels":sorted(train_filter),"val_labels":sorted(val_filter),"train_image_ids":sorted(train_ids),"val_image_ids":sorted(val_ids),"selected_image_ids":sorted(requested_ids)}}
