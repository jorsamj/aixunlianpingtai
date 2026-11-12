"""Operator-invoked native HTTP probe. Creates no task, GT or capacity manifest.

A valid empty result proves protocol compatibility, not recognition quality.
Requests timeout limits connect/read inactivity, not remote inference lifetime.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import statistics
import sys
import time
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_core.providers.base import ProviderRequestError
from platform_core.providers.wevisone_vision import WeVisOneVisionProvider


def probe(base_url, *, image_bytes, model, labels, workers=1, repeat=2, timeout=30, api_key=""):
    """Explicit calls only, no retries, no discovery, no persistent writes."""
    if workers not in {1,2} or not 1 <= repeat <= 20 or not 1 <= timeout <= 180:
        raise ValueError("invalid bounded probe settings")
    parts = urlsplit(base_url)
    if parts.scheme not in {"http","https"} or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("base URL must have no credentials, query or fragment")
    provider = WeVisOneVisionProvider(base_url=base_url,model=model,timeout=timeout,api_key=api_key)
    def call(index):
        started = time.monotonic()
        try:
            result = provider.annotate(image_bytes=image_bytes,prompt="",output_schema={},labels=labels)
            boxes = json.loads(result["text"])["boxes"]
            return {"probe_index":index,"success":True,"empty":not boxes,"http_status":result.get("status_code",200),
                    "request_id":result.get("request_id") or None,
                    "backend_instance_id":result.get("backend_instance_id") or None,
                    "actual_model":result.get("actual_model") or None,
                    "model_matches_expected":result.get("actual_model") == model if result.get("actual_model") else None,
                    "duration_ms":round((time.monotonic()-started)*1000,3)}
        except ProviderRequestError as error:
            return {"probe_index":index,"success":False,"empty":False,"error_code":error.code,
                    "http_status":error.status_code,"request_id":error.request_id or None,
                    "backend_instance_id":error.backend_instance_id or None,"actual_model":error.actual_model or None,
                    "model_matches_expected":error.actual_model == model if error.actual_model else None,
                    "duration_ms":round((time.monotonic()-started)*1000,3)}
        except Exception:
            return {"probe_index":index,"success":False,"empty":False,"error_code":"PROBE_LOCAL_ERROR",
                    "duration_ms":round((time.monotonic()-started)*1000,3)}
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(call,range(repeat)))
    wall = max(.000001,time.monotonic()-started)
    durations = sorted(row["duration_ms"] for row in results)
    instances = sorted({row["backend_instance_id"] for row in results if row.get("backend_instance_id")})
    observed = sorted({row["actual_model"] for row in results if row.get("actual_model")})
    return {"expected_model":model,"workers":workers,"repeat":repeat,"retries":0,
            "success":sum(row["success"] for row in results),"empty":sum(row["empty"] for row in results),
            "failure":sum(not row["success"] for row in results),"wall_seconds":round(wall,6),
            "mean_ms":statistics.mean(durations),"p50_ms":durations[int((len(durations)-1)*.5)],
            "p95_ms":durations[int((len(durations)-1)*.95)],"requests_per_minute":round(len(results)/wall*60,3),
            "observed_model_ids":observed,"observed_backend_instance_ids":instances,
            "instance_identity_status":"provided" if instances else "unknown",
            "recognition_quality":"NOT VERIFIED","gpu_participation":"NOT VERIFIED","results":results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url",required=True)
    parser.add_argument("--direct-base-url",action="append",default=[])
    parser.add_argument("--image",type=Path,required=True)
    parser.add_argument("--model",required=True)
    parser.add_argument("--labels",required=True,help="Comma-separated frozen labels")
    parser.add_argument("--workers",type=int,choices=[1,2],default=1)
    parser.add_argument("--repeat",type=int,choices=range(1,21),default=2)
    parser.add_argument("--timeout",type=int,choices=range(1,181),default=30)
    parser.add_argument("--api-key-env",help="Explicit environment variable name; never a key value")
    args = parser.parse_args(argv)
    if len(args.direct_base_url)>2:
        parser.error("at most two direct URLs")
    labels = [value.strip() for value in args.labels.split(",") if value.strip()]
    if not 1 <= len(labels) <= 100:
        parser.error("provide 1 to 100 labels")
    if args.api_key_env and not os.environ.get(args.api_key_env):
        parser.error("requested credential environment variable is unavailable")
    try:
        if args.image.stat().st_size>10*1024*1024:
            raise ValueError()
        image = args.image.read_bytes()
        common = dict(image_bytes=image,model=args.model,labels=labels,timeout=args.timeout,
                      api_key=os.environ.get(args.api_key_env,"") if args.api_key_env else "")
        direct = [probe(url,workers=1,repeat=1,**common) for url in args.direct_base_url]
        gateway = probe(args.base_url,workers=args.workers,repeat=args.repeat,**common)
    except (OSError,ValueError):
        parser.error("invalid local image or URL settings")
    print(json.dumps({"probe_kind":"operator_http_only","direct":direct,"gateway":gateway,
                      "capacity_manifest_written":False,"gt_written":False},ensure_ascii=False))
    return 0 if gateway["failure"]==0 and all(row["failure"]==0 for row in direct) else 1


if __name__ == "__main__":
    raise SystemExit(main())
