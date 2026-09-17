from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

from train_worker import (
    analyze_detection_errors,
    build_report_from_metrics,
    derive_training_completion_metadata,
    now_iso,
    read_json,
    update_job,
    write_json,
)


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_within(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} is outside the trusted task directory") from error
    return resolved


def _bind_runtime_device(assigned_device: str, resource_context_path: str) -> tuple[str, dict]:
    from platform_core.training_devices import normalize_training_device

    assigned = normalize_training_device(assigned_device)
    context = read_json(Path(resource_context_path), {}) if resource_context_path else {}
    if assigned.startswith("cuda:"):
        gpu_index = int(assigned.split(":", 1)[1])
        visible = os.environ.get("CUDA_VISIBLE_DEVICES")
        entries = [item.strip() for item in visible.split(",")] if visible else []
        physical = context.get("gpu_uuid") or (entries[gpu_index] if gpu_index < len(entries) else str(gpu_index))
        os.environ["CUDA_VISIBLE_DEVICES"] = str(physical)
        return "0", context
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    return "cpu", context


def _copy_verified_models(project_dir: Path, run_name: str, checkpoint_sha256: str, YOLO) -> tuple[list[str], list[str], str, str]:
    weights = (project_dir / "runs" / run_name / "weights").resolve()
    models_dir = (project_dir / "models").resolve()
    models_dir.mkdir(parents=True, exist_ok=True)

    best_source = _require_within(weights / "best.pt", weights, "best checkpoint")
    if not best_source.is_file() or best_source.stat().st_size <= 0:
        raise FileNotFoundError("trusted best.pt checkpoint is missing")
    if _sha256(best_source) != checkpoint_sha256:
        raise ValueError("trusted best.pt checkpoint SHA256 changed before final validation")

    copied: list[str] = []
    verified: list[str] = []
    best_path = ""
    last_path = ""
    for kind in ("best", "last"):
        source = _require_within(weights / f"{kind}.pt", weights, f"{kind} checkpoint")
        if not source.is_file() or source.stat().st_size <= 0:
            continue
        destination = models_dir / f"{run_name}_{kind}.pt"
        shutil.copy2(source, destination)
        copied.append(str(destination))
        YOLO(str(destination))
        verified.append(str(destination))
        if kind == "best":
            best_path = str(destination)
        else:
            last_path = str(destination)

    if not best_path or not verified:
        raise RuntimeError("final validation could not publish a verified best checkpoint")
    return copied, verified, best_path, last_path


