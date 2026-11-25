"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from fastapi import HTTPException

import shutil
import uuid
from pathlib import Path
from fastapi import File, Form, UploadFile
from PIL import Image, ImageDraw
from platform_core.algorithms import list_algorithms as list_algorithm_assets, update_algorithm_version
from platform_core.conversion import sha256_file

@dataclass(frozen=True)
class ModelInferenceDependencies:
    IMAGE_EXTS: Callable[..., Any]
    LOCAL_MODELS_FILE: Callable[..., Any]
    _authorize_business_file_project: Callable[..., Any]
    _business_file_response: Callable[..., Any]
    _business_file_url: Callable[..., Any]
    _labels_b64: Callable[..., Any]
    _module_available: Callable[..., Any]
    _project_label_names: Callable[..., Any]
    _register_prediction_files: Callable[..., Any]
    _resolve_business_file: Callable[..., Any]
    _testable_version_pt_path: Callable[..., Any]
    _write_job_json: Callable[..., Any]
    algorithms_file: Callable[..., Any]
    get_active_paddle_env: Callable[..., Any]
    get_active_ultralytics_env: Callable[..., Any]
    get_project: Callable[..., Any]
    image_info: Callable[..., Any]
    list_algorithms_internal: Callable[..., Any]
    list_models_internal: Callable[..., Any]
    now_iso: Callable[..., Any]
    project_dir: Callable[..., Any]
    read_json: Callable[..., Any]
    resolve_any_model_path: Callable[..., Any]
    resolve_inference_python: Callable[..., Any]
    resolve_ultralytics_model_path: Callable[..., Any]
    run_predict_by_env: Callable[..., Any]
    safe_filename: Callable[..., Any]
    shared_task_artifacts: Callable[..., Any]
    shared_task_repository: Callable[..., Any]
    v39_list_deploy_artifacts: Callable[..., Any]


