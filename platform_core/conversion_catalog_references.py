"""Read-only reference evidence for the existing conversion catalog Owner."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .compute_platform_catalog import conversion_templates, local_chip_key
from .errors import PlatformError
from .task_runtime.artifacts import ArtifactStore


def _json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _object(path):
    value=_json(path)
    if not isinstance(value,dict): raise ValueError("引用对象格式非法："+str(path))
    return value


def _rows(path, query):
    if not path.exists(): return
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True, timeout=5)) as db:
        db.row_factory=sqlite3.Row
        for row in db.execute(query): yield dict(row)


def _nodes(value):
    # Identity belongs to one record/contract scope, never the union of sibling versions.
    pending=[(value,"","","")]
    while pending:
        node,target,chip,vendor=pending.pop()
        if isinstance(node,list):
            pending.extend((item,target,chip,vendor) for item in node)
        elif isinstance(node,dict):
            target=str(node.get("target") or node.get("target_kind") or target)
            contracts=[node]+[node[k] for k in ("params","metadata","conversion_params","conversion_contract") if isinstance(node.get(k),dict)]
            chips={c.get("local_chip_id") for c in contracts if c.get("local_chip_id")}
            vendors={c.get("local_vendor_id") for c in contracts if c.get("local_vendor_id")}
            if len(chips)>1 or len(vendors)>1: raise ValueError("同一引用合同本地身份冲突")
            chip=next(iter(chips),chip);vendor=next(iter(vendors),vendor)
            yield node,target,chip,vendor
            pending.extend((item,target,chip,vendor) for item in node.values() if isinstance(item,(dict,list)))


def catalog_references(data_dir, catalog, entity, record):
    """All statuses and rows are checked; corruption never means no reference."""
    root=Path(data_dir)
    chips=[record] if entity=="chips" else [c for c in catalog["chips"] if c["vendor_id"]==record["id"]]
    vendors={v["id"]:v for v in catalog["vendors"]}
    adapters={t["id"]:t["adapter"] for t in conversion_templates()}
    sdk_identities={(adapters.get(vendors.get(c["vendor_id"],{}).get("template_id")),local_chip_key(c.get("sdk_code"))) for c in chips if c.get("sdk_code")}
    references=[];count=0
    def add(kind,identity):
        nonlocal count
        count+=1
        if len(references)<50: references.append({"type":kind,"id":str(identity)})
    def matches(value):
        if not isinstance(value,(dict,list)): raise ValueError("引用JSON必须为对象或数组")
        for node,target,local_chip,local_vendor in _nodes(value):
            if entity=="vendors" and local_vendor:
                if local_vendor==record["id"]: return True
                continue
            if local_chip:
                if any(c["id"]==local_chip for c in chips): return True
                continue
            if local_vendor and entity=="chips" and record["vendor_id"]!=local_vendor: continue
            code=node.get("sdk_chip_code") or node.get("chip_code") or node.get("chip") or node.get("sdk_code") or node.get("remote_chip_code") or node.get("chipCode") or node.get("soc_version")
            if code and (target,local_chip_key(code)) in sdk_identities: return True
        return False
    try:
        if entity=="vendors":
            for chip in chips: add("CHILD_CHIP",chip["id"])
        for row in _rows(root/"model_artifacts"/"artifacts.sqlite3","SELECT artifact_id,target,chip_code,metadata_json FROM model_artifacts"):
            row["metadata"]=json.loads(row.pop("metadata_json") or "{}")
            if not isinstance(row["metadata"],dict): raise ValueError("模型资产Metadata格式损坏："+row["artifact_id"])
            if matches(row): add("MODEL_ARTIFACT",row["artifact_id"])
        for pattern in ("*/deployment/jobs/*/job.json","*/deploy/jobs/*/job.json"):
            for path in (root/"projects").glob(pattern):
                if matches(_object(path)): add("CONVERSION_JOB",str(path.relative_to(root)))
        tasks=root/"task_runtime"/"tasks.sqlite3"
        store=None
        for row in _rows(tasks,"SELECT task_id,payload_ref FROM tasks WHERE kind='MODEL_CONVERSION'"):
            if store is None: store=ArtifactStore(root/"task_runtime"/"artifacts")
            path=store.artifact_path(row["task_id"],row["payload_ref"])
            if not path.is_file(): raise ValueError("转换任务payload缺失："+row["task_id"])
            payload=_object(path)
            remote=payload.get("remote_execution") or {}
            if not isinstance(remote,dict): raise ValueError("转换任务remote_execution格式损坏："+row["task_id"])
            conversion=remote.get("conversion") or {}
            if not isinstance(conversion,dict): raise ValueError("转换任务conversion格式损坏："+row["task_id"])
            if not payload.get("job_dir") and not (payload.get("target") and isinstance(payload.get("params"),dict)) and not (conversion.get("target") and isinstance(conversion.get("params"),dict)):
                raise ValueError("转换任务payload缺少可核验的任务合同："+row["task_id"])
            referenced=matches(payload)
            if payload.get("job_dir"):
                job_path=Path(payload["job_dir"]).resolve()/"job.json"
                if (root.resolve()/"projects") not in job_path.parents: raise ValueError("转换任务job_dir不在项目数据目录："+row["task_id"])
                referenced=matches(_object(job_path)) or referenced
            if referenced: add("DURABLE_CONVERSION_TASK",row["task_id"])
        for project in (root/"projects").iterdir() if (root/"projects").exists() else ():
            if not project.is_dir(): continue
            db=project/"algorithms.sqlite3"
            if db.exists():
                for table in ("algorithms","algorithm_versions"):
                    for row in _rows(db,f"SELECT id,payload_json FROM {table}"):
                        if matches(json.loads(row["payload_json"])): add("ALGORITHM_VERSION",row["id"])
            legacy=project/"algorithms.json"
            if legacy.exists() and matches(_json(legacy)): add("LEGACY_ALGORITHM",str(legacy.relative_to(root)))
        publications=root/"external_algorithm_publish"/"publications.sqlite3"
        for row in _rows(publications,"SELECT artifact_id,target,chip_code FROM external_model_artifacts"):
            if matches(row): add("EXTERNAL_PUBLICATION",row["artifact_id"])
        # New publication mappings refer to the same ModelArtifact identities.
        for row in _rows(publications,"SELECT mapping_id,synced_payload_json,remote_chip_code FROM external_artifact_publications"):
            receipt=json.loads(row["synced_payload_json"] or "{}")
            code=local_chip_key(row.get("remote_chip_code") or receipt.get("chipCode"))
            if matches(receipt) or (code and any(sdk==code for _,sdk in sdk_identities)):
                add("EXTERNAL_WEIGHT_MAPPING",row["mapping_id"])
        config=root/"external_algorithm_publish"/"config.json"
        if config.exists():
            value=_object(config)
            if matches(value): add("BUSINESS_CONFIGURATION",str(config.relative_to(root)))
            for target,mapping in value.get("target_mappings",{}).items():
                codes=list((mapping.get("chip_mappings") or {}).keys())+[mapping.get("chip_code")]
                if any((target,local_chip_key(code)) in sdk_identities for code in codes if code): add("EXTERNAL_CHIP_BINDING",target)
    except (OSError,ValueError,TypeError,sqlite3.Error) as error:
        raise PlatformError("CATALOG_REFERENCE_CHECK_FAILED","无法完整核验历史引用，禁止物理删除或改挂",str(error),"请修复引用证据后重试；可以停用以保留历史。",409) from error
    return {"can_delete":count==0,"reference_count":count,"references":references,"references_truncated":count>len(references),
            "solution":"已有业务引用，只能停用；不会删除历史数据。" if count else "未发现业务引用，可确认物理删除。"}