def _blind_test(best_model, data_yaml: Path, device: str) -> dict:
    import yaml
    from platform_core.training_evaluation import evaluate_blind_detection

    runtime_spec = yaml.safe_load(data_yaml.read_text(encoding="utf-8")) or {}
    dataset_root = Path(str(runtime_spec.get("path") or "."))
    if not dataset_root.is_absolute():
        dataset_root = (data_yaml.resolve().parent / dataset_root).resolve()
    else:
        dataset_root = dataset_root.resolve()

    test_images_dir = dataset_root / "images" / "test"
    hidden_ground_truth_dir = dataset_root.parent / "evaluation" / "ground_truth" / "test"
    if not test_images_dir.is_dir() or not hidden_ground_truth_dir.is_dir():
        return {"status": "not_requested", "metrics": {}}
    if not any(path.suffix.lower() in IMAGE_SUFFIXES for path in test_images_dir.iterdir() if path.is_file()):
        return {"status": "not_requested", "metrics": {}}

    def blind_predict(image_path):
        results = best_model.predict(
            source=str(image_path),
            conf=0.001,
            iou=0.7,
            device=device,
            verbose=False,
        )
        result = results[0] if results else None
        rows = []
        if result is not None and getattr(result, "boxes", None) is not None:
            boxes = result.boxes
            xyxy = boxes.xyxy.detach().cpu().tolist()
            classes = boxes.cls.detach().cpu().tolist()
            confidences = boxes.conf.detach().cpu().tolist()
            rows = [
                {
                    "class_id": int(class_id),
                    "confidence": float(confidence),
                    "box": list(map(float, box)),
                }
                for box, class_id, confidence in zip(xyxy, classes, confidences)
            ]
        return rows

    return evaluate_blind_detection(
        test_images_dir,
        hidden_ground_truth_dir,
        blind_predict,
        names=getattr(best_model, "names", None),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--assigned-device", required=True)
    parser.add_argument("--resource-context", default="")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--val-max-samples", type=int, default=0)
    parser.add_argument("--requested-epochs", type=int, default=0)
    parser.add_argument("--recovery", action="store_true")
    args = parser.parse_args()

    if args.batch < 1:
        raise ValueError("final validation batch must be >= 1")
    if args.workers < 0:
        raise ValueError("final validation workers must be >= 0")

    project_dir = Path(args.project_dir).resolve()
    job_file = project_dir / "jobs" / args.task_id / "job.json"
    result_file = job_file.parent / "final-validation.json"
    data_yaml = Path(args.data).resolve()
    run_weights = (project_dir / "runs" / args.run_name / "weights").resolve()
    checkpoint = _require_within(Path(args.checkpoint), run_weights, "checkpoint")

    result = {
        "schema_version": 1,
        "task_id": args.task_id,
        "snapshot_id": args.snapshot_id,
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": args.checkpoint_sha256,
        "started_at": now_iso(),
        "finished_at": None,
        "success": False,
        "recovery": bool(args.recovery),
        "resource_profile": {
            "workers": args.workers,
            "batch": args.batch,
            "cache": False,
            "reason": "isolated final checkpoint validation",
        },
    }

    try:
        job = read_json(job_file, {})
        job_task_id = str(job.get("task_id") or job.get("id") or "").strip()
        if job_task_id != args.task_id:
            raise ValueError("final validation task identity mismatch")
        if str(job.get("snapshot_id") or "").strip() != args.snapshot_id:
            raise ValueError("final validation snapshot identity mismatch")
        if not checkpoint.is_file() or checkpoint.stat().st_size <= 0:
            raise FileNotFoundError("final validation checkpoint is missing")
        if _sha256(checkpoint) != args.checkpoint_sha256:
            raise ValueError("final validation checkpoint SHA256 mismatch")

        runtime_device, resource_context = _bind_runtime_device(args.assigned_device, args.resource_context)
        import torch
        from ultralytics import YOLO

        update_job(
            job_file,
            status="running",
            message="训练完成，正在独立验证最佳模型",
            current_item="最终模型验证",
            progress_percent=max(96.0, float(job.get("progress_percent") or 0.0)),
            final_validation_resource_profile=result["resource_profile"],
            recovery_attempted=bool(args.recovery),
        )

        best_model = YOLO(str(checkpoint))
        metrics = best_model.val(
            data=str(data_yaml),
            split="val",
            imgsz=args.imgsz,
            batch=args.batch,
            device=runtime_device,
            workers=args.workers,
            cache=False,
            verbose=False,
            plots=False,
        )
        training_report = {
            "generated_at": now_iso(),
            "gate_events": job.get("gate_events") or [],
            "quality_gate_reason": str(job.get("quality_gate_reason") or ""),
            "metrics": {},
            "per_class": [],
            "weak_labels": [],
            "test_metrics": {},
            "test_result": {"status": "not_requested", "metrics": {}},
            "ai_intervention_events": job.get("ai_intervention_events") or [],
        }
        training_report.update(build_report_from_metrics(metrics, getattr(best_model, "names", None)))

        update_job(
            job_file,
            message="最终模型验证完成，正在执行独立试验集评测",
            current_item="独立试验集盲测",
            progress_percent=97.0,
        )
        try:
            blind_result = _blind_test(best_model, data_yaml, runtime_device)
            training_report["test_result"] = blind_result
            training_report["test_metrics"] = blind_result.get("metrics") or {}
            training_report["test_per_class"] = blind_result.get("per_class") or []
            training_report["test_protocol"] = blind_result.get("protocol") or {}
        except Exception as test_error:
            training_report["test_note"] = "独立试验集盲测失败：" + str(test_error)
            training_report["test_result"] = {
                "status": "failed",
                "metrics": {},
                "error": str(test_error),
                "protocol": {"mode": "blind_image_only_inference_then_hidden_ground_truth_scoring"},
            }

        try:
            analysis_limit = args.val_max_samples if args.val_max_samples > 0 else 200
            training_report["error_samples"] = analyze_detection_errors(
                best_model,
                str(data_yaml),
                runtime_device,
                max_images=min(500, analysis_limit),
            )
            training_report["error_sample_count"] = len(
                [item for item in training_report["error_samples"] if not item.get("analysis_error")]
            )
        except Exception as analysis_error:
            training_report["error_analysis_error"] = str(analysis_error)

        copied, verified, best_path, last_path = _copy_verified_models(
            project_dir,
            args.run_name,
            args.checkpoint_sha256,
            YOLO,
        )

        current_job = read_json(job_file, {})
        completed_epochs = int(current_job.get("current_epoch") or current_job.get("completed_epochs") or 0)
        requested_epochs = int(current_job.get("total_epochs") or current_job.get("requested_epochs") or args.requested_epochs or completed_epochs)
        completion = derive_training_completion_metadata(
            None,
            requested_epochs=requested_epochs,
            completed_epochs=completed_epochs,
            gate_reason=str(current_job.get("quality_gate_reason") or ""),
            ai_plan=current_job.get("ai_continuation") if isinstance(current_job.get("ai_continuation"), dict) else None,
        )
        training_report["completion"] = {
            key: value for key, value in completion.items() if key != "completion_message"
        }

        update_job(
            job_file,
            status="done",
            message=completion["completion_message"],
            run_dir=str((project_dir / "runs" / args.run_name).resolve()),
            models=copied,
            verified_models=verified,
            best_path=best_path,
            last_path=last_path,
            artifact_verified=True,
            training_report=training_report,
            training_outcome=completion["training_outcome"],
            completion_reason=completion["completion_reason"],
            early_stopping_reason=completion["early_stopping_reason"],
            early_stopping_patience=completion["early_stopping_patience"],
            best_epoch=completion["best_epoch"],
            completed_epochs=completion["completed_epochs"],
            requested_epochs=completion["requested_epochs"],
            progress_percent=100,
            current_item="最终验证完成",
            finished_at=now_iso(),
            recoverable=False,
            recovery_action=None,
            recovery_action_available=True,
            recovery_completed=bool(args.recovery),
        )

        result.update(
            success=True,
            finished_at=now_iso(),
            device=runtime_device,
            gpu_uuid=resource_context.get("gpu_uuid"),
            validation_metrics=training_report.get("metrics") or {},
            test_result=training_report.get("test_result") or {},
            published_models=verified,
        )
        write_json(result_file, result)
        print(f"[{now_iso()}] 独立最终验证完成", flush=True)
        return 0
    except Exception as error:
        result.update(
            success=False,
            finished_at=now_iso(),
            error=str(error),
        )
        write_json(result_file, result)
        print("最终模型验证失败：", error, flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
