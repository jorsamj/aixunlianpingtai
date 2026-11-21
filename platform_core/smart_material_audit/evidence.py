"""Read-only projection of existing verified model/evaluation/frozen evidence."""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3

from ..algorithm_sql_store import AlgorithmSqlStore
from ..evaluation_analysis import analyze_evaluation_trust
from ..scenario_models import resolve_scenario_model, ScenarioModelUnavailable


def load_evidence(project, options, repository, artifacts):
    empty = {"splits": {}, "predictions": {}, "provenance": {},
             "reason": "未选择可信模型评测；划分泄漏与错标分析未检查"}
    if not options.get("algorithm_id") or not options.get("version_id"):
        return empty
    try:
        project = Path(project)
        if not project.is_dir():
            return dict(empty,reason="项目不存在；不创建或迁移算法存储")
        store = AlgorithmSqlStore(project / "algorithms.json")
        # Use the existing Owner's row decoder; never ensure_ready/read_one,
        # because those intentionally migrate legacy stores in normal workflows.
        with closing(sqlite3.connect(store.db_path.resolve().as_uri()+"?mode=ro", uri=True)) as database:
            database.row_factory = sqlite3.Row
            if not store._initialization_complete(database):
                return dict(empty, reason="算法存储尚无受支持的只读证据；不自动迁移")
            algorithm = store._read_one_conn(database, options["algorithm_id"])
        if not algorithm:
            return dict(empty, reason="指定算法不可用，未检查预测与冻结划分")
        version = next((v for v in algorithm.get("versions", []) if v.get("id") == options["version_id"]), None)
        if not version:
            return dict(empty, reason="指定版本不可用，未检查预测与冻结划分")
        model = resolve_scenario_model(project.name, project, algorithm, version, repository, artifacts)
        evaluation = version.get("evaluation") or {}
        snapshot_id = str(evaluation.get("snapshot_id") or "")
        if not re.fullmatch("[0-9a-f]{64}", snapshot_id):
            return dict(empty, reason="缺少冻结Snapshot身份")
        path = project/"snapshots"/(snapshot_id+".json")
        if path.stat().st_size > 64*1024*1024:
            return dict(empty, reason="冻结证据超过当前只读内存上限，未检查")
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        trust = analyze_evaluation_trust(evaluation, snapshot, version, verified_model=model)
        if not any(c["code"] == "identity" and c["status"] == "passed" for c in trust["checks"]):
            return dict(empty, reason="原评测可信身份检查未通过；不使用其预测或展示字段推断划分")
        scope = evaluation["benchmark_scope"]["scope_id"]
        provenance = {"evaluation_id": evaluation["evaluation_id"], "model_sha256": model["model_sha256"],
                      "benchmark_scope_id": scope, "snapshot_id": snapshot_id,
                      "algorithm_id": options["algorithm_id"], "version_id": options["version_id"]}
        splits = {}
        for row in snapshot.get("images", []):
            role = {"validation": "val", "train": "train", "test": "test", "val": "val"}.get(row.get("role"))
            if role:
                splits[str(row.get("image_id"))] = {"split": role, "content_sha256": row.get("content_sha256")}
        labels = {int(row["class_id"]): str(row["code"]) for row in snapshot.get("label_schema", [])}
        predictions = {}
        for row in evaluation.get("sample_evidence", []):
            image_id = str(row.get("image_id") or "")
            if not image_id or row.get("evidence_complete") is not True or row.get("boxes_truncated"):
                continue
            boxes = []
            for box in row.get("pred_boxes", []):
                code = labels[int(box["class_id"])]
                x1,y1,x2,y2 = box["box"]
                boxes.append({"label": code, "class_id": int(box["class_id"]), "x1": x1,"y1": y1,"x2": x2,"y2": y2,
                              "confidence": box["confidence"]})
            predictions[image_id] = {"pred_boxes": boxes, "prediction_evidence": {
                **provenance, "image_content_sha256": row.get("image_content_sha256"),
                "image_width": row.get("image_width"), "image_height": row.get("image_height")}}
        return {"splits": splits, "predictions": predictions, "provenance": provenance, "reason": ""}
    except (OSError, ValueError, TypeError, KeyError, StopIteration, sqlite3.Error, ScenarioModelUnavailable):
        return dict(empty, reason="模型、评测或冻结证据不可验证；对应分析未检查，原业务不变")
