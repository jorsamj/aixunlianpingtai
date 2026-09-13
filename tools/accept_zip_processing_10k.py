from __future__ import annotations

import argparse
import io
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from collections import Counter
from pathlib import Path
from statistics import median

import psutil
import requests
from PIL import Image


IMAGE_COUNT = 10_000
TERMINAL = {"done", "failed"}


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
    return ordered[index]


def tiny_jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="JPEG", quality=75)
    return buffer.getvalue()


def build_yolo_zip(path: Path) -> dict[str, float | int]:
    payload = tiny_jpeg()
    label = b"0 0.5 0.5 0.5 0.5\n"
    started = time.perf_counter()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        archive.writestr(
            "data.yaml",
            "train: images/train\nval: images/train\nnc: 1\nnames: [object]\n",
        )
        for index in range(IMAGE_COUNT):
            stem = f"image_{index:05d}"
            archive.writestr(f"images/train/{stem}.jpg", payload)
            archive.writestr(f"labels/train/{stem}.txt", label)
    seconds = time.perf_counter() - started
    return {
        "zip_build_seconds": round(seconds, 6),
        "zip_bytes": path.stat().st_size,
        "zip_mb": round(path.stat().st_size / 1024 / 1024, 3),
    }


def process_tree(process: psutil.Process) -> list[psutil.Process]:
    processes = [process]
    try:
        processes.extend(process.children(recursive=True))
    except (psutil.Error, OSError):
        pass
    return processes


def process_resources(process: psutil.Process) -> tuple[float, int]:
    rss = 0
    fd = 0
    for current in process_tree(process):
        try:
            rss += current.memory_info().rss
            if hasattr(current, "num_fds"):
                fd += current.num_fds()
        except (psutil.Error, OSError):
            continue
    return rss / 1024 / 1024, fd


def classify_fd_target(target: str) -> str:
    lowered = target.lower()
    if "materials.sqlite3" in lowered:
        return "materials_sqlite"
    if "annotations.sqlite3" in lowered:
        return "annotations_sqlite"
    if lowered.endswith(".sqlite3") or ".sqlite3-" in lowered:
        return "other_sqlite"
    if target.startswith("socket:"):
        return "socket"
    if target.startswith("pipe:"):
        return "pipe"
    if target.startswith("anon_inode:"):
        return "anon_inode"
    if "ten-thousand-yolo.zip" in lowered:
        return "source_zip"
    if "/import_jobs/" in lowered:
        return "import_job_file"
    if "/uploads/" in lowered:
        return "uploaded_material"
    if target.startswith("/"):
        return "regular_file"
    return "other"


