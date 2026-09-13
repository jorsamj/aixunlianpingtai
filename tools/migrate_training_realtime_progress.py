from __future__ import annotations

from pathlib import Path

WORKER = Path("train_worker.py")
HANDLER = Path("platform_core/training_tasks.py")
PROGRESS_TEST = Path("tests/unit/test_training_progress_v2.py")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def migrate_worker() -> None:
    text = WORKER.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "import sys\nimport traceback\n",
        "import sys\nimport tempfile\nimport time\nimport traceback\n",
        label="realtime progress imports",
    )
    text = replace_once(
        text,
        '''def write_json(path: Path, data):\n    path.parent.mkdir(parents=True, exist_ok=True)\n    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")\n''',
        '''def write_json(path: Path, data):\n    path.parent.mkdir(parents=True, exist_ok=True)\n    descriptor, name = tempfile.mkstemp(\n        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"\n    )\n    temporary = Path(name)\n    try:\n        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:\n            descriptor = -1\n            json.dump(data, stream, ensure_ascii=False, indent=2)\n            stream.flush()\n            os.fsync(stream.fileno())\n        os.replace(temporary, path)\n    finally:\n        if descriptor >= 0:\n            os.close(descriptor)\n        temporary.unlink(missing_ok=True)\n''',
        label="atomic job json",
    )
    old = '''def publish_epoch_progress(job_file, telemetry, trainer, requested_total_epochs):\n    telemetry.on_epoch_end(trainer)\n    progress = dict(telemetry.latest_epoch or {})\n    epoch = int(progress.get("epoch") or (int(getattr(trainer, "epoch", 0)) + 1))\n    total = max(epoch, int(progress.get("total_epochs") or requested_total_epochs or epoch))\n    percent = round(min(90.0, epoch / max(1, total) * 90.0), 2)\n    update_job(\n        job_file,\n        current_epoch=epoch,\n        total_epochs=total,\n        progress_percent=percent,\n        training_progress=progress,\n        elapsed_seconds=progress.get("elapsed_seconds"),\n        eta_seconds=progress.get("eta_seconds"),\n        message=f"训练中 · Epoch {epoch}/{total}",\n    )\n    return progress\n'''
    new = '''def _training_phase_percent(completed_epochs, total_epochs, *, phase_start=20.0, phase_end=90.0):\n    total = max(1.0, float(total_epochs or 1))\n    completed = max(0.0, min(total, float(completed_epochs or 0)))\n    start = float(phase_start)\n    end = max(start, float(phase_end))\n    return round(start + (end - start) * completed / total, 2)\n\n\ndef publish_batch_progress(\n    job_file, trainer, requested_total_epochs, completed_batches, total_batches,\n    *, phase_start=20.0, phase_end=90.0,\n):\n    epoch_index = max(0, int(getattr(trainer, "epoch", 0)))\n    current_epoch = epoch_index + 1\n    total_epochs = max(\n        current_epoch,\n        int(getattr(trainer, "epochs", 0) or requested_total_epochs or current_epoch),\n    )\n    batches = max(1, int(total_batches or 1))\n    completed = max(0, min(batches, int(completed_batches or 0)))\n    epoch_fraction = epoch_index + completed / batches\n    percent = _training_phase_percent(\n        epoch_fraction, total_epochs, phase_start=phase_start, phase_end=phase_end,\n    )\n    current_item = f"Epoch {current_epoch}/{total_epochs} · Batch {completed}/{batches}"\n    update_job(\n        job_file,\n        current_epoch=current_epoch,\n        total_epochs=total_epochs,\n        current_batch=completed,\n        total_batches=batches,\n        progress_percent=percent,\n        current_item=current_item,\n        message=f"训练中 · {current_item}",\n    )\n    return percent\n\n\ndef attach_training_batch_progress(\n    model, job_file, requested_total_epochs, *, min_interval=0.25,\n    phase_start=20.0, phase_end=90.0,\n):\n    state = {"epoch": None, "completed_batches": 0, "last_write": None}\n\n    def on_train_batch_end(trainer):\n        epoch_index = max(0, int(getattr(trainer, "epoch", 0)))\n        if state["epoch"] != epoch_index:\n            state["epoch"] = epoch_index\n            state["completed_batches"] = 0\n            state["last_write"] = None\n        try:\n            total_batches = max(1, len(trainer.train_loader))\n        except (TypeError, AttributeError):\n            total_batches = 1\n        state["completed_batches"] = min(total_batches, state["completed_batches"] + 1)\n        now = time.monotonic()\n        final_batch = state["completed_batches"] >= total_batches\n        last_write = state["last_write"]\n        if not final_batch and last_write is not None and now - last_write < max(0.05, float(min_interval)):\n            return\n        publish_batch_progress(\n            job_file, trainer, requested_total_epochs,\n            state["completed_batches"], total_batches,\n            phase_start=phase_start, phase_end=phase_end,\n        )\n        state["last_write"] = now\n\n    model.add_callback("on_train_batch_end", on_train_batch_end)\n    return on_train_batch_end\n\n\ndef publish_epoch_progress(job_file, telemetry, trainer, requested_total_epochs):\n    telemetry.on_epoch_end(trainer)\n    progress = dict(telemetry.latest_epoch or {})\n    epoch = int(progress.get("epoch") or (int(getattr(trainer, "epoch", 0)) + 1))\n    total = max(epoch, int(progress.get("total_epochs") or requested_total_epochs or epoch))\n    percent = _training_phase_percent(epoch, total)\n    progress.update(epoch=epoch, total_epochs=total)\n    update_job(\n        job_file,\n        current_epoch=epoch,\n        total_epochs=total,\n        current_batch=None,\n        total_batches=None,\n        progress_percent=percent,\n        training_progress=progress,\n        elapsed_seconds=progress.get("elapsed_seconds"),\n        eta_seconds=progress.get("eta_seconds"),\n        current_item=f"Epoch {epoch}/{total}",\n        message=f"训练中 · Epoch {epoch}/{total}",\n    )\n    return progress\n'''
    text = replace_once(text, old, new, label="realtime progress publishers")
    text = replace_once(
        text,
        '''        attach_resource_callbacks(model)\n        retries = 0\n''',
        '''        attach_resource_callbacks(model)\n        attach_training_batch_progress(model, job_file, int(args.epochs))\n        retries = 0\n''',
        label="initial batch callback",
    )
    text = replace_once(
        text,
        '''            model.add_callback("on_fit_epoch_end", on_fit_epoch_end)\n            attach_resource_callbacks(model)\n''',
        '''            model.add_callback("on_fit_epoch_end", on_fit_epoch_end)\n            attach_resource_callbacks(model)\n            attach_training_batch_progress(model, job_file, int(args.epochs))\n''',
        label="retry batch callback",
    )
    WORKER.write_text(text, encoding="utf-8")


def migrate_handler() -> None:
    text = HANDLER.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''                current = str(job.get("current_epoch") or "") or None\n''',
        '''                current = str(job.get("current_item") or job.get("current_epoch") or "") or None\n''',
        label="durable batch current item",
    )
    HANDLER.write_text(text, encoding="utf-8")


def migrate_existing_test() -> None:
    text = PROGRESS_TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '    assert job["progress_percent"] == 33.75\n',
        '    assert job["progress_percent"] == 46.25\n',
        label="progress v2 phase expectation",
    )
    PROGRESS_TEST.write_text(text, encoding="utf-8")


def main() -> None:
    migrate_worker()
    migrate_handler()
    migrate_existing_test()
    print("TRAINING_REALTIME_PROGRESS_MIGRATED=1")


if __name__ == "__main__":
    main()
