"""Remote Sophon transport used only by the existing MODEL_CONVERSION owner."""
from __future__ import annotations

from contextlib import ExitStack
import json
import os
import re
import stat
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

import requests

from platform_core.conversion import ConversionError, sha256_file, validate_target
from platform_core.task_runtime import ExecutionFencedError


def _check_response(response):
    if response.status_code in {401, 403}:
        raise ConversionError("REMOTE_AUTH_REQUIRED", "远程认证失败", solution="检查远程部署资源 API Key")
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = None
        if isinstance(detail, dict) and detail.get("code") in {"TPU_MLIR_NOT_FOUND", "TPU_MLIR_UNAVAILABLE"}:
            raise ConversionError(detail["code"], str(detail.get("error") or "TPU-MLIR unavailable"), solution=str(detail.get("solution") or "检查远程 TPU-MLIR 环境"))
    response.raise_for_status()


def safe_extract_zip(zf, destination, *, max_bytes=4 * 1024**3, max_entries=10000):
    destination = Path(destination).resolve()
    members = zf.infolist()
    if len(members) > max_entries or sum(m.file_size for m in members) > max_bytes:
        raise ValueError("远程产物 ZIP 超出大小限制")
    names = set()
    for member in members:
        name = member.orig_filename
        if name != member.filename or "\x00" in name:
            raise ValueError("远程产物 ZIP 路径被平台隐式转换")
        path = PurePosixPath(name)
        mode = member.external_attr >> 16
        if (not name or "\\" in name or ":" in name or path.is_absolute()
                or ".." in path.parts or stat.S_ISLNK(mode)
                or name.casefold() in names or member.flag_bits & 1):
            raise ValueError("远程产物 ZIP 含非法条目")
        names.add(name.casefold())
        (destination / name).resolve().relative_to(destination)
    zf.extractall(destination)


def validate_remote_artifacts(directory, job):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    expected = validate_target("sophon", job["params"])
    target = manifest.get("target") or {}
    parameters = manifest.get("parameters") or {}
    for field in ("kind", "chip", "precision", "batch", "num_core", "dynamic", "input_height", "input_width", "preprocessing"):
        for actual in (target, parameters):
            if type(actual.get(field)) is not type(expected[field]) or actual[field] != expected[field]:
                raise ValueError(f"远程 manifest 转换参数不匹配：{field}")
    # Remote artifacts must prove the requested channel contract, not only chip/shape.
    if "input_color_order" in expected:
        for field in ("source_color_order", "input_color_order"):
            if target.get(field) != expected[field] or parameters.get(field) != expected[field]:
                raise ValueError(f"远程颜色适配合同不一致：{field}")
        color_evidence = (manifest.get("execution_evidence") or {}).get("color_adapter") or {}
        if expected["source_color_order"] != expected["input_color_order"] and not (
            color_evidence.get("applied") is True and color_evidence.get("verified") is True
            and color_evidence.get("input_color_order") == expected["input_color_order"]
        ):
            raise ValueError("远程产物缺少已通过数值验证的颜色适配证据")
    if "csc" in expected:
        for actual in (target, parameters):
            if actual.get('csc') != expected['csc'] or actual.get('csc_contract') != expected['csc_contract']:
                raise ValueError('远程CSC合同与冻结请求不一致')
        if (manifest.get('execution_evidence') or {}).get('csc') != expected['csc_contract']:
            raise ValueError('远程CSC部署约定证据缺失或不一致')
        outputs = {r.get('name') for r in manifest.get('outputs') or []}
        if expected['csc_contract'].get('capability')=='contract_only' and not {'csc_deployment_contract.json','csc_deployment_reference.zip'} <= outputs:
            raise ValueError('远程CSC部署辅助产物不完整')
        if expected['csc_contract'].get('capability')=='contract_only':
            from tempfile import TemporaryDirectory
            from .conversion_csc import write_csc_deployment_bundle
            with TemporaryDirectory(prefix='conversion-csc-verify-') as temporary:
                write_csc_deployment_bundle(temporary, expected['csc_contract'], include_reference_sources=False)
                for name in ('csc_deployment_contract.json','csc_deployment_reference.zip'):
                    if not (directory/name).is_file() or sha256_file(directory/name)!=sha256_file(Path(temporary)/name):
                        raise ValueError('远程CSC部署辅助文件与平台可信参考不一致：'+name)
    trace = job.get("source_trace") or {}
    source_path = Path(str(job.get("source_path") or ""))
    recorded_sha = str(trace.get("sha256") or "").lower()
    source_sha = sha256_file(source_path) if source_path.is_file() else recorded_sha
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha) or (recorded_sha and source_sha != recorded_sha):
        raise ValueError("本地源模型与冻结 SHA256 不匹配")
    source = manifest.get("source") or {}
    if source.get("sha256") != source_sha:
        raise ValueError("远程 manifest 源模型 SHA256 不匹配")
    for field in ("version_id", "algorithm_id"):
        if trace.get(field) and source.get(field) != trace[field]:
            raise ValueError(f"远程 manifest 源版本身份不匹配：{field}")
    onnx = manifest.get("onnx") or {}
    shape = [[1, 3, expected["input_height"], expected["input_width"]]]
    if (onnx.get("input_shapes") != shape or any(type(value) is not int for row in onnx.get("input_shapes", []) for value in row)
            or onnx.get("checker") != "passed" or onnx.get("runtime") != "onnxruntime"):
        raise ValueError("远程 ONNX 实际输入形状或验证证据不匹配")
    structure = manifest.get("sophon_validation") or {}
    observed_chips = set(re.findall(r"\b(?:bm|cv)\d+[a-z]*\b", str(structure.get("inspection") or "").lower()))
    if (structure.get("structure") != "passed" or structure.get("chip") != expected["chip"]
            or observed_chips != {expected["chip"]} or structure.get("preprocessing") != expected["preprocessing"]):
        raise ValueError("远程 BMODEL 缺少匹配本次转换的结构检查证据")
    records = manifest.get("outputs") or []
    if not records:
        raise ValueError("远程 manifest 缺少产物")
    names = set()
    for record in records:
        name = str(record.get("name") or "")
        path = (directory / name).resolve()
        if not name or "\\" in name or ":" in name or ".." in PurePosixPath(name).parts:
            raise ValueError("远程 manifest 产物路径非法")
        path.relative_to(directory)
        if not path.is_file() or path.stat().st_size <= 0 or path.stat().st_size != record.get("size_bytes"):
            raise ValueError("远程产物大小不匹配")
        digest = sha256_file(path)
        if digest != record.get("sha256"):
            raise ValueError("远程产物 SHA256 不匹配")
        if name.casefold() in names:
            raise ValueError("远程 manifest 重复产物")
        names.add(name.casefold())
    actual = {p.relative_to(directory).as_posix().casefold() for p in directory.rglob("*") if p.is_file() and p.name != "manifest.json"}
    if actual != names or not any(name.endswith(".bmodel") for name in names):
        raise ValueError("远程 manifest 与实际 BMODEL 产物不匹配")
    def evidence_record(evidence):
        return {field: evidence.get(field) for field in ("name", "size_bytes", "sha256")}
    bmodels = [evidence_record(row) for row in records if str(row.get("name") or "").lower().endswith(".bmodel")]
    onnx_models = [evidence_record(row) for row in records if str(row.get("name") or "").lower().endswith(".onnx")]
    if bmodels != [evidence_record(structure.get("artifact") or {})] or onnx_models != [evidence_record(onnx)]:
        raise ValueError("远程验证证据未绑定到实际下载的 ONNX/BMODEL 文件")
    return manifest


