from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

import train_worker as base_worker


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="畅联云 YOLO checkpoint 断点续训 Worker")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--resume-checkpoint", required=True)
    parser.add_argument("--resume-checkpoint-sha256", required=True)
    parser.add_argument("--resume-from-epoch", type=int, required=True)
    parser.add_argument("--epochs", type=int, required=True)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--assigned-device", required=True)
    parser.add_argument("--requested-device", default="auto")
    parser.add_argument("--resource-context", default="")
    parser.add_argument("--resource-resolution", default="")
    parser.add_argument("--metrics-db", default="")
    parser.add_argument("--val-max-samples", type=int, default=0)
    return parser


def _runtime_device(assigned: str, resource_context: dict) -> tuple[str, int | None]:
    from platform_core.training_devices import normalize_training_device

    normalized = normalize_training_device(assigned)
    gpu_index = int(normalized[5:]) if normalized.startswith("cuda:") else None
    if gpu_index is None:
        os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
        return "cpu", None

    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    entries = visible.split(",") if visible is not None else []
    physical = resource_context.get("gpu_uuid") or (entries[gpu_index] if entries and gpu_index < len(entries) else str(gpu_index))
    os.environ["CUDA_VISIBLE_DEVICES"] = str(physical)
    return "0", gpu_index


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    project_dir = Path(args.project_dir).resolve()
    runs_dir = (project_dir / "runs").resolve()
    run_dir = (runs_dir / args.run_name).resolve()
    checkpoint = Path(args.resume_checkpoint).resolve()
    job_file = project_dir / "jobs" / args.job_id / "job.json"
    data_yaml = Path(args.data).resolve()

    if not _inside(run_dir, runs_dir):
        raise RuntimeError("RESUME_RUN_PATH_INVALID: run directory escaped project runs root")
    if checkpoint != (run_dir / "weights" / "last.pt").resolve():
        raise RuntimeError("RESUME_CHECKPOINT_INVALID: only the task-local last.pt can resume training")
    if not checkpoint.is_file() or checkpoint.stat().st_size <= 0:
        raise RuntimeError("RESUME_CHECKPOINT_MISSING: last.pt is unavailable")
    if _sha256(checkpoint) != str(args.resume_checkpoint_sha256):
        raise RuntimeError("RESUME_CHECKPOINT_CHANGED: last.pt changed after recovery admission")
    if not data_yaml.is_file():
        raise RuntimeError("RESUME_DATASET_MISSING: runtime dataset yaml is unavailable")

    job = base_worker.read_json(job_file, {})
    if str(job.get("task_id") or job.get("id") or "") != str(args.job_id):
        raise RuntimeError("RESUME_TASK_MISMATCH: job identity differs from durable task")
    if str(job.get("snapshot_id") or "") != str(args.snapshot_id):
        raise RuntimeError("RESUME_SNAPSHOT_MISMATCH: job snapshot differs from durable task")
    if int(args.resume_from_epoch) <= 0 or int(args.resume_from_epoch) >= int(args.epochs):
        raise RuntimeError("RESUME_EPOCH_INVALID: checkpoint is not an incomplete training checkpoint")

    resource_context = base_worker.read_json(Path(args.resource_context), {}) if args.resource_context else {}
    if not isinstance(resource_context, dict):
        resource_context = {}
    logical_device, gpu_index = _runtime_device(args.assigned_device, resource_context)

    base_worker.update_job(
        job_file,
        status="running",
        recovery_mode="training_checkpoint_resume",
        recovery_state="loading_checkpoint",
        recovery_auto=True,
        resume_from_epoch=int(args.resume_from_epoch),
        resume_checkpoint=str(checkpoint),
        resume_checkpoint_sha256=str(args.resume_checkpoint_sha256),
        current_epoch=max(int(args.resume_from_epoch), int(job.get("current_epoch") or 0)),
        total_epochs=int(args.epochs),
        progress_percent=max(20.0, float(job.get("progress_percent") or 20.0)),
        current_item=f"从 Epoch {int(args.resume_from_epoch)} 恢复训练",
        message=f"检测到可信 last.pt，正在从 Epoch {int(args.resume_from_epoch)} 继续训练",
    )
    print(
        f"[{base_worker.now_iso()}] 断点续训：Epoch {int(args.resume_from_epoch)}/{int(args.epochs)} · {checkpoint}",
        flush=True,
    )

    started = time.monotonic()
    try:
        from platform_core.training_devices import normalize_training_device

        assigned = normalize_training_device(args.assigned_device)
        requested = normalize_training_device(args.requested_device)
        if requested != "auto" and requested != assigned:
            raise RuntimeError("TRAINING_DEVICE_ASSIGNMENT_MISMATCH")

        import ultralytics
        import torch
        from ultralytics import YOLO

        runtime_device = "cuda:0" if gpu_index is not None else "cpu"
        probe = torch.empty(1, device=runtime_device)
        props = torch.cuda.get_device_properties(0) if gpu_index is not None else None
        raw_uuid = getattr(props, "uuid", None) if props is not None else None
        actual_uuid = str(raw_uuid) if raw_uuid is not None else None
        expected_uuid = resource_context.get("gpu_uuid")
        if expected_uuid and actual_uuid and str(expected_uuid).lower().removeprefix("gpu-") != actual_uuid.lower().removeprefix("gpu-"):
            raise RuntimeError("GPU_IDENTITY_MISMATCH: resumed trainer differs from reserved GPU")
        del probe
        if gpu_index is not None:
            torch.cuda.synchronize(0)

        model = YOLO(str(checkpoint))
        first_batch = False

        def on_train_start(trainer):
            if str(trainer.device) != runtime_device:
                raise RuntimeError(
                    f"TRAINING_DEVICE_RUNTIME_MISMATCH: expected={runtime_device}; actual={trainer.device}"
                )
            base_worker.update_job(
                job_file,
                recovery_state="training",
                actual_device=assigned,
                ultralytics_version=getattr(ultralytics, "__version__", "unknown"),
                current_item=f"断点续训 · Epoch {int(args.resume_from_epoch)}/{int(args.epochs)}",
                message="Checkpoint 已加载，继续训练中",
            )

        def on_train_batch_start(_trainer):
            nonlocal first_batch
            if first_batch:
                return
            first_batch = True
            base_worker.update_job(
                job_file,
                recovery_state="training",
                training_started=True,
                resume_first_batch_at=base_worker.now_iso(),
                current_item=f"断点续训已开始 · Epoch {int(args.resume_from_epoch) + 1}/{int(args.epochs)}",
                message="断点续训已恢复 Batch 执行",
            )

        def on_fit_epoch_end(trainer):
            epoch = max(int(args.resume_from_epoch), int(getattr(trainer, "epoch", 0)) + 1)
            total = max(epoch, int(getattr(trainer, "epochs", 0) or args.epochs))
            metrics = {}
            for key, value in dict(getattr(trainer, "metrics", {}) or {}).items():
                try:
                    metrics[str(key)] = float(value)
                except (TypeError, ValueError):
                    continue
            progress = {
                "epoch": epoch,
                "total_epochs": total,
                "metrics": metrics,
                "resume_from_epoch": int(args.resume_from_epoch),
                "resumed": True,
            }
            percent = base_worker._training_phase_percent(epoch, total)
            base_worker.update_job(
                job_file,
                recovery_state="training",
                current_epoch=epoch,
                total_epochs=total,
                current_batch=None,
                total_batches=None,
                progress_percent=percent,
                training_progress=progress,
                current_item=f"断点续训 · Epoch {epoch}/{total}",
                message=f"断点续训中 · Epoch {epoch}/{total}",
            )

        model.add_callback("on_train_start", on_train_start)
        model.add_callback("on_train_batch_start", on_train_batch_start)
        model.add_callback("on_fit_epoch_end", on_fit_epoch_end)
        base_worker.attach_training_batch_progress(
            model,
            job_file,
            int(args.epochs),
            item_prefix="断点续训",
        )

        # Ultralytics resume=True restores optimizer, scheduler, AMP state,
        # start_epoch and the original run arguments from last.pt. Device is the
        # only runtime override: the durable Scheduler owns the concrete device.
        model.train(resume=True, device=logical_device)
        current = base_worker.read_json(job_file, {})
        base_worker.update_job(
            job_file,
            recovery_state="training_loop_completed",
            current_epoch=max(int(current.get("current_epoch") or 0), int(args.epochs)),
            total_epochs=int(args.epochs),
            progress_percent=max(95.0, float(current.get("progress_percent") or 0.0)),
            current_item="断点续训主循环完成，等待独立模型验证",
            message="断点续训完成，正在移交最终验证",
            resume_elapsed_seconds=round(time.monotonic() - started, 3),
        )
        return 0
    except Exception as error:
        base_worker.update_job(
            job_file,
            recovery_state="failed",
            recovery_error=str(error),
            current_item=f"断点续训失败：{error}",
            message=f"断点续训失败：{error}",
        )
        print(traceback.format_exc(), flush=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
