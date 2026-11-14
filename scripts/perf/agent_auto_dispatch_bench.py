"""Isolated Agent auto-assignment load probe; never connects to production.

Records per-request P50/P95, SQLite writer probe latency/busy events and
execution-fence correctness. Descriptive figures, not production SLA evidence.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from platform_core.agent_execution import AgentExecutionService
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


def summary(values):
    if not values:
        return {"samples": 0, "p50_ms": 0, "p95_ms": 0, "max_ms": 0}
    values = sorted(values)
    def pct(p):
        x = (len(values) - 1) * p / 100.0
        i = int(x)
        return round(values[i] + (values[min(i + 1, len(values) - 1)] - values[i]) * (x - i), 3)
    return {"samples": len(values), "p50_ms": pct(50), "p95_ms": pct(95), "max_ms": round(values[-1], 3)}


def seed(repo, artifacts, size, profile):
    local = {"epochs": 10}
    remote = {"target": "remote", "remote_execution": {
        "version": 1, "task_kind": "TRAINING", "transport": "object-storage-v1"}}
    payload = remote if profile == "remote-heavy" else local
    start = time.perf_counter()
    artifacts.atomic_write_json("bench-000000", "request.json", payload)
    repo.create(TaskRecord.new(
        task_id="bench-000000", project_id="isolated-perf", kind=TaskKind.TRAINING,
        payload_ref="request.json",
        resource_key="training:remote:scheduler" if profile == "remote-heavy" else "training:auto",
        priority=1,
    ), artifacts=artifacts)
    with closing(repo._connect()) as db:
        base_row = db.execute("SELECT * FROM tasks WHERE task_id='bench-000000'").fetchone()
        keys = list(base_row.keys())
        index = keys.index("task_id")
        vals = [base_row[k] for k in keys]
        query = f"INSERT INTO tasks ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})"
        new_rows = []
        encoded = json.dumps(payload)
        for n in range(1, size):
            tid = f"bench-{n:06d}"
            vals_copy = list(vals)
            vals_copy[index] = tid
            new_rows.append(tuple(vals_copy))
            path = artifacts.artifact_path(tid, "request.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(encoded, encoding="utf-8")
        db.execute("BEGIN IMMEDIATE")
        db.executemany(query, new_rows)
        db.commit()
    if profile == "local-tail":
        artifacts.atomic_write_json("remote-at-end", "request.json", remote)
        repo.create(TaskRecord.new(
            task_id="remote-at-end", project_id="isolated-perf", kind=TaskKind.TRAINING,
            payload_ref="request.json", resource_key="training:remote:scheduler",
            priority=50,
        ), artifacts=artifacts)
    return round(time.perf_counter() - start, 3)


def register(repo, count):
    nodes = ServiceNodeRepository(repo)
    result = []
    for n in range(count):
        node_id = f"agent-{n}"
        _, token = nodes.create({
            "node_id": node_id, "display_name": node_id, "connection_mode": "agent",
            "enabled": True, "allowed_capabilities": ["training"],
        })
        nodes.heartbeat(node_id, token, {
            "hostname": node_id, "build_id": "isolated-benchmark",
            "reported_capabilities": ["training"],
            "resources": {
                "cpu": {"logical_cores": 8},
                "memory": {"available_bytes": 16 * 1024**3},
                "disk": {"free_bytes": 128 * 1024**3},
                "gpu": {"gpus": [{
                    "id": "cuda:0", "index": 0, "uuid": f"synthetic-gpu-{n}",
                    "name": "isolated-benchmark", "memory_total_bytes": 24 * 1024**3,
                    "memory_free_bytes": 20 * 1024**3, "utilization_percent": 0,
                }]},
            },
        })
        result.append((node_id, token))
    return result


def probe_writer(repo, stop, measurements):
    while not stop.is_set():
        begin = time.perf_counter()
        try:
            with sqlite3.connect(repo.path, timeout=0.2, isolation_level=None) as db:
                db.execute("PRAGMA busy_timeout=200")
                db.execute("BEGIN IMMEDIATE")
                db.rollback()
            measurements["latencies"].append((time.perf_counter() - begin) * 1000)
        except sqlite3.OperationalError as error:
            if "locked" in str(error).lower() or "busy" in str(error).lower():
                measurements["busy"] += 1
            else:
                measurements["errors"].append(str(error))
        stop.wait(0.03)


def run_case(size, agents, repeat, profile):
    with tempfile.TemporaryDirectory(prefix="agent-auto-load-") as directory:
        runtime = Path(directory) / "task_runtime"
        repo = TaskRepository(runtime / "tasks.sqlite3")
        artifacts = ArtifactStore(runtime / "artifacts")
        setup_seconds = seed(repo, artifacts, size, profile)
        nodes = register(repo, agents)
        stop = threading.Event()
        writer = {"latencies": [], "busy": 0, "errors": []}
        watcher = threading.Thread(target=probe_writer, args=(repo, stop, writer), daemon=True)
        watcher.start()
        def claim(n):
            node_id, token = nodes[n % agents]
            begin = time.perf_counter()
            initialized_at = None
            claim_started = None
            try:
                # FastAPI creates this service on each /assignments/claim request.
                service = AgentExecutionService(
                    repo, artifacts, heartbeat_ttl_seconds=3600, auto_assign_enabled=True)
                initialized_at = time.perf_counter()
                claim_started = initialized_at
                item = service.claim_assignment(node_id, token)
                claim = None
                if item:
                    assignment = item["assignment"]
                    claim = {
                        "task_id": item["task"]["task_id"],
                        "token": assignment["assignment_lease_token"],
                        "expires_at": assignment["lease_expires_at"],
                        "observed_at": datetime.now(timezone.utc).timestamp(),
                    }
                ended = time.perf_counter()
                return (
                    (ended - begin) * 1000,
                    (initialized_at - begin) * 1000,
                    (ended - claim_started) * 1000,
                    claim, None,
                )
            except Exception as error:
                ended = time.perf_counter()
                return (
                    (ended - begin) * 1000,
                    ((initialized_at or ended) - begin) * 1000,
                    (ended - claim_started) * 1000 if claim_started is not None else 0,
                    None, f"{type(error).__name__}: {error}",
                )
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=agents) as pool:
            results = list(pool.map(claim, range(agents * repeat)))
        wall_s = round(time.perf_counter() - start, 3)
        stop.set()
        watcher.join(timeout=2)
        claims = [claim for _, _, _, claim, _ in results if claim]
        failures = [error for _, _, _, _, error in results if error] + writer["errors"]
        # CLAIMED is an expiring reservation, not a started execution. A task
        # whose Agent never calls /start can be offered again with a new token
        # after its prior claim lease expires. That is not duplicate execution.
        # Only overlapping valid claim tokens would violate exclusive claiming.
        by_task = {}
        overlap = []
        lease_reissues = 0
        for claim in sorted(claims, key=lambda value: value["observed_at"]):
            prior = by_task.get(claim["task_id"])
            if prior is not None:
                lease_reissues += 1
                prior_expires = datetime.fromisoformat(
                    str(prior["expires_at"]).replace("Z", "+00:00")
                ).timestamp()
                if (
                    prior["token"] == claim["token"]
                    or claim["observed_at"] < prior_expires - 0.5
                ):
                    overlap.append(claim["task_id"])
            by_task[claim["task_id"]] = claim
        if overlap:
            failures.append(f"OVERLAPPING_CLAIM_TOKENS: {overlap[:5]}")
        with closing(repo._connect()) as db:
            active = db.execute(
                "SELECT COUNT(*) FROM task_node_assignments WHERE state IN ('ASSIGNED','CLAIMED')"
            ).fetchone()[0]
        return {
            "queue_profile": profile, "queued_task_count": size, "agent_count": agents,
            "polls_per_agent": repeat, "setup_seconds_excluded": setup_seconds,
            "poll_wall_s": wall_s,
            "poll_latency": summary([ms for ms, _, _, _, _ in results]),
            # Inclusive timing split for root cause analysis: constructor
            # includes node/assignment schema ensure and fenced repository;
            # business includes authentication, claim, and Agent auto-assign.
            "service_init_latency": summary([ms for _, ms, _, _, _ in results]),
            "claim_business_latency": summary([ms for _, _, ms, _, _ in results]),
            "sqlite_writer_latency": summary(writer["latencies"]),
            "sqlite_writer_busy": writer["busy"],
            "total_claim_responses": len(claims),
            "distinct_claimed_tasks": len(by_task),
            "lease_reissues_without_start": lease_reissues,
            "active_assignments": active,
            "errors": failures[:10],
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000])
    parser.add_argument("--agents", nargs="+", type=int, default=[1, 4, 8])
    parser.add_argument("--polls", type=int, default=3)
    parser.add_argument("--output", default="agent_dispatch_benchmark.json")
    args = parser.parse_args()
    results = {"host": {"python": platform.python_version(), "system": platform.platform()},
               "mode": "isolated_service_claim_not_full_http", "cases": []}
    failed = False
    try:
        for profile in ("local-tail", "remote-heavy"):
            for size in args.sizes:
                for agents in args.agents:
                    outcome = run_case(size, agents, args.polls, profile)
                    failed = failed or bool(outcome["errors"])
                    results["cases"].append(outcome)
                    print(json.dumps(outcome, ensure_ascii=False), flush=True)
    finally:
        Path(args.output).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Isolated benchmark results written to {args.output}", flush=True)
    print("Numbers are NOT a production SLA, HTTP network measurement or OSS/GPU UAT.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