def synchronize_remote_conversion(context, request, *, recovering=False, http=requests):
    jd = Path(request["job_dir"])
    jf = jd / "job.json"
    job = json.loads(jf.read_text(encoding="utf-8"))
    terminal = {"done", "failed", "stopped", "cancelled", "blocked_by_hardware", "blocked_by_environment"}
    if job.get("status") in terminal:
        return job
    connection = request.get("remote_connection") or {}
    base = str(connection.get("base_url") or "").rstrip("/")
    from platform_core.secrets import KeyringSecretStore
    key = KeyringSecretStore().get(str(connection.get("secret_ref") or "")) or ""
    rid = str(job.get("remote_job_id") or job["id"])
    upload_not_attempted = not job.get("remote_upload_attempted") and not job.get("remote_job_id")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", rid):
        raise ValueError("远程任务 ID 非法")
    headers = {"X-API-Key": key}
    started = time.time()
    deadline = float(job.get("remote_deadline") or (started + min(max(float(request.get("timeout_seconds") or 3600), 1), 86400)))

    def persist():
        context.assert_current_execution()
        temporary = jf.with_name(f".job-{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
            context.assert_current_execution()
            os.replace(temporary, jf)
        finally:
            temporary.unlink(missing_ok=True)

    def stop():
        context.assert_current_execution()
        response = http.post(base + f"/api/deploy/jobs/{rid}/stop", headers=headers, timeout=10)
        _check_response(response)

    try:
        context.assert_current_execution()
        if context.cancel_requested() and upload_not_attempted:
            job.update(status="stopped", stage="已停止", message="用户取消", cancel_requested=True)
            persist()
            return job
        if not key:
            raise ConversionError("REMOTE_AUTH_REQUIRED", "远程转换需要 API Key", solution="配置远程部署资源密钥")
        if upload_not_attempted:
            # Persist request identity BEFORE upload: an ambiguous POST response
            # may only be resolved by reading this ID, never by creating a new job.
            # Recovery before this receipt exists still owns the first upload.
            job.update(remote_job_id=rid, remote_upload_attempted=True, remote_deadline=deadline,
                       status="running", stage="上传到转换服务器", progress=5)
            persist()
            context.heartbeat(progress=5, stage=job["stage"])
            with ExitStack() as stack:
                source = Path(job["source_path"])
                stream = stack.enter_context(source.open("rb"))
                files = {"source_model": (source.name, stream, "application/octet-stream")}
                params = dict(job["params"])
                config = Path(str(params.pop("config_path", "") or ""))
                if config.is_file():
                    files["config_file"] = (config.name, stack.enter_context(config.open("rb")), "application/octet-stream")
                try:
                    context.assert_current_execution()
                    response = http.post(base + "/api/deploy/convert", headers=headers,
                        files=files,
                        data={"target": "sophon", "params_json": json.dumps(params), "client_job_id": rid,
                              "source_trace_json": json.dumps(job.get("source_trace") or {})}, timeout=30)
                    _check_response(response)
                    if response.json().get("job_id") != rid:
                        raise ValueError("远程服务器未保留客户端任务身份")
                except requests.RequestException:
                    # GET below resolves uncertain upload completion.
                    pass
        while True:
            context.assert_current_execution()
            if context.cancel_requested():
                stop()
                job.update(status="stopped", stage="已停止", message="用户取消", cancel_requested=True)
                persist()
                return job
            if time.time() >= deadline:
                stop()
                raise ConversionError("REMOTE_CONVERSION_TIMEOUT", "远程转换超时，已请求终止", solution="检查远程日志后新建任务")
            response = http.get(base + f"/api/deploy/jobs/{rid}", headers=headers, timeout=15)
            _check_response(response)
            remote = response.json()
            context.assert_current_execution()
            # Never import remote output paths or hardware success claims.
            for field in ("status", "stage", "progress", "message", "error", "error_code", "solution"):
                if field in remote:
                    job[field] = remote[field]
            if str(remote.get("status") or "").lower() in {"done", "blocked_by_hardware"}:
                response = http.get(base + f"/api/deploy/jobs/{rid}/artifacts.zip", headers=headers, timeout=30, stream=True)
                _check_response(response)
                import tempfile
                with tempfile.TemporaryDirectory(prefix="remote-artifacts-", dir=jd) as temporary:
                    staged = Path(temporary)
                    archive = jd / "remote_artifacts.download"
                    try:
                        chunks = response.iter_content(1024**2) if hasattr(response, "iter_content") else [response.content]
                        received = 0
                        with archive.open("wb") as stream:
                            for chunk in chunks:
                                context.assert_current_execution()
                                received += len(chunk)
                                if received > 4 * 1024**3:
                                    raise ValueError("远程下载超出大小限制")
                                stream.write(chunk)
                        with zipfile.ZipFile(archive) as zf:
                            safe_extract_zip(zf, staged)
                    finally:
                        archive.unlink(missing_ok=True)
                        if hasattr(response, "close"):
                            response.close()
                    manifest = validate_remote_artifacts(staged, job)
                    manifest.update(hardware_verified=False, status="converted_unverified")
                    (staged / "manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
                    artifacts = jd / "artifacts"
                    artifacts.mkdir(exist_ok=True)
                    for path in staged.rglob("*"):
                        if path.is_file():
                            context.assert_current_execution()
                            target = artifacts / path.relative_to(staged)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            os.replace(path, target)
                if (manifest.get("tool") or {}).get("version"):
                    job["params"]={**job.get("params",{}),"sdk_version":manifest["tool"]["version"]}
                execution = manifest.get("execution_evidence") or {}
                job["execution_evidence"]=dict(execution) if isinstance(execution,dict) else {}
                job.update(status="blocked_by_hardware", hardware_verified=False, conversion_status="converted",
                    stage="等待目标硬件验证", progress=100, manifest_path=str(artifacts / "manifest.json"),
                    outputs=[{"name":p.name,"path":str(p),"rel":str(p.relative_to(jd)),"size_bytes":p.stat().st_size}
                             for p in artifacts.rglob("*") if p.is_file() and p.suffix.lower() not in {".py",".md"}])
                persist()
                return job
            persist()
            context.heartbeat(progress=float(job.get("progress") or 0), stage=str(job.get("stage") or "远程转换中"))
            if job.get("status") in terminal:
                return job
            time.sleep(0.25)
    except ExecutionFencedError:
        raise
    except Exception as error:
        job.update(status="failed", stage="远程转换失败", error=str(error), message=str(error),
                   error_code=getattr(error, "code", "REMOTE_CONVERSION_FAILED"),
                   solution=getattr(error, "solution", "检查远程任务状态与产物后重试"))
        persist()
        return job