class ModelInferenceService:
    def __init__(self, dependencies: ModelInferenceDependencies):
        self.dependencies = dependencies

    def list_models(self, project_id: str):
        self.dependencies.get_project(project_id)
        return self.dependencies.list_models_internal(project_id)

    def download_model(self, project_id: str, model_name: str):
        return self.dependencies._business_file_response(project_id, 'models', model_name, download=True)

    async def predict_image(self,
        project_id: str,
        model_name: str = Form(...),
        conf: float = Form(0.25),
        file: UploadFile = File(...),
    ):
        project = self.dependencies.get_project(project_id)
        p = self.dependencies.project_dir(project_id)
        model_path = p / "models" / self.dependencies.safe_filename(model_name)
        if not model_path.exists():
            raise HTTPException(status_code=404, detail="模型不存在，请先训练模型")
        ext = Path(file.filename or "test.jpg").suffix.lower()
        if ext not in self.dependencies.IMAGE_EXTS():
            ext = ".jpg"
        pred_id = uuid.uuid4().hex[:12]
        in_path = p / "predictions" / f"{pred_id}_input{ext}"
        out_path = p / "predictions" / f"{pred_id}_result.jpg"
        in_path.write_bytes(await file.read())
        try:
            from ultralytics import YOLO
            model = YOLO(str(model_path))
            results = model.predict(source=str(in_path), conf=float(conf), save=False, verbose=False)
            result = results[0]
            detections = []
            names = result.names
            img = Image.open(in_path).convert("RGB")
            draw = ImageDraw.Draw(img)
            for box in result.boxes:
                xyxy = box.xyxy[0].tolist()
                cls_id = int(box.cls[0])
                score = float(box.conf[0])
                label = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else str(cls_id)
                detections.append({
                    "class_id": cls_id,
                    "label": label,
                    "confidence": round(score, 4),
                    "x1": round(xyxy[0], 2), "y1": round(xyxy[1], 2), "x2": round(xyxy[2], 2), "y2": round(xyxy[3], 2),
                })
                x1, y1, x2, y2 = xyxy
                draw.rectangle([x1, y1, x2, y2], outline=(255, 30, 30), width=3)
                text = f"{label} {score:.2f}"
                draw.rectangle([x1, max(0, y1 - 24), x1 + min(320, len(text) * 12 + 10), y1], fill=(255, 30, 30))
                draw.text((x1 + 4, max(0, y1 - 21)), text, fill=(255, 255, 255))
            img.save(out_path, quality=92)
            self.dependencies._register_prediction_files(project_id, pred_id, in_path, out_path)
            return {"ok": True, "detections": detections, "image_url": self.dependencies._business_file_url(project_id, 'predictions', out_path.name), "labels": project["labels"]}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"预测失败：{e}")

    def export_onnx(self, project_id: str, model_name: str = Form(...)):
        self.dependencies._authorize_business_file_project(project_id)
        p = self.dependencies.project_dir(project_id)
        model_path = self.dependencies._resolve_business_file(project_id, 'models', model_name).path
        if model_path.suffix.lower() == ".onnx":
            return {"ok": True, "onnx": str(model_path), "download_url": self.dependencies._business_file_url(project_id, 'models', model_path.name)}
        # Extend the existing training record. Unbound standalone files cannot
        # manufacture a new model registry merely by being exportable.
        source_job = None
        source_version = None
        for jf in (p / 'jobs').glob('*/job.json'):
            job = self.dependencies.read_json(jf, {})
            if any(Path(str(raw)).absolute() == model_path for raw in job.get('models') or []):
                source_job = (jf, job)
                break
        if source_job is None:
            for algorithm in list_algorithm_assets(self.dependencies.algorithms_file(project_id)):
                for version in algorithm.get('versions') or []:
                    if Path(str(version.get('stored_path') or '')).absolute() == model_path:
                        source_version = (algorithm['id'], version)
                        break
        if source_job is None and source_version is None:
            raise HTTPException(409, detail='模型缺少可追加导出记录的原训练任务，请从正式模型转换入口导出。')
        try:
            from ultralytics import YOLO
            model = YOLO(str(model_path))
            exported = model.export(format="onnx")
            exported_path = Path(exported)
            dst = p / "models" / f"{model_path.stem}.onnx"
            if exported_path.exists():
                shutil.copy2(exported_path, dst)
            owner = source_job[1] if source_job is not None else source_version[1]
            entries = [row for row in owner.get('exported_models') or [] if row.get('path') != str(dst)]
            entries.append({'path': str(dst), 'sha256': sha256_file(dst), 'source_path': str(model_path), 'format': 'onnx'})
            if source_job is not None:
                owner['exported_models'] = entries
                self.dependencies._write_job_json(source_job[0], owner)
            else:
                update_algorithm_version(self.dependencies.algorithms_file(project_id), source_version[0], owner['id'],
                                         {'exported_models': entries}, now=self.dependencies.now_iso())
            return {"ok": True, "onnx": str(dst), "download_url": self.dependencies._business_file_url(project_id, 'models', dst.name)}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"导出失败：{e}")

    async def v12_predict_image(self,
        project_id: str,
        model_name: str = Form(""),
        model_source: str = Form("project"),
        local_path: str = Form(""),
        algorithm_id: str = Form(""),
        version_id: str = Form(""),
        conf: float = Form(0.25),
        inference_framework: str = Form("ultralytics"),
        inference_env_id: str = Form(""),
        file: UploadFile = File(...),
    ):
        project = self.dependencies.get_project(project_id)
        p = self.dependencies.project_dir(project_id)
        (p / "predictions").mkdir(parents=True, exist_ok=True)
        framework = (inference_framework or "ultralytics").lower()
        source = (model_source or "project").lower()
        model_value = ""
        feedback_version = None

        # 解析模型来源。v27 修复：原始模型 builtin、算法版本、项目模型、本机模型、飞桨模型统一收口，避免 model_path 未定义。
        try:
            if framework == "paddle" or source in {"paddle_builtin", "paddle_model"} or str(model_name).startswith("paddledet::"):
                framework = "paddle"
                if source == "local" and local_path:
                    model_value = local_path.replace("local::", "", 1)
                else:
                    model_value = model_name or "PP-YOLOE-S_human"
            else:
                framework = "ultralytics"
                if source == "builtin":
                    model_value = self.dependencies.resolve_ultralytics_model_path(model_name or "yolo11n.pt", project_id)
                elif algorithm_id and version_id:
                    algos = self.dependencies.list_algorithms_internal(project_id)
                    version = None
                    for a in algos:
                        if a.get("id") == algorithm_id:
                            version = next((x for x in a.get("versions", []) if x.get("id") == version_id), None)
                            break
                    if not version:
                        raise HTTPException(status_code=404, detail="算法版本不存在")
                    feedback_version = dict(version)
                    model_path = Path(version.get("stored_path", ""))
                    if not model_path.exists():
                        raise HTTPException(status_code=404, detail="算法版本模型文件不存在")
                    model_value = str(model_path)
                else:
                    model_path, _, _ = self.dependencies.resolve_any_model_path(project_id, model_name, source, local_path)
                    model_value = str(model_path)
            if not model_value:
                raise HTTPException(status_code=400, detail="测试模型为空，请重新选择模型。")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"解析测试模型失败：{e}")

        ext = Path(file.filename or "test.jpg").suffix.lower()
        if ext not in self.dependencies.IMAGE_EXTS():
            ext = ".jpg"
        pred_id = uuid.uuid4().hex[:12]
        in_path = p / "predictions" / f"{pred_id}_input{ext}"
        out_path = p / "predictions" / f"{pred_id}_result.jpg"
        in_path.write_bytes(await file.read())

        python_path = self.dependencies.resolve_inference_python(framework, inference_env_id)
        data = self.dependencies.run_predict_by_env(framework, python_path, str(model_value), in_path, out_path, float(conf))
        response = {
            "ok": True,
            "prediction_id": pred_id,
            "feedback_eligible": False,
            "detections": data.get("detections", []),
            "image_url": self.dependencies._business_file_url(project_id, 'predictions', out_path.name),
            "labels": project.get("labels", []),
            "elapsed_ms": data.get("elapsed_ms", 0),
            "model": data.get("model") or Path(str(model_value)).name,
            "engine": data.get("engine") or framework,
            "python_path": python_path,
            "note": data.get("note", ""),
        }
        if feedback_version is not None and algorithm_id and version_id:
            try:
                from platform_core.online_feedback import validate_prediction_evidence
                info = self.dependencies.image_info(in_path)
                evidence = validate_prediction_evidence({
                    "schema_version": 1,
                    "prediction_id": pred_id,
                    "algorithm_id": str(algorithm_id),
                    "version_id": str(version_id),
                    "model_sha256": sha256_file(Path(str(model_value))),
                    "input_sha256": sha256_file(in_path),
                    "original_filename": self.dependencies.safe_filename(file.filename or f"{pred_id}{ext}"),
                    "input_file": in_path.name,
                    "width": int(info["width"]),
                    "height": int(info["height"]),
                    "confidence": float(conf),
                    "engine": data.get("engine") or framework,
                    "detections": list(data.get("detections") or []),
                    "created_at": self.dependencies.now_iso(),
                    "source_channel": "platform_test",
                })
                self.dependencies._register_prediction_files(project_id, pred_id, in_path, out_path, evidence)
                response.update({
                    "feedback_eligible": True,
                    "algorithm_id": evidence["algorithm_id"],
                    "version_id": evidence["version_id"],
                    "model_sha256": evidence["model_sha256"],
                    "input_sha256": evidence["input_sha256"],
                })
            except (OSError, ValueError):
                # Prediction remains usable even when evidence cannot be promoted.
                response["feedback_eligible"] = False
        self.dependencies._register_prediction_files(project_id, pred_id, in_path, out_path)
        return response

    def v12_test_models(self, project_id: str, probe_optional: bool = True, model_scope: str = ""):
        project = self.dependencies.get_project(project_id)
        if model_scope == "scenario":
            from platform_core.scenario_models import resolve_scenario_model, ScenarioModelUnavailable
            items = []
            for algorithm in self.dependencies.list_algorithms_internal(project_id):
                for version in algorithm.get("versions") or []:
                    try:
                        item = resolve_scenario_model(project_id, self.dependencies.project_dir(project_id), algorithm, version,
                            self.dependencies.shared_task_repository(), self.dependencies.shared_task_artifacts(), use_list_cache=True)
                    except ScenarioModelUnavailable:
                        continue
                    item["is_current_version"] = str(version.get("id")) == str(algorithm.get("current_version_id"))
                    items.append(item)
            items.sort(key=lambda row: (str(row.get("finished_at") or row.get("created_at") or ""), str(row.get("version_id"))), reverse=True)
            return {"ok": True, "items": items}
        project_label_names = self.dependencies._project_label_names(project)
        project_labels_token = self.dependencies._labels_b64(project_label_names)
        items = []
        # 检测台常用“原始模型”，用于和训练后的新模型做同图对比。
        items.append({"label": "原始模型：YOLO11n 官方预训练", "model_name": "yolo11n.pt", "model_source": "builtin", "framework": "ultralytics", "path": "yolo11n.pt"})
        items.append({"label": "原始模型：YOLO11s 官方预训练", "model_name": "yolo11s.pt", "model_source": "builtin", "framework": "ultralytics", "path": "yolo11s.pt"})
        for m in self.dependencies.list_models_internal(project_id):
            if m.get("type") == "pt":
                items.append({"label": f"项目模型：{m['name']}", "model_name": m["name"], "model_source": "project", "framework": "ultralytics", "path": m.get("path")})
            elif m.get("type") in {"pdparams", "pdmodel", "pdiparams"}:
                cfg = m.get("config_path", "") or ""
                fam = m.get("family_key", "") or ""
                nc = m.get("num_classes", 0) or 0
                labels_token = project_labels_token
                encoded = f"paddledet::{m.get('path','')}::{cfg}::{fam}::{nc}::{labels_token}"
                items.append({"label": f"飞桨模型：{m['name']}", "model_name": encoded, "model_source": "paddle_model", "framework": "paddle", "path": m.get("path"), "config_path": cfg, "labels": project_label_names})
        local = self.dependencies.read_json(self.dependencies.LOCAL_MODELS_FILE(), {})
        for m in (local.get("items", []) if isinstance(local, dict) else []):
            if str(m.get("path", "")).lower().endswith(".pt"):
                items.append({"label": f"本机模型：{m.get('name')}", "model_name": f"local::{m.get('path')}", "model_source": "local", "path": m.get("path")})
        active_env = self.dependencies.get_active_ultralytics_env()
        for m in active_env.get("models", []) if isinstance(active_env.get("models", []), list) else []:
            candidate = Path(str(m.get("path") or ""))
            if candidate.suffix.lower() == ".pt" and candidate.is_file() and candidate.stat().st_size >= 1024:
                items.append({"label": f"Ultralytics环境：{m.get('name')}", "model_name": f"local::{m.get('path')}", "model_source": "local", "path": m.get("path")})
        # 飞桨内置/配置模型：只有检测到 paddlex 时才展示，避免误选后 Internal Server Error。
        p_env = self.dependencies.get_active_paddle_env()
        if probe_optional and p_env and p_env.get("python_path") and Path(str(p_env.get("python_path"))).exists():
            try:
                px = self.dependencies._module_available(str(p_env.get("python_path")), "paddlex")
            except Exception:
                px = {"ok": False}
            if px.get("ok"):
                items.append({"label": "飞桨内置：PP-YOLOE-S_human 人员检测", "model_name": "PP-YOLOE-S_human", "model_source": "paddle_builtin", "framework": "paddle", "path": "PP-YOLOE-S_human"})
        # 算法版本
        for a in self.dependencies.list_algorithms_internal(project_id):
            current_version_id = str(a.get("current_version_id") or "")
            versions = list(a.get("versions", []) or [])
            versions.sort(key=lambda version: (
                str(version.get("id") or "") == current_version_id,
                str(version.get("finished_at") or version.get("created_at") or ""),
            ), reverse=True)
            for v in versions:
                verified_path = self.dependencies._testable_version_pt_path(v)
                if verified_path is None:
                    continue
                is_current = str(v.get("id") or "") == current_version_id
                current_suffix = "（当前）" if is_current else ""
                items.append({
                    "label": f"算法版本：{a.get('name')} / {v.get('version_name') or v.get('id')}{current_suffix}",
                    "algorithm_id": a.get("id"), "version_id": v.get("id"),
                    "version_name": v.get("version_name") or v.get("id"),
                    "is_current_version": is_current, "model_source": "algorithm_version",
                    "framework": "ultralytics", "path": str(verified_path),
                    "artifact_name": verified_path.name, "is_verified_training_weight": True,
                })
        # Real conversion artifacts are selectable in the deployment test page.
        try:
            for artifact in self.dependencies.v39_list_deploy_artifacts(project_id).get("items", []):
                suffix = Path(str(artifact.get("path") or "")).suffix.lower()
                if suffix not in {".onnx", ".engine", ".om", ".rknn", ".bmodel"}:
                    continue
                framework = "ultralytics" if suffix in {".onnx", ".engine"} else "vendor"
                items.append({
                    "label": f"转换产物：{artifact.get('name')}",
                    "model_name": artifact.get("name") or "", "model_source": "deployment_artifact",
                    "framework": framework, "runtime_format": suffix.lstrip("."),
                    "path": artifact.get("path") or "",
                })
        except Exception:
            pass
        return {"ok": True, "items": items}
