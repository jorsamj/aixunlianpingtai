"""Standalone optional engine. Execute in its own environment/process, once per task.

Only temporary FiftyOne metadata is written. Original paths are referenced, never
exported/copied. This module is not imported by platform startup or base cleaning.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
from contextlib import contextmanager
import subprocess
import socket
import ipaddress
import math

if __package__:
    from .contract import FEATURE, validate_manifest
else:
    from contract import FEATURE, validate_manifest


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _feature(path):
    import numpy as np
    from PIL import Image, ImageOps
    from skimage.feature import hog

    with Image.open(path) as image:
        rgb = np.asarray(ImageOps.exif_transpose(image).convert("RGB").resize((64, 64)), dtype=np.float32) / 255
    gray = rgb @ np.array([.2126, .7152, .0722], dtype=np.float32)
    shape = hog(gray, orientations=9, pixels_per_cell=(16, 16), cells_per_block=(1, 1), feature_vector=True)
    color = np.concatenate([np.histogram(rgb[:, :, channel], bins=16, range=(0, 1))[0] for channel in range(3)])
    color = np.sqrt(color / max(1, color.sum()))
    vector = np.concatenate([shape / max(1e-12, np.linalg.norm(shape)) * .8, color * .2]).astype("float32")
    return vector / max(1e-12, np.linalg.norm(vector))


def _mistakenness(dataset, rows, ids, brain, fo):
    """Analyze copied detection evidence; never publish it as formal GT/metrics."""
    from PIL import Image
    import math
    eligible = []
    for row, sample_id in zip(rows, ids):
        proof = row.get("prediction_evidence")
        if (not isinstance(proof, dict) or not all(re.fullmatch("[0-9a-f]{64}", str(proof.get(key, "")))
                for key in ("evaluation_id", "model_sha256", "benchmark_scope_id"))
            or proof.get("image_content_sha256") != row["content_sha256"]
            or not re.fullmatch("[0-9a-f]{64}", str(row.get("annotation_digest", "")))
            or row.get("annotation_state") not in {"annotated", "confirmed_empty"}
            or not isinstance(row.get("gt_boxes"), list) or not isinstance(row.get("pred_boxes"), list)):
            continue
        with Image.open(row["path"]) as image:
            width, height = image.size

        def detections(boxes, predicted):
            output = []
            for box in boxes:
                label = box.get("label")
                coordinates = [float(box[key]) for key in ("x1", "y1", "x2", "y2")]
                x1, y1, x2, y2 = coordinates
                if not label or not all(math.isfinite(v) for v in coordinates) or not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                    raise ValueError("invalid verified detection coordinates/label")
                kwargs = {}
                if predicted:
                    confidence = float(box["confidence"])
                    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                        raise ValueError("invalid verified prediction confidence")
                    kwargs["confidence"] = confidence
                output.append(fo.Detection(label=label, bounding_box=[x1/width, y1/height, (x2-x1)/width, (y2-y1)/height], **kwargs))
            return fo.Detections(detections=output)

        sample = dataset[sample_id]
        sample["formal_gt_copy"] = detections(row["gt_boxes"], False)
        sample["verified_predictions"] = detections(row["pred_boxes"], True)
        sample.save()
        eligible.append(sample_id)
    if not eligible:
        return {"status": "not_checked", "checked": 0, "reason": "未提供经过核验的模型预测与正式GT证据"}, []
    view = dataset.select(eligible)
    brain.compute_mistakenness(view, "verified_predictions", "formal_gt_copy", copy_missing=False, progress=False)
    candidates = []
    mapping = dict(zip(ids, rows))
    for sample in view:
        row = mapping[sample.id]
        missing, spurious = int(sample["possible_missing"] or 0), int(sample["possible_spurious"] or 0)
        score = sample["mistakenness"]
        # Brain uses -1 when no matched GT exists; this is unavailable, not a score.
        if score is not None and score < 0:
            score = None
        if missing or spurious or score is not None and score > .5:
            candidates.append({"image_id": row["image_id"], "issue_type": "suspected_annotation",
                "possible_missing": missing, "possible_spurious": spurious, "mistakenness": score,
                "annotation_digest": row["annotation_digest"], "prediction_evidence": row["prediction_evidence"],
                "reason": "模型与GT存在差异，仅为疑似问题，需人工复核；不改变正式评测统计",
                "requires_confirmation": True})
    return {"status": "completed" if len(eligible) == len(rows) else "partial",
            "checked": len(eligible), "not_checked": len(rows)-len(eligible)}, candidates


def _configure(root, database_name):
    # Refuse reuse: a parent must launch a fresh child for each analysis.
    if "fiftyone" in sys.modules:
        raise RuntimeError("FiftyOne engine requires a fresh isolated process")
    root.mkdir(parents=True, exist_ok=False)
    (root / "ownership.json").write_text(json.dumps({"database_name": database_name}), encoding="utf-8")
    config = root / "config.json"
    config.write_text("{}", encoding="utf-8")
    for key in list(os.environ):
        if key.startswith("FIFTYONE_"):
            del os.environ[key]
    os.environ.update({
        "FIFTYONE_CONFIG_PATH": str(config), "FIFTYONE_DATABASE_NAME": database_name,
        "FIFTYONE_DATABASE_DIR": str(root / "database"), "FIFTYONE_DO_NOT_TRACK": "true",
        "FIFTYONE_MODEL_ZOO_DIR": str(root / "models"), "FIFTYONE_DATASET_ZOO_DIR": str(root / "datasets"),
        "FIFTYONE_PLUGINS_DIR": str(root / "plugins"),
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    })


def analyze(value, work_root):
    value = validate_manifest(value)
    root = Path(work_root).resolve()
    database_name = "smart_audit_" + uuid.uuid4().hex
    _configure(root, database_name)
    with _local_connections_only():
        with _isolated_mongo(root):
            return _analyze(value, root, database_name)


@contextmanager
def _local_connections_only():
    """Fail closed on Python network model/telemetry calls in this child only."""
    connect, connect_ex, lookup = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def check(host):
        if host == "localhost":
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        raise PermissionError("SMART_AUDIT_OFFLINE: external connections disabled")

    def checked_connect(method):
        def invoke(instance, address):
            if isinstance(address, tuple):
                check(address[0])
            return method(instance, address)
        return invoke

    def checked_lookup(host, *args, **kwargs):
        check(host)
        return lookup(host, *args, **kwargs)

    socket.socket.connect, socket.socket.connect_ex = checked_connect(connect), checked_connect(connect_ex)
    socket.getaddrinfo = checked_lookup
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, lookup


@contextmanager
def _isolated_mongo(root):
    """Do not use FiftyOne's multi-client service (it can reuse another dbpath)."""
    import importlib.metadata
    import psutil
    import importlib.util

    # Reuse the original controller without importing platform_core.__init__
    # (which initializes the platform's material-module dependency graph).
    control_path = Path(__file__).resolve().parents[1] / "task_runtime" / "process_control.py"
    spec = importlib.util.spec_from_file_location("_smart_audit_existing_process_control", control_path)
    control = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = control
    spec.loader.exec_module(control)

    for name, version in (("fiftyone", "1.22.1"), ("fiftyone-brain", "0.25.0"), ("fiftyone-db", "1.4.1")):
        if importlib.metadata.version(name) != version:
            raise ValueError(f"SMART_AUDIT_ENGINE_VERSION_UNVERIFIED: {name}")

    installed = importlib.metadata.distribution("fiftyone-db")
    executable = next((Path(installed.locate_file(path)).resolve() for path in installed.files
        if str(path).replace("\\", "/").endswith("/bin/mongod.exe" if os.name == "nt" else "/bin/mongod")), None)
    if executable is None or not executable.is_file():
        raise ValueError("isolated mongod executable unavailable")
    directory = root / "database"
    directory.mkdir()
    argv = [str(executable), "--dbpath", str(directory), "--bind_ip", "127.0.0.1", "--port", "0",
            "--logpath", str(root / "mongo.log")]
    if os.name != "nt":
        argv.append("--nounixsocket")
    # Reuse the pinned upstream single-client parent-death monitor, never its
    # global multi-client service discovery. EOF also occurs on os._exit/crash.
    supervisor = Path(importlib.metadata.distribution("fiftyone").locate_file("fiftyone/service/main.py"))
    argv = [sys.executable, str(supervisor), "--51-service", "smart-audit-" + uuid.uuid4().hex, *argv]
    with (root / "mongo-stdio.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        identity = control.ProcessIdentity(process.pid, psutil.Process(process.pid).create_time(), control.hash_command(argv))
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and process.poll() is None:
                children = psutil.Process(process.pid).children(recursive=True)
                listeners = [c for child in children for c in child.net_connections(kind="inet")
                    if c.status == psutil.CONN_LISTEN]
                if listeners:
                    if len(listeners) != 1 or listeners[0].laddr.ip != "127.0.0.1":
                        raise RuntimeError("unexpected MongoDB listen address")
                    os.environ["FIFTYONE_DATABASE_URI"] = f"mongodb://127.0.0.1:{listeners[0].laddr.port}"
                    os.environ["FIFTYONE_DISABLE_SERVICES"] = "1"
                    yield
                    return
                time.sleep(.1)
            raise TimeoutError("isolated MongoDB failed to listen")
        finally:
            if process.poll() is None:
                process.stdin.close()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    control.ProcessController().terminate_tree(identity, timeout=5)
                    process.wait(timeout=5)


def _analyze(value, root, database_name):
    started = time.monotonic()
    import numpy as np
    import fiftyone as fo
    import fiftyone.brain as brain
    import fiftyone.core.odm.database as database

    result = {"schema_version": 1, "project_id": value["project_id"], "task_id": value["task_id"],
              "engine": "fiftyone", "feature": FEATURE, "feature_description": "HOG形状与颜色直方图，非语义模型；仅供人工复核",
              "total": len(value["images"]), "scanned": 0, "failed": 0, "failures": [], "similar_pairs": [],
              "uniqueness": [], "checks": {}, "database_cleaned": False,
              "threshold": value.get("threshold", .4), "metric": "unit_normalized_euclidean",
              "distance_description": "单位特征欧氏距离，越小越相似；不是相似百分比", "automatic_execution": False,
              "requires_confirmation": True, "source_images_copied": 0}
    dataset = None
    try:
        if fo.config.database_name != database_name or Path(fo.config.database_dir).resolve() != root / "database":
            raise RuntimeError("isolated database identity mismatch")
        dataset = fo.Dataset(name=database_name)
        samples, embeddings, rows = [], [], []
        for row in value["images"]:
            try:
                if _digest(row["path"]) != row["content_sha256"]:
                    raise ValueError("SOURCE_CONTENT_CHANGED")
                feature = _feature(row["path"])
                if _digest(row["path"]) != row["content_sha256"]:
                    raise ValueError("SOURCE_CONTENT_CHANGED")
                samples.append(fo.Sample(filepath=row["path"], platform_image_id=row["image_id"],
                    source_sha256=row["content_sha256"], frozen_split=row.get("frozen_split", "")))
                embeddings.append(feature)
                rows.append(row)
            except (OSError, ValueError) as error:
                result["failed"] += 1
                result["failures"].append({"image_id": row["image_id"], "reason": type(error).__name__ + ": " + str(error)[:200]})
            result["scanned"] += 1
        result["succeeded"] = len(rows)
        if not rows:
            raise ValueError("SMART_AUDIT_NO_READABLE_INPUT")
        dataset.add_samples(samples)
        ids = dataset.values("id")
        mapping = dict(zip(ids, rows))
        vectors = np.asarray(embeddings, dtype="float32")
        if len(rows) > 1:
            # The pinned sklearn backend centers its array in-place. Euclidean
            # distance is translation-invariant; centered cosine is not. Supply
            # a copy and report this exact metric rather than a fake percentage.
            similarity = brain.compute_similarity(dataset, embeddings=vectors.copy(), backend="sklearn", metric="euclidean", progress=False)
            duplicates = brain.compute_near_duplicates(dataset, similarity_index=similarity,
                threshold=result["threshold"], progress=False)
            result["duplicate_count"] = len(duplicates.duplicate_ids)
            for source_id, neighbors in duplicates.neighbors_map.items():
                for target_id, distance in neighbors:
                    result["similar_pairs"].append({"image_ids": [mapping[source_id]["image_id"], mapping[target_id]["image_id"]],
                        "distance": float(distance), "issue_type": "visual_similarity", "requires_confirmation": True})
            brain.compute_uniqueness(dataset, embeddings=vectors.copy(), progress=False)
            result["uniqueness"] = [{"image_id": row["image_id"],
                "value": float(score) if score is not None and math.isfinite(float(score)) else None,
                "status": "computed" if score is not None and math.isfinite(float(score)) else "not_checked",
                "reason": None if score is not None and math.isfinite(float(score)) else "特征距离退化，独特性未定义"}
                for row, score in zip(rows, dataset.values("uniqueness"))]
            result["checks"]["visual_similarity"] = {"status": "completed", "checked": len(rows)}
            proof = value.get("frozen_split_evidence", "")
            if re.fullmatch("[0-9a-f]{64}", str(proof)) and all(row.get("frozen_split") in {"train", "val", "test"} for row in rows):
                leaks = brain.compute_leaky_splits(dataset, splits="frozen_split", similarity_index=similarity,
                    threshold=result["threshold"], progress=False)
                result["checks"]["leakage"] = {"status": "completed", "checked": len(rows), "evidence": proof,
                    "image_ids": sorted({mapping[key]["image_id"] for key in leaks.leak_ids})}
            else:
                result["checks"]["leakage"] = {"status": "not_checked", "reason": "缺少完整可信冻结划分"}
        else:
            result["checks"]["visual_similarity"] = {"status": "not_checked", "reason": "不足两张可读图片"}
            result["checks"]["leakage"] = {"status": "not_checked", "reason": "不足两张可读图片"}
        result["checks"]["mistakenness"], result["annotation_candidates"] = _mistakenness(dataset, rows, ids, brain, fo)
        result["checks"]["hardness"] = {"status": "not_checked", "reason": "不生成缺少logits依据的困难度分数"}
        result["complete"] = result["failed"] == 0
        result["elapsed_seconds"] = time.monotonic() - started
        return result
    finally:
        # Own exact UUID database only; never enumerate/drop platform databases.
        if dataset is not None:
            dataset.delete()
        ownership = json.loads((root / "ownership.json").read_text(encoding="utf-8"))
        if ownership["database_name"] == database_name and fo.config.database_name == database_name:
            client = database.get_db_client()
            client.drop_database(database_name)
            result["database_cleaned"] = database_name not in client.list_database_names()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("work_root")
    parser.add_argument("output")
    args = parser.parse_args()
    outcome = analyze(json.loads(Path(args.manifest).read_text(encoding="utf-8")), args.work_root)
    Path(args.output).write_text(json.dumps(outcome, ensure_ascii=False, allow_nan=False), encoding="utf-8")