def fd_snapshot(process: psutil.Process) -> dict[str, object]:
    if os.name != "posix" or not Path("/proc").is_dir():
        return {"supported": False, "processes": [], "target_counts": {}, "category_counts": {}}
    rows: list[dict[str, object]] = []
    target_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    for current in process_tree(process):
        try:
            pid = current.pid
            name = current.name()
        except (psutil.Error, OSError):
            continue
        fd_root = Path(f"/proc/{pid}/fd")
        entries: list[dict[str, object]] = []
        try:
            children = sorted(fd_root.iterdir(), key=lambda path: int(path.name))
        except (OSError, ValueError):
            children = []
        for entry in children:
            try:
                target = os.readlink(entry)
            except OSError as error:
                target = f"<unreadable:{type(error).__name__}>"
            category = classify_fd_target(target)
            entries.append({"fd": int(entry.name), "target": target, "category": category})
            target_counts[target] += 1
            category_counts[category] += 1
        rows.append({"pid": pid, "name": name, "fds": entries})
    return {
        "supported": True,
        "processes": rows,
        "target_counts": dict(sorted(target_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
    }


def positive_counter_delta(end: dict[str, int], start: dict[str, int]) -> dict[str, int]:
    keys = set(end) | set(start)
    return {
        key: end.get(key, 0) - start.get(key, 0)
        for key in sorted(keys)
        if end.get(key, 0) - start.get(key, 0) > 0
    }


def timed_get(session: requests.Session, url: str, timeout: float = 10.0):
    started = time.perf_counter()
    response = session.get(url, timeout=timeout)
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    return response, elapsed


def wait_for_server(session: requests.Session, base_url: str, process: subprocess.Popen, timeout: float = 45.0):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"uvicorn exited early with code {process.returncode}")
        try:
            response = session.get(f"{base_url}/docs", timeout=1.0)
            if response.status_code < 500:
                return
        except Exception as error:
            last_error = error
        time.sleep(0.1)
    raise RuntimeError(f"uvicorn did not become ready: {last_error}")


def sqlite_truth(project_path: Path) -> dict[str, int]:
    material_db = project_path / "materials.sqlite3"
    annotation_db = project_path / "annotations.sqlite3"
    with sqlite3.connect(material_db) as database:
        material_total, material_boxes, material_annotated = database.execute(
            "SELECT COUNT(*), COALESCE(SUM(box_count),0), COALESCE(SUM(annotated),0) FROM materials"
        ).fetchone()
    annotation_boxes = 0
    with sqlite3.connect(annotation_db) as database:
        annotation_total, annotation_annotated, annotation_empty, annotation_unannotated = database.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(annotation_state='annotated'),0),
                   COALESCE(SUM(annotation_state='confirmed_empty'),0),
                   COALESCE(SUM(annotation_state='unannotated'),0)
            FROM annotations
            """
        ).fetchone()
        for (boxes_json,) in database.execute("SELECT boxes_json FROM annotations"):
            annotation_boxes += len(json.loads(boxes_json or "[]"))
    uploads = project_path / "uploads"
    upload_file_count = sum(1 for path in uploads.iterdir() if path.is_file()) if uploads.exists() else 0
    return {
        "material_total": int(material_total),
        "material_boxes": int(material_boxes),
        "material_annotated": int(material_annotated),
        "annotation_total": int(annotation_total),
        "annotation_annotated": int(annotation_annotated),
        "annotation_confirmed_empty": int(annotation_empty),
        "annotation_unannotated": int(annotation_unannotated),
        "annotation_boxes": int(annotation_boxes),
        "upload_file_count": int(upload_file_count),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=float, default=1200.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    workspace = Path(tempfile.mkdtemp(prefix="zip-processing-10k-acceptance-")).resolve()
    data_root = workspace / "platform-data"
    data_root.mkdir(parents=True, exist_ok=True)
    zip_path = workspace / "ten-thousand-yolo.zip"
    server_log = workspace / "uvicorn.log"
    metrics = build_yolo_zip(zip_path)

    env = os.environ.copy()
    env["MC_TRAIN_DATA_DIR"] = str(data_root)
    env["MC_PLATFORM_VERSION"] = "test"
    env["PYTHONUNBUFFERED"] = "1"
    base_url = f"http://127.0.0.1:{args.port}"

    with server_log.open("w", encoding="utf-8") as log_handle:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
                "--log-level",
                "warning",
            ],
            cwd=repo_root,
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )

    process = psutil.Process(server.pid)
    session = requests.Session()
    result: dict[str, object] = {
        "image_count": IMAGE_COUNT,
        "workspace": str(workspace),
        **metrics,
    }
    try:
        wait_for_server(session, base_url, server)
        rss_baseline_mb, fd_baseline = process_resources(process)
        fd_baseline_snapshot = fd_snapshot(process)
        result["rss_baseline_mb"] = round(rss_baseline_mb, 3)
        result["fd_baseline"] = fd_baseline
        result["fd_baseline_snapshot"] = fd_baseline_snapshot

        create_project = session.post(
            f"{base_url}/api/projects",
            json={"name": "zip-10k-processing-acceptance", "description": "", "labels": []},
            timeout=30,
        )
        create_project.raise_for_status()
        project_id = create_project.json()["id"]
        result["project_id"] = project_id

        upload_result: dict[str, object] = {}
        upload_ping_latencies: list[float] = []
        upload_ping_failures = 0

        def do_upload():
            started = time.perf_counter()
            try:
                with zip_path.open("rb") as stream:
                    response = session.post(
                        f"{base_url}/api/v19/projects/{project_id}/datasets/default/import/jobs",
                        files={"file": (zip_path.name, stream, "application/zip")},
                        timeout=300,
                    )
                upload_result["http_seconds"] = time.perf_counter() - started
                upload_result["status_code"] = response.status_code
                upload_result["body"] = response.json()
            except BaseException as error:
                upload_result["error"] = repr(error)

        upload_thread = threading.Thread(target=do_upload, daemon=True)
        upload_thread.start()
        while upload_thread.is_alive():
            try:
                _, latency = timed_get(session, f"{base_url}/api/projects", timeout=5.0)
                upload_ping_latencies.append(latency)
            except Exception:
                upload_ping_failures += 1
            time.sleep(0.05)
        upload_thread.join()
        if upload_result.get("error"):
            raise RuntimeError(f"upload failed: {upload_result['error']}")
        if int(upload_result.get("status_code") or 0) >= 400:
            raise RuntimeError(f"upload status={upload_result.get('status_code')} body={upload_result.get('body')}")
        job = dict(upload_result["body"])
        job_id = job["id"]
        result.update(
            {
                "job_id": job_id,
                "create_http_seconds": round(float(upload_result["http_seconds"]), 6),
                "server_upload_seconds": float(job.get("upload_seconds") or 0),
                "server_scan_seconds": float(job.get("scan_seconds") or 0),
                "create_image_count": int(job.get("image_count") or 0),
                "create_preview_count": len(job.get("images") or []),
                "create_images_truncated": bool(job.get("images_truncated")),
                "upload_ping_samples": len(upload_ping_latencies),
                "upload_ping_failures": upload_ping_failures,
                "upload_ping_p50_ms": round(median(upload_ping_latencies) * 1000, 3) if upload_ping_latencies else 0.0,
                "upload_ping_p95_ms": round(percentile(upload_ping_latencies, 0.95) * 1000, 3) if upload_ping_latencies else 0.0,
                "upload_ping_max_ms": round(max(upload_ping_latencies) * 1000, 3) if upload_ping_latencies else 0.0,
            }
        )

        start_started = time.perf_counter()
        start_response = session.post(
            f"{base_url}/api/v19/projects/{project_id}/import/jobs/{job_id}/start",
            json={"selected_paths": []},
            timeout=30,
        )
        start_seconds = time.perf_counter() - start_started
        start_response.raise_for_status()
        result["start_http_seconds"] = round(start_seconds, 6)
        result["start_status"] = start_response.json().get("status")

        poll_latencies: list[float] = []
        progress_values: list[float] = []
        observed_updates: set[str] = set()
        stage_first_seen: dict[str, float] = {}
        stage_last_seen: dict[str, float] = {}
        rss_peak_mb = rss_baseline_mb
        fd_peak = fd_baseline
        worker_started = time.perf_counter()
        terminal_job = None
        first_94_at = None
        last_progress = -1.0
        deadline = time.monotonic() + args.timeout

        while time.monotonic() < deadline:
            response, latency = timed_get(
                session,
                f"{base_url}/api/v19/projects/{project_id}/import/jobs/{job_id}",
                timeout=10.0,
            )
            poll_latencies.append(latency)
            body = response.json()
            progress = float(body.get("progress") or 0.0)
            if progress + 1e-9 < last_progress:
                raise AssertionError(f"progress regressed: {last_progress} -> {progress}")
            last_progress = progress
            progress_values.append(progress)
            observed_updates.add(str(body.get("updated_at") or ""))
            stage = str(body.get("stage") or "")
            now = time.perf_counter()
            stage_first_seen.setdefault(stage, now - worker_started)
            stage_last_seen[stage] = now - worker_started
            if first_94_at is None and progress >= 94.0 and body.get("status") == "running":
                first_94_at = now
            rss_mb, fd_count = process_resources(process)
            rss_peak_mb = max(rss_peak_mb, rss_mb)
            fd_peak = max(fd_peak, fd_count)
            if body.get("status") in TERMINAL:
                terminal_job = body
                break
            time.sleep(0.1)

        if terminal_job is None:
            raise TimeoutError(f"10k import did not finish within {args.timeout}s")
        worker_wall_seconds = time.perf_counter() - worker_started
        rss_end_mb, fd_end = process_resources(process)
        fd_end_snapshot = fd_snapshot(process)
        baseline_targets = dict(fd_baseline_snapshot.get("target_counts") or {})
        end_targets = dict(fd_end_snapshot.get("target_counts") or {})
        baseline_categories = dict(fd_baseline_snapshot.get("category_counts") or {})
        end_categories = dict(fd_end_snapshot.get("category_counts") or {})
        result.update(
            {
                "worker_wall_seconds": round(worker_wall_seconds, 6),
                "images_per_second": round(IMAGE_COUNT / worker_wall_seconds, 3),
                "terminal_status": terminal_job.get("status"),
                "terminal_progress": float(terminal_job.get("progress") or 0.0),
                "server_processing_seconds": float(terminal_job.get("processing_seconds") or 0.0),
                "poll_samples": len(poll_latencies),
                "poll_p50_ms": round(median(poll_latencies) * 1000, 3),
                "poll_p95_ms": round(percentile(poll_latencies, 0.95) * 1000, 3),
                "poll_max_ms": round(max(poll_latencies) * 1000, 3),
                "observed_job_updates": len(observed_updates),
                "observed_progress_values": len(set(progress_values)),
                "rss_peak_mb": round(rss_peak_mb, 3),
                "rss_growth_peak_mb": round(rss_peak_mb - rss_baseline_mb, 3),
                "rss_end_mb": round(rss_end_mb, 3),
                "fd_peak": fd_peak,
                "fd_peak_growth": fd_peak - fd_baseline,
                "fd_end": fd_end,
                "fd_end_growth": fd_end - fd_baseline,
                "fd_end_snapshot": fd_end_snapshot,
                "fd_positive_target_delta": positive_counter_delta(end_targets, baseline_targets),
                "fd_positive_category_delta": positive_counter_delta(end_categories, baseline_categories),
                "terminal_tail_seconds": round(time.perf_counter() - first_94_at, 6) if first_94_at else None,
                "stage_first_seen_seconds": {key: round(value, 6) for key, value in stage_first_seen.items()},
                "stage_last_seen_seconds": {key: round(value, 6) for key, value in stage_last_seen.items()},
            }
        )

        report = dict(terminal_job.get("report") or {})
        result.update(
            {
                "report_imported_images": int(report.get("imported_images") or 0),
                "report_annotated_images": int(report.get("annotated_images") or 0),
                "report_boxes": int(report.get("boxes") or 0),
                "report_invalid_boxes": int(report.get("invalid_boxes") or 0),
                "report_missing_images": int(report.get("missing_images") or 0),
                "report_skipped_images": int(report.get("skipped_images") or 0),
                "report_unmatched_labels": int(report.get("unmatched_labels") or 0),
            }
        )

        project_path = data_root / "projects" / project_id
        result.update(sqlite_truth(project_path))
        job_path = project_path / "import_jobs" / job_id / "job.json"
        manifest_path = project_path / "import_jobs" / job_id / "scan-images.json"
        result["job_json_bytes"] = job_path.stat().st_size
        result["scan_manifest_bytes"] = manifest_path.stat().st_size
        result["scan_manifest_count"] = len(json.loads(manifest_path.read_text(encoding="utf-8")))

        log_text = server_log.read_text(encoding="utf-8", errors="replace") if server_log.exists() else ""
        lock_matches = re.findall(r"database\s+is\s+locked|sqlite[^\n]{0,80}\bbusy\b", log_text, flags=re.I)
        result["sqlite_lock_busy_incidents"] = len(lock_matches)
        result["server_log_bytes"] = len(log_text.encode("utf-8"))

        assertions = {
            "terminal_done": terminal_job.get("status") == "done",
            "progress_100": float(terminal_job.get("progress") or 0.0) == 100.0,
            "create_10k": result["create_image_count"] == IMAGE_COUNT,
            "bounded_create_preview": result["create_preview_count"] <= 500 and result["create_images_truncated"] is True,
            "report_truth": result["report_imported_images"] == IMAGE_COUNT and result["report_annotated_images"] == IMAGE_COUNT and result["report_boxes"] == IMAGE_COUNT,
            "material_truth": result["material_total"] == IMAGE_COUNT and result["material_boxes"] == IMAGE_COUNT and result["material_annotated"] == IMAGE_COUNT,
            "annotation_truth": result["annotation_total"] == IMAGE_COUNT and result["annotation_annotated"] == IMAGE_COUNT and result["annotation_boxes"] == IMAGE_COUNT,
            "stored_file_truth": result["upload_file_count"] == IMAGE_COUNT,
            "manifest_truth": result["scan_manifest_count"] == IMAGE_COUNT,
            "hot_job_bounded": result["job_json_bytes"] < 64 * 1024,
            "progress_is_live": result["observed_job_updates"] >= 10 and result["observed_progress_values"] >= 10,
            "start_is_background": result["start_http_seconds"] < 5.0,
            "control_plane_responsive": result["poll_p95_ms"] < 2000 and result["poll_max_ms"] < 5000,
            "upload_control_plane_responsive": result["upload_ping_failures"] == 0 and (not upload_ping_latencies or result["upload_ping_p95_ms"] < 2000),
            "sqlite_no_lock_busy": result["sqlite_lock_busy_incidents"] == 0,
            "fd_recovered": result["fd_peak_growth"] < 128 and result["fd_end_growth"] < 32,
            "rss_bounded": result["rss_growth_peak_mb"] < 1024 and result["rss_peak_mb"] < 1536,
            "no_import_errors": result["report_invalid_boxes"] == 0 and result["report_missing_images"] == 0 and result["report_skipped_images"] == 0,
        }
        result["assertions"] = assertions
        result["acceptance_passed"] = all(assertions.values())

        output = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        print("ZIP_10K_ACCEPTANCE=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
        print(output)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output + "\n", encoding="utf-8")
        failed = [name for name, value in assertions.items() if not value]
        if failed:
            raise AssertionError("10k acceptance failed: " + ", ".join(failed))
    finally:
        try:
            session.close()
        except Exception:
            pass
        if server.poll() is None:
            try:
                server.send_signal(signal.SIGTERM)
                server.wait(timeout=10)
            except Exception:
                server.kill()
                server.wait(timeout=5)
        if server_log.exists():
            print("ZIP_10K_SERVER_LOG_TAIL")
            print(server_log.read_text(encoding="utf-8", errors="replace")[-8000:])


if __name__ == "__main__":
    main()
