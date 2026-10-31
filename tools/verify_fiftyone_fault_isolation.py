"""Isolated acceptance using the existing process controller and base cleaning.

Invoke with the optional environment's Python path; no production paths/URLs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import psutil
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platform_core.cleaning import image_metrics
from platform_core.task_runtime.process_control import launch_process, ProcessController


CHILD = """
import sys,os,time,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import engine
root=Path(sys.argv[3]);ready=Path(sys.argv[4]);go=Path(sys.argv[5]);mode=sys.argv[6]
original=engine._feature
original_analyze=engine._analyze
def analyze_hook(*args):
 result=original_analyze(*args)
 if mode=='guardian_stall':
  import psutil
  guardians=[p for p in psutil.Process().children() if '--51-service' in p.cmdline() and str(root/'database') in p.cmdline()]
  assert len(guardians)==1
  guardians[0].suspend()
 return result
engine._analyze=analyze_hook
def feature(path):
 ready.write_text('ready')
 while not go.exists():time.sleep(.05)
 if mode=='crash':os._exit(23)
 if mode=='timeout':time.sleep(300)
 return original(path)
engine._feature=feature
result=engine.analyze(json.loads(Path(sys.argv[2]).read_text()),root)
Path(sys.argv[7]).write_text(json.dumps(result))
"""


def environment_digest():
    return hashlib.sha256(json.dumps(sorted((d.metadata['Name'], d.version)
        for d in importlib.metadata.distributions())).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("python")
    parser.add_argument("--out", required=True)
    parser.add_argument("--cases", nargs="+", choices=("success", "crash", "timeout", "guardian_stall"), default=["success", "crash", "timeout"])
    args = parser.parse_args()
    before_environment = environment_digest()
    results = []
    for mode in args.cases:
        with tempfile.TemporaryDirectory(prefix="smart-audit-owned-") as temporary:
            root = Path(temporary)
            image = Image.new("RGB", (96, 72), "navy")
            ImageDraw.Draw(image).rectangle((10, 8, 50, 55), fill="orange")
            image.save(root / "original.png")
            image.resize((192, 144)).save(root / "resized.jpg", quality=95)
            rows = [dict(image_id=name, path=str(root / name), content_sha256=hashlib.sha256((root/name).read_bytes()).hexdigest())
                for name in ("original.png", "resized.jpg")]
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(dict(project_id="isolated", task_id=mode, feature="hog-color-v1", images=rows)))
            ready, go, output = root / "ready", root / "go", root / "result.json"
            log = (root / "engine.log").open("w", encoding="utf-8")
            launched = launch_process([args.python, "-X", "utf8", "-c", CHILD,
                str(Path(__file__).resolve().parents[1]/"platform_core"/"smart_material_audit"),
                str(manifest), str(root/"engine"), str(ready), str(go), mode, str(output)],
                stdout=log, stderr=subprocess.STDOUT)
            started, peak_rss, peak_disk = time.monotonic(), 0, 0
            observed = {}
            baseline_completed = False
            try:
                while launched.process.poll() is None:
                    if time.monotonic() - started > 90:
                        raise TimeoutError("PoC startup/execution exceeded deadline")
                    try:
                        processes = [psutil.Process(launched.identity.pid)]
                        processes.extend(processes[0].children(recursive=True))
                    except psutil.NoSuchProcess:
                        continue
                    rss = 0
                    for process in processes:
                        try:
                            observed[process.pid] = process.create_time()
                            rss += process.memory_info().rss
                        except psutil.NoSuchProcess:
                            pass
                    peak_rss = max(peak_rss, rss)
                    peak_disk = max(peak_disk, sum(p.stat().st_size for p in root.rglob("*") if p.is_file()))
                    if ready.exists() and not baseline_completed:
                        # Real base image analysis while FiftyOne+Mongo are live.
                        metrics = image_metrics(root/"original.png", require_blur=True)
                        assert metrics["sha256"] == rows[0]["content_sha256"]
                        assert metrics["width"] == 96 and metrics["height"] == 72
                        baseline_completed = True
                        go.write_text("go")
                        if mode == "timeout":
                            ProcessController().terminate_tree(launched.identity, timeout=10)
                    time.sleep(.1)
                assert baseline_completed
                if mode in {"success", "guardian_stall"}:
                    assert launched.process.returncode == 0
                    outcome = json.loads(output.read_text())
                    assert outcome["database_cleaned"] and len(outcome["similar_pairs"]) == 1
                    if mode == "guardian_stall":
                        assert time.monotonic()-started >= 30
                elif mode == "crash":
                    assert launched.process.returncode == 23
                else:
                    assert launched.process.returncode != 0
                deadline = time.monotonic() + 15
                while True:
                    alive = []
                    for pid, creation in observed.items():
                        try:
                            if psutil.Process(pid).create_time() == creation:
                                alive.append(pid)
                        except psutil.NoSuchProcess:
                            pass
                    if not alive or time.monotonic() >= deadline:
                        break
                    time.sleep(.1)
                assert not alive, f"owned child processes survived {mode}: {alive}"
                assert all(hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() == row["content_sha256"] for row in rows)
                results.append(dict(case=mode, base_cleaning_passed=True, source_sha_unchanged=True,
                    remaining_owned_processes=0, elapsed_seconds=time.monotonic()-started,
                    peak_process_tree_rss_bytes=peak_rss, peak_temporary_logical_bytes=peak_disk))
            finally:
                if launched.process.poll() is None:
                    ProcessController().terminate_tree(launched.identity, timeout=10)
                log.close()
    assert environment_digest() == before_environment
    receipt = dict(cases=results, original_python_environment_unchanged=True,
        original_python=sys.executable, optional_python=args.python,
        scope="isolated fixtures; base image analysis only, not all platform business routes",
        temporary_roots_cleaned=True, physical_allocation="NOT VERIFIED; logical file bytes sampled")
    Path(args.out).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
