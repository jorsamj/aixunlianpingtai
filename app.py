import json
import asyncio
import base64
import hashlib
import math
import re
import os
import secrets
import errno
import shutil
import subprocess
import sys
import time
import threading
import uuid
from collections import OrderedDict
from dataclasses import replace
import zipfile
import random
import sqlite3
import mimetypes
import logging
from urllib.parse import quote
from contextlib import closing, contextmanager, nullcontext
from contextvars import ContextVar
from datetime import datetime, timezone
from itertools import islice
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

import requests
import yaml
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictInt, PrivateAttr, model_validator
from PIL import Image, ImageDraw
from filelock import FileLock, Timeout

from platform_core.annotations import annotation_summary, atomic_write_json, normalize_boxes, restore_box_provenance
from platform_core.annotation_repository import (
    AnnotationConflictError,
    AnnotationLabelStateError,
    AnnotationRepository,
)
from platform_core.storage.import_confirmation import (
    IMPORT_LABEL_CREATION_BLOCKED_DETAIL,
    confirm_import,
    external_label_facts,
    public_quality,
    resolve_external_label_mapping,
)
from platform_core.algorithms import (
    algorithm_store_revision,
    attach_version_if_current as attach_algorithm_version_if_current,
    choose_algorithm_iteration_base,
    choose_iteration_base,
    delete_algorithm_version,
    is_trainable_version,
    project_current_version,
    resolve_current_version_id,
    rollback_algorithm_version,
    retry_algorithm_version_cleanup,
    create_algorithm as create_algorithm_asset,
    delete_algorithm as delete_algorithm_asset,
    list_algorithms as list_algorithm_assets,
    update_algorithm as update_algorithm_asset,
    update_algorithm_version,
)
from platform_core import auto_label as auto_label_core
from platform_core.annotation_candidates import CandidateDecision, CandidateStore
from platform_core.annotation_task_service import commit_candidate_decisions, sync_annotation_statistics
from platform_core.annotation_runtime import prepare_request as prepare_annotation_request
from platform_core.bootstrap import choose_project, choose_requested_project
from platform_core.runtime_paths import resolve_data_dir
from platform_core.build_identity import resolve_build_id
from platform_core.conversion import sha256_file, validate_target, derive_version_conversion_defaults
from platform_core.errors import PlatformError, error_body
from platform_core.changlian_login_auth import (
    DEFAULT_CHANGLIAN_LOGIN_BASE_URL,
    DEFAULT_SESSION_ABSOLUTE_TTL_SECONDS,
    DEFAULT_SESSION_IDLE_TTL_SECONDS,
    DEFAULT_SESSION_RENEW_WINDOW_SECONDS,
    SESSION_COOKIE_NAME,
    ChangLianLoginClient,
    ChangLianLoginError,
    SignedSessionManager,
    auth_guard_decision,
)
from platform_core.local_login_auth import DEFAULT_LOCAL_PASSWORD, LocalLoginVerifier
from platform_core.labels import (
    active_label_options,
    confirmed_alias_updates,
    label_governance_fence,
    label_identity_values,
    normalize_label_aliases,
)
from platform_core.material_store import MaterialStore
from platform_core.model_artifacts import (
    ModelArtifactService,
    SUCCESSFUL_CONVERSION_STATUSES,
    delivery_artifact_quality_preflight,
    model_delivery_version_fence,
)
from platform_core.mother_model_assets import (
    asset_selection as _verified_mother_model_asset,
    get_asset as _get_mother_model_asset,
    initial_asset as _register_mother_model_asset,
    list_assets as _list_mother_model_assets,
    put_asset as _update_mother_model_asset,
    verify_checkpoint_in_sandbox as _verify_mother_model_checkpoint,
    verify_trusted_official_checkpoint as _verify_official_mother_model_checkpoint,
    verifier_environment_status as _mother_model_verifier_environment,
    public_asset_status as _public_mother_model_asset_status,
)
from platform_core.mother_model_inventory import project_node_inventory as _project_node_mother_models
from platform_core.material_repository import (
    AnnotationMaterialLifecycleError,
    DATASET_DELETE_CLAIM_FIELD,
    MaterialRepository,
    material_annotation_lifecycle_fence,
    material_dataset_matches,
)
from platform_core.materials import initial_processing_status, mark_ready
from platform_core.prompts import render_prompt, template_version_id, version_template
from platform_core.quality import compute_quality
from platform_core.reports import build_algorithm_report, build_version_report
from platform_core.resource_cache import ResourceCache
from platform_core.resource_discovery import (
    DiscoveryCache,
    ModelResolution,
    ModelResolver,
    OFFICIAL_DOWNLOADABLE_MODELS,
    probe_python_environment,
)
from platform_core.resource_discovery.request_scope import resolve_discovery_request_roots
from platform_core.resource_discovery.tasks import (
    CACHE_FILENAME as RESOURCE_DISCOVERY_CACHE_FILENAME,
    PROGRESS_REF as RESOURCE_DISCOVERY_PROGRESS_REF,
)
from platform_core.secrets import KeyringSecretStore, SecretCredentialStore, secret_ref
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_node_assignments import (
    CentralTaskAllocator,
    NodeAssignmentError,
    task_preemptible,
)
from platform_core.storage import (
    StorageError,
    StorageManager,
    StorageProviderFactory,
    StorageSource,
    StorageSourceRepository,
    StorageType,
    redact_storage_error,
    storage_source_lifecycle_fence,
)
from platform_core.storage.import_candidates import ImportCandidateStore, RescanCandidateStore
from platform_core.storage.import_tasks import (
    MANIFEST_REF as STORAGE_IMPORT_MANIFEST_REF,
    load_legacy_candidates,
    server_import_dir,
)
from platform_core.zip_multipart import ZipMultipartRepository
from platform_core.zip_label_samples import build_zip_class_samples
from platform_core.storage import zip_folders
from platform_core.storage.zip_import import (
    ServerZipImportError,
    resolve_server_zip,
    safe_member_path,
)
from platform_core.snapshots import build_snapshot, is_training_ground_truth, persist_snapshot
from platform_core.training_lineage import build_training_lineage
from platform_core.training_tasks import (
    TrainingAdmissionError,
    freeze_training_inputs,
    read_training_input_freeze,
    resolve_training_selection,
)
from platform_core.training_label_tasks import (
    inherited_training_label_preview,
    project_training_rows,
    resolve_training_label_contract,
    training_background_selection_fingerprint,
)
from platform_core.training_precision import TrainingPrecisionError, normalize_training_precision
from platform_core.training_compatibility import (
    compatibility_page,
    evaluate_training_compatibility,
    normalize_benchmark_duplicate_review,
)
from platform_core.upload_batches import UploadBatchStore, UploadRequestBusy, apply_decisions
from platform_core.training_job_projection import (
    apply_training_display_progress,
    apply_training_task_truth,
    build_training_display_progress,
)
from platform_core.task_runtime import (
    ArtifactStore,
    ProcessController,
    ProcessIdentity,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
    WorkerInstanceService,
    task_to_public,
    training_queue_truth,
)
from platform_core.training_splits import SplitMode, SplitRequest, exclude_reserved_test_components
from platform_core.training_devices import discover_training_devices, normalize_training_device, training_python
from platform_core.gpu_resources import GPUResourceManager, read_gpu_runtime_truth
from platform_core.video_tasks import SamplingMode, VideoSampleRequest
from platform_core.material_batches import (
    BatchOperation as MaterialBatchOperation,
    BatchRequestError as MaterialBatchRequestError,
    SELECTION_REF as MATERIAL_BATCH_SELECTION_REF,
    create_annotation_remap_batch,
    create_annotation_remap_by_label,
    create_annotation_remap_by_labels,
    assert_material_input_admission,
    estimate_batch as estimate_material_batch,
    prepare_batch as prepare_material_batch,
    publish_prepared_batch as publish_prepared_material_batch,
    public_batch as public_material_batch,
)
from platform_core.material_selection import MaterialSelectionSpec, SelectionScope

BASE_DIR = Path(__file__).resolve().parent
BUILD_ID = resolve_build_id(BASE_DIR)
def _read_app_version() -> str:
    env_v = os.environ.get("MC_PLATFORM_VERSION", "").strip()
    if env_v:
        return env_v
    try:
        v = (BASE_DIR / "VERSION.txt").read_text(encoding="utf-8", errors="ignore").strip()
        if v:
            return v
    except Exception:
        pass
    return "42.14.0"

APP_VERSION = _read_app_version()
STATIC_DIR = BASE_DIR / "static"
PROCESS_REGISTRY: Dict[str, subprocess.Popen] = {}

# v34: 持久化数据目录。默认放到用户目录，避免页面刷新、重启、升级版本后素材/数据丢失。
# 如需强制使用当前程序目录下的 data，可在 start.bat 中设置 MC_TRAIN_DATA_DIR=%~dp0data。
def _default_data_dir() -> Path:
    return resolve_data_dir(base_dir=BASE_DIR)

DATA_DIR = _default_data_dir()
DEFAULT_PROJECT_ID = "f1fb1e6fa373"
DEFAULT_PROJECT_NAME = "默认空间"
from platform_core.changlian_login_auth import isolated_test_access_enabled
ALLOW_MULTIPLE_PROJECTS_FOR_TESTS = isolated_test_access_enabled(DATA_DIR)

_SHARED_TASK_REPOSITORY: Optional[TaskRepository] = None
_SHARED_TASK_ARTIFACTS: Optional[ArtifactStore] = None


def shared_task_repository() -> TaskRepository:
    global _SHARED_TASK_REPOSITORY
    if _SHARED_TASK_REPOSITORY is None:
        _SHARED_TASK_REPOSITORY = TaskRepository(DATA_DIR / "task_runtime" / "tasks.sqlite3")
    return _SHARED_TASK_REPOSITORY


def shared_task_artifacts() -> ArtifactStore:
    global _SHARED_TASK_ARTIFACTS
    if _SHARED_TASK_ARTIFACTS is None:
        _SHARED_TASK_ARTIFACTS = ArtifactStore(DATA_DIR / "task_runtime" / "artifacts")
    return _SHARED_TASK_ARTIFACTS

PROJECTS_FILE = DATA_DIR / "projects.json"
SERVERS_FILE = DATA_DIR / "train_servers.json"
LOCAL_MODELS_FILE = DATA_DIR / "local_models_scan.json"
ULTRALYTICS_ENV_FILE = DATA_DIR / "ultralytics_env.json"
RESOURCE_DISCOVERY_CACHE_FILE = DATA_DIR / RESOURCE_DISCOVERY_CACHE_FILENAME
PADDLE_ENV_FILE = DATA_DIR / "paddle_env.json"
PRELABEL_SERVICES_FILE = DATA_DIR / "prelabel_services.json"
MODEL_CONFIGS_FILE = DATA_DIR / "model_configs.json"
PROMPT_LIBRARY_FILE = DATA_DIR / "prompt_library.json"
MODEL_SECRET_STORE: Any = None

DATA_DIR.mkdir(parents=True, exist_ok=True)
from platform_core.storage.local import controlled_local_startup_guard
with controlled_local_startup_guard(DATA_DIR):
    pass  # An explicit offline reclaim holds this barrier until it has finished.
if not PROJECTS_FILE.exists():
    PROJECTS_FILE.write_text("[]", encoding="utf-8")
if not SERVERS_FILE.exists():
    SERVERS_FILE.write_text("[]", encoding="utf-8")
if not LOCAL_MODELS_FILE.exists():
    LOCAL_MODELS_FILE.write_text("[]", encoding="utf-8")
if not ULTRALYTICS_ENV_FILE.exists():
    ULTRALYTICS_ENV_FILE.write_text("{}", encoding="utf-8")
if not PADDLE_ENV_FILE.exists():
    PADDLE_ENV_FILE.write_text("{}", encoding="utf-8")
if not PRELABEL_SERVICES_FILE.exists():
    PRELABEL_SERVICES_FILE.write_text("[]", encoding="utf-8")
if not MODEL_CONFIGS_FILE.exists():
    MODEL_CONFIGS_FILE.write_text("[]", encoding="utf-8")
if not PROMPT_LIBRARY_FILE.exists():
    PROMPT_LIBRARY_FILE.write_text("[]", encoding="utf-8")

app = FastAPI(title="算法训练", version=APP_VERSION)
# Same-origin is the safe default for independent LAN deployments. Different
# front-end origins must be explicitly enumerated; wildcard + credentials is
# forbidden by the browser CORS contract.
_CORS_ALLOWED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.environ.get("MC_CORS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip() and origin.strip() != "*"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ALLOWED_ORIGINS,
    allow_credentials=bool(_CORS_ALLOWED_ORIGINS),
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Request-ID"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/app", StaticFiles(directory=str(STATIC_DIR / "vue-app"), html=True, check_dir=False), name="vue_application")

_CHANGLIAN_LOGIN_BASE_URL = os.environ.get(
    "MC_CHANGLIAN_LOGIN_BASE_URL",
    DEFAULT_CHANGLIAN_LOGIN_BASE_URL,
).strip() or DEFAULT_CHANGLIAN_LOGIN_BASE_URL
_CHANGLIAN_LOGIN_CLIENT = ChangLianLoginClient(base_url=_CHANGLIAN_LOGIN_BASE_URL)
_LOCAL_LOGIN_VERIFIER = LocalLoginVerifier()


def _auth_env_seconds(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return int(default)
    try:
        return max(int(minimum), int(raw))
    except ValueError:
        return int(default)


_CHANGLIAN_AUTH_SESSIONS = SignedSessionManager(
    DATA_DIR / "auth",
    idle_ttl_seconds=_auth_env_seconds(
        "MC_AUTH_SESSION_IDLE_SECONDS",
        DEFAULT_SESSION_IDLE_TTL_SECONDS,
        minimum=300,
    ),
    absolute_ttl_seconds=_auth_env_seconds(
        "MC_AUTH_SESSION_ABSOLUTE_SECONDS",
        DEFAULT_SESSION_ABSOLUTE_TTL_SECONDS,
        minimum=300,
    ),
    renew_window_seconds=_auth_env_seconds(
        "MC_AUTH_SESSION_RENEW_WINDOW_SECONDS",
        DEFAULT_SESSION_RENEW_WINDOW_SECONDS,
        minimum=60,
    ),
)


def _verify_browser_session(token: str) -> Optional[Dict[str, Any]]:
    claims = _CHANGLIAN_AUTH_SESSIONS.verify(token)
    if claims is None:
        return None
    if str(claims.get("provider") or "") == "local":
        revision = _CHANGLIAN_AUTH_SESSIONS.local_credential_revision(
            _LOCAL_LOGIN_VERIFIER.username,
            os.environ.get("MC_LOCAL_PASSWORD", DEFAULT_LOCAL_PASSWORD),
        )
        if not secrets.compare_digest(str(claims.get("credential_revision") or ""), revision):
            return None
    return claims


def _auth_request_is_secure(request: Request) -> bool:
    forwarded = str(request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
    return forwarded == "https" or request.url.scheme == "https"


def _set_auth_cookie(response: Response, request: Request, token: str, claims: Mapping[str, Any]) -> None:
    try:
        remaining = max(1, int(claims.get("exp") or 0) - int(time.time()))
    except (TypeError, ValueError):
        remaining = _CHANGLIAN_AUTH_SESSIONS.idle_ttl_seconds
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=remaining,
        httponly=True,
        secure=_auth_request_is_secure(request),
        samesite="lax",
        path="/",
    )


def _public_auth_session(claims: Mapping[str, Any]) -> Dict[str, Any]:
    now = int(time.time())
    expires_at = int(claims.get("exp") or 0)
    hard_expires_at = int(
        claims.get("hard_exp")
        or (
            int(claims.get("created_at") or claims.get("iat") or now)
            + _CHANGLIAN_AUTH_SESSIONS.absolute_ttl_seconds
        )
    )
    upstream_exp = claims.get("upstream_exp")
    return {
        "authenticated": True,
        "provider": str(claims.get("provider") or "changlian"),
        "user": {"username": str(claims.get("username") or "")},
        "expires_at": expires_at,
        "remaining_seconds": max(0, expires_at - now),
        "absolute_expires_at": hard_expires_at,
        "absolute_remaining_seconds": max(0, hard_expires_at - now),
        "idle_ttl_seconds": _CHANGLIAN_AUTH_SESSIONS.idle_ttl_seconds,
        "renew_window_seconds": _CHANGLIAN_AUTH_SESSIONS.renew_window_seconds,
        "upstream_token_expires_at": int(upstream_exp) if upstream_exp else None,
        "upstream_token_expiry_source": str(
            claims.get("upstream_expiry_source") or "undocumented"
        ),
    }


def _auth_test_bypass_enabled() -> bool:
    return ALLOW_MULTIPLE_PROJECTS_FOR_TESTS and isolated_test_access_enabled(DATA_DIR)


from platform_core.performance_diagnostics import PerformanceDiagnosticsMiddleware, stage as performance_stage, count as performance_count, measure as performance_measure
app.add_middleware(PerformanceDiagnosticsMiddleware)


@app.middleware("http")
async def changlian_login_guard(request: Request, call_next):
    if _auth_test_bypass_enabled():
        return await call_next(request)

    decision = auth_guard_decision(
        request.url.path,
        authorization=request.headers.get("authorization"),
    )
    if decision in {"public", "machine"}:
        return await call_next(request)

    claims = _verify_browser_session(
        request.cookies.get(SESSION_COOKIE_NAME, "")
    )
    if claims is not None:
        request.state.changlian_user = claims
        return await call_next(request)

    if request.url.path.startswith("/api/"):
        error = PlatformError(
            code="AUTH_REQUIRED",
            message="请先登录算法训练平台",
            detail="当前浏览器会话未登录或登录已过期。",
            solution="请重新登录后继续操作。",
            status_code=401,
        )
        return JSONResponse(status_code=401, content=error_body(error))

    return RedirectResponse(url="/login?next=%2F", status_code=307)


def fast_json_response(content: Any) -> Response:
    """Serialize large JSON payloads without FastAPI's extra recursive copy."""
    try:
        import orjson

        body = orjson.dumps(content)
    except ImportError:
        body = json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return Response(content=body, media_type="application/json")


_HTTP_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    503: "SERVICE_UNAVAILABLE",
}

_HTTP_ERROR_SOLUTIONS = {
    400: "请检查输入内容后重试。",
    401: "请重新登录或检查访问凭据。",
    403: "请确认当前账号具备操作权限。",
    404: "请刷新列表并确认目标仍然存在。",
    409: "请刷新页面，确认当前状态后重试。",
    422: "请检查必填项和字段格式。",
    503: "请稍后重试；若持续失败，请检查对应服务状态。",
}


@app.exception_handler(PlatformError)
async def platform_error_handler(_request: Request, exc: PlatformError):
    return JSONResponse(status_code=exc.status_code, content=error_body(exc))


@app.exception_handler(HTTPException)
async def http_error_handler(_request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        message = str(exc.detail.get("message") or "操作失败")
        detail = json.dumps(exc.detail, ensure_ascii=False)
    else:
        message = str(exc.detail or "操作失败")
        detail = message
    error = PlatformError(
        code=_HTTP_ERROR_CODES.get(exc.status_code, f"HTTP_{exc.status_code}"),
        message=message,
        detail=detail,
        solution=_HTTP_ERROR_SOLUTIONS.get(exc.status_code, "请稍后重试或查看服务日志。"),
        status_code=exc.status_code,
    )
    return JSONResponse(status_code=exc.status_code, content=error_body(error), headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    error = PlatformError(
        code="VALIDATION_ERROR",
        message="提交的数据不完整或格式不正确",
        detail=json.dumps(exc.errors(), ensure_ascii=False, default=str),
        solution="请检查必填项和字段格式。",
        status_code=422,
    )
    return JSONResponse(status_code=422, content=error_body(error))

class ChangLianLoginReq(BaseModel):
    provider: Literal["local", "changlian"] = "local"
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)
    code: Optional[str] = Field(default=None, max_length=128)
    uuid: Optional[str] = Field(default=None, max_length=256)


@app.get("/login", response_class=HTMLResponse)
def changlian_login_page(request: Request):
    claims = _verify_browser_session(
        request.cookies.get(SESSION_COOKIE_NAME, "")
    )
    if claims is not None:
        return RedirectResponse(url="/", status_code=303)
    return HTMLResponse(
        (STATIC_DIR / "login.html").read_text(encoding="utf-8"),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/auth/session")
def changlian_auth_session(request: Request):
    if _auth_test_bypass_enabled():
        now = int(time.time())
        return {
            "authenticated": True,
            "provider": "test",
            "user": {"username": "isolated-test-runtime"},
            "expires_at": now + 60 * 60,
            "remaining_seconds": 60 * 60,
            "absolute_expires_at": now + 60 * 60,
            "absolute_remaining_seconds": 60 * 60,
            "idle_ttl_seconds": 60 * 60,
            "renew_window_seconds": 10 * 60,
            "upstream_token_expires_at": None,
            "upstream_token_expiry_source": "test_bypass",
            "test_bypass": True,
        }

    claims = _verify_browser_session(
        request.cookies.get(SESSION_COOKIE_NAME, "")
    )
    if claims is None:
        return {"authenticated": False, "user": None}

    renewed_token = _CHANGLIAN_AUTH_SESSIONS.renew(claims)
    if renewed_token:
        renewed_claims = _verify_browser_session(renewed_token)
        if renewed_claims is not None:
            claims = renewed_claims

    response = JSONResponse(_public_auth_session(claims))
    response.headers["Cache-Control"] = "no-store"
    if renewed_token:
        _set_auth_cookie(response, request, renewed_token, claims)
    return response


@app.post("/api/auth/login")
def changlian_auth_login(payload: ChangLianLoginReq, request: Request):
    username = str(payload.username or "").strip()
    if not username:
        raise PlatformError(
            code="LOGIN_USERNAME_REQUIRED",
            message="请输入用户名",
            detail="username 不能为空。",
            solution="请输入账号后重试。",
            status_code=422,
        )
    if payload.provider == "local":
        client_ip = request.client.host if request.client else "unknown"
        status = _LOCAL_LOGIN_VERIFIER.authenticate(username, payload.password, client_key=client_ip)
        if status != "ok":
            raise PlatformError(
                code="LOCAL_LOGIN_THROTTLED" if status == "throttled" else "LOCAL_LOGIN_REJECTED",
                message="登录尝试过于频繁，请稍后重试" if status == "throttled" else "本地用户名或密码错误",
                detail="本地凭据校验未通过。",
                solution="请检查本地账号密码，或联系管理员检查 MC_LOCAL_USERNAME / MC_LOCAL_PASSWORD 配置。",
                status_code=429 if status == "throttled" else 401,
            )
        revision = _CHANGLIAN_AUTH_SESSIONS.local_credential_revision(
            _LOCAL_LOGIN_VERIFIER.username, payload.password,
        )
        token = _CHANGLIAN_AUTH_SESSIONS.issue(
            username, provider="local", upstream_expiry_source="local",
            credential_revision=revision,
        )
        claims = _verify_browser_session(token)
        if claims is None:
            raise PlatformError("AUTH_SESSION_CREATE_FAILED", "本地会话创建失败", "无法验证新签发的会话。", "请检查服务器时间和认证存储。", 500)
        response = JSONResponse({"ok": True, **_public_auth_session(claims)})
        response.headers["Cache-Control"] = "no-store"
        _set_auth_cookie(response, request, token, claims)
        return response
    try:
        result = _CHANGLIAN_LOGIN_CLIENT.login(
            username=username,
            password=payload.password,
            code=payload.code,
            uuid=payload.uuid,
        )
    except ChangLianLoginError as error:
        raise PlatformError(
            code=error.code,
            message=error.message,
            detail=error.detail,
            solution=error.solution,
            status_code=error.status_code,
        ) from error

    token = _CHANGLIAN_AUTH_SESSIONS.issue(
        username,
        provider="changlian",
        upstream_expires_at=result.get("upstream_expires_at"),
        upstream_expiry_source=str(
            result.get("upstream_expiry_source") or "undocumented"
        ),
    )
    claims = _CHANGLIAN_AUTH_SESSIONS.verify(token)
    if claims is None:
        raise PlatformError(
            code="AUTH_SESSION_CREATE_FAILED",
            message="登录成功但会话创建失败",
            detail="本平台未能创建安全登录会话。",
            solution="请刷新页面后重新登录；若持续失败，请检查服务器时间。",
            status_code=500,
        )
    response = JSONResponse(
        {
            "ok": True,
            "provider": "changlian",
            **_public_auth_session(claims),
            "upstream": {
                "code": result.get("code"),
                "message": result.get("message", ""),
                "token_present": bool(result.get("token_present")),
                "expires_in": result.get("upstream_expires_in"),
                "expires_at": result.get("upstream_expires_at"),
                "expiry_source": result.get("upstream_expiry_source"),
            },
        }
    )
    response.headers["Cache-Control"] = "no-store"
    _set_auth_cookie(response, request, token, claims)
    return response


@app.post("/api/auth/logout")
def changlian_auth_logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if token:
        try:
            _CHANGLIAN_AUTH_SESSIONS.revoke(token)
        except (OSError, sqlite3.Error) as error:
            raise PlatformError(
                code="AUTH_LOGOUT_REVOKE_FAILED",
                message="无法安全退出登录",
                detail="服务端会话撤销未完成，不能仅清除本地 Cookie。",
                solution="请检查认证存储后重试。",
                status_code=503,
            ) from error
    response = JSONResponse({"ok": True, "authenticated": False})
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        samesite="lax",
    )
    return response


from platform_core.runtime_catalog_service import RuntimeCatalogDependencies, RuntimeCatalogService
from platform_core.runtime_catalog_api import create_runtime_catalog_router_1, create_runtime_catalog_router_2, create_runtime_catalog_router_3, create_runtime_catalog_router_4, create_runtime_catalog_router_5, create_runtime_catalog_router_6, create_runtime_catalog_router_7


def _runtime_catalog_service() -> RuntimeCatalogService:
    return RuntimeCatalogService(RuntimeCatalogDependencies(
        APP_DISPLAY_NAME=lambda: APP_DISPLAY_NAME,
        APP_VERSION=lambda: APP_VERSION,
        BASE_DIR=lambda: BASE_DIR,
        BUILD_ID=lambda: BUILD_ID,
        DATA_DIR=lambda: DATA_DIR,
        LOCAL_MODELS_FILE=lambda: LOCAL_MODELS_FILE,
        PADDLE_ENV_FILE=lambda: PADDLE_ENV_FILE,
        SERVERS_FILE=lambda: SERVERS_FILE,
        TRAINING_CATALOG=lambda: TRAINING_CATALOG,
        _create_discovery_task=lambda *args, **kwargs: _create_discovery_task(*args, **kwargs),
        _detect_paddle_candidate=lambda *args, **kwargs: _detect_paddle_candidate(*args, **kwargs),
        _discovery_cache=lambda *args, **kwargs: _discovery_cache(*args, **kwargs),
        _prepared_mother_model_rows=lambda *args, **kwargs: _prepared_mother_model_rows(*args, **kwargs),
        _public_discovery_task=lambda *args, **kwargs: _public_discovery_task(*args, **kwargs),
        _record_legacy_health=lambda *args, **kwargs: _record_legacy_health(*args, **kwargs),
        _remote_capabilities=lambda *args, **kwargs: _remote_capabilities(*args, **kwargs),
        _system_recommendation_payload=lambda *args, **kwargs: _system_recommendation_payload(*args, **kwargs),
        _worker_gpu_recommendation=lambda *args, **kwargs: _worker_gpu_recommendation(*args, **kwargs),
        default_paddle_roots=lambda *args, **kwargs: default_paddle_roots(*args, **kwargs),
        get_active_paddle_env=lambda *args, **kwargs: get_active_paddle_env(*args, **kwargs),
        get_active_ultralytics_env=lambda *args, **kwargs: get_active_ultralytics_env(*args, **kwargs),
        inference_env_items=lambda *args, **kwargs: inference_env_items(*args, **kwargs),
        list_models_internal=lambda *args, **kwargs: list_models_internal(*args, **kwargs),
        logger=lambda: logging,
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        read_json=lambda *args, **kwargs: read_json(*args, **kwargs),
        resolve_ultralytics_model=lambda *args, **kwargs: resolve_ultralytics_model(*args, **kwargs),
        scan_paddle_weights=lambda *args, **kwargs: scan_paddle_weights(*args, **kwargs),
        scan_paddledet_algorithms=lambda *args, **kwargs: scan_paddledet_algorithms(*args, **kwargs),
        shared_task_artifacts=lambda *args, **kwargs: shared_task_artifacts(*args, **kwargs),
        shared_task_repository=lambda *args, **kwargs: shared_task_repository(*args, **kwargs),
    ))


app.include_router(create_runtime_catalog_router_1(_runtime_catalog_service))


def system_version():
    return _runtime_catalog_service().system_version()


def list_worker_runtime():
    return _runtime_catalog_service().list_worker_runtime()


def gpu_runtime_truth():
    return _runtime_catalog_service().gpu_runtime_truth()


def _runtime_task_for_project(project_id: str, task_id: str) -> TaskRecord:
    get_project(project_id)
    task = shared_task_repository().get(task_id)
    if task is None or task.project_id != project_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


from platform_core.task_runtime.management_api import create_task_management_router
from platform_core.task_runtime.query_api import create_task_query_router

_task_query_router = create_task_query_router(
    get_project=lambda project_id: get_project(project_id),
    shared_task_repository=lambda: shared_task_repository(),
    shared_task_artifacts=lambda: shared_task_artifacts(),
    algorithms_file=lambda project_id: algorithms_file(project_id),
    _runtime_task_for_project=lambda project_id, task_id: _runtime_task_for_project(project_id, task_id),
)
app.include_router(_task_query_router)


_task_management_router = create_task_management_router(
    task_for_project=lambda project_id, task_id: _runtime_task_for_project(project_id, task_id),
    repository=lambda: shared_task_repository(),
    cancel_prepare_child=lambda repository, task: _cancel_training_prepare_child(repository, task),
    terminate_tree=lambda identity: ProcessController().terminate_tree(identity),
    public_task=lambda task, repository: task_to_public(task, repository),
)
app.include_router(_task_management_router)


def _cancel_training_prepare_child(repository, parent: TaskRecord) -> None:
    """Cancel the deterministic prepare child after the user stops its parent."""
    child = repository.get(f"trainprep_{parent.task_id}")
    if (child is not None and child.kind is TaskKind.TRAINING_PREPARE
            and child.project_id == parent.project_id):
        repository.request_cancel(child.task_id)


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
LABEL_EXTS = {".txt"}
MODEL_EXTS = {".pt", ".pth", ".onnx", ".engine", ".rknn", ".bmodel", ".om", ".pdparams", ".pdmodel", ".pdiparams"}
MODEL_CONFIG_NAMES = {"infer_cfg.yml", "infer_cfg.yaml", "inference.yml", "inference.yaml", "deploy.yml", "deploy.yaml", "model.yml", "model.yaml"}
PADDLEX_SERVICE_FILE_NAMES = {"human_service.py", "download_model.py", "service.py", "app.py"}
SKIP_SCAN_DIRS = {"$recycle.bin", "system volume information", "windows", "program files", "program files (x86)", "appdata", "node_modules", ".git", ".venv", "venv", "__pycache__"}


TRAINING_CATALOG: Dict[str, Any] = {
    "frameworks": [
        {
            "key": "ultralytics",
            "name": "Ultralytics YOLO",
            "status": "ready",
            "description": "当前可直接训练，适合本机快速跑通。基础模型使用 .pt。",
        },
        {
            "key": "paddle",
            "name": "飞桨 PaddleX / PaddleDetection",
            "status": "configured",
            "description": "平台可导出 COCO 数据集并按预置命令模板执行训练；需要本机已安装 PaddleDetection/PaddleX。",
        },
    ],
    "algorithms": [
        {
            "key": "yolo11n_det",
            "framework": "ultralytics",
            "name": "YOLO11n 目标检测",
            "short_name": "YOLO11n",
            "task": "detect",
            "base_model": "yolo11n.pt",
            "recommended": True,
            "default_epochs": 150,
            "default_imgsz": 640,
            "default_batch": 4,
            "description": "最轻量，适合 CPU/普通笔记本先跑通安全帽、人员、烟火等目标检测流程。",
        },
        {
            "key": "yolo11s_det",
            "framework": "ultralytics",
            "name": "YOLO11s 目标检测",
            "short_name": "YOLO11s",
            "task": "detect",
            "base_model": "yolo11s.pt",
            "recommended": False,
            "default_epochs": 150,
            "default_imgsz": 640,
            "default_batch": 4,
            "description": "比 n 版更准一些，建议有 NVIDIA 显卡或训练服务器时使用。",
        },
        {
            "key": "yolo11m_det",
            "framework": "ultralytics",
            "name": "YOLO11m 目标检测",
            "short_name": "YOLO11m",
            "task": "detect",
            "base_model": "yolo11m.pt",
            "recommended": False,
            "default_epochs": 150,
            "default_imgsz": 640,
            "default_batch": 2,
            "description": "中等模型，精度更高但资源占用更大，本机 CPU 不建议首选。",
        },
        {
            "key": "paddledet_ppyoloe_s",
            "framework": "paddle",
            "name": "PP-YOLOE-S 目标检测",
            "short_name": "PP-YOLOE-S",
            "task": "detect",
            "base_model": "PP-YOLOE-S",
            "recommended": True,
            "default_epochs": 30,
            "default_imgsz": 640,
            "default_batch": 4,
            "description": "飞桨轻量目标检测路线，适合后续闭源/国产化项目验证。需要本机配置 PaddleDetection。",
            "config_relpath": "configs/ppyoloe/ppyoloe_crn_s_300e_coco.yml",
            "command_template": "{python} {paddledet_dir}\\tools\\train.py -c {paddledet_dir}\\configs\\ppyoloe\\ppyoloe_crn_s_300e_coco.yml -o TrainDataset.dataset_dir={dataset_dir} TrainDataset.anno_path={train_json} EvalDataset.dataset_dir={dataset_dir} EvalDataset.anno_path={val_json} epoch={epochs} batch_size={batch} save_dir={run_dir}",
        },
        {
            "key": "paddledet_ppyoloe_plus_s",
            "framework": "paddle",
            "name": "PP-YOLOE+ S 目标检测",
            "short_name": "PP-YOLOE+ S",
            "task": "detect",
            "base_model": "PP-YOLOE_plus-S",
            "recommended": False,
            "default_epochs": 50,
            "default_imgsz": 640,
            "default_batch": 4,
            "description": "飞桨 PP-YOLOE+ 小模型，适合正式效果对比。需要本机配置 PaddleDetection。",
            "config_relpath": "configs/ppyoloe/ppyoloe_plus_crn_s_80e_coco.yml",
            "command_template": "{python} {paddledet_dir}\\tools\\train.py -c {paddledet_dir}\\configs\\ppyoloe\\ppyoloe_plus_crn_s_80e_coco.yml -o TrainDataset.dataset_dir={dataset_dir} TrainDataset.anno_path={train_json} EvalDataset.dataset_dir={dataset_dir} EvalDataset.anno_path={val_json} epoch={epochs} batch_size={batch} save_dir={run_dir}",
        },
        {
            "key": "paddlex_human_pretrain",
            "framework": "paddle",
            "name": "PaddleX PP-YOLOE-S_human 人员检测源",
            "short_name": "PP-YOLOE-S_human",
            "task": "detect",
            "base_model": "PP-YOLOE-S_human",
            "recommended": False,
            "default_epochs": 30,
            "default_imgsz": 640,
            "default_batch": 4,
            "description": "更适合先作为人员检测预标注源；如要训练，需要本机具备对应 PaddleX/PaddleDetection 训练能力。",
            "config_relpath": "configs/ppyoloe/ppyoloe_crn_s_300e_coco.yml",
            "command_template": "{python} {paddledet_dir}\\tools\\train.py -c {paddledet_dir}\\configs\\ppyoloe\\ppyoloe_crn_s_300e_coco.yml -o TrainDataset.dataset_dir={dataset_dir} TrainDataset.anno_path={train_json} EvalDataset.dataset_dir={dataset_dir} EvalDataset.anno_path={val_json} epoch={epochs} batch_size={batch} save_dir={run_dir}",
        },
    ],
}


def get_algorithm_config(key: str) -> Optional[Dict[str, Any]]:
    for item in TRAINING_CATALOG["algorithms"]:
        if item["key"] == key:
            return item
    return None


def _norm_path(path: Any) -> str:
    return str(path or "").strip().strip('"')


from platform_core.paddle_detection_catalog import _parse_paddle_config_name, _safe_key


def scan_paddledet_algorithms(paddledet_dir: str, max_items: int = 500) -> Dict[str, Any]:
    root = Path(_norm_path(paddledet_dir))
    if not root.exists():
        return {"ok": False, "items": [], "total": 0, "error": "PaddleDetection 目录不存在"}
    configs = root / "configs"
    if not configs.exists():
        return {"ok": False, "items": [], "total": 0, "error": "没有找到 configs 目录"}
    skip_dirs = {"_base_", "base", "application", "legacy_model", "runtime", "datasets", "common", "deploy"}
    skip_names = {"runtime.yml", "optimizer.yml", "reader.yml", "ppyolo_reader.yml", "ppyoloe_reader.yml", "picodet_reader.yml"}
    items: List[Dict[str, Any]] = []
    skipped = 0
    for fp in configs.rglob("*.yml"):
        try:
            rel_parts = [x.lower() for x in fp.relative_to(configs).parts[:-1]]
            name = fp.name.lower()
            if any(x in skip_dirs for x in rel_parts):
                skipped += 1
                continue
            if name in skip_names or name.startswith("_") or "reader" in name or "optimizer" in name or "runtime" in name or "_test" in name or name.startswith("test") or name in {"ppyolo_test.yml", "ppyoloe_test.yml"}:
                skipped += 1
                continue
            # README 配套、量化/蒸馏/部署配置先不直接作为“训练算法”展示
            if any(k in name for k in ["quant", "slim", "distill", "prune", "infer", "deploy"]):
                skipped += 1
                continue
            item = _parse_paddle_config_name(fp, root)
            items.append(item)
            if len(items) >= max_items:
                break
        except Exception:
            skipped += 1
    items.sort(key=lambda x: (
        0 if x.get("family_key") == "picodet" else 1 if x.get("family_key") == "ppyoloe" else 2,
        x.get("family", ""),
        x.get("default_batch", 99),
        x.get("default_imgsz", 9999),
        x.get("name", ""),
    ))
    families: Dict[str, int] = {}
    for it in items:
        families[it.get("family", "其他")] = families.get(it.get("family", "其他"), 0) + 1
    return {"ok": True, "items": items, "total": len(items), "families": families, "skipped": skipped, "configs_dir": str(configs)}


def scan_paddle_weights(paddledet_dir: str = "", extra_roots: Optional[List[str]] = None, max_items: int = 200) -> List[Dict[str, Any]]:
    roots: List[Path] = []
    for r in extra_roots or []:
        if r:
            roots.append(Path(_norm_path(r)))
    if paddledet_dir:
        pd = Path(_norm_path(paddledet_dir))
        roots.extend([pd / "output", pd / "pretrained", pd / "weights", pd.parent / "PaddleModels"])
    # 用户当前路径常用目录
    roots.extend([BASE_DIR.parent / "PaddleModels", BASE_DIR.parent / "models"])
    seen = set()
    items: List[Dict[str, Any]] = []
    for root in roots:
        if not root.exists() or str(root).lower() in seen:
            continue
        seen.add(str(root).lower())
        try:
            for fp in root.rglob("*.pdparams"):
                if fp.is_file() and fp.stat().st_size > 0:
                    items.append({
                        "label": f"飞桨权重：{fp.name}",
                        "value": str(fp),
                        "framework": "paddle",
                        "source": "local_pdparams",
                        "size_mb": round(fp.stat().st_size / 1024 / 1024, 2),
                    })
                    if len(items) >= max_items:
                        return items
        except Exception:
            continue
    return items


def get_paddle_algorithm_by_key(key: str) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    # 先查固定目录，再查当前保存的 PaddleDetection 环境
    penv = get_active_paddle_env() if 'get_active_paddle_env' in globals() else {}
    scan = scan_paddledet_algorithms(penv.get("paddledet_dir", "")) if penv.get("paddledet_dir") else {"items": []}
    for item in scan.get("items", []):
        if item.get("key") == key:
            return item
    # 兜底静态目录
    for item in TRAINING_CATALOG["algorithms"]:
        if item.get("key") == key:
            return item
    return None


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_dt_value(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        # Runtime jobs historically store local naive timestamps while durable tasks
        # use UTC offsets. Normalize aware values to the server local clock before
        # mixing the two representations.
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(text[:26], fmt)
        except Exception:
            pass
    return None


def _human_seconds(seconds: Any) -> str:
    try:
        seconds = int(max(0, float(seconds)))
    except Exception:
        return "-"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}小时{m}分"
    if m:
        return f"{m}分{s}秒"
    return f"{s}秒"


def _job_log_text(project_id: str, job_id: str, limit: int = 120000) -> str:
    f = project_dir(project_id) / "jobs" / job_id / "train.log"
    if not f.exists():
        return ""
    try:
        # A legacy training log can grow to GBs. Progress inference only needs
        # its bounded tail; never read the entire file for a status/list GET.
        max_chars = max(0, int(limit))
        if not max_chars:
            return ""
        max_bytes = max_chars * 4 + 4
        with f.open("rb") as stream:
            stream.seek(max(0, f.stat().st_size - max_bytes))
            return stream.read(max_bytes).decode("utf-8", errors="ignore")[-max_chars:]
    except Exception:
        return ""


def _infer_epoch_from_log(log_text: str, total_epochs: int) -> int:
    if not log_text or not total_epochs:
        return 0
    cur = 0
    # Ultralytics 常见：1/30、2/30；只取分母等于训练轮次的值，避免 1/1 batch 被误判。
    for a, b in re.findall(r"(?<!\d)(\d{1,5})\s*/\s*(\d{1,5})(?!\d)", log_text):
        try:
            aa, bb = int(a), int(b)
            if bb == int(total_epochs) and 0 <= aa <= bb:
                cur = max(cur, aa)
        except Exception:
            pass
    # PaddleDetection 部分日志可能出现 epoch: 3 或 Epoch 3。
    for a in re.findall(r"(?:epoch|Epoch)[:=\s\[]+(\d{1,5})", log_text):
        try:
            aa = int(a)
            if 0 <= aa <= int(total_epochs):
                cur = max(cur, aa)
        except Exception:
            pass
    return cur



def _pid_alive(pid: Any) -> bool:
    try:
        pid = int(pid or 0)
        if pid <= 0:
            return False
        import psutil
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False


def _terminate_pid_tree(pid: Any) -> bool:
    try:
        import psutil
        proc = psutil.Process(int(pid))
        children = proc.children(recursive=True)
        for child in children:
            try: child.terminate()
            except Exception: pass
        try: proc.terminate()
        except Exception: pass
        _, alive = psutil.wait_procs(children + [proc], timeout=3)
        for item in alive:
            try: item.kill()
            except Exception: pass
        return True
    except Exception:
        return False


_TRAINING_TASK_NOT_LOADED = object()


@performance_stage("task_projection")
def enrich_job_runtime(
    project_id: str,
    job: Dict[str, Any],
    *,
    repository=None,
    worker_runtime=None,
    queued_candidates=None,
    allow_version_archive: bool = True,
    durable_task=_TRAINING_TASK_NOT_LOADED,
) -> Dict[str, Any]:
    if not job:
        return job
    repository = repository or shared_task_repository()
    job_id = job.get("id") or ""
    if not str(job.get("asset_algorithm_name") or "").strip():
        legacy_name = str(job.get("algorithm_name") or "").strip()
        if legacy_name:
            job["asset_algorithm_name"] = legacy_name
        else:
            algorithm_id = str(
                job.get("asset_algorithm_id") or job.get("algorithm_asset_id") or ""
            ).strip()
            if algorithm_id:
                try:
                    algorithm = next(
                        (
                            row for row in list_algorithms_internal(project_id, algorithm_id=algorithm_id)
                            if str(row.get("id") or "") == algorithm_id
                        ),
                        None,
                    )
                except HTTPException as error:
                    if error.status_code != 404:
                        raise
                    algorithm = None
                job["asset_algorithm_name"] = (
                    str(algorithm.get("name") or "已删除算法")
                    if algorithm is not None else "已删除算法"
                )
            else:
                job["asset_algorithm_name"] = "未命名算法"
    worker_error = str(job.get("error") or "").strip()
    worker_message = str(job.get("message") or "").strip()
    worker_progress_truth = dict(job)
    durable = (repository.get(str(job_id)) if job_id else None) if durable_task is _TRAINING_TASK_NOT_LOADED else durable_task
    public_runtime = None
    if durable is not None and durable.project_id == project_id and durable.kind is TaskKind.TRAINING:
        mapped = {
            TaskStatus.QUEUED: "queued",
            TaskStatus.RUNNING: "paused" if durable.stage == "paused" else "running",
            TaskStatus.CANCEL_REQUESTED: "running",
            TaskStatus.SUCCEEDED: "done",
            TaskStatus.PARTIAL_SUCCESS: "done",
            TaskStatus.CANCELLED: "stopped",
            TaskStatus.FAILED: "failed",
            TaskStatus.BLOCKED_BY_ENVIRONMENT: "failed",
            TaskStatus.BLOCKED_BY_HARDWARE: "failed",
        }.get(durable.status, str(job.get("status") or "queued"))
        public_runtime = task_to_public(durable, repository)
        if durable.status is TaskStatus.QUEUED:
            public_runtime.update(
                training_queue_truth(
                    durable,
                    repository,
                    worker_runtime=worker_runtime,
                    queued_candidates=queued_candidates,
                )
            )
        if public_runtime["status"] == "WAITING_RESOURCE":
            mapped = "waiting"
        apply_training_task_truth(job, public_runtime, legacy_status=mapped)
        job.update(
            result_ref=durable.result_ref or job.get("result_ref"),
            queue_priority=int(durable.priority),
            queue_rank=int(durable.queue_rank),
            priority_scheme="lower_number_first",
        )
        snapshot_truth = shared_task_artifacts().read_json(
            durable.task_id,
            "snapshot.json",
            default={},
        )
        if isinstance(snapshot_truth, dict):
            snapshot_id = str(snapshot_truth.get("snapshot_id") or "").strip()
            revision_id = str(snapshot_truth.get("dataset_revision_id") or "").strip()
            if snapshot_id:
                job["snapshot_id"] = snapshot_id
            if revision_id:
                job["dataset_revision_id"] = revision_id
        if durable.result_ref:
            durable_result = shared_task_artifacts().read_json(
                durable.task_id,
                durable.result_ref,
                default={},
            )
            if isinstance(durable_result, dict):
                lineage = durable_result.get("training_lineage") or {}
                if (isinstance(lineage, dict) and lineage.get("task_id") == durable.task_id
                        and durable_result.get("task_id") == durable.task_id):
                    execution = lineage.get("execution") or {}
                    if isinstance(execution, dict) and execution.get("worker_id"):
                        job["verified_last_worker_id"] = str(execution["worker_id"])
                dataset_manifest_ref = str(
                    durable_result.get("dataset_manifest_ref") or ""
                ).strip()
                if dataset_manifest_ref:
                    # Training version archival consumes this exact task-owned
                    # evidence. Keep the overlay deliberately whitelisted:
                    # legacy job JSON must not become a second copy of result truth.
                    job["dataset_manifest_ref"] = dataset_manifest_ref
        if durable.error:
            if durable.status in {
                TaskStatus.FAILED,
                TaskStatus.BLOCKED_BY_ENVIRONMENT,
                TaskStatus.BLOCKED_BY_HARDWARE,
            }:
                # Durable task error is lifecycle evidence. Preserve the
                # worker-owned job error/message as the root cause when they
                # exist instead of overwriting them with completion-handshake
                # or scheduler wrappers.
                job["task_error"] = durable.error
                job["error"] = worker_error or durable.error
                job["message"] = worker_message or worker_error or durable.error
            elif durable.status is TaskStatus.PARTIAL_SUCCESS:
                # PARTIAL_SUCCESS is a completed training lifecycle with a
                # non-fatal post-training/evaluation warning. Never project it
                # as the current fatal error or overwrite the successful
                # completion message.
                job["warning_message"] = durable.error
                job.pop("error", None)
            elif durable.status is TaskStatus.SUCCEEDED:
                # A retry/recovery may leave historical task.error evidence on
                # the durable record. Successful terminal truth wins.
                job.pop("error", None)
        elif durable.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}:
            job.pop("error", None)
        if durable.finished_at:
            # Keep the worker's own finished_at when present so started/finished use
            # the same clock representation; durable UTC is the recovery fallback.
            job.setdefault("finished_at", durable.finished_at)
    proc = PROCESS_REGISTRY.get(job_id) if job_id else None
    successful_terminal_statuses = {"done", "finished", "completed", "succeeded", "success"}
    ended_terminal_statuses = successful_terminal_statuses | {"failed", "stopped", "cancelled", "canceled"}
    status = str(job.get("status") or "queued").strip().lower()
    if proc:
        code = proc.poll()
        if code is None and status in {"queued", "waiting", "pending"}:
            status = "running"
            job["status"] = "running"
            job["message"] = job.get("message") or "训练中"
            job.setdefault("started_at", job.get("updated_at") or now_iso())
        elif code is not None:
            PROCESS_REGISTRY.pop(job_id, None)
            # The worker writes its final artifact metadata immediately before exiting.
            # Re-read after poll() observes exit so a stale in-flight request cannot
            # overwrite that successful result with an inferred failure.
            persisted = read_json(project_dir(project_id) / "jobs" / job_id / "job.json", {})
            persisted_status = str(persisted.get("status") or "").strip().lower()
            if persisted_status in ended_terminal_statuses:
                job = persisted
                worker_progress_truth = dict(persisted)
                status = persisted_status
            if status in {"queued", "running", "waiting", "pending"}:
                # 正常情况下 worker 会写 done/failed；如果服务刚好轮询到进程已退但文件未回写，则兜底。
                job["status"] = "done" if code == 0 else "failed"
                job["message"] = "训练完成" if code == 0 else f"训练进程退出码：{code}"
                job.setdefault("finished_at", now_iso())
    # 服务重启后 PROCESS_REGISTRY 会丢失，但 worker 可能仍在运行。使用持久化 pid 恢复状态判断。
    status = job.get("status") or status
    if not proc and job.get("target") != "remote" and status in {"queued", "running", "waiting", "pending"} and job.get("pid"):
        if _pid_alive(job.get("pid")):
            job["status"] = "running"
            status = "running"
            job["message"] = job.get("message") or "训练中"
        else:
            # 正常 worker 会在退出前把状态改为 done/failed；若仍是 running，说明异常退出。
            job["status"] = "failed"
            status = "failed"
            job["message"] = "训练进程已结束，但没有写入成功结果，请查看训练日志"
            job.setdefault("finished_at", now_iso())
    if durable is not None and public_runtime is not None:
        # Live Durable jobs use one canonical display projection. Do not scan
        # logs or recompute elapsed/ETA on each GET.
        apply_training_display_progress(
            job,
            public_runtime,
            telemetry_job=worker_progress_truth,
        )
        status = str(job.get("status") or status).strip().lower()
        job["elapsed_text"] = _human_seconds(job.get("elapsed_seconds")) if job.get("elapsed_seconds") is not None else "-"
        job["eta_text"] = _human_seconds(job.get("eta_seconds")) if job.get("eta_seconds") is not None else "估算中"
        job["status_text"] = {"queued":"排队中", "waiting":"等待资源", "running":"训练中", "paused":"已暂停", "done":"已完成", "finished":"已完成", "completed":"已完成", "succeeded":"已完成", "success":"已完成", "failed":"失败", "stopped":"已停止", "cancelled":"已取消", "canceled":"已取消"}.get(status, status)
    else:
        # Historical pre-Durable compatibility/recovery is the only path that
        # may infer epoch/progress from an old training log.
        training_progress = job.get("training_progress") if isinstance(job.get("training_progress"), dict) else {}
        try:
            total = int(float(training_progress.get("total_epochs") or job.get("total_epochs") or job.get("epochs") or 0))
        except (TypeError, ValueError):
            total = 0
        try:
            persisted_cur = int(float(training_progress.get("epoch") or job.get("current_epoch") or 0))
        except (TypeError, ValueError):
            persisted_cur = 0
        log_text = _job_log_text(project_id, job_id)
        cur = max(persisted_cur, _infer_epoch_from_log(log_text, total))
        if status in successful_terminal_statuses:
            # 100% means the task lifecycle is terminal. It must not fabricate the
            # final epoch number when training legitimately ended early.
            progress = 100
        elif status in ended_terminal_statuses:
            progress = int(min(99, round((cur / total) * 100))) if total and cur else int(job.get("progress_percent") or 0)
        else:
            progress = int(min(99, round((cur / total) * 100))) if total and cur else int(job.get("progress_percent") or 0)
        started = _parse_dt_value(job.get("started_at") or job.get("created_at"))
        finished = _parse_dt_value(job.get("finished_at")) if status in ended_terminal_statuses else None
        clock = finished or datetime.now()
        elapsed = int((clock - started).total_seconds()) if started else 0
        # 暂停期间不计入真实训练耗时/ETA。
        paused_seconds = int(job.get("paused_seconds") or 0)
        if status == "paused" and job.get("paused_at"):
            pdt = _parse_dt_value(job.get("paused_at"))
            if pdt:
                paused_seconds += max(0, int((datetime.now() - pdt).total_seconds()))
        elapsed = max(0, elapsed - paused_seconds)
        eta = None
        if status == "running" and total and cur and elapsed > 0:
            eta = int(max(0, elapsed * (total - cur) / max(1, cur)))
        elif status in ended_terminal_statuses:
            eta = 0
        elif status == "paused":
            eta = None
        job["current_epoch"] = cur
        job["total_epochs"] = total
        job["progress_percent"] = progress
        job["elapsed_seconds"] = elapsed
        job["elapsed_text"] = _human_seconds(elapsed) if elapsed else "-"
        job["eta_seconds"] = eta
        job["eta_text"] = _human_seconds(eta) if eta is not None else "估算中"
        job["status_text"] = {"queued":"排队中", "running":"训练中", "paused":"已暂停", "done":"已完成", "finished":"已完成", "completed":"已完成", "succeeded":"已完成", "success":"已完成", "failed":"失败", "stopped":"已停止", "cancelled":"已取消", "canceled":"已取消"}.get(status, status)
    if (
        allow_version_archive
        and str(job.get("status") or "").lower() in successful_terminal_statuses
        and not job.get("never_started")
        and job.get("asset_algorithm_id")
    ):
        try:
            _v48_archive_training_version(project_id, job)
        except Exception as archive_error:
            job["version_archive_error"] = str(archive_error)
    return job


def read_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# N5 residual risk: app.py wrote jobs/<id>/job.json directly while the numeric
# evidence publisher and the conversion worker use ``<job.json>.lock`` plus a
# whole-file atomic replacement. Every app writer now shares that exact lock
# identity so a concurrent projection can never be torn or silently lost.
_JOB_JSON_PROJECTION_FIELDS = (
    "numeric_status",
    "publication_status",
    "numeric_validation",
    "numeric_validation_binding_status",
    "delivery_quality",
)


_JOB_JSON_IO_DEADLINE_SECONDS = 15.0


def read_json_strict(path: Path) -> Any:
    """Read a JSON record, propagating transient Windows sharing errors."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    value = json.loads(raw)
    return value


def _write_job_json(job_file: Path, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Persist one job record under the shared ``<job.json>.lock`` contract.

    Read-modify-write callers elsewhere load a snapshot before publishing
    progress. Under the lock, projection fields owned by the numeric/delivery
    evidence path are carried forward when the incoming snapshot predates them,
    then the whole file is replaced atomically (readers never see half a file).
    JSON content semantics are otherwise unchanged.
    """
    job_file = Path(job_file)
    job_file.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(job_file) + ".lock", timeout=30, thread_local=False)
    try:
        with lock:
            value: Dict[str, Any] = dict(payload)
            # Never silently treat an unreadable current record as empty: that
            # would drop evidence projections written by the numeric/delivery
            # publisher. Readers may briefly hold the file on Windows, so retry
            # within a bounded deadline instead of losing the projection.
            current: Any = {}
            read_deadline = time.monotonic() + _JOB_JSON_IO_DEADLINE_SECONDS
            while True:
                try:
                    current = read_json_strict(job_file)
                    break
                except PermissionError:
                    if time.monotonic() >= read_deadline:
                        raise PlatformError(
                            "JOB_RECORD_READ_BUSY",
                            "任务记录正在被读取，暂时无法安全更新",
                            str(job_file),
                        )
                    time.sleep(0.01)
            if isinstance(current, Mapping):
                for field in _JOB_JSON_PROJECTION_FIELDS:
                    if field in current and not value.get(field):
                        value[field] = current[field]
            temporary = job_file.with_name(
                f".{job_file.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            try:
                temporary.write_text(
                    json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                # Windows can transiently deny the atomic replace when another
                # process/thread holds a read handle; retry with backoff within a
                # bounded deadline instead of failing the task update spuriously.
                replace_deadline = time.monotonic() + _JOB_JSON_IO_DEADLINE_SECONDS
                delay = 0.005
                while True:
                    try:
                        os.replace(temporary, job_file)
                        break
                    except PermissionError:
                        if time.monotonic() >= replace_deadline:
                            raise
                        time.sleep(delay)
                        delay = min(0.2, delay * 2)
            finally:
                temporary.unlink(missing_ok=True)
            return value
    except Timeout as error:
        raise PlatformError(
            "JOB_RECORD_WRITE_BUSY",
            "任务记录正在被其他写入者更新，请重试",
            str(job_file),
            "请保留当前页面并稍后重试；写入锁超时不代表任务状态已改变。",
            409,
        ) from error


def project_dir(project_id: str) -> Path:
    return DATA_DIR / "projects" / project_id


def get_project(project_id: str) -> Dict[str, Any]:
    meta = project_dir(project_id) / "meta.json"
    if not meta.exists():
        raise HTTPException(status_code=404, detail="项目不存在")
    return read_json(meta, {})



def _authorize_business_file_project(project_id: str) -> Dict[str, Any]:
    # Login is verified by the existing middleware. Production exposes one
    # canonical space; existence alone is not proof of access to another space.
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', str(project_id)):
        raise HTTPException(404, detail='文件不存在或无权访问')
    if not _auth_test_bypass_enabled() and not any(str(row.get('id')) == str(project_id) for row in list_projects()):
        raise HTTPException(404, detail='文件不存在或无权访问')
    return get_project(project_id)


def _business_file_url(project_id: str, kind: str, identifier: str) -> str:
    from platform_core.business_files import BusinessFileService
    return BusinessFileService.url(project_id, kind, identifier)


def _raise_file_storage_error(error, status_code=503):
    code = str(getattr(error, 'code', 'FILE_UNAVAILABLE'))
    if not re.fullmatch(r'[A-Z_0-9]{1,80}', code):
        code = 'FILE_UNAVAILABLE'
    raise HTTPException(status_code, detail={'code': code, 'message': '文件暂不可用或无权访问',
        'retryable': bool(getattr(error, 'retryable', False))}) from None


def _business_material_by_name(project_id, stored_name):
    matches = [row for row in material_store(project_id).read().rows
               if row.get('stored_name') == stored_name]
    return matches[0] if len(matches) == 1 else None


def _business_file_records(project_id, kind, identifier):
    """Project existing owners only; directory entries never register public bytes."""
    from platform_core.business_files import _read, _plain
    root = project_dir(project_id)
    def record(path, digest='', alias=None):
        row = {'project_id': project_id, 'path': str(path), 'sha256': digest}
        if alias is not None:
            row['identifier'] = alias
        return row
    if kind in {'models', 'jobs', 'runs'}:
        # This is the SQL-backed algorithm owner, not its retained JSON mirror.
        for algorithm in list_algorithm_assets(algorithms_file(project_id)):
            for version in algorithm.get('versions') or []:
                for output in version.get('exported_models') or []:
                    if isinstance(output, dict) and output.get('path') and output.get('sha256'):
                        yield record(output['path'], output['sha256'])
                for field in ('stored_path', 'best_path', 'last_path'):
                    path = str(version.get(field) or '')
                    if path:
                        alias = f"versions/{algorithm['id']}/{version['id']}/{Path(path).name}"
                        digest = str(version.get('sha256') or version.get('model_sha256') or '')
                        if identifier == alias and Path(path).is_file():
                            yield record(path, digest or sha256_file(Path(path)), alias)
                        yield record(path, digest)
        jobs = root / 'jobs'
        if jobs.is_dir():
            _plain(jobs, DATA_DIR)
            for metadata in jobs.glob('*/job.json'):
                job = _read(metadata, DATA_DIR)
                if job.get('project_id', project_id) != project_id:
                    continue
                for path in job.get('models') or []:
                    if isinstance(path, str):
                        yield record(path)
                for output in list(job.get('outputs') or []) + list(job.get('exported_models') or []):
                    if isinstance(output, dict) and output.get('path'):
                        yield record(output['path'], str(output.get('sha256') or ''))
        if (DATA_DIR / 'model_artifacts' / 'artifacts.sqlite3').is_file():
            from platform_core.model_artifacts import ModelArtifactRepository
            repo = ModelArtifactRepository(DATA_DIR)
            offset = 0
            while True:
                rows = repo.list(project_id=project_id, limit=500, offset=offset)
                for item in rows:
                    path = str(item.get('source_path') or '')
                    if path:
                        alias = f"artifacts/{item['id']}/{Path(path).name}" if 'id' in item else f"artifacts/{item['artifact_id']}/{Path(path).name}"
                        yield record(path, str(item.get('sha256') or ''), alias if identifier == alias else None)
                if len(rows) < 500:
                    break
                offset += len(rows)
    elif kind == 'deployment':
        parts = identifier.split('/')
        if len(parts) < 3 or parts[0] != 'jobs':
            return
        job_id = parts[1]
        job = _read(_deploy_job_dir(project_id, job_id) / 'job.json', DATA_DIR)
        if job.get('id') != job_id or job.get('project_id', project_id) != project_id:
            return
        if job.get('status') not in {'done', 'blocked_by_hardware'}:
            return
        for item in job.get('outputs') or []:
            if isinstance(item, dict) and item.get('path'):
                yield record(item['path'], str(item.get('sha256') or ''))
    elif kind == 'predictions':
        parts = identifier.split('/')
        if len(parts) == 2:
            task = shared_task_repository().get(parts[0])
            if task is None or task.project_id != project_id or task.kind is not TaskKind.DEPLOYMENT_TEST:
                return
            request = shared_task_artifacts().read_json(task.task_id, task.payload_ref, default={})
            expected_input = root / 'predictions' / task.task_id / parts[1]
            if parts[1].startswith('input.') and str(request.get('input_path') or '') == str(expected_input):
                yield record(expected_input)
            if parts[1] == 'result.jpg' and task.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}:
                result = shared_task_artifacts().read_json(task.task_id, task.result_ref, default={}) if task.result_ref else {}
                expected = root / 'predictions' / task.task_id / 'result.jpg'
                result_path = str(result.get('output_path') or request.get('output_path') or '')
                if result_path == str(expected):
                    yield record(expected)
            return
        if len(parts) != 1:
            return
        name = parts[0]
        prediction_id = Path(name).stem.rsplit('_', 1)[0]
        metadata = root / 'predictions' / f'{prediction_id}.evidence.json'
        if not metadata.is_file():
            return
        evidence = _read(metadata, DATA_DIR)
        if evidence.get('prediction_id') != prediction_id:
            return
        for item in (evidence.get('files') or {}).values():
            if isinstance(item, dict) and item.get('name') == name and item.get('sha256'):
                yield record(root / 'predictions' / name, item['sha256'])
                return
        # Legacy online-feedback records already bind the input digest and
        # formal version. Preserve only their two known image roles.
        if evidence.get('algorithm_id') and evidence.get('version_id'):
            verified, input_path, _, _ = _online_prediction_evidence(project_id, prediction_id)
            if name == verified.get('input_file'):
                yield record(input_path, verified['input_sha256'])
            elif name == f'{prediction_id}_result.jpg':
                yield record(root / 'predictions' / name, str(verified.get('result_sha256') or ''))
    elif kind == 'exports' and '/' not in identifier:
        package = Path(identifier).stem
        meta = root / 'exports' / package / 'model_meta.json'
        if not meta.is_file():
            return
        item = _read(meta, DATA_DIR)
        export_id = str(item.get('export_id') or '')
        if (item.get('project_id') == project_id and export_id
                and package.endswith('_' + export_id) and item.get('model_file')
                and item.get('model_path_source')):
            yield record(root / 'exports' / identifier, str(item.get('zip_sha256') or ''))


def _resolve_business_file(project_id, kind, identifier):
    from platform_core.business_files import BusinessFileService, BusinessFileNotFound
    _authorize_business_file_project(project_id)
    try:
        return BusinessFileService(DATA_DIR,
            records=lambda pid, category: _business_file_records(pid, category, identifier),
            material_lookup=_business_material_by_name, storage_manager=storage_manager,
        ).resolve(project_id, kind, identifier)
    except (BusinessFileNotFound, StorageError, OSError, ValueError, KeyError):
        raise HTTPException(404, detail='文件不存在或无权访问') from None


def _business_file_response(project_id, kind, identifier, *, download=False):
    item = _resolve_business_file(project_id, kind, identifier)
    headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'}
    kwargs = {'media_type': item.media_type, 'headers': headers}
    if download:
        kwargs['filename'] = item.filename
    if item.manager is not None:
        from platform_core.storage.http import StoredSourceFileResponse
        return StoredSourceFileResponse(item.path, manager=item.manager, material=item.material, **kwargs)
    return FileResponse(item.path, **kwargs)


@app.get('/api/projects/{project_id}/files/{kind}/{identifier:path}')
def controlled_business_file(project_id: str, kind: str, identifier: str):
    return _business_file_response(project_id, kind, identifier)


@app.get('/data/projects/{project_id}/{relativepath:path}')
def controlled_legacy_business_file(project_id: str, relativepath: str):
    kind, separator, identifier = relativepath.partition('/')
    if not separator:
        raise HTTPException(404, detail='文件不存在或无权访问')
    return _business_file_response(project_id, kind, identifier)


def _register_prediction_files(project_id, prediction_id, input_path, output_path, evidence=None):
    path = project_dir(project_id) / 'predictions' / f'{prediction_id}.evidence.json'
    value = dict(evidence or read_json(path, {}))
    value.update(project_id=project_id, prediction_id=prediction_id)
    value['files'] = {role: {'name': item.name, 'sha256': sha256_file(item)}
                      for role, item in (('input', Path(input_path)), ('result', Path(output_path)))
                      if item.is_file()}
    write_json(path, value)


def _authorized_model_url(project_id, model_path):
    try:
        relative = Path(model_path).absolute().relative_to(project_dir(project_id).absolute())
        kind, identifier = relative.as_posix().split('/', 1)
        _resolve_business_file(project_id, kind, identifier)
        return _business_file_url(project_id, kind, identifier)
    except (HTTPException, ValueError):
        return ''


def _material_governance_actor(request: Request, project_id: str) -> Dict[str, Any]:
    """Use the existing verified login; all project users have equal material rights."""
    claims = getattr(request.state, 'changlian_user', None)
    if claims is None:
        claims = _verify_browser_session(request.cookies.get(SESSION_COOKIE_NAME, ''))
    actor_id = str((claims or {}).get('username') or '').strip()
    if not actor_id:
        if not _auth_test_bypass_enabled():
            raise HTTPException(401, detail={'code':'AUTH_REQUIRED','message':'请先登录平台后管理当前项目素材'})
        # Preserve the pre-existing server-controlled isolated test harness only.
        actor_id = 'isolated-test'
    get_project(project_id)
    return {'actor_id': actor_id}


def save_project(project: Dict[str, Any]):
    project["updated_at"] = now_iso()
    meta_path = project_dir(project["id"]) / "meta.json"
    with FileLock(str(PROJECTS_FILE) + ".lock", timeout=60):
        with FileLock(str(meta_path) + ".lock", timeout=60):
            atomic_write_json(meta_path, project)
            projects = read_json(PROJECTS_FILE, [])
            found = False
            for i, item in enumerate(projects):
                if item["id"] == project["id"]:
                    projects[i] = project
                    found = True
                    break
            if not found:
                projects.append(project)
            atomic_write_json(PROJECTS_FILE, projects)

    # Keep the ready startup snapshot coherent with authoritative project
    # metadata. Label creation/disable/merge is a project mutation, and a
    # browser refresh must never resurrect labels from an older bootstrap
    # snapshot. Publish a replacement snapshot atomically instead of mutating
    # the shared object field by field.
    snapshot = globals().get("_V53_BOOTSTRAP_SNAPSHOT")
    if (
        isinstance(snapshot, dict)
        and str((snapshot.get("project") or {}).get("id") or "")
        == str(project.get("id") or "")
    ):
        refreshed = dict(snapshot)
        refreshed["project"] = dict(project)
        refreshed["labels"] = project_label_items(project)
        if isinstance(snapshot.get("projects"), list):
            refreshed_projects = []
            for item in snapshot["projects"]:
                if str((item or {}).get("id") or "") != str(project.get("id") or ""):
                    refreshed_projects.append(item)
                    continue
                replacement = dict(project)
                if isinstance(item, dict) and "bootstrap_counts" in item:
                    replacement["bootstrap_counts"] = item["bootstrap_counts"]
                refreshed_projects.append(replacement)
            refreshed["projects"] = refreshed_projects
        refreshed["generated_at"] = now_iso()
        globals()["_V53_BOOTSTRAP_SNAPSHOT"] = refreshed


def safe_filename(filename: str) -> str:
    name = Path(filename).name.replace(" ", "_")
    safe = "".join(c for c in name if c.isalnum() or c in "._-()[]{}+@#中文标签数据集模型训练")
    return safe.strip(".") or "file"


def image_info(path: Path) -> Dict[str, Any]:
    with Image.open(path) as img:
        return {"width": img.width, "height": img.height}


def ensure_project_dirs(pid: str):
    p = project_dir(pid)
    for d in ["uploads", "annotations", "dataset", "paddle_dataset", "runs", "models", "jobs", "predictions", "imports", "exports", "prelabels", "videos", "frame_tasks", "prelabel_tasks", "upload_batches"]:
        (p / d).mkdir(parents=True, exist_ok=True)


def material_store(project_id: str) -> MaterialRepository:
    return MaterialRepository(project_dir(project_id))


def storage_source_repository() -> StorageSourceRepository:
    def references(source_id: str) -> int:
        projects_root = DATA_DIR / "projects"
        if not projects_root.is_dir():
            return 0
        total = 0
        for child in projects_root.iterdir():
            if not child.is_dir() or not (child / "meta.json").is_file():
                continue
            total += MaterialRepository(child).reference_count(source_id)
        return total

    return StorageSourceRepository(
        DATA_DIR / "storage" / "storage_sources.sqlite3",
        reference_counter=references,
    )


def storage_credentials() -> SecretCredentialStore:
    return SecretCredentialStore(_v35_secret_store())


_STORAGE_SOURCE_DEPENDENCY_STATUSES = (
    TaskStatus.QUEUED,
    TaskStatus.RUNNING,
    TaskStatus.CANCEL_REQUESTED,
    TaskStatus.AWAITING_CONFIRMATION,
)
_STORAGE_SOURCE_DEPENDENCY_KINDS = (
    TaskKind.MATERIAL_IMPORT,
    TaskKind.MATERIAL_BATCH,
    TaskKind.AI_ANNOTATION,
    TaskKind.TRAINING,
    TaskKind.TRAINING_PREPARE,
    TaskKind.MODEL_CONVERSION,
)


def _storage_source_fence():
    return storage_source_lifecycle_fence(
        DATA_DIR / "storage" / "storage_sources.sqlite3"
    )


def _storage_source_runtime_generation(source: StorageSource) -> tuple[Any, ...]:
    return (
        # Identity plus a durable configuration epoch defeats both deletion
        # and in-place A->B->A changes, without penalizing display renames.
        source.created_at,
        int(source.runtime_revision),
        source.type,
        json.dumps(source.config, ensure_ascii=False, sort_keys=True),
        source.secret_ref,
        bool(source.enabled),
    )


def _payload_references_storage_source(value: Any, source_id: str) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) == "storage_source_id" and str(item) == str(source_id):
                return True
            if _payload_references_storage_source(item, source_id):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_payload_references_storage_source(item, source_id) for item in value)
    return False


def _storage_dependency_image_ids(value: Any) -> set[str]:
    image_ids: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized == "image_id" and str(item or "").strip():
                image_ids.add(str(item).strip())
            elif normalized.endswith("image_ids") and isinstance(item, (list, tuple)):
                image_ids.update(
                    str(candidate).strip()
                    for candidate in item
                    if str(candidate or "").strip()
                )
            else:
                image_ids.update(_storage_dependency_image_ids(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            image_ids.update(_storage_dependency_image_ids(item))
    return image_ids


def _material_ids_reference_source(
    project_id: str, image_ids: Sequence[str], source_id: str,
) -> bool:
    candidates = list(dict.fromkeys(
        str(value).strip() for value in image_ids if str(value).strip()
    ))
    material_path = project_dir(project_id) / "materials.sqlite3"
    if not material_path.is_file():
        return False
    materials = MaterialRepository(material_path.parent)
    for offset in range(0, len(candidates), 500):
        if any(
            str(row.get("storage_source_id") or "default_local") == str(source_id)
            for row in materials.get_many(candidates[offset:offset + 500])
        ):
            return True
    return False


def _material_batch_references_source(task: TaskRecord, source_id: str) -> bool:
    selection = shared_task_artifacts().artifact_path(
        task.task_id, MATERIAL_BATCH_SELECTION_REF,
    )
    material_path = project_dir(task.project_id) / "materials.sqlite3"
    if not material_path.is_file():
        return False
    materials = MaterialRepository(material_path.parent)
    if materials.reference_count(source_id) <= 0:
        return False
    if not selection.is_file():
        # An active task with missing dependency evidence is unsafe to mutate
        # underneath.  Fail closed until the task becomes terminal/repaired.
        return True
    try:
        with closing(sqlite3.connect(selection.as_uri() + "?mode=ro", uri=True)) as database:
            database.execute(
                "ATTACH DATABASE ? AS material_index",
                (materials.path.as_uri() + "?mode=ro",),
            )
            row = database.execute(
                "SELECT 1 FROM selection s "
                "JOIN material_index.materials m ON m.id=s.image_id "
                "WHERE m.storage_source_id=? LIMIT 1",
                (str(source_id),),
            ).fetchone()
    except sqlite3.DatabaseError:
        return True
    return row is not None


def _active_storage_source_dependencies(source_id: str) -> list[str]:
    repository = shared_task_repository()
    artifacts = shared_task_artifacts()
    conflicts: list[str] = []
    cursor = None
    while True:
        page = repository.list(
            kinds=_STORAGE_SOURCE_DEPENDENCY_KINDS,
            statuses=_STORAGE_SOURCE_DEPENDENCY_STATUSES,
            limit=100,
            cursor=cursor,
        )
        for task in page.items:
            if (
                task.status is TaskStatus.AWAITING_CONFIRMATION
                and task.kind is not TaskKind.MATERIAL_IMPORT
            ):
                # Review-only AI/MaterialBatch stages commit already-produced
                # evidence and no longer materialize source bytes.
                continue
            if task.kind is TaskKind.TRAINING and task.stage not in {
                "training_input_pending",
                "remote_input_pending",
                "preparing_input",
            }:
                # TRAINING_PREPARE owns source reads.  Once it activates the
                # parent, the immutable dataset bundle has replaced the live
                # Storage Source dependency.
                continue
            payload = artifacts.read_json(task.task_id, task.payload_ref, default={})
            referenced = _payload_references_storage_source(payload, source_id)
            dependency_payloads = [payload]
            if task.kind is TaskKind.TRAINING:
                try:
                    frozen = read_training_input_freeze(
                        artifacts, task.task_id, payload, default={},
                    )
                except (OSError, ValueError):
                    frozen = {}
                if not isinstance(frozen, Mapping):
                    frozen = {}
                dependency_payloads.append(frozen)
                referenced = referenced or _payload_references_storage_source(
                    frozen, source_id,
                )
            if not referenced and task.kind is TaskKind.MATERIAL_BATCH:
                referenced = _material_batch_references_source(task, source_id)
            if not referenced and task.kind is TaskKind.TRAINING_PREPARE:
                parent_id = str((payload or {}).get("training_task_id") or "")
                parent = repository.get(parent_id) if parent_id else None
                if parent is not None:
                    parent_payload = artifacts.read_json(
                        parent.task_id, parent.payload_ref, default={}
                    )
                    try:
                        parent_frozen = read_training_input_freeze(
                            artifacts, parent.task_id, parent_payload, default={},
                        )
                    except (OSError, ValueError):
                        parent_frozen = {}
                    if not isinstance(parent_frozen, Mapping):
                        parent_frozen = {}
                    referenced = _payload_references_storage_source(
                        parent_payload, source_id,
                    ) or _payload_references_storage_source(
                        parent_frozen, source_id,
                    ) or _material_ids_reference_source(
                        parent.project_id,
                        _storage_dependency_image_ids(parent_payload)
                        | _storage_dependency_image_ids(parent_frozen),
                        source_id,
                    )
            if not referenced:
                image_ids: set[str] = set()
                for dependency_payload in dependency_payloads:
                    image_ids.update(
                        _storage_dependency_image_ids(dependency_payload)
                    )
                if image_ids:
                    referenced = _material_ids_reference_source(
                        task.project_id, sorted(image_ids), source_id,
                    )
            if referenced:
                conflicts.append(f"{task.kind.value}:{task.task_id}:{task.status.value}")
                if len(conflicts) >= 20:
                    return conflicts
        cursor = page.next_cursor
        if not cursor:
            return conflicts


def _assert_storage_source_mutation_allowed(source_id: str) -> None:
    conflicts = _active_storage_source_dependencies(source_id)
    if conflicts:
        raise PlatformError(
            "STORAGE_SOURCE_ACTIVE_TASK_DEPENDENCY",
            "存储源正被活动任务使用，不能修改访问配置或凭据",
            "；".join(conflicts),
            "请等待任务结束或取消完成后重试；仅修改显示名称不受影响。",
            409,
        )


def storage_manager(project_id: str) -> StorageManager:
    return StorageManager(
        data_dir=DATA_DIR,
        project_id=project_id,
        materials=material_store(project_id),
        sources=storage_source_repository(),
        credentials=storage_credentials(),
    )


def resolve_material_path(project_id: str, material: str | Dict[str, Any]) -> Path:
    """Resolve any indexed material through its configured storage provider."""
    return storage_manager(project_id).materialize(material).path


def material_content_url(project_id: str, image_id: str) -> str:
    return f"/api/v61/projects/{project_id}/materials/{image_id}/content"


def public_material(project_id: str, value: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(value)
    row.setdefault("storage_source_id", "default_local")
    row.setdefault("storage_type", "local")
    source_type = str(row.get("source_type") or "").strip().lower()
    annotation_state = str(row.get("annotation_state") or row.get("annotation_status") or "").strip().lower()
    if (
        source_type.startswith("imported_")
        and annotation_state in {"annotated", "confirmed_empty"}
        and not str(row.get("annotation_origin") or "").strip()
    ):
        row["annotation_origin"] = "imported"
    if not row.get("object_key") and row.get("stored_name"):
        row["object_key"] = f"uploads/{Path(str(row['stored_name'])).name}"
    row["url"] = material_content_url(project_id, str(row.get("id") or ""))
    if re.fullmatch(r"[0-9a-f]{64}", str(row.get("content_sha256") or "")):
        row["thumbnail_url"] = row["url"] + "/thumbnail?edge=384"
    return row


def upload_batch_store(project_id: str) -> UploadBatchStore:
    return UploadBatchStore(project_dir(project_id) / "upload_batches")


def load_images(project_id: str) -> list[dict]:
    return material_store(project_id).read().rows


from platform_core.storage_configuration_contracts import StorageSourceCreateReq


from platform_core.storage_configuration_contracts import StorageSourceUpdateReq


from platform_core.storage_ingestion_contracts import StorageImportScanReq


from platform_core.storage_ingestion_contracts import StorageImportConfirmReq


def _validate_storage_source_config(source_type: str, config: Dict[str, Any]) -> str:
    try:
        normalized = StorageType.parse(source_type).value
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    missing = []
    if normalized == "oss":
        if not str(config.get("endpoint") or "").strip():
            missing.append("Endpoint")
        if not str(config.get("bucket") or "").strip():
            missing.append("Bucket")
        public_base_url = str(config.get("public_base_url") or "").strip()
        if public_base_url and not public_base_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="外网地址必须以 http:// 或 https:// 开头")
    elif normalized == "s3":
        if not str(config.get("bucket") or "").strip():
            missing.append("Bucket")
    elif normalized == "remote":
        if not str(config.get("base_url") or "").strip():
            missing.append("服务器地址")
        if not str(config.get("namespace") or "").strip():
            missing.append("命名空间")
    if missing:
        raise HTTPException(status_code=422, detail="缺少必填配置：" + "、".join(missing))
    return normalized


def _public_storage_source(source: StorageSource) -> Dict[str, Any]:
    state = {"configured": False, "masked": ""}
    if source.secret_ref:
        state = storage_credentials().public_state(source.secret_ref)
    return source.to_public_dict(
        secret_configured=bool(state["configured"]),
        secret_masked=str(state["masked"]),
    )


def _raise_storage_error(error: StorageError, *, status_code: int = 503):
    body = error.to_public_dict()
    raise PlatformError(
        code=str(body["code"]), message=str(body["message"]),
        detail=str(body["detail"]), solution=str(body["solution"]),
        status_code=status_code,
    ) from error


from platform_core.storage_configuration_service import StorageConfigurationDependencies, StorageConfigurationService
from platform_core.storage_configuration_api import create_storage_configuration_router_1


def _storage_configuration_service() -> StorageConfigurationService:
    return StorageConfigurationService(StorageConfigurationDependencies(
        DATA_DIR=lambda: DATA_DIR,
        _assert_storage_source_mutation_allowed=lambda *args, **kwargs: _assert_storage_source_mutation_allowed(*args, **kwargs),
        _public_storage_source=lambda *args, **kwargs: _public_storage_source(*args, **kwargs),
        _raise_storage_error=lambda *args, **kwargs: _raise_storage_error(*args, **kwargs),
        _storage_source_fence=lambda *args, **kwargs: _storage_source_fence(*args, **kwargs),
        _validate_storage_source_config=lambda *args, **kwargs: _validate_storage_source_config(*args, **kwargs),
        algorithms_file=lambda *args, **kwargs: algorithms_file(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        storage_credentials=lambda *args, **kwargs: storage_credentials(*args, **kwargs),
        storage_source_repository=lambda *args, **kwargs: storage_source_repository(*args, **kwargs),
    ))


app.include_router(create_storage_configuration_router_1(_storage_configuration_service))


def list_storage_sources():
    return _storage_configuration_service().list_storage_sources()


def create_storage_source(payload: StorageSourceCreateReq):
    return _storage_configuration_service().create_storage_source(payload)


def update_storage_source(source_id: str, payload: StorageSourceUpdateReq):
    return _storage_configuration_service().update_storage_source(source_id, payload)


def set_default_storage_source(source_id: str):
    return _storage_configuration_service().set_default_storage_source(source_id)


def test_storage_source(source_id: str):
    return _storage_configuration_service().test_storage_source(source_id)


def delete_storage_source(source_id: str):
    return _storage_configuration_service().delete_storage_source(source_id)


_STORAGE_IMPORT_COUNTERS = {
    "scanned_files", "importable_images", "duplicates", "invalid_images",
    "skipped_files", "failed", "extracted_files", "extracted_bytes",
    "declared_files", "declared_bytes", "selected", "indexed_at_least",
    "newly_imported", "index_duplicates", "indexed", "imported", "candidates",
    # Compatibility names used by the current storage-source UI.
    "scanned", "importable",
    "annotations_written", "boxes_imported", "boxes_skipped", "negative_samples",
    "existing_materials_updated", "new_materials_indexed",
}


def _public_storage_import_text(value: object, *, maximum: int = 500) -> str:
    text = redact_storage_error(value)[:maximum]
    # Worker-facing errors can include local roots. They are useful in server
    # logs but must never disclose absolute filesystem paths through this API.
    text = re.sub(r"(?<!\w)(?:[A-Za-z]:[\\/]|\\\\|/)[^\s\"'<>]*", "[REDACTED PATH]", text)
    return text


def _public_storage_import_mapping(value: object) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    public: Dict[str, Any] = {}
    for key in _STORAGE_IMPORT_COUNTERS:
        raw = value.get(key)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)):
            public[key] = max(0, raw)
    for key in ("stage", "mode", "execution_mode", "storage_source_id", "prefix", "manifest_ref", "scan_result_ref", "import_format", "dataset_yaml"):
        raw = value.get(key)
        if isinstance(raw, str):
            public[key] = _public_storage_import_text(raw)
    if isinstance(value.get("recursive"), bool):
        public["recursive"] = value["recursive"]
    error = value.get("error")
    if isinstance(error, dict):
        public_error = {
            key: _public_storage_import_text(error.get(key))
            for key in ("code", "message", "detail", "solution")
            if error.get(key) is not None
        }
        context = error.get("context")
        if isinstance(context, dict):
            public_error["context"] = {
                str(key)[:80]: number
                for key, number in list(context.items())[:20]
                if isinstance(number, (int, float)) and not isinstance(number, bool)
            }
        public["error"] = public_error
    public.update(public_quality(value, _public_storage_import_text))
    return public


def _public_storage_import_task(task: TaskRecord) -> Dict[str, Any]:
    artifacts = shared_task_artifacts()
    request = _public_storage_import_mapping(
        artifacts.read_json(task.task_id, task.payload_ref, default=None)
    ) or {}
    result = None
    if task.result_ref:
        result = _public_storage_import_mapping(
            artifacts.read_json(task.task_id, task.result_ref, default=None)
        )
    checkpoint = artifacts.read_json(
        task.task_id, "checkpoints/worker.json", default=None,
    )
    metrics = _public_storage_import_mapping(checkpoint) or {}
    if isinstance(result, dict):
        import_format = str(request.get("import_format") or result.get("import_format") or "images")
        external_classes = list(result.get("external_classes") or [])
        if import_format in {"yolo", "coco", "voc"} and external_classes:
            result["external_classes"] = external_label_facts(external_classes)
    if isinstance(checkpoint, dict):
        zip_import = checkpoint.get("zip_import")
        if isinstance(zip_import, dict):
            zip_metrics = _public_storage_import_mapping(zip_import) or {}
            for key in _STORAGE_IMPORT_COUNTERS:
                if key in zip_metrics:
                    metrics[key] = zip_metrics[key]
        else:
            zip_import = {}
        current = (
            checkpoint.get("current_object")
            or checkpoint.get("current_file")
            or zip_import.get("current_file")
        )
        if isinstance(current, str):
            metrics["current_file"] = _public_storage_import_text(current)
    return {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "kind": task.kind.value,
        "status": task.status.value,
        "progress": task.progress,
        "stage": task.stage,
        "current_item": _public_storage_import_text(task.current_item) if task.current_item else None,
        "error": _public_storage_import_text(task.error) if task.error else None,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "finished_at": task.finished_at,
        "mode": request.get("mode"),
        "execution_mode": request.get("execution_mode") or "local",
        "storage_source_id": request.get("storage_source_id"),
        "import_format": request.get("import_format"),
        "prefix": request.get("prefix"),
        "recursive": request.get("recursive"),
        "metrics": metrics,
        "result": result,
    }


from platform_core.storage_ingestion_contracts import StorageRescanCreateReq


from platform_core.storage_ingestion_contracts import StorageRescanConfirmReq


def _storage_rescan_task(project_id: str, task_id: str):
    return _storage_ingestion_service()._storage_rescan_task(project_id, task_id)


def _public_storage_rescan(task):
    artifacts = shared_task_artifacts()
    request = artifacts.read_json(task.task_id, task.payload_ref, default={})
    result = artifacts.read_json(task.task_id, task.result_ref, default={}) if task.result_ref else {}
    checkpoint = artifacts.read_json(task.task_id, 'checkpoints/worker.json', default={})
    summary = result if 'counts' in result else checkpoint
    public_error = _public_storage_import_mapping(result).get('error') if result else None
    annotation_counts = {
        key: max(0, int(value))
        for key, value in (summary.get('annotation_counts') or {}).items()
        if key in {
            'ANNOTATION_NEW', 'ANNOTATION_CHANGED', 'ANNOTATION_REMOVED',
            'ANNOTATION_UNCHANGED', 'ANNOTATION_CONFLICT', 'ANNOTATION_INVALID',
        }
    }
    annotation_examples = {
        key: [_public_storage_import_text(value) for value in values[:20]]
        for key, values in (summary.get('annotation_examples') or {}).items()
    }
    quality_view = public_quality(summary, _public_storage_import_text)
    external_classes = quality_view.get('external_classes', [])
    import_format = str(request.get('import_format') or summary.get('import_format') or 'images')
    if import_format in {'yolo', 'coco', 'voc'} and external_classes:
        external_classes = external_label_facts(external_classes)
    return {
        'task_id': task.task_id,
        'project_id': task.project_id,
        'status': task.status.value,
        'stage': task.stage,
        'accepted': task.accepted,
        'execution_mode': str(request.get('execution_mode') or 'local'),
        'import_format': import_format,
        'dataset_yaml': str(summary.get('dataset_yaml') or request.get('dataset_yaml') or ''),
        'worker_id': str(task.worker_id or ''),
        'resource_wait_reason': _public_storage_import_text(task.resource_wait_reason or ''),
        'current_item': _public_storage_import_text(task.current_item or ''),
        'error': public_error,
        'counts': {
            key: max(0, int(value))
            for key, value in summary.get('counts', {}).items()
            if key in {'NEW', 'MISSING', 'CHANGED', 'UNCHANGED', 'INVALID', 'SKIPPED'}
        },
        'examples': {
            key: [_public_storage_import_text(value) for value in values[:20]]
            for key, values in summary.get('examples', {}).items()
        },
        'annotation_counts': annotation_counts,
        'annotation_examples': annotation_examples,
        'annotation_applied': max(0, int(summary.get('annotation_applied') or 0)),
        'quality': quality_view.get('quality'),
        'external_classes': external_classes,
        'applied': max(0, int(summary.get('applied') or 0)),
    }


def _storage_rescan_agent_preflight(project_id: str, source_id: str) -> Dict[str, Any]:
    return _storage_ingestion_service()._storage_rescan_agent_preflight(project_id, source_id)


from platform_core.storage_ingestion_service import StorageIngestionDependencies, StorageIngestionService
from platform_core.storage_ingestion_api import create_storage_ingestion_router_1


def _storage_ingestion_service() -> StorageIngestionService:
    return StorageIngestionService(StorageIngestionDependencies(
        DATA_DIR=lambda: DATA_DIR,
        _authorize_business_file_project=lambda *args, **kwargs: _authorize_business_file_project(*args, **kwargs),
        _label_sample_content_type=lambda *args, **kwargs: _label_sample_content_type(*args, **kwargs),
        _public_storage_import_task=lambda *args, **kwargs: _public_storage_import_task(*args, **kwargs),
        _public_storage_import_text=lambda *args, **kwargs: _public_storage_import_text(*args, **kwargs),
        _public_storage_rescan=lambda *args, **kwargs: _public_storage_rescan(*args, **kwargs),
        _raise_file_storage_error=lambda *args, **kwargs: _raise_file_storage_error(*args, **kwargs),
        _remote_execution_transport_service=lambda *args, **kwargs: _remote_execution_transport_service(*args, **kwargs),
        _storage_source_fence=lambda *args, **kwargs: _storage_source_fence(*args, **kwargs),
        _storage_source_runtime_generation=lambda *args, **kwargs: _storage_source_runtime_generation(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        material_store=lambda *args, **kwargs: material_store(*args, **kwargs),
        project_label_items=lambda *args, **kwargs: project_label_items(*args, **kwargs),
        remember_project_label_aliases=lambda *args, **kwargs: remember_project_label_aliases(*args, **kwargs),
        shared_task_artifacts=lambda *args, **kwargs: shared_task_artifacts(*args, **kwargs),
        shared_task_repository=lambda *args, **kwargs: shared_task_repository(*args, **kwargs),
        storage_manager=lambda *args, **kwargs: storage_manager(*args, **kwargs),
        storage_source_repository=lambda *args, **kwargs: storage_source_repository(*args, **kwargs),
    ))


app.include_router(create_storage_ingestion_router_1(_storage_ingestion_service))


def storage_rescan_preflight(project_id: str, source_id: str):
    return _storage_ingestion_service().storage_rescan_preflight(project_id, source_id)


def create_storage_rescan(project_id: str, source_id: str, payload: Optional[StorageRescanCreateReq]=None):
    return _storage_ingestion_service().create_storage_rescan(project_id, source_id, payload)


def get_storage_rescan(project_id: str, task_id: str):
    return _storage_ingestion_service().get_storage_rescan(project_id, task_id)


def confirm_storage_rescan(project_id: str, task_id: str, payload: StorageRescanConfirmReq):
    return _storage_ingestion_service().confirm_storage_rescan(project_id, task_id, payload)


def cancel_storage_rescan(project_id: str, task_id: str):
    return _storage_ingestion_service().cancel_storage_rescan(project_id, task_id)


def create_storage_import_scan(project_id: str, payload: StorageImportScanReq):
    return _storage_ingestion_service().create_storage_import_scan(project_id, payload)


def get_storage_import_scan(project_id: str, task_id: str):
    return _storage_ingestion_service().get_storage_import_scan(project_id, task_id)


def confirm_storage_import(project_id: str, task_id: str, payload: StorageImportConfirmReq):
    return _storage_ingestion_service().confirm_storage_import(project_id, task_id, payload)


def _label_review_candidate_store(project_id: str, task_id: str):
    return _storage_ingestion_service()._label_review_candidate_store(project_id, task_id)


def _label_sample_content_type(filename: str) -> str:
    detected = mimetypes.guess_type(str(filename or ""))[0] or "application/octet-stream"
    return detected if detected.startswith("image/") else "application/octet-stream"


def label_review_samples_v61(project_id: str, task_id: str, class_id: str, limit: int=Query(default=8, ge=1, le=12)):
    return _storage_ingestion_service().label_review_samples_v61(project_id, task_id, class_id, limit)


def label_review_sample_content_v61(project_id: str, task_id: str, class_id: str, object_key: str=Query(..., min_length=1, max_length=4096)):
    return _storage_ingestion_service().label_review_sample_content_v61(project_id, task_id, class_id, object_key)


def _material_legacy_zip_batch_ids(project_id, source_batch_id):
    """Old membership stays in its canonical report; no history/GT backfill."""
    if not source_batch_id:
        return ()
    repository=material_store(project_id)
    with closing(repository._connect()) as db:
        if db.execute("SELECT 1 FROM materials WHERE json_extract(payload_json,'$.import_batch_id')=? LIMIT 1",(source_batch_id,)).fetchone():
            return ()
    if not re.fullmatch(r'[0-9a-f]{10}',source_batch_id):
        return ()
    try:
        job=v19_read_job(project_id,source_batch_id)
    except HTTPException as error:
        if error.status_code==404:return ()
        raise
    if job.get('status')!='done':return ()
    return tuple(dict.fromkeys(str(value) for value in v19_read_import_report(project_id,source_batch_id,job).get('imported_image_ids') or [] if value))


from platform_core.material_catalog_service import MaterialCatalogDependencies, MaterialCatalogService
from platform_core.material_catalog_api import (
    create_material_reader_router,
    create_material_thumbnail_router,
    create_dataset_directory_router,
    create_legacy_material_reader_router,
    create_label_directory_router,
    create_dataset_quality_router,
    create_dataset_summary_router,
)


def _material_catalog_service() -> MaterialCatalogService:
    return MaterialCatalogService(MaterialCatalogDependencies(
        _annotation_label_catalog=lambda *args, **kwargs: _annotation_label_catalog(*args, **kwargs),
        _authorize_business_file_project=lambda *args, **kwargs: _authorize_business_file_project(*args, **kwargs),
        _material_legacy_zip_batch_ids=lambda *args, **kwargs: _material_legacy_zip_batch_ids(*args, **kwargs),
        _raise_file_storage_error=lambda *args, **kwargs: _raise_file_storage_error(*args, **kwargs),
        _v52_schedule_annotation_index=lambda *args, **kwargs: _v52_schedule_annotation_index(*args, **kwargs),
        datasets_file=lambda *args, **kwargs: datasets_file(*args, **kwargs),
        ensure_default_datasets=lambda *args, **kwargs: ensure_default_datasets(*args, **kwargs),
        fast_json_response=lambda *args, **kwargs: fast_json_response(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        load_images=lambda *args, **kwargs: load_images(*args, **kwargs),
        material_store=lambda *args, **kwargs: material_store(*args, **kwargs),
        normalize_box_for_project=lambda *args, **kwargs: normalize_box_for_project(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        project_label_items=lambda *args, **kwargs: project_label_items(*args, **kwargs),
        public_material=lambda *args, **kwargs: public_material(*args, **kwargs),
        read_annotation=lambda *args, **kwargs: read_annotation(*args, **kwargs),
        read_annotations_many=lambda *args, **kwargs: read_annotations_many(*args, **kwargs),
        storage_manager=lambda *args, **kwargs: storage_manager(*args, **kwargs),
        write_json=lambda *args, **kwargs: write_json(*args, **kwargs),
    ))


app.include_router(create_material_reader_router(_material_catalog_service))


def list_materials_v61(project_id: str, cursor: Optional[str]=None, limit: int=100, page: Optional[int]=None, page_size: Optional[int]=None, query: str='', storage_source_id: Optional[List[str]]=Query(default=None), processing_status: Optional[str]=None, label: Optional[List[str]]=Query(default=None), annotated: Optional[bool]=None, annotation_state: Optional[Literal['unannotated', 'annotated', 'confirmed_empty', 'partial', 'needs_review']]=None, source_batch_id: Optional[str]=None, quality_status: Optional[Literal['pending_decision', 'processed', 'issue']]=None, created_from: Optional[str]=None, created_to: Optional[str]=None, reader_view: bool=False):
    return _material_catalog_service().list_materials_v61(project_id, cursor, limit, page, page_size, query, storage_source_id, processing_status, label, annotated, annotation_state, source_batch_id, quality_status, created_from, created_to, reader_view)


def list_material_ids_v61(project_id: str, cursor: Optional[str]=None, limit: int=1000, query: str='', storage_source_id: Optional[List[str]]=Query(default=None), processing_status: Optional[str]=None, label: Optional[List[str]]=Query(default=None), annotated: Optional[bool]=None, annotation_state: Optional[Literal['unannotated', 'annotated', 'confirmed_empty', 'partial', 'needs_review']]=None, source_batch_id: Optional[str]=None, quality_status: Optional[Literal['pending_decision', 'processed', 'issue']]=None, created_from: Optional[str]=None, created_to: Optional[str]=None, narrow: bool=False, expected_revision: Optional[int]=None):
    return _material_catalog_service().list_material_ids_v61(project_id, cursor, limit, query, storage_source_id, processing_status, label, annotated, annotation_state, source_batch_id, quality_status, created_from, created_to, narrow, expected_revision)


def material_status_counts_v61(project_id: str, storage_source_id: Optional[List[str]]=Query(default=None)):
    return _material_catalog_service().material_status_counts_v61(project_id, storage_source_id)


def material_content_v61(project_id: str, image_id: str):
    return _material_catalog_service().material_content_v61(project_id, image_id)


@app.get('/api/v62/projects/{project_id}/storage/lifecycle-summary')
def storage_lifecycle_summary_v62(project_id: str):
    get_project(project_id)
    from platform_core.storage.lifecycle_summary import storage_lifecycle_summary
    return {'ok':True, **storage_lifecycle_summary(DATA_DIR, project_id)}


app.include_router(create_material_thumbnail_router(_material_catalog_service))


def material_thumbnail_v61(project_id: str, image_id: str, request: Request, edge: int=Query(384, ge=16, le=1024)):
    return _material_catalog_service().material_thumbnail_v61(project_id, image_id, request, edge)


def normalize_label(name: str) -> str:
    return str(name or "").strip().replace(" ", "_")

def default_label_color(index: int) -> str:
    palette = ["#2563eb", "#16a34a", "#dc2626", "#ea580c", "#7c3aed", "#0891b2", "#be123c", "#4b5563", "#65a30d", "#ca8a04"]
    return palette[index % len(palette)]


def ensure_label(project: Dict[str, Any], label: str) -> int:
    label = normalize_label(label)
    if not label:
        raise HTTPException(status_code=400, detail="标签不能为空")
    labels = project.setdefault("labels", [])
    for i, item in enumerate(labels):
        if item == label:
            if _prune_canonical_label_alias_conflicts(project):
                save_project(project)
            return i
    labels.append(label)
    meta = project.setdefault("label_meta", [])
    meta.append({
        "code": label,
        "display_name": label,
        "color": default_label_color(len(labels)-1),
        "type": "bbox",
        "hotkey": str(len(labels)) if len(labels) <= 9 else "",
        "aliases": [],
    })
    _prune_canonical_label_alias_conflicts(project)
    save_project(project)
    return len(labels) - 1


def get_label_id(project: Dict[str, Any], label: str) -> int:
    label = normalize_label(label)
    if label not in project.get("labels", []):
        return ensure_label(project, label)
    return project["labels"].index(label)


def is_image_file(path: str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS


def read_yaml_names(path: Path) -> List[str]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        names = data.get("names", [])
        if isinstance(names, dict):
            return [str(names[k]) for k in sorted(names.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x))]
        if isinstance(names, list):
            return [str(x) for x in names]
    except Exception:
        return []
    return []


def yolo_line_to_box(line: str, img_w: int, img_h: int) -> Optional[Dict[str, Any]]:
    parts = line.strip().split()
    if len(parts) < 5:
        return None
    try:
        cls = int(float(parts[0]))
        xc, yc, bw, bh = map(float, parts[1:5])
        x1 = (xc - bw / 2) * img_w
        y1 = (yc - bh / 2) * img_h
        x2 = (xc + bw / 2) * img_w
        y2 = (yc + bh / 2) * img_h
        x1 = max(0, min(x1, img_w))
        x2 = max(0, min(x2, img_w))
        y1 = max(0, min(y1, img_h))
        y2 = max(0, min(y2, img_h))
        if x2 - x1 < 2 or y2 - y1 < 2:
            return None
        return {"class_id": cls, "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2)}
    except Exception:
        return None


def box_to_yolo_line(b: Dict[str, Any], w: int, h: int) -> str:
    x_center = ((b["x1"] + b["x2"]) / 2) / w
    y_center = ((b["y1"] + b["y2"]) / 2) / h
    bw = (b["x2"] - b["x1"]) / w
    bh = (b["y2"] - b["y1"]) / h
    return f"{int(b['class_id'])} {x_center:.6f} {y_center:.6f} {bw:.6f} {bh:.6f}"


_IMAGE_BATCH_CTX: ContextVar[Optional[Dict[str, Any]]] = ContextVar("image_batch_context", default=None)
_V50_IMPORT_LOCK_GUARD = threading.Lock()
_V50_IMPORT_LOCKS: Dict[str, threading.RLock] = {}
_V50_DATASET_LOCK_GUARD = threading.Lock()
_V50_DATASET_LOCKS: Dict[Tuple[str, str], threading.RLock] = {}


class _V50DatasetSourceChanged(RuntimeError):
    pass

def _v50_project_import_lock(project_id: str) -> threading.RLock:
    with _V50_IMPORT_LOCK_GUARD:
        lock = _V50_IMPORT_LOCKS.get(project_id)
        if lock is None:
            lock = threading.RLock()
            _V50_IMPORT_LOCKS[project_id] = lock
        return lock


def _v50_dataset_lock_key(project_id: str, dataset_id: str) -> Tuple[str, str]:
    return (str(project_id), str(dataset_id or "default"))


def _v50_dataset_lock(project_id: str, dataset_id: str) -> threading.RLock:
    key = _v50_dataset_lock_key(project_id, dataset_id)
    with _V50_DATASET_LOCK_GUARD:
        lock = _V50_DATASET_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _V50_DATASET_LOCKS[key] = lock
        return lock


@contextmanager
def _v50_dataset_locks(project_id: str, dataset_ids):
    keys = sorted({
        _v50_dataset_lock_key(project_id, dataset_id)
        for dataset_id in dataset_ids
    })
    locks = [_v50_dataset_lock(*key) for key in keys]
    for lock in locks:
        lock.acquire()
    try:
        yield
    finally:
        for lock in reversed(locks):
            lock.release()

def _v50_active_image_batch(project_id: str):
    batch = _IMAGE_BATCH_CTX.get()
    if batch and batch.get("project_id") == project_id:
        return batch
    return None

def _v50_begin_image_batch(project_id: str):
    _IMAGE_BATCH_CTX.set({
        "project_id": project_id,
        "records": {},
        "patches": {},
        # Plain multi-image uploads may defer only their initial unannotated
        # placeholders so one SQLite upsert_many persists the batch. Structured
        # imports already know final GT and persist that truth immediately once.
        "deferred_annotations": {},
        "annotation_repository": None,
        # Storage source schema/provider/credential setup is request-scoped,
        # not image-scoped. Reuse one manager across the whole import batch.
        "storage_manager": None,
    })


def _v50_annotation_repository(project_id: str) -> AnnotationRepository:
    batch = _v50_active_image_batch(project_id)
    if batch is not None:
        repository = batch.get("annotation_repository")
        if repository is None:
            repository = AnnotationRepository(project_dir(project_id))
            batch["annotation_repository"] = repository
        return repository
    return AnnotationRepository(project_dir(project_id))


def _v50_storage_manager(project_id: str) -> StorageManager:
    batch = _v50_active_image_batch(project_id)
    if batch is not None:
        manager = batch.get("storage_manager")
        if manager is None:
            manager = storage_manager(project_id)
            batch["storage_manager"] = manager
        return manager
    return storage_manager(project_id)


def _v50_queue_image_patch(project_id: str, image_id: str, patch: Dict[str, Any]) -> bool:
    batch = _v50_active_image_batch(project_id)
    if not batch:
        return False
    normalized_id = str(image_id)
    record = batch["records"].get(normalized_id)
    if record is not None:
        record.update(dict(patch))
    else:
        batch["patches"].setdefault(normalized_id, {}).update(dict(patch))
    return True


def _v50_cleanup_buffered_image_batch_files(
    project_id: str, records: List[Dict[str, Any]],
    *, upload_manager: Optional[StorageManager] = None,
) -> List[str]:
    errors = []
    p = project_dir(project_id)
    # _v50_end_image_batch clears the ContextVar before rollback: pass the
    # original provider cache explicitly rather than resolving a changed
    # Storage Source config (which could delete the wrong object location).
    manager = upload_manager or storage_manager(project_id)
    for record in records:
        image_id = str(record.get("id") or "")
        try:
            material_store(project_id).record_deferred_cleanup(record,
                owner='upload_batch_rollback',error='PHYSICAL_DELETE_SAFETY_UNVERIFIED')
        except Exception as error:
            errors.append(f"延期回收记录未保存 {record.get('object_key') or record.get('stored_name')}: {redact_storage_error(error)}")
        paths = []
        if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", image_id):
            paths.append(p / "annotations" / f"{image_id}.json")
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                errors.append(f"{path.name}: {error}")
    image_ids = [
        str(record.get("id") or "")
        for record in records
        if str(record.get("id") or "")
    ]
    if image_ids:
        try:
            AnnotationRepository(p).remove(image_ids)
        except Exception as error:
            errors.append(f"annotation sqlite cleanup: {error}")
    return errors


def _v50_end_image_batch(save: bool = True):
    batch = _IMAGE_BATCH_CTX.get()
    _IMAGE_BATCH_CTX.set(None)
    if not batch:
        return []
    project_id = str(batch.get("project_id") or "")
    records = [dict(record) for record in batch.get("records", {}).values()]
    patches = {
        str(image_id): dict(patch)
        for image_id, patch in batch.get("patches", {}).items()
    }
    deferred_annotations = [
        dict(row) for row in batch.get("deferred_annotations", {}).values()
    ]
    if not save:
        # Roll back against the same provider used for this upload, even
        # if Storage Source config changed before final admission.
        cleanup_errors = _v50_cleanup_buffered_image_batch_files(
            project_id, records, upload_manager=batch.get("storage_manager"),
        )
        if cleanup_errors:
            raise RuntimeError(
                "批量导入回滚失败：" + "; ".join(cleanup_errors)
            )
        return []
    if not records and not patches and not deferred_annotations:
        return []

    try:
        records_by_id = {
            str(record.get("id")): record for record in records
        }
        for image_id in list(patches):
            record = records_by_id.get(image_id)
            if record is not None:
                record.update(patches.pop(image_id))

        target_dataset_ids = {
            str(record.get("dataset_id") or "default")
            for record in records
        }
        target_dataset_ids.update(
            str(patch.get("dataset_id") or "default")
            for patch in patches.values()
            if "dataset_id" in patch
        )
        with _v50_dataset_locks(project_id, target_dataset_ids):
            for dataset_id in sorted(target_dataset_ids):
                _v50_assert_dataset_writable_locked(project_id, dataset_id)
            repository = material_store(project_id)
            with material_annotation_lifecycle_fence(project_dir(project_id)):
                if not patches:
                    persisted_materials = repository.upsert_many(records)
                else:
                    # Rare compatibility fallback: a batch may contain patches
                    # for pre-existing rows. Preserve its single Material DB
                    # transaction while the shared lifecycle fence is held.
                    def commit(rows):
                        by_id = {}
                        for row in rows:
                            by_id.setdefault(str(row.get("id")), row)
                        changed_ids = []
                        for incoming in records:
                            image_id = str(incoming.get("id"))
                            row = by_id.get(image_id)
                            if row is None:
                                row = dict(incoming)
                                rows.append(row)
                                by_id[image_id] = row
                            else:
                                row.update(incoming)
                            changed_ids.append(image_id)
                        for image_id, patch in patches.items():
                            row = by_id.get(image_id)
                            if row is None:
                                continue
                            row.update(patch)
                            if image_id not in changed_ids:
                                changed_ids.append(image_id)
                        return [dict(by_id[image_id]) for image_id in changed_ids]

                    persisted_materials = repository.mutate(commit)
                if deferred_annotations:
                    annotation_repository = (
                        batch.get("annotation_repository")
                        or AnnotationRepository(project_dir(project_id))
                    )
                    # Formal Material admission is bounded to 500 IDs per call.
                    # Keep that safety contract and batch the importer instead
                    # of sending the entire ZIP's annotations in one call.
                    for offset in range(0, len(deferred_annotations), 500):
                        annotation_repository.upsert_many(
                            deferred_annotations[offset:offset + 500],
                            project_material=True,
                            return_rows=True,
                        )
                    persisted = []
                    record_ids = [str(record.get("id") or "") for record in records]
                    for offset in range(0, len(record_ids), 500):
                        persisted.extend(repository.get_many(record_ids[offset:offset + 500]))
                    return persisted
                return persisted_materials
    except Exception as error:
        # Material and Annotation are separate SQLite commits. If the Material
        # commit already landed but Annotation failed, deleting the uploaded
        # source bytes would leave permanent dangling Material references.
        # An unreadable Material index is equally unsafe to treat as empty.
        record_ids = [str(row.get("id")) for row in records if str(row.get("id") or "")]
        try:
            indexed_rows = []
            materials = material_store(project_id)
            for offset in range(0, len(record_ids), 500):
                indexed_rows = materials.get_many(record_ids[offset:offset + 500])
                if indexed_rows:
                    break
        except Exception as inspection_error:
            raise RuntimeError(
                f"{error}; 无法确认素材索引状态，已保留源文件以避免误删：{inspection_error}"
            ) from error
        if indexed_rows:
            raise RuntimeError(
                f"{error}; 素材已写入正式索引但后续步骤失败，已保留源文件和索引供完整性修复"
            ) from error
        cleanup_errors = _v50_cleanup_buffered_image_batch_files(
            project_id, records, upload_manager=batch.get("storage_manager"),
        )
        if cleanup_errors:
            raise RuntimeError(
                f"{error}; 批量上传回滚未完全完成：" + "; ".join(cleanup_errors)
            ) from error
        raise

def _v50_mark_image_processed(project_id: str, image_id: str, annotated: bool = False):
    if not annotated:
        return
    patch = {
        "processing_status": "processed",
        "annotated_at": now_iso(),
    }
    if not _v50_queue_image_patch(project_id, image_id, patch):
        material_store(project_id).patch({str(image_id): patch})

def _annotation_box_source_fallback(material: Optional[Dict[str, Any]] = None) -> str:
    row = material or {}
    origin = str(row.get("annotation_origin") or "").strip().lower()
    if origin == "ai_confirmed":
        return "ai_candidate_confirmed"
    if origin == "imported":
        return "imported"
    if origin == "manual":
        return "manual"
    if str(row.get("source_type") or "").strip().lower().startswith("imported_"):
        return "imported"
    return "manual"

def _annotation_summary_for_material_index(
    boxes: List[Dict[str, Any]],
    annotation_state: Optional[str],
    material: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Rebuild material annotation summary without erasing durable provenance.

    Box-level provenance is authoritative when present. Legacy annotations may
    predate box provenance, so index migration may fall back to the material's
    durable origin or structured-import source type only when every box lacks
    an explicit source.
    """
    summary = annotation_summary(boxes, annotation_state)
    if summary.get("annotation_state") not in {"annotated", "confirmed_empty"}:
        return summary
    explicit_sources = [
        str(box.get("source") or "").strip().lower()
        for box in boxes
        if str(box.get("source") or "").strip()
    ]
    if explicit_sources:
        return summary
    row = material or {}
    durable_origin = str(row.get("annotation_origin") or "").strip().lower()
    if durable_origin in {"manual", "ai_confirmed", "mixed", "imported"}:
        summary["annotation_origin"] = durable_origin
    elif str(row.get("source_type") or "").strip().lower().startswith("imported_"):
        summary["annotation_origin"] = "imported"
    return summary

def _v50_material_annotation_patch(
    saved: Dict[str, Any], annotation_origin: Optional[str] = None,
    *, material: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    boxes = list(saved.get("boxes") or [])
    state = str(saved.get("annotation_state") or ("annotated" if boxes else "unannotated"))
    updated = str(saved.get("updated_at") or now_iso())
    summary = annotation_summary(boxes, state)
    if annotation_origin:
        summary["annotation_origin"] = str(annotation_origin)
    patch = {
        **summary,
        "annotation_version": int(saved.get("version") or 0),
        "annotation_scope": list(saved.get("annotation_scope") or []),
        "annotation_hash": str(saved.get("content_digest") or ""),
        "annotation_summary_at": updated,
    }
    if state in {"annotated", "confirmed_empty"}:
        patch["processing_status"] = "processed"
        patch["annotated_at"] = updated
        source_hash = str((material or {}).get("content_sha256") or "").strip().lower()
        if len(source_hash) == 64 and all(c in "0123456789abcdef" for c in source_hash):
            # Bind formal GT to the material generation seen before writing
            # AnnotationRepository. Snapshot rechecks after concurrent rescan.
            patch["annotation_source_content_sha256"] = source_hash
            if str((material or {}).get("annotation_review_reason") or "") == "SOURCE_CONTENT_CHANGED":
                patch.update(
                    annotation_needs_review=False,
                    annotation_review_reason="",
                    needs_review=False,
                )
    return patch


def write_annotation(
    project_id: str, image_id: str, boxes: List[Dict[str, Any]],
    annotation_state=None, annotation_origin: Optional[str] = None,
    *, annotation_scope=None, expected_version: Optional[int] = None,
    source_content_sha256: Optional[str] = None,
    review_evidence=None, reviewed_label_codes=None,
):
    # AnnotationRepository is the ground-truth owner. Persist explicit/final
    # truth immediately. If this image had only a deferred plain-upload
    # unannotated placeholder, cancel that placeholder before writing final GT.
    batch = _v50_active_image_batch(project_id)
    if batch is not None:
        batch.get("deferred_annotations", {}).pop(str(image_id), None)
        pending_material = batch.get("records", {}).get(str(image_id))
        if pending_material is not None:
            # Match AnnotationRepository's canonical default: an importer that
            # supplies a final empty annotation is explicit reviewed truth.
            # Plain uploads pass ``unannotated`` explicitly and stay pending.
            state = annotation_state or ("annotated" if boxes else "confirmed_empty")
            batch["deferred_annotations"][str(image_id)] = {
                "image_id": str(image_id),
                "boxes": list(boxes or []),
                "annotation_state": state,
                "annotation_scope": annotation_scope,
                "expected_version": expected_version,
                "source_content_sha256": (
                    source_content_sha256
                    or pending_material.get("content_sha256")
                ),
                "annotation_origin": annotation_origin,
            }
            return {
                "image_id": str(image_id),
                "boxes": list(boxes or []),
                "annotation_state": state,
                "annotation_scope": list(annotation_scope or []),
                "version": int(expected_version or 0),
                "content_digest": "",
                "updated_at": now_iso(),
            }
    saved = _v50_annotation_repository(project_id).upsert(
        image_id,
        boxes,
        annotation_state,
        annotation_scope=annotation_scope,
        project_material=True,
        expected_version=expected_version,
        source_content_sha256=source_content_sha256,
        annotation_origin=annotation_origin,
        review_evidence=review_evidence,
        reviewed_label_codes=reviewed_label_codes,
    )
    return saved


def read_annotation(project_id: str, image_id: str) -> Dict[str, Any]:
    return _v50_annotation_repository(project_id).get(image_id)


def read_annotations_many(project_id: str, image_ids) -> Dict[str, Dict[str, Any]]:
    """Bounded formal Ground Truth read through the canonical repository owner."""
    ids = list(dict.fromkeys(str(value) for value in image_ids if str(value)))
    if len(ids) > 500:
        raise ValueError("annotation batch lookup is limited to 500 image ids")
    return _v50_annotation_repository(project_id).get_many(ids)


def write_annotations_many(project_id: str, rows) -> List[Dict[str, Any]]:
    """Persist a bounded formal-GT batch and update material projections once.

    AnnotationRepository remains the only Ground Truth owner. MaterialRepository
    receives only the derived searchable projection, matching write_annotation().
    """
    incoming = [dict(row) for row in rows or []]
    if len(incoming) > 500:
        raise ValueError("annotation batch write is limited to 500 image ids")
    if not incoming:
        return []
    seen = set()
    origins = {}
    prepared = []
    batch = _v50_active_image_batch(project_id)
    for row in incoming:
        image_id = str(row.get("image_id") or "")
        if not image_id or image_id in seen:
            raise ValueError("annotation batch image ids must be present and unique")
        seen.add(image_id)
        if batch is not None:
            batch.get("deferred_annotations", {}).pop(image_id, None)
        origins[image_id] = str(row.get("annotation_origin") or "").strip() or None
        prepared.append({
            "image_id": image_id,
            "boxes": list(row.get("boxes") or []),
            "annotation_state": row.get("annotation_state"),
            "annotation_scope": row.get("annotation_scope"),
            "expected_version": row.get("expected_version"),
            "source_content_sha256": row.get("source_content_sha256"),
            "annotation_origin": origins[image_id],
            "candidate_commit": row.get("candidate_commit"),
            "candidate_proof_only": row.get("candidate_proof_only"),
            "expected_content_digest": row.get("expected_content_digest"),
            "force_version_advance": row.get("force_version_advance"),
        })
    saved_rows = _v50_annotation_repository(project_id).upsert_many(
        prepared,
        project_material=True,
        return_rows=True,
    )
    return saved_rows


class _NonClosingImageStream:
    """Let Pillow inspect a caller-owned stream without closing it."""
    def __init__(self, stream):
        self._stream = stream

    def read(self, *args, **kwargs):
        return self._stream.read(*args, **kwargs)

    def seek(self, *args, **kwargs):
        return self._stream.seek(*args, **kwargs)

    def tell(self):
        return self._stream.tell()

    def readline(self, *args, **kwargs):
        return self._stream.readline(*args, **kwargs)

    def close(self):
        return None

    def __getattr__(self, name):
        return getattr(self._stream, name)

def add_image_record(
    project_id: str, src: Any, original_name: str,
    source_type: str = "raw", dataset_id: str = "default",
    storage_source_id: str = "default_local", annotation_builder=None,
    content_sha256: Optional[str] = None,
    defer_unannotated_annotation: bool = False,
    annotation_scope=None,
    empty_annotation_state: str = "confirmed_empty",
) -> Optional[Dict[str, Any]]:
    p = project_dir(project_id)
    path_source = isinstance(src, (str, Path))
    ext = (Path(src).suffix if path_source else Path(original_name).suffix).lower()
    if ext not in IMAGE_EXTS:
        return None
    img_id = uuid.uuid4().hex[:16]
    dst_name = f"{img_id}{ext}"
    try:
        if path_source:
            info = image_info(Path(src))
        else:
            src.seek(0)
            image = Image.open(_NonClosingImageStream(src))
            try:
                info = {"width": image.width, "height": image.height}
            finally:
                image.close()
            src.seek(0)
    except Exception:
        try:
            if not path_source:
                src.seek(0)
        except Exception:
            pass
        return None
    manager = _v50_storage_manager(project_id)
    source_config = manager.sources.get(storage_source_id)
    if source_config is None:
        raise StorageError(
            code="STORAGE_SOURCE_NOT_FOUND", message="素材保存位置不存在",
            detail=f"找不到存储源 {storage_source_id}。",
            solution="请刷新保存位置后重试。",
        )
    object_key = f"uploads/{dst_name}"
    metadata = manager.upload_object(
        storage_source_id, object_key, src,
        content_type=f"image/{'jpeg' if ext in {'.jpg', '.jpeg'} else ext.lstrip('.')}",
    )
    content_hash = str(content_sha256 or metadata.sha256 or "").strip().lower()
    if not content_hash:
        if path_source:
            content_hash = sha256_file(Path(src))
        else:
            src.seek(0)
            digest = hashlib.sha256()
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                digest.update(chunk)
            content_hash = digest.hexdigest()
            src.seek(0)
    target_dataset_id = dataset_id or "default"
    record = {
        "id": img_id,
        "filename": original_name,
        "stored_name": dst_name,
        "url": material_content_url(project_id, img_id),
        "storage_source_id": source_config.id,
        "storage_type": source_config.type,
        "object_key": object_key,
        "content_sha256": content_hash,
        "etag": metadata.etag,
        "width": info["width"],
        "height": info["height"],
        "source_type": source_type,
        "dataset_id": target_dataset_id,
        "split": "unassigned",
        "processing_status": initial_processing_status(has_valid_boxes=False),
        "size_bytes": int(metadata.size_bytes),
        # Microseconds preserve same-batch insertion order for deterministic
        # duplicate-cleaning and cursor pagination.
        "created_at": datetime.now().isoformat(timespec="microseconds"),
    }
    annotation_path = p / "annotations" / f"{img_id}.json"
    batch = None
    try:
        prepared_annotation_boxes = None
        structured_import = bool(annotation_builder is not None and str(source_type).startswith("imported_"))
        if annotation_builder is not None:
            prepared_annotation_boxes = list(annotation_builder(dict(record)) or [])
            if structured_import:
                prepared_annotation_boxes = restore_box_provenance(
                    prepared_annotation_boxes, [],
                    existing_source_fallback="imported", new_source="imported",
                )
        with _v50_dataset_locks(project_id, [target_dataset_id]):
            _v50_assert_dataset_writable_locked(project_id, target_dataset_id)
            batch = _v50_active_image_batch(project_id)
            if batch:
                image_id = str(img_id)
                buffered = dict(record)
                pending_patch = batch["patches"].pop(image_id, None)
                if pending_patch:
                    buffered.update(pending_patch)
                batch["records"][image_id] = buffered
            else:
                record = material_store(project_id).upsert(record)
            if prepared_annotation_boxes is not None:
                # Structured import paths already know the final GT. Persist it once
                # before returning instead of durable unannotated -> final double writes.
                if not prepared_annotation_boxes and empty_annotation_state == "unannotated":
                    write_annotation(project_id, img_id, [], "unannotated")
                else:
                    write_annotation(
                        project_id, img_id, prepared_annotation_boxes,
                        annotation_origin="imported" if structured_import else None,
                        annotation_scope=annotation_scope,
                    )
            elif batch and defer_unannotated_annotation:
                batch["deferred_annotations"][str(img_id)] = {
                    "image_id": str(img_id),
                    "boxes": [],
                    "annotation_state": "unannotated",
                }
            elif not annotation_path.exists():
                write_annotation(project_id, img_id, [], "unannotated")
    except Exception as original_error:
        annotation_path.unlink(missing_ok=True)
        _v50_annotation_repository(project_id).remove([img_id])
        try:
            material_store(project_id).record_deferred_cleanup(record,
                owner='upload_rollback',error=redact_storage_error(original_error))
        except Exception as cleanup_error:
            original_error.add_note('延期回收记录保存失败：'+redact_storage_error(cleanup_error))
        raise
    if batch:
        return dict(batch["records"][str(img_id)])
    return record


def zip_dir(src_dir: Path, zip_path: Path):
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(src_dir))


@app.get("/", response_class=HTMLResponse)
def index():
    # 禁止浏览器缓存旧首页。版本升级后必须立即加载当前静态资源，避免“代码里有部署转换但页面看不到”。
    return HTMLResponse(
        (STATIC_DIR / "index.html").read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"},
    )


@app.get("/api/health")
def health():
    return {"ok": True, "version": APP_VERSION, "time": now_iso(), "base_dir": str(BASE_DIR), "engines": ["ultralytics", "paddle_command"], "ui": f"v{APP_VERSION}"}


from platform_core.project_management_contracts import ProjectCreate

from platform_core.project_management_contracts import ProjectUpdate


from platform_core.project_management_service import ProjectManagementDependencies, ProjectManagementService
from platform_core.project_management_api import create_project_management_router_1, create_project_management_router_2


def _project_management_service() -> ProjectManagementService:
    return ProjectManagementService(ProjectManagementDependencies(
        ALLOW_MULTIPLE_PROJECTS_FOR_TESTS=lambda: ALLOW_MULTIPLE_PROJECTS_FOR_TESTS,
        DEFAULT_PROJECT_ID=lambda: DEFAULT_PROJECT_ID,
        DEFAULT_PROJECT_NAME=lambda: DEFAULT_PROJECT_NAME,
        PROJECTS_FILE=lambda: PROJECTS_FILE,
        _prune_canonical_label_alias_conflicts=lambda *args, **kwargs: _prune_canonical_label_alias_conflicts(*args, **kwargs),
        default_label_color=lambda *args, **kwargs: default_label_color(*args, **kwargs),
        ensure_project_dirs=lambda *args, **kwargs: ensure_project_dirs(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        list_models_internal=lambda *args, **kwargs: list_models_internal(*args, **kwargs),
        material_store=lambda *args, **kwargs: material_store(*args, **kwargs),
        normalize_label=lambda *args, **kwargs: normalize_label(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        read_annotations_many=lambda *args, **kwargs: read_annotations_many(*args, **kwargs),
        read_json=lambda *args, **kwargs: read_json(*args, **kwargs),
        save_project=lambda *args, **kwargs: save_project(*args, **kwargs),
        sync_jobs_index=lambda *args, **kwargs: sync_jobs_index(*args, **kwargs),
        write_json=lambda *args, **kwargs: write_json(*args, **kwargs),
    ))


app.include_router(create_project_management_router_1(_project_management_service))


def list_projects():
    return _project_management_service().list_projects()


def update_project(project_id: str, payload: ProjectUpdate):
    return _project_management_service().update_project(project_id, payload)


def delete_project(project_id: str):
    return _project_management_service().delete_project(project_id)


def datasets_file(project_id: str) -> Path:
    return project_dir(project_id) / "datasets.json"


def ensure_default_datasets(project_id: str) -> List[Dict[str, Any]]:
    f = datasets_file(project_id)
    ds = read_json(f, [])
    if not ds:
        ds = [{"id":"default", "name":"默认数据集", "description":"", "created_at": now_iso(), "updated_at": now_iso()}]
        write_json(f, ds)
    return ds


from platform_core.material_catalog_contracts import DatasetReq


app.include_router(create_dataset_directory_router(_material_catalog_service))


def list_datasets(project_id: str):
    return _material_catalog_service().list_datasets(project_id)


def create_dataset(project_id: str, payload: DatasetReq):
    return _material_catalog_service().create_dataset(project_id, payload)


def update_dataset(project_id: str, dataset_id: str, payload: DatasetReq):
    return _material_catalog_service().update_dataset(project_id, dataset_id, payload)


_V50_DATASET_DELETE_CLAIM_FIELD = DATASET_DELETE_CLAIM_FIELD
_V50_ACTIVE_DATASET_DELETIONS_GUARD = threading.Lock()
_V50_ACTIVE_DATASET_DELETION_TOKENS: set = set()
_V50_ACTIVE_DATASET_DELETION_TARGETS: Dict[str, Tuple[str, str]] = {}
_V50_DATASET_DELETE_STATUSES = {
    "created",
    "claimed",
    "staging",
    "staged",
    "finalized",
    "metadata_removed",
    "recovering",
    "recovered",
    "deletion_finished",
    "recovery_failed",
    "manual_recovery_required",
    "rolled_back",
    "rollback_failed",
}


def _v50_dataset_deletion_root(project_id: str) -> Path:
    return project_dir(project_id) / "imports" / "dataset_deletions"


def _v50_dataset_delete_journal_path(project_id: str, token: str) -> Path:
    return _v50_dataset_deletion_root(project_id) / f"{token}.json"


def _v50_dataset_delete_staging_dir(project_id: str, token: str) -> Path:
    return _v50_dataset_deletion_root(project_id) / "staging" / token


def _v50_recovery_conflict(message: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=f"数据集删除恢复记录无效：{message}",
    )


def _v50_safe_journal_identifier(value: Any, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _v50_recovery_conflict(f"{field} 类型无效")
    normalized = str(value)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", normalized):
        raise _v50_recovery_conflict(f"{field} 格式无效")
    return normalized


def _v50_safe_stored_name(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 255:
        raise _v50_recovery_conflict("stored_name 类型或长度无效")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise _v50_recovery_conflict("stored_name 不是文件名")
    if Path(value).is_absolute() or Path(value).drive or Path(value).name != value:
        raise _v50_recovery_conflict("stored_name 不是安全的 basename")
    if any(ord(character) < 32 for character in value):
        raise _v50_recovery_conflict("stored_name 包含控制字符")
    return value


def _v50_resolve_expected_path(path: Path, root: Path, field: str) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as error:
        raise _v50_recovery_conflict(f"{field} 越出预期目录") from error
    if not relative.parts:
        raise _v50_recovery_conflict(f"{field} 不能指向目录根")
    return resolved


def _v50_read_datasets_strict(project_id: str) -> List[Dict[str, Any]]:
    path = datasets_file(project_id)
    try:
        raw = path.read_text(encoding="utf-8")
        datasets = json.loads(raw)
    except Exception as error:
        raise HTTPException(
            status_code=409,
            detail=f"数据集元数据无法确认，已保留删除恢复记录：{error}",
        ) from error
    if not isinstance(datasets, list):
        raise HTTPException(
            status_code=409,
            detail="数据集元数据格式错误，已保留删除恢复记录",
        )
    normalized = []
    seen = set()
    for index, item in enumerate(datasets):
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=409,
                detail=f"数据集元数据第 {index + 1} 项格式错误",
            )
        try:
            dataset_id = _v50_safe_journal_identifier(
                item.get("id"), f"datasets[{index}].id"
            )
        except HTTPException as error:
            raise HTTPException(
                status_code=409,
                detail=f"数据集元数据无法确认：{error.detail}",
            ) from error
        if dataset_id in seen:
            raise HTTPException(status_code=409, detail="数据集元数据包含重复 ID")
        seen.add(dataset_id)
        normalized.append(item)
    return normalized


def _v50_validate_dataset_delete_journal(
    expected_project_id: str, path: Path, journal: Any
) -> Dict[str, Any]:
    if not isinstance(journal, dict):
        raise _v50_recovery_conflict("顶层必须是对象")
    project_id = _v50_safe_journal_identifier(
        journal.get("project_id"), "project_id"
    )
    if project_id != str(expected_project_id):
        raise _v50_recovery_conflict("project_id 与项目不匹配")
    dataset_id = _v50_safe_journal_identifier(
        journal.get("dataset_id"), "dataset_id"
    )
    token = str(journal.get("token") or "")
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise _v50_recovery_conflict("token 格式无效")
    expected_journal = _v50_dataset_delete_journal_path(project_id, token)
    if path.resolve() != expected_journal.resolve() or path.stem != token:
        raise _v50_recovery_conflict("日志路径与 token 不匹配")
    _v50_resolve_expected_path(
        expected_journal,
        _v50_dataset_deletion_root(project_id),
        "journal_path",
    )
    status = journal.get("status")
    if not isinstance(status, str) or status not in _V50_DATASET_DELETE_STATUSES:
        raise _v50_recovery_conflict("status 无效")
    if not isinstance(journal.get("created_at"), str):
        raise _v50_recovery_conflict("created_at 无效")
    claimed_rows = journal.get("claimed_rows")
    positions = journal.get("claimed_positions")
    files = journal.get("files")
    if not isinstance(claimed_rows, list):
        raise _v50_recovery_conflict("claimed_rows 必须是数组")
    if not isinstance(positions, dict):
        raise _v50_recovery_conflict("claimed_positions 必须是对象")
    if not isinstance(files, list):
        raise _v50_recovery_conflict("files 必须是数组")

    expected_staging = _v50_dataset_delete_staging_dir(project_id, token)
    staging_value = journal.get("staging_dir")
    if not isinstance(staging_value, str) or not Path(staging_value).is_absolute():
        raise _v50_recovery_conflict("staging_dir 无效")
    if Path(staging_value).resolve() != expected_staging.resolve():
        raise _v50_recovery_conflict("staging_dir 与 token 不匹配")
    _v50_resolve_expected_path(
        expected_staging,
        _v50_dataset_deletion_root(project_id) / "staging",
        "staging_dir",
    )

    expected_files = {}
    seen_ids = set()
    for index, row in enumerate(claimed_rows):
        if not isinstance(row, dict):
            raise _v50_recovery_conflict(f"claimed_rows[{index}] 必须是对象")
        image_id = _v50_safe_journal_identifier(
            row.get("id"), f"claimed_rows[{index}].id"
        )
        if image_id in seen_ids:
            raise _v50_recovery_conflict("claimed_rows 包含重复 image_id")
        seen_ids.add(image_id)
        if str(row.get("dataset_id") or "default") != dataset_id:
            raise _v50_recovery_conflict("claimed row dataset_id 与日志不匹配")
        if _V50_DATASET_DELETE_CLAIM_FIELD in row:
            raise _v50_recovery_conflict("claimed row 不应包含内部 claim")
        stored_name = _v50_safe_stored_name(row.get("stored_name"))
        position = positions.get(image_id)
        if isinstance(position, bool) or not isinstance(position, int) or position < 0:
            raise _v50_recovery_conflict("claimed_positions 与 image_id 不匹配")
        row_staging = expected_staging / image_id
        upload_source = project_dir(project_id) / "uploads" / stored_name
        annotation_source = project_dir(project_id) / "annotations" / f"{image_id}.json"
        expected_files[(image_id, "image")] = (
            _v50_resolve_expected_path(
                upload_source, project_dir(project_id) / "uploads", "upload source"
            ),
            _v50_resolve_expected_path(
                row_staging / f"image{Path(stored_name).suffix}",
                expected_staging,
                "staged image",
            ),
        )
        expected_files[(image_id, "annotation")] = (
            _v50_resolve_expected_path(
                annotation_source,
                project_dir(project_id) / "annotations",
                "annotation source",
            ),
            _v50_resolve_expected_path(
                row_staging / "annotation.json",
                expected_staging,
                "staged annotation",
            ),
        )
    if set(positions) != seen_ids:
        raise _v50_recovery_conflict("claimed_positions 包含未知 image_id")

    recorded_keys = set()
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise _v50_recovery_conflict(f"files[{index}] 必须是对象")
        image_id = _v50_safe_journal_identifier(
            item.get("image_id"), f"files[{index}].image_id"
        )
        kind = item.get("kind")
        key = (image_id, kind)
        if kind not in {"image", "annotation"} or key not in expected_files:
            raise _v50_recovery_conflict(f"files[{index}] 类型或 image_id 无效")
        if key in recorded_keys:
            raise _v50_recovery_conflict("files 包含重复路径记录")
        recorded_keys.add(key)
        if not isinstance(item.get("existed"), bool):
            raise _v50_recovery_conflict(f"files[{index}].existed 无效")
        source_value = item.get("source")
        staged_value = item.get("staged")
        if (
            not isinstance(source_value, str)
            or not Path(source_value).is_absolute()
            or not isinstance(staged_value, str)
            or not Path(staged_value).is_absolute()
        ):
            raise _v50_recovery_conflict(f"files[{index}] 路径无效")
        expected_source, expected_staged = expected_files[key]
        if Path(source_value).resolve() != expected_source:
            raise _v50_recovery_conflict(f"files[{index}].source 不匹配")
        if Path(staged_value).resolve() != expected_staged:
            raise _v50_recovery_conflict(f"files[{index}].staged 不匹配")
    if recorded_keys != set(expected_files):
        raise _v50_recovery_conflict("files 未覆盖所有素材路径")
    return journal


def _v50_dataset_delete_token_active(token: str) -> bool:
    with _V50_ACTIVE_DATASET_DELETIONS_GUARD:
        return token in _V50_ACTIVE_DATASET_DELETION_TOKENS


def _v50_register_dataset_delete_token(
    token: str, project_id: str, dataset_id: str
):
    with _V50_ACTIVE_DATASET_DELETIONS_GUARD:
        _V50_ACTIVE_DATASET_DELETION_TOKENS.add(token)
        _V50_ACTIVE_DATASET_DELETION_TARGETS[token] = (
            str(project_id),
            str(dataset_id),
        )


def _v50_unregister_dataset_delete_token(token: str):
    with _V50_ACTIVE_DATASET_DELETIONS_GUARD:
        _V50_ACTIVE_DATASET_DELETION_TOKENS.discard(token)
        _V50_ACTIVE_DATASET_DELETION_TARGETS.pop(token, None)


def _v50_dataset_delete_target_active(project_id: str, dataset_id: str) -> bool:
    target = (str(project_id), str(dataset_id))
    with _V50_ACTIVE_DATASET_DELETIONS_GUARD:
        return target in _V50_ACTIVE_DATASET_DELETION_TARGETS.values()


def _v50_write_dataset_delete_journal(journal: Dict[str, Any]):
    journal["updated_at"] = now_iso()
    project_id = str(journal.get("project_id") or "")
    path = _v50_dataset_delete_journal_path(
        project_id, str(journal.get("token") or "")
    )
    _v50_validate_dataset_delete_journal(project_id, path, journal)
    atomic_write_json(path, journal)


def _v50_read_dataset_delete_journal(
    project_id: str, path: Path
) -> Dict[str, Any]:
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise HTTPException(
            status_code=409,
            detail=f"数据集删除恢复记录无法读取：{error}",
        ) from error
    return _v50_validate_dataset_delete_journal(project_id, path, journal)


def _v50_dataset_delete_journals(
    project_id: str, dataset_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    root = _v50_dataset_deletion_root(project_id)
    if not root.exists():
        return []
    journals = []
    for path in sorted(root.glob("*.json")):
        journal = _v50_read_dataset_delete_journal(project_id, path)
        if dataset_id is not None and str(journal.get("dataset_id") or "") != str(dataset_id):
            continue
        journals.append(journal)
    return journals


def _v50_dataset_delete_file_entries(
    project_id: str, journal: Dict[str, Any]
) -> List[Dict[str, Any]]:
    token = str(journal.get("token") or "")
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise _v50_recovery_conflict("token 格式无效")
    staging_dir = _v50_dataset_delete_staging_dir(project_id, token)
    recorded = {
        (str(item.get("image_id") or ""), str(item.get("kind") or "")): item
        for item in journal.get("files", [])
        if isinstance(item, dict)
    }
    entries = []
    for row in journal.get("claimed_rows", []):
        if not isinstance(row, dict):
            continue
        image_id = _v50_safe_journal_identifier(row.get("id"), "image_id")
        row_dir = staging_dir / image_id
        stored_name = _v50_safe_stored_name(row.get("stored_name"))
        pairs = [(
            "image",
            _v50_resolve_expected_path(
                project_dir(project_id) / "uploads" / stored_name,
                project_dir(project_id) / "uploads",
                "upload source",
            ),
            _v50_resolve_expected_path(
                row_dir / f"image{Path(stored_name).suffix}",
                staging_dir,
                "staged image",
            ),
        )]
        pairs.append((
            "annotation",
            _v50_resolve_expected_path(
                project_dir(project_id) / "annotations" / f"{image_id}.json",
                project_dir(project_id) / "annotations",
                "annotation source",
            ),
            _v50_resolve_expected_path(
                row_dir / "annotation.json",
                staging_dir,
                "staged annotation",
            ),
        ))
        for kind, source, staged in pairs:
            previous = recorded.get((image_id, kind), {})
            entries.append({
                "image_id": image_id,
                "kind": kind,
                "source": str(source),
                "staged": str(staged),
                "existed": bool(previous.get("existed", source.exists())),
            })
    return entries


def _v50_restore_dataset_delete_files(
    project_id: str, journal: Dict[str, Any]
):
    errors = []
    for item in _v50_dataset_delete_file_entries(project_id, journal):
        source = Path(item["source"])
        staged = Path(item["staged"])
        try:
            if item.get("existed") and staged.exists() and not source.exists():
                _v50_stage_material_file(staged, source)
            if item.get("existed") and not source.exists():
                errors.append(f"{item['image_id']}:{item['kind']} 恢复文件缺失")
        except OSError as error:
            errors.append(f"{item['image_id']}:{item['kind']} {error}")
    if errors:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "数据集删除恢复未完成，已保留恢复记录",
                "errors": errors,
            },
        )


def _v50_restore_dataset_delete_rows(
    project_id: str, journal: Dict[str, Any]
):
    token = str(journal.get("token") or "")
    originals = []
    for row in journal.get("claimed_rows", []):
        if not isinstance(row, dict):
            continue
        original = dict(row)
        original.pop(_V50_DATASET_DELETE_CLAIM_FIELD, None)
        originals.append(original)
    positions = {
        str(image_id): int(position)
        for image_id, position in (journal.get("claimed_positions") or {}).items()
    }

    def restore(rows):
        by_id = {str(row.get("id")): row for row in rows}
        restored = []
        for original in sorted(
            originals,
            key=lambda row: positions.get(str(row.get("id")), len(rows)),
        ):
            image_id = str(original.get("id"))
            current = by_id.get(image_id)
            if current is None:
                inserted = dict(original)
                position = max(0, min(positions.get(image_id, len(rows)), len(rows)))
                rows.insert(position, inserted)
                by_id[image_id] = inserted
                restored.append(image_id)
            elif current.get(_V50_DATASET_DELETE_CLAIM_FIELD) == token:
                current.pop(_V50_DATASET_DELETE_CLAIM_FIELD, None)
                restored.append(image_id)
        return restored

    return material_store(project_id).mutate(restore)




def _v50_cleanup_dataset_delete_artifacts(journal: Dict[str, Any]):
    project_id = str(journal.get("project_id") or "")
    token = str(journal.get("token") or "")
    staging_dir = _v50_dataset_delete_staging_dir(project_id, token)
    if staging_dir.exists():
        paths=list(staging_dir.rglob('*'))
        if staging_dir.is_symlink() or any(path.is_symlink() or not path.is_dir() for path in paths):
            raise _v50_recovery_conflict('STAGED_BYTES_RETAINED: staging仍有原图或证据，已保留等待独立恢复')
        for path in sorted(paths,key=lambda path:len(path.parts),reverse=True):
            path.rmdir()
        staging_dir.rmdir()
    AnnotationRepository(project_dir(project_id)).complete_delete(token)
    _v50_dataset_delete_journal_path(project_id, token).unlink(missing_ok=True)


def _v50_recover_one_dataset_deletion(
    project_id: str, journal: Dict[str, Any]
):
    token = str(journal.get("token") or "") if isinstance(journal, dict) else ""
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise _v50_recovery_conflict("token 格式无效")
    journal = _v50_validate_dataset_delete_journal(
        project_id,
        _v50_dataset_delete_journal_path(project_id, token),
        journal,
    )
    dataset_id = str(journal.get("dataset_id") or "")
    if _v50_dataset_delete_token_active(token):
        return False
    try:
        journal["status"] = "recovering"
        _v50_write_dataset_delete_journal(journal)
        datasets = _v50_read_datasets_strict(project_id)
        dataset_present = any(
            str(item.get("id") or "") == dataset_id for item in datasets
        )
        annotation_repository = AnnotationRepository(project_dir(project_id))
        if dataset_present:
            _v50_restore_dataset_delete_files(project_id, journal)
            with material_annotation_lifecycle_fence(project_dir(project_id)):
                _v50_restore_dataset_delete_rows(project_id, journal)
                annotation_repository.restore_delete(token)
            journal["status"] = "recovered"
        else:
            journal['status']='manual_recovery_required'
            journal['last_error']='DATASET_METADATA_ABSENT: 原图和GT备份已保留，需要独立恢复'
            _v50_write_dataset_delete_journal(journal)
            raise _v50_recovery_conflict(journal['last_error'])
        _v50_write_dataset_delete_journal(journal)
        _v50_cleanup_dataset_delete_artifacts(journal)
        return True
    except Exception as error:
        if journal.get('status') != 'manual_recovery_required':
            journal["status"] = "recovery_failed"
        journal["last_error"] = str(
            error.detail if isinstance(error, HTTPException) else error
        )
        try:
            _v50_write_dataset_delete_journal(journal)
        except Exception:
            pass
        if isinstance(error, HTTPException) and error.status_code == 409:
            raise
        raise HTTPException(
            status_code=409,
            detail=f"数据集删除恢复失败，已保留恢复记录：{error}",
        ) from error


def _v50_clear_orphan_dataset_delete_claims(
    project_id: str, dataset_id: str
):
    journal_root = _v50_dataset_deletion_root(project_id)
    valid_tokens = {
        path.stem
        for path in journal_root.glob("*.json")
        if re.fullmatch(r"[0-9a-f]{32}", path.stem)
    } if journal_root.exists() else set()
    with _V50_ACTIVE_DATASET_DELETIONS_GUARD:
        valid_tokens.update(_V50_ACTIVE_DATASET_DELETION_TOKENS)
    return material_store(project_id).clear_orphan_dataset_delete_claims(
        dataset_id, valid_tokens,
    )


def _v50_recover_dataset_deletions_locked(
    project_id: str, dataset_id: str
) -> List[str]:
    recovered = []
    for journal in _v50_dataset_delete_journals(project_id, dataset_id):
        token = str(journal.get("token") or "")
        if _v50_dataset_delete_token_active(token):
            continue
        if _v50_recover_one_dataset_deletion(project_id, journal):
            recovered.append(token)
    _v50_clear_orphan_dataset_delete_claims(project_id, dataset_id)
    return recovered


def _v50_recover_dataset_deletions(
    project_id: str, dataset_id: Optional[str] = None
):
    if dataset_id is not None:
        normalized_dataset_id = str(dataset_id or "default")
        with _v50_dataset_locks(project_id, [normalized_dataset_id]):
            return _v50_recover_dataset_deletions_locked(
                project_id, normalized_dataset_id
            )

    journals = _v50_dataset_delete_journals(project_id)
    dataset_ids = {
        str(journal.get("dataset_id") or "default") for journal in journals
    }
    for row in material_store(project_id).list_dataset_delete_claims():
        dataset_ids.add(str(row.get("dataset_id") or "default"))
    recovered = []
    for current_dataset_id in sorted(dataset_ids):
        with _v50_dataset_locks(project_id, [current_dataset_id]):
            recovered.extend(
                _v50_recover_dataset_deletions_locked(
                    project_id, current_dataset_id
                )
            )
    return recovered


def _v50_initialize_default_dataset_locked(
    project_id: str,
) -> List[Dict[str, Any]]:
    metadata_path = datasets_file(project_id)
    if metadata_path.exists():
        datasets = _v50_read_datasets_strict(project_id)
    else:
        datasets = []
    if not datasets:
        timestamp = now_iso()
        atomic_write_json(
            metadata_path,
            [
                {
                    "id": "default",
                    "name": "默认数据集",
                    "description": "",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
            ],
        )
        datasets = _v50_read_datasets_strict(project_id)
    return datasets


def _v50_assert_dataset_writable_locked(project_id: str, dataset_id: str):
    target_dataset_id = str(dataset_id or "default")
    _v50_recover_dataset_deletions(project_id, target_dataset_id)
    if _v50_dataset_delete_target_active(project_id, target_dataset_id):
        raise HTTPException(status_code=409, detail="数据集正在删除，不能写入素材")
    if _v50_dataset_delete_journals(project_id, target_dataset_id):
        raise HTTPException(status_code=409, detail="数据集删除尚待恢复，不能写入素材")
    if target_dataset_id == "default":
        datasets = _v50_initialize_default_dataset_locked(project_id)
    else:
        datasets = _v50_read_datasets_strict(project_id)
    if not any(
        str(item.get("id")) == target_dataset_id for item in datasets
    ):
        raise HTTPException(status_code=409, detail="目标数据集已不存在，不能写入素材")


def _v50_stage_material_file(source: Path, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)


def _require_material_delete_preview(project_id: str):
    raise HTTPException(status_code=409, detail={
        'code':'MATERIAL_DELETE_PREVIEW_REQUIRED',
        'message':'请通过统一素材治理预览精确范围并确认，旧同步删除入口已停用。',
        'preview_url':f'/api/v62/projects/{project_id}/material-batches/estimate',
        'operation':'DELETE_INDEX',
    })


from platform_core.material_governance_service import MaterialGovernanceDependencies, MaterialGovernanceService
from platform_core.material_governance_api import create_material_governance_router_1, create_material_governance_router_2, create_material_governance_router_3, create_material_governance_router_4, create_material_governance_router_5, create_material_governance_router_6


def _material_governance_service() -> MaterialGovernanceService:
    return MaterialGovernanceService(MaterialGovernanceDependencies(
        _V50DatasetSourceChanged=_V50DatasetSourceChanged,
        _require_material_delete_preview=lambda *args, **kwargs: _require_material_delete_preview(*args, **kwargs),
        _v50_assert_dataset_writable_locked=lambda *args, **kwargs: _v50_assert_dataset_writable_locked(*args, **kwargs),
        _v50_dataset_locks=lambda *args, **kwargs: _v50_dataset_locks(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        load_images=lambda *args, **kwargs: load_images(*args, **kwargs),
        material_store=lambda *args, **kwargs: material_store(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        read_annotation=lambda *args, **kwargs: read_annotation(*args, **kwargs),
    ))


app.include_router(create_material_governance_router_1(_material_governance_service))


def delete_dataset(project_id: str, dataset_id: str):
    return _material_governance_service().delete_dataset(project_id, dataset_id)


def _system_recommendation_payload(cuda: Optional[bool] = None, gpu_name: str = "训练节点未确认"):
    # Web-host resources have no authority over the Worker selected by the
    # scheduler. Expose them only for the explicitly requested local probe.
    cpu = (os.cpu_count() or 1) if cuda is not None else None
    ram_gb = None
    if cuda is not None:
        try:
            import psutil
            ram_gb = round(psutil.virtual_memory().total / 1024 / 1024 / 1024, 1)
        except Exception:
            ram_gb = 0
    gpu_name = str(gpu_name or "训练节点未确认")
    if cuda is None:
        # The Web process may be on a different host from the actual Worker.
        # Do not silently prescribe CPU training from the Web host's devices.
        rec = {"device":"auto", "model":"yolo11n.pt", "epochs":50, "imgsz":640, "batch":4,
               "reason":"当前未指定训练节点；推荐值仅为保守起点，实际设备和资源由训练节点准入检查决定。"}
    elif cuda:
        rec = {"device":"0", "model":"yolo11s.pt", "epochs":50, "imgsz":640, "batch":8, "reason":"检测到当前 Python 的 CUDA 可用，推荐使用 YOLO11s 进行首轮效果验证。"}
    elif ram_gb and ram_gb >= 24 and cpu >= 12:
        rec = {"device":"cpu", "model":"yolo11n.pt", "epochs":20, "imgsz":640, "batch":4, "reason":"当前未确认 CUDA 可用，但 CPU/内存较充足，推荐 YOLO11n + CPU 小批量训练。"}
    else:
        rec = {"device":"cpu", "model":"yolo11n.pt", "epochs":10, "imgsz":416, "batch":2, "reason":"当前未确认 CUDA 可用，推荐降低图片尺寸和 batch，先跑通流程。"}
    return {"ok": True, "cpu_count": cpu, "ram_gb": ram_gb, "cuda": cuda, "gpu": gpu_name,
            "recommendation_source": "web_runtime" if cuda is not None else "unverified_fallback",
            "worker_verified": False, "recommendation": rec}


def _worker_gpu_recommendation(runtime: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Recommend only from online training Worker + fresh, visible GPU facts."""
    workers = {
        (str(worker.get("node_id") or ""), str(worker.get("worker_id") or ""))
        for worker in runtime.get("workers", [])
        if isinstance(worker, Mapping) and worker.get("online") is True
        and "TRAINING" in (worker.get("task_kinds") or [])
    }
    visible = {
        (str(item.get("node_id") or ""), str(item.get("gpu_uuid") or ""))
        for item in runtime.get("worker_gpu_visibility", [])
        if isinstance(item, Mapping)
        and (str(item.get("node_id") or ""), str(item.get("worker_id") or "")) in workers
    }
    gpus = [
        gpu for gpu in runtime.get("gpus", [])
        if isinstance(gpu, Mapping) and gpu.get("metrics_fresh") is True
        and gpu.get("telemetry_available") is True
        and (str(gpu.get("node_id") or ""), str(gpu.get("gpu_uuid") or "")) in visible
    ]
    if not gpus:
        return None
    # Multiple eligible GPU nodes may exist: never bind a device index or a
    # specific model size to one host before scheduling has selected it.
    names = sorted({str(gpu.get("name") or gpu.get("gpu_name") or "GPU") for gpu in gpus})
    result = _system_recommendation_payload()
    result.update(
        gpu="、".join(names), recommendation_source="worker_gpu_telemetry",
        worker_verified=True, worker_gpu_count=len(gpus), online_training_workers=len(workers),
        sampled_at=runtime.get("generated_at"),
    )
    result["recommendation"]["reason"] = (
        "已核验在线训练 Worker 的近期 GPU 采样；设备仍由调度器选择，"
        "batch、显存余量和训练资格以正式任务准入为准。"
    )
    return result


from platform_core.runtime_catalog_contracts import TrainingRobustnessPolicyReq


app.include_router(create_runtime_catalog_router_2(_runtime_catalog_service))


def training_robustness_policy():
    return _runtime_catalog_service().training_robustness_policy()


def save_training_robustness_policy(payload: TrainingRobustnessPolicyReq):
    return _runtime_catalog_service().save_training_robustness_policy(payload)


def system_recommendation(probe_local_cuda: bool=False):
    return _runtime_catalog_service().system_recommendation(probe_local_cuda)


app.include_router(create_project_management_router_2(_project_management_service))


def create_project(payload: ProjectCreate):
    return _project_management_service().create_project(payload)


def read_project(project_id: str):
    return _project_management_service().read_project(project_id)


from platform_core.annotation_governance_contracts import AddLabelReq


from platform_core.annotation_governance_service import AnnotationGovernanceDependencies, AnnotationGovernanceService
from platform_core.annotation_governance_api import create_annotation_governance_router_1, create_annotation_governance_router_2, create_annotation_governance_router_3, create_annotation_governance_router_4, create_annotation_governance_router_5


def _annotation_governance_service() -> AnnotationGovernanceService:
    return AnnotationGovernanceService(AnnotationGovernanceDependencies(
        _V50_DATASET_DELETE_CLAIM_FIELD=lambda: _V50_DATASET_DELETE_CLAIM_FIELD,
        _annotation_box_source_fallback=lambda *args, **kwargs: _annotation_box_source_fallback(*args, **kwargs),
        _online_feedback_repository=lambda *args, **kwargs: _online_feedback_repository(*args, **kwargs),
        _prune_canonical_label_alias_conflicts=lambda *args, **kwargs: _prune_canonical_label_alias_conflicts(*args, **kwargs),
        _set_project_label_aliases=lambda *args, **kwargs: _set_project_label_aliases(*args, **kwargs),
        _validate_label_aliases=lambda *args, **kwargs: _validate_label_aliases(*args, **kwargs),
        default_label_color=lambda *args, **kwargs: default_label_color(*args, **kwargs),
        ensure_label=lambda *args, **kwargs: ensure_label(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        material_store=lambda *args, **kwargs: material_store(*args, **kwargs),
        normalize_label=lambda *args, **kwargs: normalize_label(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        project_label_items=lambda *args, **kwargs: project_label_items(*args, **kwargs),
        read_annotation=lambda *args, **kwargs: read_annotation(*args, **kwargs),
        save_project=lambda *args, **kwargs: save_project(*args, **kwargs),
        shared_task_artifacts=lambda *args, **kwargs: shared_task_artifacts(*args, **kwargs),
        shared_task_repository=lambda *args, **kwargs: shared_task_repository(*args, **kwargs),
        write_annotation=lambda *args, **kwargs: write_annotation(*args, **kwargs),
    ))


app.include_router(create_annotation_governance_router_1(_annotation_governance_service))


def add_label(project_id: str, payload: AddLabelReq):
    return _annotation_governance_service().add_label(project_id, payload)


def _add_label_locked(project_id: str, payload: AddLabelReq):
    return _annotation_governance_service()._add_label_locked(project_id, payload)


async def _plain_upload_manifest(files: Sequence[UploadFile]) -> List[Dict[str, Any]]:
    """Bind receipt identity to actual bytes, not only browser-supplied metadata.

    Hash in bounded chunks and restore each input stream before the existing
    image upload path. This runs only for uploads that supply a request ID.
    """
    return await asyncio.to_thread(_plain_upload_manifest_sync, files)


def _plain_upload_manifest_sync(files: Sequence[UploadFile]) -> List[Dict[str, Any]]:
    manifest = []
    for file in files:
        filename = safe_filename(file.filename or "image.jpg")
        digest = hashlib.sha256()
        byte_count = 0
        stream = file.file
        stream.seek(0)
        try:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                byte_count += len(chunk)
        finally:
            stream.seek(0)
        manifest.append({
            "name": filename,
            "size": byte_count,
            "content_type": str(file.content_type or ""),
            "sha256": digest.hexdigest(),
        })
    return manifest


def _plain_upload_replay_response(project_id: str, batch: Dict[str, Any]) -> Dict[str, Any]:
    image_ids = [str(item.get("image_id") or "") for item in (batch.get("items") or []) if str(item.get("image_id") or "")]
    indexed = {}
    materials = material_store(project_id)
    for offset in range(0, len(image_ids), 500):
        indexed.update({
            str(row.get("id")): row
            for row in materials.get_many(image_ids[offset:offset + 500])
        })
    uploaded = [dict(indexed[image_id]) for image_id in image_ids if image_id in indexed]
    failed = [dict(item) for item in (batch.get("upload_failed") or [])]
    return {
        "batch_id": str(batch.get("id") or ""),
        "uploaded": uploaded, "failed": failed,
        "uploaded_image_ids": [str(item.get("id")) for item in uploaded],
        "uploaded_count": len(uploaded), "failed_count": len(failed),
        "elapsed_seconds": float(batch.get("upload_elapsed_seconds") or 0.0),
        "total": int(batch.get("upload_material_total") or material_store(project_id).count()),
        "replayed": True,
    }


def _plain_upload_recover_receipt(project_id: str, store: UploadBatchStore, receipt: Dict[str, Any]):
    """Reconcile an interrupted request against canonical Material/Annotation truth.

    Caller must hold the cross-process upload-request claim. We never retry
    uploading unknown bytes or assert success from an uncommitted receipt.
    """
    batch_id = str(receipt["id"])
    prepared = receipt.get("upload_prepared_image_ids")
    if isinstance(prepared, list):
        ids = [str(value) for value in prepared]
        if len(ids) == len(set(ids)) and all(ids):
            materials = material_store(project_id)
            rows = {}
            annotations = {}
            repository = _v50_annotation_repository(project_id)
            for offset in range(0, len(ids), 500):
                chunk = ids[offset:offset + 500]
                rows.update({
                    str(row.get("id")): row for row in materials.get_many(chunk)
                })
                # AnnotationRepository intentionally limits get_many to 500.
                annotations.update(repository.get_many(chunk))
            if (
                len(rows) == len(ids)
                and all(
                    str(rows[image_id].get("dataset_id") or "default")
                        == str(receipt.get("upload_dataset_id") or "default")
                    and str(rows[image_id].get("storage_source_id") or "default_local")
                        == str(receipt.get("upload_storage_source_id") or "default_local")
                    and image_id in annotations
                    and str((annotations[image_id] or {}).get("annotation_state") or "")
                        == "unannotated"
                    # get_many returns synthetic legacy version=0 for missing
                    # rows; a canonical committed GT must have version>=1.
                    and int((annotations[image_id] or {}).get("version") or 0) >= 1
                    for image_id in ids
                )
            ):
                completed = store.complete_upload_request(
                    batch_id, ids, failed=receipt.get("upload_failed") or [],
                    finished_at=now_iso(), elapsed_seconds=0.0,
                    material_total=materials.count(),
                )
                return _plain_upload_replay_response(project_id, completed)

    # A PROCESSING receipt without a prepared intent cannot have reached the
    # Material commit; otherwise only a full ID+GT match proves success.
    # Any partial/missing truth stays visible as failed, never auto reuploads.
    error = "上传进程已中断，未能确认全部素材正式入库；请核查批次后以新的请求 ID 重传未入库图片"
    store.fail_upload_request(batch_id, error=error, failed_at=now_iso())
    raise PlatformError(
        "UPLOAD_REQUEST_RECOVERY_UNCONFIRMED", "上传恢复状态无法确认",
        error, "请先核对该批正式素材，再使用新的请求 ID 重传未入库文件", 409,
    )


def _plain_upload_source_generation(storage_source_id: str) -> tuple[Any, ...]:
    """Capture the canonical source identity under the source lifecycle fence.

    Network uploads are intentionally outside the fence. Only source identity
    reads and the final Material commit are serialized with PATCH/DELETE.
    """
    with _storage_source_fence():
        source = storage_source_repository().get(storage_source_id)
        if source is None or not source.enabled:
            raise PlatformError(
                "UPLOAD_STORAGE_SOURCE_UNAVAILABLE", "素材存储源不可用",
                "素材存储源不存在或已停用", "请刷新保存位置后重试", 409,
            )
        return _storage_source_runtime_generation(source)


def _plain_upload_assert_source_generation(
    storage_source_id: str, expected_generation: tuple[Any, ...],
) -> None:
    """Called WITH the lifecycle fence held immediately before DB commit."""
    source = storage_source_repository().get(storage_source_id)
    if (
        source is None or not source.enabled
        or _storage_source_runtime_generation(source) != expected_generation
    ):
        raise PlatformError(
            "UPLOAD_STORAGE_SOURCE_CHANGED", "存储源配置已变化",
            "上传期间存储源配置或凭据发生变化，未将本批素材写入正式索引",
            "请刷新存储源配置，核对本批素材后重试", 409,
        )


from platform_core.material_ingestion_service import MaterialIngestionDependencies, MaterialIngestionService
from platform_core.material_ingestion_api import create_material_ingestion_router_1, create_material_ingestion_router_2, create_material_ingestion_router_3, create_material_ingestion_router_4, create_material_ingestion_router_5


def _material_ingestion_service() -> MaterialIngestionService:
    return MaterialIngestionService(MaterialIngestionDependencies(
        V19_ZIP_PHASE_LABELS=lambda: V19_ZIP_PHASE_LABELS,
        V19_ZIP_PHASE_WINDOWS=lambda: V19_ZIP_PHASE_WINDOWS,
        V36_ANNOTATED_IMPORT_BLOCKED_DETAIL=lambda: V36_ANNOTATED_IMPORT_BLOCKED_DETAIL,
        _authorize_business_file_project=lambda *args, **kwargs: _authorize_business_file_project(*args, **kwargs),
        _plain_upload_images_claimed=lambda *args, **kwargs: _plain_upload_images_claimed(*args, **kwargs),
        _v19_cleanup_uncommitted_job=lambda *args, **kwargs: _v19_cleanup_uncommitted_job(*args, **kwargs),
        _v19_fifo_import_jobs=lambda *args, **kwargs: _v19_fifo_import_jobs(*args, **kwargs),
        _v19_fifo_queue_position=lambda *args, **kwargs: _v19_fifo_queue_position(*args, **kwargs),
        _v19_finish_cancel=lambda *args, **kwargs: _v19_finish_cancel(*args, **kwargs),
        _v19_job_record_token=lambda *args, **kwargs: _v19_job_record_token(*args, **kwargs),
        _v19_multipart_repository=lambda *args, **kwargs: _v19_multipart_repository(*args, **kwargs),
        _v19_prepare_scan=lambda *args, **kwargs: _v19_prepare_scan(*args, **kwargs),
        _v19_recover_multipart_finalize=lambda *args, **kwargs: _v19_recover_multipart_finalize(*args, **kwargs),
        _v19_schedule_multipart_finalize=lambda *args, **kwargs: _v19_schedule_multipart_finalize(*args, **kwargs),
        _v19_stop_fence=lambda *args, **kwargs: _v19_stop_fence(*args, **kwargs),
        _v19_store_folder_scan=lambda *args, **kwargs: _v19_store_folder_scan(*args, **kwargs),
        _v19_write_job_locked=lambda *args, **kwargs: _v19_write_job_locked(*args, **kwargs),
        _v33_get_task=lambda *args, **kwargs: _v33_get_task(*args, **kwargs),
        _v36_detect_source_annotation_formats=lambda *args, **kwargs: _v36_detect_source_annotation_formats(*args, **kwargs),
        _v36_is_url=lambda *args, **kwargs: _v36_is_url(*args, **kwargs),
        _v36_load_source_jobs=lambda *args, **kwargs: _v36_load_source_jobs(*args, **kwargs),
        _v36_normalize_source=lambda *args, **kwargs: _v36_normalize_source(*args, **kwargs),
        _v36_run_source_import=lambda *args, **kwargs: _v36_run_source_import(*args, **kwargs),
        _v36_scan_local_root=lambda *args, **kwargs: _v36_scan_local_root(*args, **kwargs),
        _v36_scan_url=lambda *args, **kwargs: _v36_scan_url(*args, **kwargs),
        _v36_write_source_job=lambda *args, **kwargs: _v36_write_source_job(*args, **kwargs),
        _v47_remove_prepared_clean_task_record=lambda *args, **kwargs: _v47_remove_prepared_clean_task_record(*args, **kwargs),
        _v47_reset_failed_clean_task_record=lambda *args, **kwargs: _v47_reset_failed_clean_task_record(*args, **kwargs),
        _v47_restore_clean_task_record=lambda *args, **kwargs: _v47_restore_clean_task_record(*args, **kwargs),
        _v55_read_upload_batch=lambda *args, **kwargs: _v55_read_upload_batch(*args, **kwargs),
        _v62_prepare_clean_compat=lambda *args, **kwargs: _v62_prepare_clean_compat(*args, **kwargs),
        _v62_publish_clean_compat=lambda *args, **kwargs: _v62_publish_clean_compat(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        list_algorithms_internal=lambda *args, **kwargs: list_algorithms_internal(*args, **kwargs),
        material_store=lambda *args, **kwargs: material_store(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        project_label_items=lambda *args, **kwargs: project_label_items(*args, **kwargs),
        read_annotations_many=lambda *args, **kwargs: read_annotations_many(*args, **kwargs),
        read_json=lambda *args, **kwargs: read_json(*args, **kwargs),
        remember_project_label_aliases=lambda *args, **kwargs: remember_project_label_aliases(*args, **kwargs),
        safe_filename=lambda *args, **kwargs: safe_filename(*args, **kwargs),
        upload_batch_store=lambda *args, **kwargs: upload_batch_store(*args, **kwargs),
        v19_import_jobs_dir=lambda *args, **kwargs: v19_import_jobs_dir(*args, **kwargs),
        v19_import_worker=lambda *args, **kwargs: v19_import_worker(*args, **kwargs),
        v19_job_dir=lambda *args, **kwargs: v19_job_dir(*args, **kwargs),
        v19_job_file=lambda *args, **kwargs: v19_job_file(*args, **kwargs),
        v19_normalize_zip_path=lambda *args, **kwargs: v19_normalize_zip_path(*args, **kwargs),
        v19_read_class_samples=lambda *args, **kwargs: v19_read_class_samples(*args, **kwargs),
        v19_read_import_report=lambda *args, **kwargs: v19_read_import_report(*args, **kwargs),
        v19_read_job=lambda *args, **kwargs: v19_read_job(*args, **kwargs),
        v19_read_scan_images=lambda *args, **kwargs: v19_read_scan_images(*args, **kwargs),
        v19_scan_zip=lambda *args, **kwargs: v19_scan_zip(*args, **kwargs),
        v19_update_job=lambda *args, **kwargs: v19_update_job(*args, **kwargs),
        v19_write_class_samples=lambda *args, **kwargs: v19_write_class_samples(*args, **kwargs),
        v19_write_job=lambda *args, **kwargs: v19_write_job(*args, **kwargs),
        v19_write_scan_images=lambda *args, **kwargs: v19_write_scan_images(*args, **kwargs),
    ))


app.include_router(create_material_ingestion_router_1(_material_ingestion_service))


async def upload_images(project_id: str, files: List[UploadFile]=File(...), dataset_id: str=Form('default'), storage_source_id: str=Form('default_local'), upload_request_id: Optional[str]=Form(None), mining_algorithm_id: str=Form(''), mining_version_id: str=Form('')):
    return await _material_ingestion_service().upload_images(project_id, files, dataset_id, storage_source_id, upload_request_id, mining_algorithm_id, mining_version_id)



def _plain_upload_mining_outcome(
    response: Dict[str, Any], project_id: str,
    algorithm_id: str, version_id: str,
) -> Dict[str, Any]:
    """Upload truth is committed independently of the optional mining job."""
    if not algorithm_id or not version_id:
        return response
    ids = [str(value) for value in response.get("uploaded_image_ids") or [] if str(value)]
    if not ids:
        return {**response, "mining_status": "skipped_no_images"}
    try:
        task = _enqueue_hard_sample_mining(
            project_id, algorithm_id, version_id, ids,
            source="upload", request_key=str(response.get("batch_id") or ""),
        )
        return {
            **response,
            "mining_status": str(task.get("status") or "QUEUED").lower(),
            "mining_task_id": str(task["id"]),
        }
    except HTTPException as error:
        return {**response, "mining_status": "not_queued",
                "mining_error": str(error.detail)}
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Optional hard-sample mining admission failed after image upload commit"
        )
        return {
            **response, "mining_status": "not_queued",
            "mining_error": "图片已入库，挖掘任务未成功排队；可从独立评测重新创建",
        }


async def _plain_upload_images_claimed(
    project_id: str, files: List[UploadFile] = File(...),
    dataset_id: str = Form("default"), storage_source_id: str = Form("default_local"),
    upload_request_id: Optional[str] = Form(None),
    mining_algorithm_id: str = "", mining_version_id: str = "",
):
    get_project(project_id)
    if bool(mining_algorithm_id) != bool(mining_version_id):
        raise HTTPException(status_code=422, detail="上传困难样本挖掘必须同时指定算法与版本")
    store = upload_batch_store(project_id)
    request_id = str(upload_request_id or "").strip()
    batch_id = request_id or uuid.uuid4().hex[:12]
    receipt_created = False
    if request_id:
        try:
            receipt, receipt_created = store.begin_upload_request(
                request_id, created_at=now_iso(), manifest=await _plain_upload_manifest(files),
                dataset_id=dataset_id, storage_source_id=storage_source_id,
            )
        except ValueError as error:
            raise PlatformError(
                "UPLOAD_REQUEST_MANIFEST_MISMATCH", "上传请求文件身份不一致",
                str(error),
                "本次文件内容与待确认上传请求不一致；请重新选择文件发起新批次",
                409,
            ) from error
        if not receipt_created:
            request_status = str(receipt.get("upload_request_status") or "").upper()
            if request_status == "SUCCEEDED":
                return await asyncio.to_thread(
                    lambda: _plain_upload_mining_outcome(
                        _plain_upload_replay_response(project_id, receipt),
                        project_id, mining_algorithm_id, mining_version_id,
                    ),
                )
            if request_status == "PROCESSING":
                return await asyncio.to_thread(
                    _plain_upload_recover_receipt, project_id, store, receipt,
                )
            raise PlatformError(
                "UPLOAD_REQUEST_FAILED", "该上传批次此前失败",
                str(receipt.get("upload_request_error") or "该上传批次此前失败，请重新选择失败素材"),
                "请核对上传批次状态后处理失败文件", 409,
            )

    # Admission is taken only for new requests; replay never needs to touch
    # possibly retired source credentials.
    try:
        source_generation = _plain_upload_source_generation(storage_source_id)
    except PlatformError as error:
        if receipt_created:
            store.fail_upload_request(batch_id, error=str(error.message), failed_at=now_iso())
        raise
    # UploadFile async methods wrap synchronous file I/O; image decoding,
    # remote storage and SQLite commits must not run on the ASGI event loop.
    # The complete batch stays on one worker thread for thread-local fencing.
    return await asyncio.to_thread(
        _plain_upload_commit_sync,
        project_id, files, dataset_id, storage_source_id, batch_id,
        receipt_created, store, source_generation,
        mining_algorithm_id, mining_version_id,
    )


def _plain_upload_commit_sync(
    project_id: str, files: List[UploadFile], dataset_id: str,
    storage_source_id: str, batch_id: str, receipt_created: bool,
    store: UploadBatchStore, source_generation: tuple[Any, ...],
    mining_algorithm_id: str, mining_version_id: str,
) -> Dict[str, Any]:
    uploaded, failed = [], []
    started = time.time()
    material_commit_started = False
    _v50_begin_image_batch(project_id)
    try:
        for file in files:
            filename = safe_filename(file.filename or "image.jpg")
            ext = Path(filename).suffix.lower()
            if ext not in IMAGE_EXTS:
                failed.append({"name": filename, "reason": "不支持的图片格式"})
                continue
            try:
                stream = file.file
                stream.seek(0)
                stream.seek(0, os.SEEK_END)
                size_bytes = stream.tell()
                stream.seek(0)
                if size_bytes <= 0:
                    failed.append({"name": filename, "reason": "文件为空"})
                    continue
                record = add_image_record(
                    project_id, stream, filename, "raw", dataset_id, storage_source_id,
                    defer_unannotated_annotation=True,
                )
                if record:
                    uploaded.append(record)
                else:
                    failed.append({"name": filename, "reason": "图片损坏或无法识别"})
            except StorageError as error:
                failed.append({"name": filename, "reason": f"{error.message}：{error.detail}"})
            except Exception as error:
                failed.append({"name": filename, "reason": str(error)})
        if receipt_created:
            # This must be durable BEFORE Material/Annotation commit starts.
            store.prepare_upload_request(
                batch_id, [str(item.get("id")) for item in uploaded],
                failed=failed, prepared_at=now_iso(),
            )
        # The identity check and canonical Material+GT commit MUST be one
        # fenced unit; otherwise PATCH/DELETE may race between the two.
        # No await and no remote upload occur while this fence is held.
        with _storage_source_fence():
            _plain_upload_assert_source_generation(storage_source_id, source_generation)
            material_commit_started = True
            committed = _v50_end_image_batch(save=True)
        if committed:
            committed_by_id = {str(item.get("id")): item for item in committed}
            uploaded = [dict(committed_by_id.get(str(item.get("id"))) or item) for item in uploaded]
        elapsed_seconds = round(max(0.0, time.time() - started), 2)
        material_total = material_store(project_id).count()
        image_ids = [str(item.get("id")) for item in uploaded]
        if receipt_created:
            store.complete_upload_request(
                batch_id, image_ids, failed=failed, finished_at=now_iso(),
                elapsed_seconds=elapsed_seconds, material_total=material_total,
            )
        else:
            store.create(batch_id, image_ids, now_iso())
    except Exception as error:
        rollback_error = None
        if _v50_active_image_batch(project_id):
            try:
                _v50_end_image_batch(save=False)
            except Exception as cleanup_error:
                rollback_error = cleanup_error
        if receipt_created and not material_commit_started:
            try:
                store.fail_upload_request(batch_id, error=str(rollback_error or error), failed_at=now_iso())
            except Exception:
                pass
        if rollback_error is not None:
            raise rollback_error from error
        raise

    result = {
        "batch_id": batch_id, "uploaded": uploaded, "failed": failed,
        "uploaded_image_ids": [str(item.get("id")) for item in uploaded],
        "uploaded_count": len(uploaded), "failed_count": len(failed),
        "elapsed_seconds": elapsed_seconds, "total": material_total, "replayed": False,
    }
    return _plain_upload_mining_outcome(
        result, project_id, mining_algorithm_id, mining_version_id,
    )


_ANNOTATION_INDEX_LOCK = threading.Lock()
_ANNOTATION_INDEX_RUNNING: set = set()
_ANNOTATION_INDEX_STATUS: Dict[str, Dict[str, Any]] = {}
_ANNOTATION_INDEX_BATCH_SIZE = 500

def _v52_annotation_index_worker(project_id: str):
    try:
        images = load_images(project_id)
        pending = [x for x in images if not x.get("annotation_summary_at")]
        total = len(pending)
        started_at = now_iso()
        _ANNOTATION_INDEX_STATUS[project_id] = {"running": True, "total": total, "processed": 0, "started_at": started_at}
        if not total:
            return
        annotations = _v50_annotation_repository(project_id)
        materials = material_store(project_id)
        for offset in range(0, total, _ANNOTATION_INDEX_BATCH_SIZE):
            batch = pending[offset:offset + _ANNOTATION_INDEX_BATCH_SIZE]
            image_ids = [str(img.get("id")) for img in batch]
            annotation_rows = annotations.get_many(image_ids)
            patches = {}
            for img, image_id in zip(batch, image_ids):
                anns = annotation_rows.get(image_id) or {
                    "annotation_state": "unannotated", "boxes": [],
                }
                boxes = anns.get("boxes", []) if isinstance(anns, dict) else []
                summary = _annotation_summary_for_material_index(
                    boxes, anns.get('annotation_state'), img,
                )
                patch = {
                    **summary,
                    "annotation_version": int(anns.get("version") or 0),
                    "annotation_hash": str(anns.get("content_digest") or ""),
                    "annotation_scope": list(anns.get("annotation_scope") or []),
                    "annotation_summary_at": anns.get("updated_at") or now_iso(),
                }
                if boxes:
                    patch["processing_status"] = "processed"
                if patch["annotation_version"] > 0 and patch["annotation_hash"]:
                    patches[image_id] = patch
            materials.patch_annotation_projections(patches)
            processed = min(total, offset + len(batch))
            _ANNOTATION_INDEX_STATUS[project_id] = {
                "running": True,
                "total": total,
                "processed": processed,
                "started_at": started_at,
                "updated_at": now_iso(),
            }
        _ANNOTATION_INDEX_STATUS[project_id] = {"running": False, "total": total, "processed": total, "started_at": started_at, "finished_at": now_iso()}
    except Exception as e:
        _ANNOTATION_INDEX_STATUS[project_id] = {"running": False, "error": str(e), "finished_at": now_iso()}
    finally:
        with _ANNOTATION_INDEX_LOCK:
            _ANNOTATION_INDEX_RUNNING.discard(project_id)

def _v52_schedule_annotation_index(project_id: str, images: Optional[List[Dict[str, Any]]] = None):
    rows = images if images is not None else load_images(project_id)
    pending = sum(1 for x in rows if not x.get("annotation_summary_at"))
    if not pending:
        _ANNOTATION_INDEX_STATUS[project_id] = {"running": False, "total": 0, "processed": 0}
        return
    with _ANNOTATION_INDEX_LOCK:
        if project_id in _ANNOTATION_INDEX_RUNNING:
            return
        _ANNOTATION_INDEX_RUNNING.add(project_id)
    _ANNOTATION_INDEX_STATUS[project_id] = {"running": True, "total": pending, "processed": 0, "queued_at": now_iso()}
    threading.Thread(target=_v52_annotation_index_worker, args=(project_id,), daemon=True).start()

app.include_router(create_legacy_material_reader_router(_material_catalog_service))


def list_images(project_id: str, dataset_id: Optional[str]=None):
    return _material_catalog_service().list_images(project_id, dataset_id)

@app.get('/api/v52/projects/{project_id}/annotation-index/status')
def v52_annotation_index_status(project_id: str):
    get_project(project_id)
    # One bounded aggregate replaces a full JSON hydration of every material:
    # the endpoint only reports pending/total counts.
    pending, total_images = material_store(project_id).annotation_index_counts()
    status = dict(_ANNOTATION_INDEX_STATUS.get(project_id) or {})
    status.setdefault('running', project_id in _ANNOTATION_INDEX_RUNNING)
    status['pending'] = pending
    status['total_images'] = total_images
    return {'ok': True, **status}


app.include_router(create_material_governance_router_2(_material_governance_service))


def delete_image(project_id: str, image_id: str, delete_source: Optional[bool]=None, confirmation: str=''):
    return _material_governance_service().delete_image(project_id, image_id, delete_source, confirmation)




from platform_core.material_governance_contracts import V46BatchDeleteImagesReq


def v46_batch_delete_images(project_id: str, payload: V46BatchDeleteImagesReq):
    return _material_governance_service().v46_batch_delete_images(project_id, payload)


LEGACY_ANNOTATED_IMPORT_BLOCKED_DETAIL = (
    "旧版带标注导入接口已关闭；请使用“上传并检查标注”统一入口，"
    "先确认外部标签到平台标签的映射后再正式入库"
)


def _reject_legacy_annotated_import(project_id: str) -> None:
    get_project(project_id)
    raise HTTPException(status_code=409, detail=LEGACY_ANNOTATED_IMPORT_BLOCKED_DETAIL)


@app.post("/api/projects/{project_id}/import/yolo_zip")
async def import_yolo_zip(project_id: str, file: UploadFile = File(...), dataset_id: str = Form("default")):
    _reject_legacy_annotated_import(project_id)
    project = get_project(project_id)
    p = project_dir(project_id)
    name = safe_filename(file.filename or "dataset.zip")
    if Path(name).suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="请上传 zip 压缩包")
    import_id = uuid.uuid4().hex[:10]
    temp_dir = p / "imports" / f"yolo_{import_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = p / "imports" / f"{import_id}.zip"
    zip_path.write_bytes(await file.read())
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_dir)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"zip 解压失败：{e}")

    yaml_files = list(temp_dir.rglob("data.yaml")) + list(temp_dir.rglob("*.yaml")) + list(temp_dir.rglob("*.yml"))
    imported_names = []
    for yf in yaml_files:
        imported_names = read_yaml_names(yf)
        if imported_names:
            break
    if not imported_names:
        imported_names = project.get("labels", [])

    # 先把导入数据的标签补充到项目中，保证类目名称不丢失
    for label in imported_names:
        if label:
            ensure_label(project, label)
    project = get_project(project_id)

    all_label_files = [x for x in temp_dir.rglob("*.txt") if x.name.lower() not in {"classes.txt", "obj.names"}]
    label_by_stem: Dict[str, List[Path]] = {}
    for lf in all_label_files:
        label_by_stem.setdefault(lf.stem, []).append(lf)

    image_files = [x for x in temp_dir.rglob("*") if x.is_file() and x.suffix.lower() in IMAGE_EXTS]
    imported = []
    annotated = 0
    skipped_labels = 0
    for img_path in image_files:
        record = add_image_record(project_id, img_path, img_path.name, "imported_yolo", dataset_id)
        if not record:
            continue
        label_file = None
        candidates = label_by_stem.get(img_path.stem, [])
        if candidates:
            # 优先选路径中包含 labels 的文件
            label_file = next((x for x in candidates if "labels" in [p.lower() for p in x.parts]), candidates[0])
        boxes = []
        if label_file and label_file.exists():
            lines = label_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line in lines:
                box = yolo_line_to_box(line, record["width"], record["height"])
                if not box:
                    continue
                old_cls = box["class_id"]
                if old_cls < len(imported_names):
                    label = normalize_label(imported_names[old_cls])
                    new_cls = get_label_id(project, label)
                elif old_cls < len(project.get("labels", [])):
                    new_cls = old_cls
                else:
                    skipped_labels += 1
                    continue
                box["class_id"] = new_cls
                box["label"] = get_project(project_id)["labels"][new_cls]
                box["id"] = uuid.uuid4().hex[:10]
                boxes.append(box)
        write_annotation(project_id, record["id"], boxes)
        if boxes:
            annotated += 1
        imported.append(record)

    shutil.rmtree(temp_dir, ignore_errors=True)
    return {
        "ok": True,
        "imported_images": len(imported),
        "annotated_images": annotated,
        "labels": get_project(project_id)["labels"],
        "skipped_labels": skipped_labels,
        "message": "已导入 YOLO 数据集。系统已把 YOLO txt 转成平台内部标注，可继续编辑。",
    }


@app.post("/api/projects/{project_id}/import/labels")
async def import_label_files(project_id: str, files: List[UploadFile] = File(...)):
    _reject_legacy_annotated_import(project_id)
    project = get_project(project_id)
    p = project_dir(project_id)
    images = load_images(project_id)
    by_stem = {Path(img["filename"]).stem: img for img in images}
    by_stored_stem = {Path(img["stored_name"]).stem: img for img in images}
    matched = 0
    boxes_count = 0
    temp_dir = p / "imports" / f"labels_{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    label_paths: List[Path] = []
    for f in files:
        fname = safe_filename(f.filename or "label.txt")
        ext = Path(fname).suffix.lower()
        raw = await f.read()
        if ext == ".zip":
            zp = temp_dir / fname
            zp.write_bytes(raw)
            try:
                with zipfile.ZipFile(zp, "r") as zf:
                    zf.extractall(temp_dir)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"标签 zip 解压失败：{e}")
        elif ext == ".txt":
            lp = temp_dir / fname
            lp.write_bytes(raw)
            label_paths.append(lp)
    label_paths.extend([x for x in temp_dir.rglob("*.txt") if x.name.lower() not in {"classes.txt", "obj.names"}])
    seen = set()
    unique_paths = []
    for lp in label_paths:
        if lp not in seen:
            unique_paths.append(lp); seen.add(lp)
    for lp in unique_paths:
        img = by_stem.get(lp.stem) or by_stored_stem.get(lp.stem)
        if not img:
            continue
        boxes = []
        for line in lp.read_text(encoding="utf-8", errors="ignore").splitlines():
            box = yolo_line_to_box(line, img["width"], img["height"])
            if not box:
                continue
            if box["class_id"] >= len(project["labels"]):
                continue
            box["id"] = uuid.uuid4().hex[:10]
            box["label"] = project["labels"][box["class_id"]]
            boxes.append(box)
        write_annotation(project_id, img["id"], boxes)
        matched += 1
        boxes_count += len(boxes)
    shutil.rmtree(temp_dir, ignore_errors=True)
    return {"ok": True, "matched_images": matched, "boxes": boxes_count}




# -----------------------------
# COCO / VOC annotated dataset import
# -----------------------------
@app.post("/api/projects/{project_id}/import/coco_zip")
async def import_coco_zip(project_id: str, file: UploadFile = File(...), dataset_id: str = Form("default")):
    _reject_legacy_annotated_import(project_id)
    project = get_project(project_id)
    p = project_dir(project_id)
    name = safe_filename(file.filename or "coco_dataset.zip")
    if Path(name).suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="请上传 COCO 数据集 zip")
    import_id = uuid.uuid4().hex[:10]
    temp_dir = p / "imports" / f"coco_{import_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = p / "imports" / f"{import_id}.zip"
    zip_path.write_bytes(await file.read())
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_dir)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"zip 解压失败：{e}")
    json_files = [x for x in temp_dir.rglob("*.json") if x.is_file()]
    if not json_files:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="未找到 COCO json 标注文件")
    ann_json = next((x for x in json_files if "train" in x.name.lower() or "instance" in x.name.lower()), json_files[0])
    try:
        coco = json.loads(ann_json.read_text(encoding="utf-8"))
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"COCO json 读取失败：{e}")
    cats = sorted(coco.get("categories", []), key=lambda c: int(c.get("id", 0)))
    cat_to_label = {}
    for c in cats:
        label = normalize_label(c.get("name") or f"class_{c.get('id')}")
        ensure_label(project, label)
        cat_to_label[int(c.get("id"))] = label
    project = get_project(project_id)
    cat_to_class = {cid: get_label_id(project, label) for cid, label in cat_to_label.items()}
    images_payload = coco.get("images", [])
    anns_by_img: Dict[int, List[Dict[str, Any]]] = {}
    for ann in coco.get("annotations", []):
        try:
            anns_by_img.setdefault(int(ann.get("image_id")), []).append(ann)
        except Exception:
            pass
    # Build quick image lookup by relative path and basename
    image_files = [x for x in temp_dir.rglob("*") if x.is_file() and x.suffix.lower() in IMAGE_EXTS]
    by_rel = {str(x.relative_to(temp_dir)).replace("\\", "/"): x for x in image_files}
    by_name: Dict[str, Path] = {}
    for x in image_files:
        by_name.setdefault(x.name, x)
    imported = []
    annotated = 0
    boxes_total = 0
    for im in images_payload:
        file_name = str(im.get("file_name") or "").replace("\\", "/")
        src = by_rel.get(file_name) or by_name.get(Path(file_name).name)
        if not src or not src.exists():
            continue
        record = add_image_record(project_id, src, Path(file_name).name, "imported_coco")
        if not record:
            continue
        boxes = []
        for ann in anns_by_img.get(int(im.get("id")), []):
            cid = int(ann.get("category_id", -1))
            if cid not in cat_to_class:
                continue
            bbox = ann.get("bbox") or []
            if len(bbox) < 4:
                continue
            x, y, w, h = [float(v) for v in bbox[:4]]
            if w <= 1 or h <= 1:
                continue
            class_id = cat_to_class[cid]
            boxes.append({
                "id": uuid.uuid4().hex[:10],
                "class_id": class_id,
                "label": get_project(project_id)["labels"][class_id],
                "x1": round(max(0, x), 2),
                "y1": round(max(0, y), 2),
                "x2": round(min(record["width"], x + w), 2),
                "y2": round(min(record["height"], y + h), 2),
            })
        write_annotation(project_id, record["id"], boxes)
        imported.append(record)
        if boxes:
            annotated += 1
            boxes_total += len(boxes)
    shutil.rmtree(temp_dir, ignore_errors=True)
    return {"ok": True, "imported_images": len(imported), "annotated_images": annotated, "boxes": boxes_total, "labels": get_project(project_id).get("labels", []), "message": "已导入 COCO 数据集并转换为平台内部标注。"}


@app.post("/api/projects/{project_id}/import/voc_zip")
async def import_voc_zip(project_id: str, file: UploadFile = File(...), dataset_id: str = Form("default")):
    _reject_legacy_annotated_import(project_id)
    import xml.etree.ElementTree as ET
    project = get_project(project_id)
    p = project_dir(project_id)
    name = safe_filename(file.filename or "voc_dataset.zip")
    if Path(name).suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="请上传 VOC 数据集 zip")
    import_id = uuid.uuid4().hex[:10]
    temp_dir = p / "imports" / f"voc_{import_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = p / "imports" / f"{import_id}.zip"
    zip_path.write_bytes(await file.read())
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_dir)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"zip 解压失败：{e}")
    image_files = [x for x in temp_dir.rglob("*") if x.is_file() and x.suffix.lower() in IMAGE_EXTS]
    by_name = {x.name: x for x in image_files}
    by_stem = {x.stem: x for x in image_files}
    imported = []
    annotated = 0
    boxes_total = 0
    for xp in temp_dir.rglob("*.xml"):
        try:
            root = ET.parse(xp).getroot()
        except Exception:
            continue
        filename = (root.findtext("filename") or "").strip()
        src = by_name.get(filename) or by_stem.get(xp.stem)
        if not src:
            continue
        record = add_image_record(project_id, src, src.name, "imported_voc")
        if not record:
            continue
        boxes = []
        for obj in root.findall("object"):
            label = normalize_label(obj.findtext("name") or "object")
            if not label:
                continue
            class_id = ensure_label(project, label)
            project = get_project(project_id)
            bb = obj.find("bndbox")
            if bb is None:
                continue
            try:
                x1 = float(bb.findtext("xmin")); y1 = float(bb.findtext("ymin")); x2 = float(bb.findtext("xmax")); y2 = float(bb.findtext("ymax"))
            except Exception:
                continue
            if x2 - x1 < 1 or y2 - y1 < 1:
                continue
            boxes.append({"id": uuid.uuid4().hex[:10], "class_id": class_id, "label": project["labels"][class_id], "x1": round(max(0,x1),2), "y1": round(max(0,y1),2), "x2": round(min(record["width"],x2),2), "y2": round(min(record["height"],y2),2)})
        write_annotation(project_id, record["id"], boxes)
        imported.append(record)
        if boxes:
            annotated += 1
            boxes_total += len(boxes)
    shutil.rmtree(temp_dir, ignore_errors=True)
    return {"ok": True, "imported_images": len(imported), "annotated_images": annotated, "boxes": boxes_total, "labels": get_project(project_id).get("labels", []), "message": "已导入 Pascal VOC 数据集并转换为平台内部标注。"}

app.include_router(create_annotation_governance_router_2(_annotation_governance_service))


def get_annotation(project_id: str, image_id: str, reader_view: bool=False):
    return _annotation_governance_service().get_annotation(project_id, image_id, reader_view)


from platform_core.annotation_governance_contracts import AnnotationSave


def save_annotation(project_id: str, image_id: str, payload: AnnotationSave):
    return _annotation_governance_service().save_annotation(project_id, image_id, payload)


from platform_core.dataset_export_contracts import BuildDatasetReq


from platform_core.dataset_export_service import DatasetExportDependencies, DatasetExportService
from platform_core.dataset_export_api import create_dataset_export_router_1, create_dataset_export_router_2, create_dataset_export_router_3


def _dataset_export_service() -> DatasetExportService:
    return DatasetExportService(DatasetExportDependencies(
        _authorize_business_file_project=lambda *args, **kwargs: _authorize_business_file_project(*args, **kwargs),
        box_to_yolo_line=lambda *args, **kwargs: box_to_yolo_line(*args, **kwargs),
        dataset_quality_report=lambda *args, **kwargs: dataset_quality_report(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        load_images=lambda *args, **kwargs: load_images(*args, **kwargs),
        normalize_box_for_project=lambda *args, **kwargs: normalize_box_for_project(*args, **kwargs),
        normalize_label=lambda *args, **kwargs: normalize_label(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        read_annotation=lambda *args, **kwargs: read_annotation(*args, **kwargs),
        resolve_material_path=lambda *args, **kwargs: resolve_material_path(*args, **kwargs),
        zip_dir=lambda *args, **kwargs: zip_dir(*args, **kwargs),
    ))


app.include_router(create_dataset_export_router_1(_dataset_export_service))


def build_dataset(project_id: str, payload: BuildDatasetReq):
    return _dataset_export_service().build_dataset(project_id, payload)


def download_dataset(project_id: str):
    return _dataset_export_service().download_dataset(project_id)






# -----------------------------
# Paddle / COCO dataset export
# -----------------------------
from platform_core.dataset_export_contracts import BuildPaddleDatasetReq


def _coco_image_item(img: Dict[str, Any], idx: int, file_name: str) -> Dict[str, Any]:
    return _dataset_export_service()._coco_image_item(img, idx, file_name)


def _coco_ann_item(ann_id: int, img_id: int, b: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return _dataset_export_service()._coco_ann_item(ann_id, img_id, b)


def build_paddle_dataset_internal(project_id: str, train_ratio: float=0.8, include_empty: bool=False, dataset_id: Optional[str]=None) -> Dict[str, Any]:
    return _dataset_export_service().build_paddle_dataset_internal(project_id, train_ratio, include_empty, dataset_id)


def build_paddle_dataset(project_id: str, payload: BuildPaddleDatasetReq):
    return _dataset_export_service().build_paddle_dataset(project_id, payload)


def download_paddle_dataset(project_id: str):
    return _dataset_export_service().download_paddle_dataset(project_id)


# -----------------------------
# Pre-label service integration
# -----------------------------
from platform_core.ai_configuration_contracts import PrelabelServiceReq


class PrelabelRunReq(BaseModel):
    service_id: Optional[str] = None
    detect_url: Optional[str] = None
    request_mode: str = "json_base64"
    image_field: str = "image"
    threshold: float = 0.5
    target_label: str = "person"
    image_ids: Optional[List[str]] = None
    overwrite: bool = False


LEGACY_DIRECT_PRELABEL_BLOCKED_DETAIL = (
    "旧版自动标注直写接口已关闭；请使用当前 AI 自动标注任务，"
    "模型结果先进入候选区，经人工二次确认后才能写入正式标注"
)


def _reject_legacy_direct_prelabel(project_id: str) -> None:
    get_project(project_id)
    raise HTTPException(status_code=409, detail=LEGACY_DIRECT_PRELABEL_BLOCKED_DETAIL)


def list_prelabel_services_internal() -> List[Dict[str, Any]]:
    return read_json(PRELABEL_SERVICES_FILE, [])


from platform_core.ai_configuration_service import AiConfigurationDependencies, AiConfigurationService
from platform_core.ai_configuration_api import create_ai_configuration_router_1, create_ai_configuration_router_2


def _ai_configuration_service() -> AiConfigurationService:
    return AiConfigurationService(AiConfigurationDependencies(
        MODEL_CONFIGS_FILE=lambda: MODEL_CONFIGS_FILE,
        PRELABEL_SERVICES_FILE=lambda: PRELABEL_SERVICES_FILE,
        PROMPT_LIBRARY_FILE=lambda: PROMPT_LIBRARY_FILE,
        _v35_clean_headers=lambda *args, **kwargs: _v35_clean_headers(*args, **kwargs),
        _v35_is_vision_provider=lambda *args, **kwargs: _v35_is_vision_provider(*args, **kwargs),
        _v35_model_items=lambda *args, **kwargs: _v35_model_items(*args, **kwargs),
        _v35_normalize_adapter=lambda *args, **kwargs: _v35_normalize_adapter(*args, **kwargs),
        _v35_prompt_items=lambda *args, **kwargs: _v35_prompt_items(*args, **kwargs),
        _v35_publish_model_config=lambda *args, **kwargs: _v35_publish_model_config(*args, **kwargs),
        _v35_sanitize_secret=lambda *args, **kwargs: _v35_sanitize_secret(*args, **kwargs),
        _v35_save_items=lambda *args, **kwargs: _v35_save_items(*args, **kwargs),
        _v35_secret_store=lambda *args, **kwargs: _v35_secret_store(*args, **kwargs),
        _v35_test_annotation=lambda *args, **kwargs: _v35_test_annotation(*args, **kwargs),
        _v35_unique_default=lambda *args, **kwargs: _v35_unique_default(*args, **kwargs),
        _v35_validate_prompt=lambda *args, **kwargs: _v35_validate_prompt(*args, **kwargs),
        list_prelabel_services_internal=lambda *args, **kwargs: list_prelabel_services_internal(*args, **kwargs),
        normalize_label=lambda *args, **kwargs: normalize_label(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        write_json=lambda *args, **kwargs: write_json(*args, **kwargs),
    ))


app.include_router(create_ai_configuration_router_1(_ai_configuration_service))


def list_prelabel_services():
    return _ai_configuration_service().list_prelabel_services()


def save_prelabel_service(payload: PrelabelServiceReq):
    return _ai_configuration_service().save_prelabel_service(payload)


def delete_prelabel_service(service_id: str):
    return _ai_configuration_service().delete_prelabel_service(service_id)


def test_prelabel_service(payload: PrelabelServiceReq):
    return _ai_configuration_service().test_prelabel_service(payload)


def resolve_prelabel_config(payload: PrelabelRunReq) -> Dict[str, Any]:
    if payload.service_id:
        svc = next((s for s in list_prelabel_services_internal() if s.get("id") == payload.service_id), None)
        if not svc:
            raise HTTPException(status_code=400, detail="预标注服务不存在")
        return svc
    if payload.detect_url:
        return {
            "id": "manual",
            "name": "手动地址",
            "detect_url": payload.detect_url.strip(),
            "request_mode": payload.request_mode,
            "image_field": payload.image_field or "image",
            "threshold": float(payload.threshold),
            "target_label": normalize_label(payload.target_label or "person"),
        }
    raise HTTPException(status_code=400, detail="请选择或填写预标注服务地址")


def parse_detection_objects(data: Any, target_label: str, threshold: float) -> List[Dict[str, Any]]:
    """Accept common outputs: objects/detections/boxes with bbox/bbox_2d/coordinate."""
    objects: List[Any] = []
    if isinstance(data, dict):
        for key in ["objects", "detections", "results", "boxes", "bboxes"]:
            v = data.get(key)
            if isinstance(v, list):
                objects.extend(v)
        for key in ["result", "res", "data"]:
            if isinstance(data.get(key), dict):
                objects.extend(parse_detection_objects(data[key], target_label, threshold))
    elif isinstance(data, list):
        objects.extend(data)

    parsed: List[Dict[str, Any]] = []
    for obj in objects:
        label = target_label
        score = 1.0
        coord = None
        if isinstance(obj, dict):
            label = str(obj.get("label") or obj.get("class") or obj.get("category") or obj.get("name") or target_label)
            score = obj.get("confidence", obj.get("score", obj.get("conf", 1.0)))
            coord = obj.get("bbox_2d") or obj.get("bbox") or obj.get("box") or obj.get("coordinate") or obj.get("rect")
        elif isinstance(obj, list) and len(obj) >= 4:
            coord = obj[:4]
        try:
            score = float(score)
        except Exception:
            score = 0.0
        if score < threshold:
            continue
        if isinstance(coord, dict):
            try:
                x = float(coord.get("x", coord.get("left", 0)))
                y = float(coord.get("y", coord.get("top", 0)))
                w = float(coord.get("width", coord.get("w", 0)))
                h = float(coord.get("height", coord.get("h", 0)))
                coord = [x, y, x + w, y + h]
            except Exception:
                continue
        if not isinstance(coord, list) or len(coord) < 4:
            continue
        try:
            x1, y1, x2, y2 = [float(v) for v in coord[:4]]
        except Exception:
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        parsed.append({"label": label, "confidence": score, "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return parsed


def call_prelabel_service(cfg: Dict[str, Any], image_path: Path) -> Dict[str, Any]:
    detect_url = cfg.get("detect_url")
    if not detect_url:
        raise ValueError("预标注检测地址为空")
    threshold = float(cfg.get("threshold", 0.5))
    mode = cfg.get("request_mode") or "json_base64"
    field = cfg.get("image_field") or "image"
    if mode == "multipart_file":
        with image_path.open("rb") as fp:
            r = requests.post(detect_url, files={field: (image_path.name, fp, "application/octet-stream")}, data={"threshold": str(threshold)}, timeout=120)
    else:
        raw = image_path.read_bytes()
        payload = {field: base64.b64encode(raw).decode("utf-8"), "threshold": threshold}
        r = requests.post(detect_url, json=payload, timeout=120)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


@app.post("/api/projects/{project_id}/prelabel/run")
def run_prelabel(project_id: str, payload: PrelabelRunReq):
    _reject_legacy_direct_prelabel(project_id)
    project = get_project(project_id)
    p = project_dir(project_id)
    cfg = resolve_prelabel_config(payload)
    target_label = normalize_label(cfg.get("target_label") or payload.target_label or "person")
    class_id = ensure_label(project, target_label)
    project = get_project(project_id)
    image_ids = set(payload.image_ids or [])
    images = load_images(project_id)
    if image_ids:
        images = [img for img in images if img["id"] in image_ids]
    if not images:
        raise HTTPException(status_code=400, detail="没有可预标注的图片")
    total_boxes = 0
    processed = 0
    errors = []
    for img in images:
        img_path = resolve_material_path(project_id, img)
        try:
            raw = call_prelabel_service(cfg, img_path)
            detections = parse_detection_objects(raw, target_label, float(cfg.get("threshold", 0.5)))
            new_boxes = []
            for det in detections:
                x1 = max(0, min(float(det["x1"]), img["width"]))
                y1 = max(0, min(float(det["y1"]), img["height"]))
                x2 = max(0, min(float(det["x2"]), img["width"]))
                y2 = max(0, min(float(det["y2"]), img["height"]))
                if x2 - x1 < 3 or y2 - y1 < 3:
                    continue
                new_boxes.append({
                    "id": uuid.uuid4().hex[:10],
                    "class_id": class_id,
                    "label": target_label,
                    "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2),
                    "source": "prelabel", "confidence": round(float(det.get("confidence", 0)), 4),
                })
            old = read_annotation(project_id, img["id"]).get("boxes", [])
            if payload.overwrite:
                merged = [b for b in old if int(b.get("class_id", -1)) != class_id] + new_boxes
            else:
                merged = old + new_boxes
            write_annotation(project_id, img["id"], merged)
            total_boxes += len(new_boxes)
            processed += 1
        except Exception as e:
            errors.append({"image": img.get("filename"), "error": str(e)})
    return {"ok": True, "processed_images": processed, "boxes_added": total_boxes, "target_label": target_label, "labels": get_project(project_id).get("labels", []), "errors": errors[:20]}

from platform_core.runtime_catalog_contracts import LocalModelScanReq


from platform_core.runtime_catalog_contracts import UltralyticsEnvDetectReq


class UltralyticsEnvSelectReq(BaseModel):
    python_path: str
    yolo_path: Optional[str] = ""
    root: Optional[str] = ""


def _path_exists(p: str) -> bool:
    try:
        return bool(p) and Path(p).exists()
    except Exception:
        return False


def _is_absolute_path_text(p: str) -> bool:
    if not p:
        return False
    try:
        return Path(p).is_absolute() or bool(re.match(r"^[A-Za-z]:[\\/]", p))
    except Exception:
        return False


def default_ultralytics_roots() -> List[str]:
    configured = os.environ.get("MC_ULTRALYTICS_ROOTS", "")
    roots = [value for value in configured.split(os.pathsep) if value]
    roots.extend(
        [
            str(BASE_DIR),
            str(Path.cwd()),
            str(Path(sys.executable).resolve().parent.parent),
            str(Path.home()),
        ]
    )
    return list(dict.fromkeys(value for value in roots if value))[:8]


def _candidate_python_paths(root: Path) -> List[Path]:
    paths: List[Path] = []
    # 用户可能直接填 .venv，也可能填 Ultralytics 根目录，也可能填 python.exe/yolo.exe
    if root.is_file():
        name = root.name.lower()
        if name == "python.exe" or name == "python":
            paths.append(root)
        elif name.startswith("yolo"):
            scripts = root.parent
            for py in [scripts / "python.exe", scripts / "python"]:
                if py.exists():
                    paths.append(py)
        return paths
    candidates = [
        root / ".venv" / "Scripts" / "python.exe",
        root / "venv" / "Scripts" / "python.exe",
        root / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
        root / "venv" / "bin" / "python",
        root / "bin" / "python",
    ]
    for p in candidates:
        if p.exists() and p not in paths:
            paths.append(p)
    return paths


def _find_pt_models_near(root: Path, limit: int = 30) -> List[Dict[str, Any]]:
    models: List[Dict[str, Any]] = []
    search_roots = []
    if root.is_file():
        search_roots.append(root.parent)
    else:
        search_roots.extend([root, root / "models", root / "weights"])
    seen = set()
    for sr in search_roots:
        if not sr.exists() or not sr.is_dir():
            continue
        try:
            for p in sr.glob("*.pt"):
                if str(p) in seen:
                    continue
                seen.add(str(p))
                try:
                    stat = p.stat()
                    models.append({
                        "name": p.name,
                        "path": str(p),
                        "size_mb": round(stat.st_size / 1024 / 1024, 2),
                        "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    })
                except Exception:
                    models.append({"name": p.name, "path": str(p)})
                if len(models) >= limit:
                    return models
        except Exception:
            pass
    return models


def _check_ultralytics_python(py: Path, root: Path) -> Optional[Dict[str, Any]]:
    code = (
        "import json, sys\n"
        "try:\n"
        " import ultralytics\n"
        " print(json.dumps({'ok': True, 'version': getattr(ultralytics, '__version__', ''), 'package_path': getattr(ultralytics, '__file__', '')}, ensure_ascii=False))\n"
        "except Exception as e:\n"
        " print(json.dumps({'ok': False, 'error': str(e)}, ensure_ascii=False))\n"
    )
    try:
        cp = subprocess.run(
            [str(py), "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        line = (cp.stdout or cp.stderr or "").strip().splitlines()[-1] if (cp.stdout or cp.stderr) else ""
        data = json.loads(line) if line else {"ok": False, "error": "无输出"}
        if not data.get("ok"):
            return None
        scripts = py.parent
        yolo = scripts / ("yolo.exe" if os.name == "nt" else "yolo")
        item = {
            "ok": True,
            "root": str(root),
            "python_path": str(py),
            "yolo_path": str(yolo) if yolo.exists() else "",
            "version": data.get("version", ""),
            "package_path": data.get("package_path", ""),
            "models": _find_pt_models_near(root),
            "updated_at": now_iso(),
        }
        return item
    except Exception:
        return None


def detect_ultralytics_env_internal(roots: Optional[List[str]]) -> Dict[str, Any]:
    root_paths = normalize_scan_roots(roots or default_ultralytics_roots())
    candidates: List[Dict[str, Any]] = []
    seen_py = set()
    for root in root_paths:
        # 如果用户给的是父目录，额外检查一层常见子目录，避免扫全盘。
        probe_roots = [root]
        for sub in ["Ultralytics", "ultralytics", "yolosuanfa\\Ultralytics", "lab\\yolosuanfa\\Ultralytics"]:
            p = root / sub
            if p.exists():
                probe_roots.append(p)
        for pr in probe_roots:
            for py in _candidate_python_paths(pr):
                key = str(py).lower()
                if key in seen_py:
                    continue
                seen_py.add(key)
                found = _check_ultralytics_python(py, pr)
                if found:
                    candidates.append(found)
    active = read_json(ULTRALYTICS_ENV_FILE, {})
    payload = {"ok": True, "active": active if isinstance(active, dict) else {}, "candidates": candidates, "roots": [str(x) for x in root_paths], "updated_at": now_iso()}
    # Compatibility helper only: discovery must not implicitly select or write
    # an active interpreter. The explicit select endpoint owns that mutation.
    return payload


_ACTIVE_ULTRA_RUNTIME_CACHE: Dict[str, Any] = {}

def get_active_ultralytics_env() -> Dict[str, Any]:
    global _ACTIVE_ULTRA_RUNTIME_CACHE
    cached = _ACTIVE_ULTRA_RUNTIME_CACHE if isinstance(_ACTIVE_ULTRA_RUNTIME_CACHE, dict) else {}
    cached_python = str(cached.get("python_path") or "")
    if cached_python and _path_exists(cached_python):
        return dict(cached)
    env = read_json(ULTRALYTICS_ENV_FILE, {})
    if isinstance(env, dict):
        python_path = str(env.get("python_path") or "")
        if python_path and _path_exists(python_path):
            # Read-only callers must never launch a probe, choose a fallback
            # interpreter, or persist a selection. Selection is explicit below.
            _ACTIVE_ULTRA_RUNTIME_CACHE = dict(env)
            return dict(env)
    _ACTIVE_ULTRA_RUNTIME_CACHE = {}
    return {}
def ultralytics_runtime_python() -> str:
    env = get_active_ultralytics_env()
    if env.get("python_path"):
        return env["python_path"]
    return sys.executable


def resolve_ultralytics_model(model_value: str, project_id: Optional[str] = None) -> ModelResolution:
    """Resolve a checkpoint without coupling environment health to its presence."""
    active_env = get_active_ultralytics_env()
    project_root = project_dir(project_id) if project_id else None
    project_models: List[Dict[str, Any]] = []
    algorithm_versions: List[Dict[str, Any]] = []
    if project_id:
        try:
            project_models = list_models_internal(project_id)
        except Exception:
            project_models = []
        try:
            for algorithm in list_algorithms_internal(project_id):
                algorithm_versions.extend(algorithm.get("versions") or [])
        except Exception:
            algorithm_versions = []
    try:
        discovery_cache: Optional[DiscoveryCache] = _discovery_cache()
    except (OSError, sqlite3.Error):
        discovery_cache = None
    resolver = ModelResolver(
        selected_environment=active_env,
        discovery_cache=discovery_cache,
        project_model_dirs=((project_root / "models",) if project_root else ()),
        project_models=project_models,
        algorithm_versions=algorithm_versions,
        platform_model_dirs=(DATA_DIR / "models", BASE_DIR / "models"),
        cwd=BASE_DIR,
    )
    return resolver.resolve(model_value, project_id=project_id)


def _ready_ultralytics_mother_model(project_id: str, requested: str) -> str:
    """Require a real local weight, never a downloadable filename, at submission."""
    reference = str(requested or "").strip()
    if not reference:
        raise HTTPException(status_code=409, detail={"code":"TRAINING_MOTHER_MODEL_UNAVAILABLE","message":"尚未选择母模型，请先到训练资源上传 .pt 权重"})
    if reference.startswith("asset:"):
        asset_id = reference[6:]
        verified = _verified_mother_model_asset(DATA_DIR, asset_id)
        if not verified:
            raise HTTPException(status_code=409, detail={"code":"TRAINING_MOTHER_MODEL_NOT_VERIFIED","message":"此母模型尚未通过安全校验，或权重 SHA256 已变化；请到母模型管理执行校验"})
        return str(Path(verified["path"]).resolve())
    resolution = resolve_ultralytics_model(reference, project_id)
    candidate = resolution.path
    if not resolution.found or candidate is None:
        raise HTTPException(status_code=409, detail={"code":"TRAINING_MOTHER_MODEL_UNAVAILABLE","message":f"母模型 {Path(reference).name} 未就绪；请先在训练资源预置 .pt 权重，训练时不自动下载"})
    candidate = candidate.resolve()
    if candidate.suffix.lower() != ".pt" or not candidate.is_file() or candidate.stat().st_size < 1024:
        raise HTTPException(status_code=409, detail={"code":"TRAINING_MOTHER_MODEL_UNAVAILABLE","message":"母模型不是可用的本地 .pt 权重文件"})
    tracked = next((item for item in _list_mother_model_assets(DATA_DIR)
                    if Path(str(item.get("path") or "")).resolve() == candidate), None)
    if tracked and not _verified_mother_model_asset(DATA_DIR, tracked["asset_id"]):
        raise HTTPException(status_code=409, detail={"code":"TRAINING_MOTHER_MODEL_NOT_VERIFIED","message":"已上传的母模型须先完成安全兼容性校验才能训练"})
    return str(candidate)


def _prepared_mother_model_rows() -> List[Dict[str, Any]]:
    """Read-only view of the existing ModelResolver DATA_DIR/models directory."""
    root = DATA_DIR / "models"
    if not root.is_dir():
        return []
    result: List[Dict[str, Any]] = []
    indexed = {str(Path(str(row.get("path") or "")).resolve()): row for row in _list_mother_model_assets(DATA_DIR)}
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.suffix.lower() != ".pt" or path.stat().st_size < 1024:
            continue
        model = indexed.get(str(path.resolve()))
        status = str(model.get("validation_status") or "UNVERIFIED") if model else "LEGACY_UNVERIFIED"
        result.append({
            "label": f"{path.name}（已预置）", "name": path.name,
            "value": f"asset:{model['asset_id']}" if model else str(path.resolve()),
            "asset_id": model.get("asset_id") if model else None,
            "validation_status": status,
            "validation_error": model.get("validation_error") if model else "",
            "verification_method": model.get("verification_method") if model else "",
            "names": model.get("names") if model else [],
            "nc": model.get("nc") if model else None,
            "task": model.get("task") if model else "unknown",
            "framework": model.get("framework") if model else "ultralytics",
            "train_framework": "ultralytics", "source": "preinstalled",
            "model_status": "FOUND", "found": True, "downloadable": False,
            "size_bytes": path.stat().st_size, "trainable": bool(model.get("trainable")) if model else True,
            "note": ("官方发布权重 SHA256 已核对" if model.get("verification_method") == "official_release_sha256" else "已完成隔离验证") if status == "VERIFIED" else "待安全校验，暂不可用于首次训练" if model else "历史预置权重；尚无结构化验证记录",
        })
    return result


def resolve_ultralytics_model_path(model_value: str, project_id: Optional[str] = None) -> str:
    """Backward-compatible string wrapper around structured model resolution."""
    resolution = resolve_ultralytics_model(model_value, project_id)
    return str(resolution.path) if resolution.found else resolution.reference


def default_scan_roots() -> List[str]:
    """Return practical default roots for Windows first, then local dev paths."""
    roots: List[str] = []
    if os.name == "nt":
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            root = f"{letter}:\\"
            if Path(root).exists():
                roots.append(root)
    else:
        # For development/testing in Linux/macOS. On the user's Windows machine this branch will not be used.
        for root in [str(BASE_DIR), str(DATA_DIR), "/mnt/data", str(Path.home())]:
            if Path(root).exists() and root not in roots:
                roots.append(root)
    return roots[:8]


def normalize_scan_roots(roots: Optional[List[str]]) -> List[Path]:
    if not roots:
        roots = default_scan_roots()
    paths: List[Path] = []
    for root in roots:
        if not root:
            continue
        # 用户可能在文本框里用逗号、分号或换行混输，这里做宽松拆分。
        parts = []
        for chunk in str(root).replace(";", "\n").replace(",", "\n").splitlines():
            chunk = chunk.strip().strip('"').strip("'")
            if chunk:
                parts.append(chunk)
        for item in parts:
            path = Path(item).expanduser()
            if path.exists() and path not in paths:
                paths.append(path)
    return paths


def is_model_candidate(path: Path) -> bool:
    if not path.is_file():
        return False
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix in MODEL_EXTS:
        return True
    if name in MODEL_CONFIG_NAMES:
        return True
    # 飞桨/PaddleX 服务经常不是模型文件，而是 human_service.py 里 create_model("PP-YOLOE-S_human")。
    # 这里只宽松检查小型 Python 文件，避免全盘读取大文件。
    if suffix == ".py" and (name in PADDLEX_SERVICE_FILE_NAMES or "paddlex" in str(path).lower() or "yolo" in str(path).lower()):
        try:
            if path.stat().st_size > 300_000:
                return False
            text = path.read_text(encoding="utf-8", errors="ignore")[:20000].lower()
            return "paddlex" in text and "create_model" in text
        except Exception:
            return False
    return False


def classify_model_file(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    name = path.name.lower()
    path_text = str(path).lower()
    framework = "未知/通用"
    framework_key = "other"
    model_type = suffix.lstrip(".") if suffix else "config"
    trainable_current = False
    trainable_paddle = False
    inferable = False
    selectable_as_base = False
    action = "仅记录路径"
    note = ""
    detected_model_name = ""

    if suffix == ".py":
        text = ""
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:50000]
        except Exception:
            pass
        match = re.search(r"create_model\(\s*[\"']([^\"']+)[\"']", text)
        detected_model_name = match.group(1) if match else ""
        framework = "PaddleX / 飞桨服务脚本"
        framework_key = "paddle_service"
        model_type = f"PaddleX 内置模型：{detected_model_name}" if detected_model_name else "PaddleX 服务脚本"
        inferable = True
        selectable_as_base = True
        action = "可登记为飞桨模型源/辅助标注服务；不是当前 Ultralytics 训练权重"
        note = "你上传的 human_service.py 就属于这种：通过 create_model 加载模型，包里没有独立训练权重文件。"
    elif suffix == ".pt":
        framework = "Ultralytics / PyTorch YOLO"
        framework_key = "ultralytics"
        model_type = "pt 训练权重"
        trainable_current = True
        inferable = True
        selectable_as_base = True
        action = "可直接作为当前平台基础模型继续训练"
        note = "适合填入训练页的“基础模型”。"
    elif suffix == ".pth":
        framework = "PyTorch 权重"
        framework_key = "pytorch"
        model_type = "pth 权重"
        inferable = False
        action = "需确认具体框架"
        note = "可能是 PyTorch 权重，但不一定是 Ultralytics YOLO，当前平台不能保证直接训练。"
    elif suffix == ".pdparams":
        framework = "PaddleDetection / 飞桨"
        framework_key = "paddle"
        model_type = "pdparams 训练权重"
        trainable_paddle = True
        inferable = False
        selectable_as_base = True
        action = "可用于 PaddleDetection/PaddleX 继续训练；不能放进 Ultralytics 训练命令"
        note = "这是飞桨训练权重，不是 Ultralytics .pt，不能直接填到当前 YOLO 训练命令里。"
    elif suffix in {".pdmodel", ".pdiparams"}:
        framework = "Paddle Inference / 飞桨推理模型"
        framework_key = "paddle_infer"
        model_type = suffix.lstrip(".")
        inferable = True
        action = "可用于飞桨推理或辅助标注"
        note = "通常是导出后的推理模型，不能直接继续训练。"
    elif suffix == ".onnx":
        framework = "ONNX 推理模型"
        framework_key = "onnx"
        model_type = "onnx"
        inferable = True
        action = "可推理/部署/辅助标注"
        note = "一般不能继续训练。"
    elif suffix == ".engine":
        framework = "TensorRT 推理模型"
        framework_key = "tensorrt"
        model_type = "engine"
        inferable = True
        action = "仅推理部署"
        note = "NVIDIA TensorRT 引擎，不能继续训练。"
    elif suffix == ".rknn":
        framework = "瑞芯微 RKNN 推理模型"
        framework_key = "rknn"
        model_type = "rknn"
        inferable = True
        action = "仅推理部署"
        note = "NPU 部署格式，不能继续训练。"
    elif suffix == ".bmodel":
        framework = "算能 BMRuntime 推理模型"
        framework_key = "sophon"
        model_type = "bmodel"
        inferable = True
        action = "仅推理部署"
        note = "算能部署格式，不能继续训练。"
    elif name in MODEL_CONFIG_NAMES:
        if "paddle" in path_text or "infer" in name or "deploy" in name:
            framework = "PaddleDetection / 飞桨配置"
            framework_key = "paddle_config"
        model_type = "配置文件"
        inferable = False
        action = "辅助识别模型包"
        note = "通常需要和 .pdmodel/.pdiparams/.pdparams 放在同一模型目录里看。"

    # 目录名/路径再辅助判断一次
    if framework == "未知/通用" and "paddle" in path_text:
        framework = "PaddleDetection / 飞桨"
        framework_key = "paddle"
    if framework == "未知/通用" and ("yolo" in path_text or name.startswith("yolo") or name in {"best.pt", "last.pt"}):
        framework = "YOLO 相关"
        framework_key = "yolo_related"

    try:
        stat = path.stat()
        size_mb = round(stat.st_size / 1024 / 1024, 2)
        updated_at = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        size_mb = 0
        updated_at = ""

    return {
        "name": path.name,
        "path": str(path),
        "dir": str(path.parent),
        "suffix": suffix,
        "framework": framework,
        "framework_key": framework_key,
        "model_type": model_type,
        "detected_model_name": detected_model_name,
        "size_mb": size_mb,
        "updated_at": updated_at,
        "trainable_current_platform": trainable_current,
        "trainable_paddle": trainable_paddle,
        "inferable": inferable,
        "selectable_as_base": selectable_as_base,
        "recommended_action": action,
        "note": note,
    }


def scan_local_models_internal(roots: Optional[List[str]], max_results: int = 3000) -> Dict[str, Any]:
    root_paths = normalize_scan_roots(roots)
    max_results = max(50, min(int(max_results or 3000), 20000))
    results: List[Dict[str, Any]] = []
    scanned_dirs = 0
    errors: List[str] = []
    start = time.time()

    for root in root_paths:
        if len(results) >= max_results:
            break
        if root.is_file():
            if is_model_candidate(root):
                results.append(classify_model_file(root))
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                scanned_dirs += 1
                # 跳过明显无关/超大的目录，避免扫盘过慢。保留 Users/工作目录/缓存目录。
                dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_SCAN_DIRS]
                for fn in filenames:
                    if len(results) >= max_results:
                        break
                    fp = Path(dirpath) / fn
                    if is_model_candidate(fp):
                        results.append(classify_model_file(fp))
                if len(results) >= max_results:
                    break
        except Exception as e:
            errors.append(f"{root}: {e}")

    # 去重并按可训练优先、修改时间倒序
    dedup: Dict[str, Dict[str, Any]] = {}
    for item in results:
        dedup[item["path"]] = item
    rows = list(dedup.values())
    rows.sort(key=lambda x: (not x.get("trainable_current_platform"), not x.get("trainable_paddle"), x.get("updated_at", "")), reverse=False)
    # 上面 reverse=False 会让 trainable True 靠前但更新时间旧靠前，不理想；重新显式排序
    rows.sort(key=lambda x: (1 if x.get("trainable_current_platform") else 0, 1 if x.get("trainable_paddle") else 0, x.get("updated_at", "")), reverse=True)
    payload = {
        "ok": True,
        "roots": [str(x) for x in root_paths],
        "total": len(rows),
        "scanned_dirs": scanned_dirs,
        "seconds": round(time.time() - start, 2),
        "items": rows,
        "errors": errors[:20],
        "updated_at": now_iso(),
    }
    write_json(LOCAL_MODELS_FILE, payload)
    return payload


def _discovery_cache() -> DiscoveryCache:
    return DiscoveryCache(RESOURCE_DISCOVERY_CACHE_FILE)


def _public_discovery_task(task: TaskRecord) -> Dict[str, Any]:
    response = _public_task(task)
    response["task_id"] = task.task_id
    response["progress_determinate"] = False
    request_payload = shared_task_artifacts().read_json(
        task.task_id, "request.json", default={}
    )
    if not isinstance(request_payload, dict):
        request_payload = {}
    scan_roots = [
        str(root).strip()
        for root in (request_payload.get("roots") or [])
        if str(root).strip()
    ]
    response["discovery_scope"] = str(request_payload.get("scope") or "").strip().lower()
    response["scan_roots"] = scan_roots
    response["scan_root_count"] = len(scan_roots)
    progress = shared_task_artifacts().read_json(
        task.task_id, RESOURCE_DISCOVERY_PROGRESS_REF, default={}
    )
    if isinstance(progress, dict):
        response["metrics"] = progress
        for key in (
            "scanned_dirs", "python_candidates", "validated_environments",
            "available_environments", "models_found", "permission_errors",
        ):
            if isinstance(progress.get(key), (int, float)):
                response[key] = progress[key]
        if progress.get("current_item"):
            response["current_item"] = progress["current_item"]
    if task.result_ref:
        result = shared_task_artifacts().read_json(
            task.task_id, task.result_ref, default=None
        )
        if isinstance(result, dict):
            response["result"] = result
    return response


def _create_discovery_task(
    discovery_type: str, scope: str, roots: Optional[List[str]]
) -> TaskRecord:
    cache = _discovery_cache()
    generation = cache.next_generation(discovery_type)
    task_id = uuid.uuid4().hex[:12]
    request_payload = {
        "discovery_type": discovery_type,
        "scope": scope,
        "roots": [str(value) for value in (roots or []) if str(value).strip()],
        "generation": generation,
    }
    shared_task_artifacts().atomic_write_json(task_id, "request.json", request_payload)
    resource_name = "environment" if discovery_type == "ultralytics_environment" else "models"
    return shared_task_repository().create(
        TaskRecord.new(
            task_id,
            "__system__",
            TaskKind.RESOURCE_DISCOVERY,
            "request.json",
            f"local-resource-discovery:{resource_name}",
            required_capabilities=("resource.discovery",),
        )
    )


app.include_router(create_runtime_catalog_router_3(_runtime_catalog_service))


def list_local_models(limit: int=200, cursor: Optional[str]=None):
    return _runtime_catalog_service().list_local_models(limit, cursor)


def scan_local_models(payload: LocalModelScanReq):
    return _runtime_catalog_service().scan_local_models(payload)


def get_ultralytics_env():
    return _runtime_catalog_service().get_ultralytics_env()


def detect_ultralytics_env(payload: UltralyticsEnvDetectReq):
    return _runtime_catalog_service().detect_ultralytics_env(payload)


@app.post("/api/ultralytics_env/select")
def select_ultralytics_env(payload: UltralyticsEnvSelectReq):
    py = Path(payload.python_path.strip().strip('"'))
    if not py.exists():
        raise HTTPException(status_code=400, detail="python.exe 路径不存在")
    root = Path(payload.root.strip().strip('"')) if payload.root else py.parent.parent
    found = probe_python_environment(py)
    if str(found.get("status") or "").upper() != "AVAILABLE":
        reason = found.get("error") or found.get("compatibility") or {}
        raise HTTPException(status_code=400, detail={
            "message": "这个 Python 环境未通过 Ultralytics/Torch/TorchVision 可用性检测",
            "reason": reason,
        })
    found["ok"] = True
    found["root"] = str(root)
    ultralytics_info = found.get("ultralytics")
    found["version"] = (
        str(ultralytics_info.get("version") or "")
        if isinstance(ultralytics_info, dict) else ""
    )
    found["updated_at"] = now_iso()
    if payload.yolo_path:
        found["yolo_path"] = payload.yolo_path
    write_json(ULTRALYTICS_ENV_FILE, found)
    global _ACTIVE_ULTRA_RUNTIME_CACHE
    _ACTIVE_ULTRA_RUNTIME_CACHE = dict(found)
    return {"ok": True, "active": found}


app.include_router(create_runtime_catalog_router_4(_runtime_catalog_service))


def get_resource_discovery_task(task_id: str):
    return _runtime_catalog_service().get_resource_discovery_task(task_id)


def cancel_resource_discovery_task(task_id: str):
    return _runtime_catalog_service().cancel_resource_discovery_task(task_id)


def training_catalog():
    return _runtime_catalog_service().training_catalog()


async def upload_preinstalled_base_model(file: UploadFile=File(...)):
    return await _runtime_catalog_service().upload_preinstalled_base_model(file)


def list_mother_model_assets():
    return _runtime_catalog_service().list_mother_model_assets()


def list_mother_model_node_inventory():
    return _runtime_catalog_service().list_mother_model_node_inventory()


def install_mother_model_to_node(asset_id: str, payload: Dict[str, Any]):
    return _runtime_catalog_service().install_mother_model_to_node(asset_id, payload)


def list_mother_model_installations(cursor: Optional[str]=None):
    return _runtime_catalog_service().list_mother_model_installations(cursor)


def cancel_mother_model_installation(task_id: str):
    return _runtime_catalog_service().cancel_mother_model_installation(task_id)


def register_discovered_mother_model(payload: Dict[str, Any]):
    return _runtime_catalog_service().register_discovered_mother_model(payload)


def verify_mother_model_asset(asset_id: str):
    return _runtime_catalog_service().verify_mother_model_asset(asset_id)


def list_base_models(project_id: Optional[str]=None):
    return _runtime_catalog_service().list_base_models(project_id)




def _remote_capabilities(server: Dict[str, Any]) -> Dict[str, Any]:
    base_url = str(server.get("base_url", "")).rstrip("/")
    if not base_url:
        return {"ok": False, "error": "服务器地址为空"}
    try:
        headers = {"X-API-Key": server.get("api_key", "") or ""}
        r = requests.get(f"{base_url}/api/remote/health", headers=headers, timeout=4)
        r.raise_for_status()
        data = r.json()
        # 兼容旧版远程服务：没有 capabilities 时给默认 Ultralytics 能力
        if "algorithms" not in data:
            data["algorithms"] = [
                {"key":"yolo11n_det","name":"YOLO11n 目标检测","framework":"ultralytics","base_model":"yolo11n.pt","default_epochs":150,"default_imgsz":640,"default_batch":4},
                {"key":"yolo11s_det","name":"YOLO11s 目标检测","framework":"ultralytics","base_model":"yolo11s.pt","default_epochs":150,"default_imgsz":640,"default_batch":4},
                {"key":"yolo11m_det","name":"YOLO11m 目标检测","framework":"ultralytics","base_model":"yolo11m.pt","default_epochs":150,"default_imgsz":640,"default_batch":2},
            ]
        if "base_models" not in data:
            data["base_models"] = [
                {"label":"yolo11n.pt","value":"yolo11n.pt","framework":"ultralytics"},
                {"label":"yolo11s.pt","value":"yolo11s.pt","framework":"ultralytics"},
                {"label":"yolo11m.pt","value":"yolo11m.pt","framework":"ultralytics"},
            ]
        return {"ok": True, **data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_LEGACY_HEALTH_TTL_SECONDS = 600
_LEGACY_ALGORITHM_FIELDS = frozenset({"key", "name", "framework", "base_model", "engine", "task",
                                      "default_epochs", "default_imgsz", "default_batch", "recommended"})
_LEGACY_MODEL_FIELDS = frozenset({"label", "value", "framework", "source", "name", "model_status"})


def _legacy_health_identity(server: Dict[str, Any]) -> str:
    """Bind a saved probe to the current endpoint and secret without exposing either."""
    identity = json.dumps([
        str(server.get("id") or ""), str(server.get("base_url") or "").rstrip("/"),
        str(server.get("api_key") or ""),
    ], ensure_ascii=False)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _cached_legacy_health(server: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = server.get("health_snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("identity") != _legacy_health_identity(server):
        return {"ok": False, "status": "unknown", "error": "尚未检测，请到训练资源手动检测"}
    try:
        age = time.time() - float(snapshot.get("checked_at_epoch") or 0)
    except (ValueError, TypeError, OverflowError):
        age = float("inf")
    if age < 0 or age > _LEGACY_HEALTH_TTL_SECONDS:
        return {"ok": False, "status": "unknown", "error": "检测结果已过期，请手动重新检测"}
    if not snapshot.get("ok"):
        return {"ok": False, "status": "offline", "error": "上次健康检测失败，请手动重新检测"}
    return {"ok": True, "status": "ready", "framework": snapshot.get("framework") or "ultralytics",
            "algorithms": snapshot.get("algorithms") or [], "base_models": snapshot.get("base_models") or [],
            "checked_at": snapshot.get("checked_at") or ""}


def _record_legacy_health(server_id: str, checked_server: Dict[str, Any], caps: Dict[str, Any]) -> None:
    """Publish an explicit check only if the saved server is still unchanged."""
    with FileLock(str(SERVERS_FILE) + ".lock", timeout=30):
        servers = read_json(SERVERS_FILE, [])
        for server in servers:
            if str(server.get("id") or "") != str(server_id):
                continue
            if _legacy_health_identity(server) != _legacy_health_identity(checked_server):
                return
            server["health_snapshot"] = {
                "identity": _legacy_health_identity(server),
                "checked_at_epoch": time.time(), "checked_at": now_iso(),
                "ok": bool(caps.get("ok")),
                "framework": str(caps.get("framework") or "ultralytics") if caps.get("ok") else "",
                "algorithms": [{key: value for key, value in row.items() if key in _LEGACY_ALGORITHM_FIELDS}
                               for row in (caps.get("algorithms") or [])[:500] if isinstance(row, dict)]
                if caps.get("ok") and isinstance(caps.get("algorithms"), list) else [],
                "base_models": [{key: value for key, value in row.items() if key in _LEGACY_MODEL_FIELDS}
                                for row in (caps.get("base_models") or [])[:200] if isinstance(row, dict)]
                if caps.get("ok") and isinstance(caps.get("base_models"), list) else [],
            }
            atomic_write_json(SERVERS_FILE, servers)
            return


@app.get("/api/training_options")
@performance_stage("training_options")
def training_options(project_id: Optional[str] = None):
    """Offer real preloaded mother weights and preserve verified version iteration."""
    options: List[Dict[str, Any]] = []
    has_iteration_base = False
    if project_id:
        try:
            # Only the current effective version qualifies. This is a local
            # algorithm index read; no per-version reports or job.json scans.
            for algorithm in list_algorithm_assets(algorithms_file(project_id)):
                try:
                    current_id = resolve_current_version_id(algorithm, framework="ultralytics")
                except PlatformError:
                    continue
                current = next((v for v in (algorithm.get("versions") or []) if str(v.get("id") or "") == current_id), None)
                if current and is_trainable_version(current, "ultralytics"):
                    has_iteration_base = True
                    break
        except Exception:
            has_iteration_base = False
    # 本机 Ultralytics
    ultra = get_active_ultralytics_env()
    if ultra:
        algs = [a for a in TRAINING_CATALOG["algorithms"] if a.get("framework") == "ultralytics"]
        models = []
        for m in ultra.get("models", []) if isinstance(ultra.get("models", []), list) else []:
            candidate = Path(str(m.get("path") or ""))
            if candidate.suffix.lower() == ".pt" and candidate.is_file() and candidate.stat().st_size >= 1024:
                models.append({"label": m.get("name") or candidate.name, "value": str(candidate.resolve()), "framework":"ultralytics", "source":"env", "model_status":"FOUND", "downloadable":False, "environment_status":str(ultra.get("status") or "AVAILABLE").upper()})
        # Shared MODEL directory is already searched by canonical ModelResolver.
        # Never advertise a missing official name as a training-ready weight.
        models.extend(_prepared_mother_model_rows())
        # Iteration weights belong to the verified version resolver, not the
        # first-training mother-model catalog. Do not scan all historical job
        # JSONs (list_models_internal/ModelResolver) on this read-only GET.
        # 训练算法从当前训练资源读取。Ultralytics 本质是同一个 detect 训练器，yolo11n/s/m 是基础权重/模型规模。
        available = " ".join([str(x.get("label", "")) + " " + str(x.get("value", "")) for x in models]).lower()
        algs = []
        for a in [x for x in TRAINING_CATALOG["algorithms"] if x.get("framework") == "ultralytics"]:
            bm = str(a.get("base_model", "")).lower()
            if bm and (bm in available or not models):
                algs.append(a)
        if not algs:
            algs = [a for a in TRAINING_CATALOG["algorithms"] if a.get("key") == "yolo11n_det"]
        options.append({
            "id":"local_ultralytics",
            "name": ultra.get("name") or "本机 Ultralytics",
            "type":"local",
            "framework":"ultralytics",
            "status":"ready" if any(model.get("trainable") is not False for model in models) or has_iteration_base else "warning",
            "python_path": ultra.get("python_path"),
            "root": ultra.get("root"),
            "version": ultra.get("version"),
            "environment_status": str(ultra.get("status") or "AVAILABLE").upper(),
            "algorithms": algs,
            "base_models": models,
        })
    # Explicit Paddle activation owns config/weight discovery; ordinary GET
    # uses that saved evidence, never recursively walks configs or weights.
    paddle = get_active_paddle_env()
    if paddle and (paddle.get("python_path") or paddle.get("paddledet_dir") or paddle.get("paddlex_dir")):
        py_ok = bool(paddle.get("python_path") and Path(paddle.get("python_path", "")).exists())
        pd_dir = paddle.get("paddledet_dir", "")
        scan = paddle.get("algorithm_scan") if isinstance(paddle.get("algorithm_scan"), dict) else {}
        if not isinstance(scan.get("items"), list):
            scan = {"ok": False, "items": [], "error": "尚无训练配置扫描快照，请重新检测并启用飞桨环境"}
        algs = scan.get("items", [])
        weights = [{"label": "使用配置默认预训练权重 / 自动下载", "value": "", "framework":"paddle", "source":"default"}]
        weights.extend(paddle.get("weight_scan") if isinstance(paddle.get("weight_scan"), list) else [])
        config_ok = bool(pd_dir and (Path(pd_dir) / "configs").is_dir())
        status = "ready" if py_ok and config_ok and scan.get("ok") and algs else ("warning" if py_ok else "offline")
        options.append({
            "id":"local_paddle",
            "name": paddle.get("name") or "本机飞桨",
            "type":"local",
            "framework":"paddle",
            "status": status,
            "python_path": paddle.get("python_path"),
            "paddledet_dir": pd_dir,
            "paddlex_dir": paddle.get("paddlex_dir"),
            "algorithms": algs,
            "base_models": weights,
            "scan": {"ok": scan.get("ok"), "total": scan.get("total", 0), "families": scan.get("families", {}), "error": scan.get("error", "")},
        })
    # 推荐远程训练入口：不绑定具体服务器。只在“在线 training Agent +
    # 可移植对象存储”同时满足时暴露为 ready，避免用户先选机器再让调度器
    # 二次改派。中央 allocator 最终拥有节点/GPU 选择权。
    try:
        training_agents = [
            node for node in ServiceNodeRepository(shared_task_repository()).list_public()
            if str(node.get("connection_mode") or "").strip().lower() == "agent"
            and bool(node.get("online"))
            and "training" in set(node.get("effective_capabilities") or [])
        ]
    except Exception:
        training_agents = []
    portable_training_storage = False
    try:
        artifact_service = ModelArtifactService(
            data_dir=DATA_DIR,
            project_dir=project_dir,
            algorithms_file=algorithms_file,
            storage_sources_factory=storage_source_repository,
            storage_credentials_factory=storage_credentials,
        )
        artifact_config = artifact_service.repository.config()
        artifact_source_id = str(artifact_config.get("storage_source_id") or "").strip()
        artifact_source = storage_source_repository().get(artifact_source_id) if artifact_source_id else None
        portable_training_storage = bool(
            artifact_source
            and artifact_source.enabled
            and StorageType.parse(artifact_source.type) in {StorageType.OSS, StorageType.S3}
        )
    except Exception:
        portable_training_storage = False

    if training_agents and portable_training_storage:
        scheduler_algs = [
            dict(item)
            for item in TRAINING_CATALOG["algorithms"]
            if str(item.get("framework") or "").lower() == "ultralytics"
        ]
        # Each Agent receives an existing verified object staged by the
        # current portable training transport; never a downloadable filename.
        scheduler_models = _prepared_mother_model_rows()
        options.insert(0, {
            "id": "cluster_scheduler",
            "server_id": "",
            "name": f"GPU 集群自动调度（推荐） · {len(training_agents)} 节点在线",
            "type": "server",
            "framework": "ultralytics",
            "status": "ready" if any(model.get("trainable") is not False for model in scheduler_models) or has_iteration_base else "warning",
            "scheduler_owned": True,
            "online_training_nodes": len(training_agents),
            "algorithms": scheduler_algs,
            "base_models": scheduler_models,
            "recommendation": {
                "device": "auto",
                "resource_strategy": "auto",
                "resource_profile": "performance",
            },
        })

    # Legacy servers remain visible, but only an explicit, unexpired health
    # check may make them selectable. This GET must perform zero remote I/O.
    for s in read_json(SERVERS_FILE, []):
        caps = _cached_legacy_health(s)
        options.append({
            "id": f"server:{s.get('id')}",
            "server_id": s.get("id"),
            "name": s.get("name") or s.get("base_url"),
            "type":"server",
            "framework": caps.get("framework", "ultralytics") if caps.get("ok") else "unknown",
            "status": caps.get("status", "unknown"),
            "base_url": s.get("base_url"),
            "error": caps.get("error"),
            "last_checked_at": caps.get("checked_at", ""),
            "algorithms": caps.get("algorithms", []),
            "base_models": caps.get("base_models", []),
        })
    return {"ok": True, "targets": options}


from platform_core.runtime_catalog_contracts import TrainServerReq




from platform_core.runtime_catalog_contracts import PaddleEnvReq


def get_active_paddle_env() -> Dict[str, Any]:
    env = read_json(PADDLE_ENV_FILE, {})
    if not isinstance(env, dict):
        return {}
    return env


app.include_router(create_runtime_catalog_router_5(_runtime_catalog_service))


def get_paddle_env():
    return _runtime_catalog_service().get_paddle_env()


def select_paddle_env(payload: PaddleEnvReq):
    return _runtime_catalog_service().select_paddle_env(payload)


def test_paddle_env(payload: PaddleEnvReq):
    return _runtime_catalog_service().test_paddle_env(payload)


def default_paddle_roots() -> List[str]:
    configured = os.environ.get("MC_PADDLE_ROOTS", "")
    roots = [value for value in configured.split(os.pathsep) if value]
    roots.extend(
        [
            os.environ.get("MC_PADDLEDET_DIR", ""),
            os.environ.get("MC_PADDLEX_DIR", ""),
            str(BASE_DIR),
            str(Path.cwd()),
            str(Path(sys.executable).resolve().parent.parent),
            str(Path.home()),
        ]
    )
    return list(dict.fromkeys(value for value in roots if value))[:12]


def _detect_paddle_candidate(root: Path) -> Optional[Dict[str, Any]]:
    python_paths = _candidate_python_paths(root)
    if root.is_file() and root.name.lower() in {"python.exe", "python"}:
        python_paths = [root]
    # 如果用户填的是 PaddleDetection 目录，本身可能没有 venv，兜底用当前 Python 做模块检测。
    if not python_paths and root.exists():
        python_paths = [Path(sys.executable)]
    paddledet_dir = ""
    paddlex_dir = ""
    if root.exists() and root.is_dir():
        candidates = [root, root / "PaddleDetection", root.parent / "PaddleDetection"]
        paddledet_dir = str(next((x for x in candidates if (x / "tools" / "train.py").exists()), ""))
        x_candidates = [root, root / "PaddleX", root.parent / "PaddleX"]
        paddlex_dir = str(next((x for x in x_candidates if x.exists() and ("paddlex" in x.name.lower() or (x / "paddlex").exists())), ""))
    for py in python_paths[:3]:
        if not py.exists():
            continue
        mods = test_paddle_env(PaddleEnvReq(python_path=str(py), paddledet_dir=paddledet_dir, paddlex_dir=paddlex_dir))
        module_info = mods.get("modules", {})
        has_paddle = str(module_info.get("paddle", "")).startswith("missing:") is False and bool(module_info.get("paddle"))
        has_paddlex = str(module_info.get("paddlex", "")).startswith("missing:") is False and bool(module_info.get("paddlex"))
        if has_paddle or has_paddlex or paddledet_dir or paddlex_dir:
            return {
                "name": "本机飞桨",
                "python_path": str(py),
                "paddledet_dir": paddledet_dir,
                "paddlex_dir": paddlex_dir,
                "modules": module_info,
                "paddle_version": module_info.get("paddle", ""),
                "paddlex_version": module_info.get("paddlex", ""),
                "algorithm_scan": scan_paddledet_algorithms(paddledet_dir) if paddledet_dir else {"ok": False, "total": 0, "families": {}},
                "status": "ready" if has_paddle or has_paddlex else "warning",
                "root": str(root),
            }
    return None



def list_paddle_env_algorithms():
    return _runtime_catalog_service().list_paddle_env_algorithms()


def scan_paddle_env_algorithms(payload: PaddleEnvReq):
    return _runtime_catalog_service().scan_paddle_env_algorithms(payload)


from platform_core.runtime_catalog_contracts import PaddleDetectReq


def detect_paddle_env(payload: PaddleDetectReq):
    return _runtime_catalog_service().detect_paddle_env(payload)

def list_train_servers():
    return _runtime_catalog_service().list_train_servers()


def save_train_server(payload: TrainServerReq):
    return _runtime_catalog_service().save_train_server(payload)


def delete_train_server(server_id: str):
    return _runtime_catalog_service().delete_train_server(server_id)


def test_train_server(payload: TrainServerReq):
    return _runtime_catalog_service().test_train_server(payload)


def test_saved_train_server(server_id: str):
    return _runtime_catalog_service().test_saved_train_server(server_id)


def training_devices():
    return _runtime_catalog_service().training_devices()


def gpu_resources():
    return _runtime_catalog_service().gpu_resources()


# The creation admission (background confirmation, material-input admission and
# the opt-in synchronous preflight) is owned by
# platform_core.training_create_service; app.py only supplies the collaborators.
from platform_core.training_create_service import (  # noqa: E402
    TrainingCreateAdmission,
    TrainingIdentityDependencies,
    TrainingSplitDependencies,
    build_training_create_payload,
    confirmed_training_iteration_action,
    freeze_training_mother_model,
    prepare_training_create_admission,
    resolve_algorithm_asset,
    resolve_training_split,
)

# Training creation contract, validation and HTTP entry points are owned by
# platform_core.training_create_api. They are imported into this module so the
# existing internal references (automation, tests) keep working; app.py only
# assembles the dependencies below.
from platform_core.training_create_api import (  # noqa: E402
    TrainReq,
    TrainingCreateDependencies,
    build_training_create_router,
    start_training as _start_training,
    validate_train_request,
)


def _training_reusable_benchmark(
    project_id: str,
    asset_algorithm: Optional[Dict[str, Any]],
    source_version_id: str = "",
    observed_scope_id: str = "",
) -> Optional[Dict[str, Any]]:
    requested_version = str(source_version_id or "").strip()
    requested_scope = str(observed_scope_id or "").strip().lower()
    if not requested_version and not requested_scope:
        return None
    if not requested_version or not requested_scope:
        raise HTTPException(
            status_code=409,
            detail="复用评测基准需要同时提交来源版本和已观察到的 Benchmark Scope，请刷新训练配置后重试",
        )
    if not re.fullmatch(r"[0-9a-f]{64}", requested_scope):
        raise HTTPException(status_code=409, detail="Benchmark Scope 身份无效，请刷新训练配置后重试")
    if not isinstance(asset_algorithm, dict):
        raise HTTPException(status_code=409, detail="评测基准所属算法不存在")

    try:
        current_version_id = str(resolve_current_version_id(asset_algorithm) or "")
    except PlatformError as error:
        raise HTTPException(status_code=409, detail=error.detail or error.message) from error
    if not current_version_id or requested_version != current_version_id:
        raise HTTPException(
            status_code=409,
            detail="算法当前版本已变化，不能继续复用旧版本评测基准，请刷新训练配置后重试",
        )
    version = next(
        (
            row for row in list(asset_algorithm.get("versions") or [])
            if str(row.get("id") or row.get("version_id") or "").strip() == current_version_id
        ),
        None,
    )
    evaluation = version.get("evaluation") if isinstance(version, dict) else None
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    if evaluation.get('historical_independence') in {'assumed_unseen', 'known_exposed', 'unavailable'}:
        raise HTTPException(
            status_code=409,
            detail='来源版本 Test 历史独立性尚未严格核验，不能复用为固定 Benchmark',
        )
    if str(evaluation.get("status") or "").strip().lower() != "succeeded":
        raise HTTPException(status_code=409, detail="当前算法版本没有成功的独立评测，无法复用评测基准")
    scope = evaluation.get("benchmark_scope")
    scope = scope if isinstance(scope, dict) else {}
    scope_id = str(scope.get("scope_id") or "").strip().lower()
    if scope.get("binding_level") != "bundle_verified" or not re.fullmatch(r"[0-9a-f]{64}", scope_id):
        raise HTTPException(
            status_code=409,
            detail="当前算法版本缺少已校验 Test Bundle 的 Benchmark Scope，只能做描述性对比",
        )
    if scope_id != requested_scope:
        raise HTTPException(status_code=409, detail="Benchmark Scope 已变化，请刷新训练配置后重新确认")

    snapshot_id = str(evaluation.get("snapshot_id") or version.get("snapshot_id") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
        raise HTTPException(status_code=409, detail="评测基准缺少有效训练 Snapshot")
    snapshot_path = project_dir(project_id) / "snapshots" / f"{snapshot_id}.json"
    if not snapshot_path.is_file():
        raise HTTPException(status_code=409, detail="评测基准对应的训练 Snapshot 已不存在")
    snapshot = read_json(snapshot_path, {})
    if not isinstance(snapshot, dict) or str(snapshot.get("snapshot_id") or "").lower() != snapshot_id:
        raise HTTPException(status_code=409, detail="评测基准 Snapshot 身份不一致")

    from platform_core.training_evaluation import build_evaluation_benchmark_scope
    try:
        snapshot_scope = build_evaluation_benchmark_scope(snapshot)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    for key in ("test_image_count", "content_digest", "ground_truth_digest", "label_schema_digest"):
        if str(scope.get(key) or "") != str(snapshot_scope.get(key) or ""):
            raise HTTPException(
                status_code=409,
                detail="已归档 Benchmark Scope 与 Snapshot truth 不一致，不能复用",
            )

    raw_ids = snapshot.get("test_image_ids")
    if raw_ids is None and isinstance(snapshot.get("ids"), dict):
        raw_ids = snapshot["ids"].get("test")
    test_ids = tuple(
        dict.fromkeys(
            str(value or "").strip()
            for value in list(raw_ids or [])
            if str(value or "").strip()
        )
    )
    if not test_ids or len(test_ids) != int(scope.get("test_image_count") or 0):
        raise HTTPException(status_code=409, detail="评测基准试验素材清单不完整")

    records = {
        str(row.get("image_id") or ""): row
        for row in list(snapshot.get("images") or [])
        if isinstance(row, dict) and str(row.get("image_id") or "")
    }
    materials = MaterialRepository(project_dir(project_id))
    material_rows = materials.get_many(test_ids)
    material_by_id = {
        str(row.get("id") or ""): row
        for row in material_rows
        if str(row.get("id") or "")
    }
    annotations = AnnotationRepository(project_dir(project_id)).get_many(test_ids)
    for image_id in test_ids:
        frozen = records.get(image_id)
        material = material_by_id.get(image_id)
        annotation = annotations.get(image_id) or {}
        if frozen is None or material is None:
            raise HTTPException(
                status_code=409,
                detail=f"评测基准素材 {image_id} 已不存在，请重新建立基准",
            )
        if str(material.get("content_sha256") or "").lower() != str(
            frozen.get("content_sha256") or ""
        ).lower():
            raise HTTPException(
                status_code=409,
                detail=f"评测基准素材 {image_id} 内容已变化，请重新评测后再建立基准",
            )
        annotation_hash = str(
            annotation.get("content_digest")
            or material.get("annotation_hash")
            or ""
        ).lower()
        annotation_state = str(
            annotation.get("annotation_state")
            or material.get("annotation_state")
            or "unannotated"
        )
        if (
            annotation_hash != str(frozen.get("annotation_hash") or "").lower()
            or annotation_state != str(frozen.get("annotation_state") or "")
        ):
            raise HTTPException(
                status_code=409,
                detail=f"评测基准素材 {image_id} 标注已变化，请重新评测后再建立基准",
            )
    return {
        "source_version_id": current_version_id,
        "source_version_name": str(version.get("version_name") or current_version_id),
        "scope_id": scope_id,
        "snapshot_id": snapshot_id,
        "test_image_ids": test_ids,
        "test_image_count": len(test_ids),
        "binding_level": "bundle_verified",
    }


def _training_compatibility_request(
    project_id: str,
    asset_algorithm: Dict[str, Any],
    request: Mapping[str, Any],
) -> Dict[str, Any]:
    """Resolve server-private Benchmark IDs before the shared scope check."""
    if asset_algorithm is None:
        asset_algorithm = next((row for row in list_algorithms_internal(project_id)
            if str(row.get('id') or '') == str(request.get('algorithm_asset_id') or '')), None)
        if asset_algorithm is None:
            raise HTTPException(status_code=404, detail='训练算法不存在')
    resolved = dict(request)
    benchmark = _training_reusable_benchmark(
        project_id,
        asset_algorithm,
        str(request.get("benchmark_source_version_id") or ""),
        str(request.get("benchmark_scope_id") or ""),
    )
    if benchmark is None:
        return resolved
    submitted_test_ids = tuple(request.get("test_image_ids") or ())
    if submitted_test_ids:
        raise HTTPException(
            status_code=409,
            detail="复用固定评测基准时不能同时提交前端试验素材清单",
        )
    train_ids = tuple(request.get("train_image_ids") or request.get("image_ids") or ())
    test_ids = tuple(benchmark["test_image_ids"])
    rows = MaterialRepository(project_dir(project_id)).get_many((*train_ids, *test_ids))
    effective_train_ids, _reserved_ids = exclude_reserved_test_components(
        rows,
        train_ids,
        test_ids,
    )
    if not effective_train_ids:
        raise HTTPException(
            status_code=409,
            detail="所选训练候选全部属于固定评测保留范围",
        )
    resolved.update({
        "split_mode": SplitMode.INDEPENDENT_TEST_SET.value,
        "train_image_ids": list(effective_train_ids),
        "test_image_ids": list(test_ids),
        "experiment_percent": None,
    })
    if request.get("duplicate_review") is not None:
        resolved["duplicate_review"] = normalize_benchmark_duplicate_review(
            project_dir(project_id), request, SplitRequest(
                mode=SplitMode.INDEPENDENT_TEST_SET,
                train_image_ids=effective_train_ids,
                test_image_ids=test_ids,
                validation_percent=float(request.get("validation_percent") or 20),
            ),
        )
    return resolved


@app.get("/api/v12/projects/{project_id}/algorithms/{algorithm_id}/benchmark-reuse")
def training_benchmark_reuse(project_id: str, algorithm_id: str):
    get_project(project_id)
    algorithm = next(
        (
            row for row in list_algorithms_internal(project_id)
            if str(row.get("id") or "") == str(algorithm_id)
        ),
        None,
    )
    if algorithm is None:
        raise HTTPException(status_code=404, detail="算法不存在")
    try:
        current_version_id = str(resolve_current_version_id(algorithm) or "")
    except PlatformError as error:
        return {"available": False, "reason": error.detail or error.message}
    if not current_version_id:
        return {"available": False, "reason": "当前算法还没有可复用评测基准的正式版本"}
    version = next(
        (row for row in list(algorithm.get("versions") or []) if str(row.get("id") or "") == current_version_id),
        {},
    )
    evaluation = version.get("evaluation") if isinstance(version, dict) else {}
    scope = evaluation.get("benchmark_scope") if isinstance(evaluation, dict) else {}
    scope_id = str((scope or {}).get("scope_id") or "").strip().lower()
    if not scope_id:
        return {"available": False, "reason": "当前版本尚未冻结 Benchmark Scope"}
    try:
        resolved = _training_reusable_benchmark(
            project_id, algorithm, current_version_id, scope_id,
        )
    except HTTPException as error:
        return {"available": False, "reason": str(error.detail or "当前评测基准不可复用")}
    return {
        "available": True,
        "algorithm_id": str(algorithm_id),
        "source_version_id": resolved["source_version_id"],
        "source_version_name": resolved["source_version_name"],
        "scope_id": resolved["scope_id"],
        "snapshot_id": resolved["snapshot_id"],
        "test_image_count": resolved["test_image_count"],
        "binding_level": resolved["binding_level"],
    }


def _training_supplement_candidate_set(
    project_id: str,
    asset_algorithm: Optional[Dict[str, Any]],
    payload: TrainReq,
    split: SplitRequest,
) -> Optional[Dict[str, Any]]:
    requested_id = str(payload.supplement_candidate_set_id or "").strip().lower()
    if not isinstance(asset_algorithm, dict):
        if requested_id:
            raise HTTPException(status_code=409, detail="补数据 Candidate Set 所属算法不存在")
        return None

    current_version_id = str(asset_algorithm.get("current_version_id") or "").strip()
    current_version = next(
        (
            row for row in list(asset_algorithm.get("versions") or [])
            if str(row.get("id") or row.get("version_id") or "").strip() == current_version_id
        ),
        None,
    )
    candidate_set = (
        current_version.get("supplement_data_candidate_set")
        if isinstance(current_version, dict)
        else None
    )
    if not isinstance(candidate_set, dict) or not str(candidate_set.get("candidate_set_id") or ""):
        if requested_id:
            raise HTTPException(status_code=409, detail="当前算法版本没有可用的补数据 Candidate Set")
        return None

    selected_ids = {
        str(value)
        for value in (*split.train_image_ids, *split.test_image_ids)
        if str(value)
    }
    candidate_material_ids = {
        str(value)
        for value in list(candidate_set.get("material_ids") or [])
        if str(value)
    }
    adopted_ids = sorted(selected_ids.intersection(candidate_material_ids))
    if not adopted_ids:
        if requested_id:
            raise HTTPException(status_code=409, detail="本次训练未实际选择 Candidate Set 中的素材")
        return None

    candidate_set_id = str(candidate_set.get("candidate_set_id") or "").strip().lower()
    if requested_id != candidate_set_id:
        raise HTTPException(
            status_code=409,
            detail="训练请求缺少或使用了过期的 Candidate Set，请刷新训练配置后重试",
        )

    materials = MaterialRepository(project_dir(project_id))
    material_rows = materials.get_many(adopted_ids)
    material_by_id = {
        str(row.get("id") or ""): row
        for row in material_rows
        if str(row.get("id") or "")
    }
    annotations = AnnotationRepository(project_dir(project_id)).get_many(adopted_ids)
    truth_rows = []
    for material_id in adopted_ids:
        material = material_by_id.get(material_id)
        if material is None:
            raise HTTPException(status_code=409, detail=f"补数据素材 {material_id} 已不存在")
        annotation = annotations.get(material_id) or {}
        truth_rows.append({
            "id": material_id,
            "content_sha256": str(material.get("content_sha256") or ""),
            "annotation_hash": str(
                annotation.get("content_digest")
                or material.get("annotation_hash")
                or ""
            ),
            "annotation_state": str(
                annotation.get("annotation_state")
                or material.get("annotation_state")
                or "unannotated"
            ),
        })

    from platform_core.online_feedback import build_supplement_training_provenance
    from platform_core.hard_sample_mining import assert_not_frozen_test, HardSampleSafetyError
    try:
        assert_not_frozen_test(project_dir(project_id), adopted_ids,
                              {row['id']: row['content_sha256'] for row in truth_rows})
        build_supplement_training_provenance(candidate_set, selected_ids, truth_rows)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return dict(candidate_set)


@app.get("/api/v62/projects/{project_id}/training-labels/inherited")
def training_inherited_labels_preview(
    project_id: str,
    algorithm_id: str,
    base_version_id: str = "",
):
    get_project(project_id)
    # The preview belongs to a single algorithm; loading every algorithm's
    # frozen versions/GT reports can block an otherwise tiny label request.
    algorithm = next(iter(list_algorithms_internal(
        project_id, algorithm_id=str(algorithm_id or ""), summary_only=True,
    )), None)
    if algorithm is None:
        raise HTTPException(status_code=404, detail="训练算法不存在")
    try:
        return inherited_training_label_preview(
            DATA_DIR,
            project_dir(project_id),
            algorithm,
            base_version_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


_TRAINING_TASK_ID_PATTERN = re.compile(r"train_[0-9a-f]{16,32}")


def _new_training_task_id() -> str:
    return f"train_{uuid.uuid4().hex[:24]}"


def _ensure_training_create_job(
    project_id: str, task_id: str, record: TaskRecord,
    request_payload: Mapping[str, Any],
) -> None:
    """Write the original queue projection once, never overwrite worker progress."""
    job_path = project_dir(project_id) / "jobs" / task_id / "job.json"
    if job_path.is_file():
        return
    payload = TrainReq.model_validate(request_payload["admission_request"])
    asset_algorithm = dict(request_payload["algorithm_identity"])
    confirmed_iteration_action = request_payload.get("confirmed_iteration_action")
    framework = str(payload.framework or "ultralytics").strip().lower()
    target = str(payload.target or "local").strip().lower()
    resource_key = str(request_payload["target_resource_key"])
    job_dir = project_dir(project_id) / "jobs" / task_id
    job_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        job_dir / "job.json",
        {
            "id": task_id,
            "task_id": task_id,
            "status": "queued",
            "task_stage": "training_input_pending",
            "phase": "training_input_pending",
            "message": "训练任务已创建，正在后台准备输入",
            "framework": framework,
            "target": target,
            "asset_algorithm_id": str(asset_algorithm.get("id") or ""),
            "algorithm_asset_id": str(asset_algorithm.get("id") or ""),
            "asset_algorithm_name": str(asset_algorithm.get("name") or "已删除算法"),
            "asset_algorithm_source_type": (asset_algorithm or {}).get("source_type", "LOCAL"),
            "external_provider": (asset_algorithm or {}).get("provider_type", ""),
            "external_product_id": (asset_algorithm or {}).get("external_product_id", ""),
            "external_analysis_id": str(payload.external_analysis_id or ""),
            "external_category_id": (asset_algorithm or {}).get("external_category_id", ""),
            "confirmed_iteration_action": confirmed_iteration_action,
            "supplement_candidate_set_id": str(payload.supplement_candidate_set_id or ""),
            "algorithm": payload.algorithm,
            "model": payload.model,
            "queue_priority": int(payload.queue_priority),
            "resource_key": resource_key,
            "device": payload.device,
            "requested_device": payload.device,
            "assigned_device": None,
            "actual_device": None,
            "split_mode": str(request_payload["requested_split"]["mode"]),
            "requested_train_images": len(request_payload["requested_split"]["train_image_ids"]),
            "requested_test_images": len(request_payload["requested_split"]["test_image_ids"]),
            "dataset_counts": {"train": 0, "validation": 0, "test": 0, "total": 0},
            "requested_resources": request_payload["requested_resources"],
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "artifact_verified": False,
        },
    )
    sync_jobs_index(project_id)


def _ensure_training_prepare_child(
    project_id: str, task_id: str, prepare_task_id: str, priority: int,
) -> TaskRecord:
    """Recreate only a missing deterministic child; never overwrite a live payload."""
    from platform_core.training_prepare_child import ensure_training_prepare_child
    try:
        return ensure_training_prepare_child(
            shared_task_repository(), shared_task_artifacts(),
            project_id, task_id, prepare_task_id, priority,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def _reconcile_training_create_replay(
    project_id: str, parent: TaskRecord, stored_payload: Mapping[str, Any],
) -> TaskRecord:
    """Recover a parent/prepare half-commit, never retry unrelated terminal tasks."""
    task_id = parent.task_id
    prepare_id = str(stored_payload.get("training_prepare_task_id") or "")
    if prepare_id != f"trainprep_{task_id}":
        raise HTTPException(status_code=409, detail="训练父子任务身份不一致")
    unclaimable = parent.required_capabilities == ("training.input.ready",)
    queued = (
        unclaimable and parent.status is TaskStatus.QUEUED
        and parent.stage in {"training_input_pending", "queued"}
    )
    create_failed = (
        unclaimable and parent.status is TaskStatus.BLOCKED_BY_ENVIRONMENT
        and parent.stage == "training_input_preparation_failed"
        and str(parent.error or "").startswith("TRAINING_PREP_TASK_CREATE_FAILED:")
    )
    if not queued and not create_failed:
        return parent
    repository = shared_task_repository()
    child = repository.get(prepare_id)
    if child is not None and child.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
        raise HTTPException(
            status_code=409, detail="训练准备子任务已结束，创建请求不可重新触发执行",
        )
    if create_failed:
        parent = repository.retry(task_id)
    try:
        _ensure_training_create_job(project_id, task_id, parent, stored_payload)
        _ensure_training_prepare_child(
            project_id, task_id, prepare_id,
            int(stored_payload.get("queue_priority", 50)),
        )
    except Exception as error:
        repository.fail_queued_precondition(
            task_id, f"TRAINING_PREP_TASK_CREATE_FAILED: {error}",
            status=TaskStatus.BLOCKED_BY_ENVIRONMENT,
            stage="training_input_preparation_failed",
        )
        raise
    return repository.get(task_id) or parent


# Split/role resolution collaborators: dataset selection references and the
# fixed-ZIP source proof keep their existing owners, resolved at use time.
_TRAINING_SPLIT = TrainingSplitDependencies(
    data_dir=lambda: DATA_DIR,
    material_store=lambda project_id: material_store(project_id),
)

def _explicit_training_split(
    payload: TrainReq, project_id: str = "",
) -> SplitRequest:
    """Compatibility binding: split resolution is owned by the creation service.

    Existing in-process callers keep this name; the implementation (selection
    references, fixed-ZIP proof, role ids) lives in training_create_service.
    """
    return resolve_training_split(
        payload=payload, project_id=project_id, dependencies=_TRAINING_SPLIT,
    )


# Training identity collaborators: asset lookup, the creation-time reference
# version, the confirmed iteration action and the mother-model freeze all stay
# with the existing owners and are resolved at use time.
_TRAINING_IDENTITY = TrainingIdentityDependencies(
    list_algorithms=lambda project_id: list_algorithms_internal(project_id),
    current_version_id=lambda asset_algorithm: resolve_current_version_id(asset_algorithm),
    confirmed_iteration_action=lambda asset_algorithm, payload: (
        _validated_training_iteration_action(asset_algorithm, payload)
    ),
    freeze_mother_model=lambda project_id, model: _ready_ultralytics_mother_model(
        project_id, model
    ),
)

# Creation admission collaborators: the service never imports app, so every
# store, artifact root and project helper is resolved through a callable at use
# time (tests and callers may replace these module-level bindings).
_TRAINING_CREATE_ADMISSION = TrainingCreateAdmission(
    data_dir=lambda: DATA_DIR,
    repository=lambda: shared_task_repository(),
    artifacts=lambda: shared_task_artifacts(),
    material_store=lambda project_id: material_store(project_id),
    compatibility_request=lambda project_id, asset_algorithm, request: (
        _training_compatibility_request(project_id, asset_algorithm, request)
    ),
    selected_input_fingerprint=lambda path, image_ids: (
        training_background_selection_fingerprint(path, image_ids)
    ),
    compatibility_evaluator=lambda data_dir, project_path, request, asset: (
        evaluate_training_compatibility(data_dir, project_path, request, asset)
    ),
    compatibility_page=lambda compatibility, **kwargs: compatibility_page(
        compatibility, **kwargs
    ),
)


def _enqueue_explicit_training(
    project_id: str, payload: TrainReq, *, review_actor_id: str = "",
) -> JSONResponse:
    """Task-ID create/repair is serialized across Web workers before any write."""
    requested = str(payload.task_id or "").strip()
    if requested and not _TRAINING_TASK_ID_PATTERN.fullmatch(requested):
        raise HTTPException(status_code=422, detail="训练任务 ID 格式不正确")
    task_id = requested or _new_training_task_id()
    locks_dir = DATA_DIR / "task_runtime" / "training_create_locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(locks_dir / f"{task_id}.lock"), timeout=30):
            return _enqueue_explicit_training_locked(
                project_id, payload, task_id, review_actor_id=review_actor_id,
            )
    except Timeout as error:
        raise PlatformError(
            code="TRAINING_CREATE_IN_PROGRESS", status_code=409,
            message="相同训练任务正在创建，请按原任务 ID 查询创建结果",
            detail=task_id, solution="保留原任务 ID，确认结果后再操作。",
        ) from error


def _enqueue_explicit_training_locked(
    project_id: str, payload: TrainReq, task_id: str, *, review_actor_id: str = "",
) -> JSONResponse:
    if shared_task_repository().is_deleted(task_id):
        raise HTTPException(status_code=409,detail="TASK_ID_RETIRED: 已删除任务身份不能重新创建")
    if payload.review_all_training_backgrounds and (
        payload.admission_mode != "background" or not review_actor_id.strip()
    ):
        raise HTTPException(
            status_code=422,
            detail="后台训练样本批量确认必须由已登录用户在快速创建时明确发起",
        )
    reference_request_identity = ""
    if payload.train_selection_ref or payload.validation_selection_ref or payload.test_selection_ref:
        # Durable request identity is bound before live-ref revision checks.
        reference_request_identity=hashlib.sha256(json.dumps(payload.model_dump(mode='json',exclude_none=True),
            ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if payload.task_id:
            existing=shared_task_repository().get(task_id)
            if existing is not None:
                stored=shared_task_artifacts().read_json(task_id,existing.payload_ref,default={})
                if (existing.project_id!=project_id or existing.kind is not TaskKind.TRAINING
                    or stored.get('reference_request_identity')!=reference_request_identity):
                    raise HTTPException(409,'训练任务 ID 已绑定其他请求，不能静默复用')
                existing=_reconcile_training_create_replay(project_id,existing,stored)
                return JSONResponse(status_code=202,content={'ok':True,'task':_public_task(existing),'idempotent':True})
    asset_algorithm, reference_version_id = resolve_algorithm_asset(
        project_id=project_id, payload=payload, dependencies=_TRAINING_IDENTITY,
    )
    try:
        requested_split = resolve_training_split(
            payload=payload, project_id=project_id,
            dependencies=_TRAINING_SPLIT,
        )
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    confirmed_iteration_action = confirmed_training_iteration_action(
        payload=payload, asset_algorithm=asset_algorithm,
        dependencies=_TRAINING_IDENTITY,
    )
    framework = str(payload.framework or "ultralytics").strip().lower()
    target = str(payload.target or "local").strip().lower()
    if target == "remote":
        # v42.25 control-plane scheduling replaces the legacy direct remote
        # server upload path. server_id is retained only as an optional
        # compatibility/affinity label; the central service-node allocator owns
        # the actual Agent selection.
        remote_id = str(payload.server_id or "").strip() or "scheduler"
        resource_key = f"training:remote:{remote_id}"
    else:
        device = normalize_training_device(payload.device)
        resource_key = f"training:{device}"
    requested_task_id = str(payload.task_id or "").strip()
    if requested_task_id and not _TRAINING_TASK_ID_PATTERN.fullmatch(requested_task_id):
        raise HTTPException(status_code=422, detail="训练任务 ID 格式不正确")
    if requested_task_id and requested_task_id != task_id:
        raise HTTPException(status_code=409, detail="训练任务 ID 与并发创建锁身份不一致")
    raw_request = payload.model_dump(mode="json", exclude_none=True)
    if requested_split.mode is SplitMode.FIXED_ZIP_TRAIN_VAL_TEST:
        raw_request.update(validation_percent=None, experiment_percent=None)
    request_identity = hashlib.sha256(
        json.dumps(raw_request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if requested_task_id:
        existing_task = shared_task_repository().get(task_id)
        if existing_task is not None:
            if existing_task.project_id == project_id and existing_task.kind is TaskKind.TRAINING:
                existing_payload = shared_task_artifacts().read_json(
                    task_id, existing_task.payload_ref, default={},
                )
                if str((existing_payload or {}).get("request_identity") or "") != request_identity:
                    raise HTTPException(
                        status_code=409,
                        detail="训练任务 ID 已绑定其他请求，不能静默复用",
                    )
                existing_task = _reconcile_training_create_replay(
                    project_id, existing_task, existing_payload,
                )
                return JSONResponse(status_code=202, content={
                    "ok": True, "task": _public_task(existing_task), "idempotent": True,
                })
            raise HTTPException(status_code=409, detail="训练任务 ID 已被占用")
    # Idempotent replays are resolved above without doing new filesystem IO.
    # On first creation, freeze the local path before persisting any task.
    frozen_mother_model = freeze_training_mother_model(
        project_id=project_id, payload=payload, asset_algorithm=asset_algorithm,
        dependencies=_TRAINING_IDENTITY,
    )
    if frozen_mother_model:
        payload.model = frozen_mother_model
        raw_request["model"] = frozen_mother_model
    prepare_task_id = f"trainprep_{task_id}"
    frozen_robustness = {}
    if payload.robustness_policy is not None:
        from platform_core.training_robustness import resolve_policy
        try:
            frozen_robustness = {"robustness_policy": resolve_policy(DATA_DIR, payload.robustness_policy)}
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    request_payload = build_training_create_payload(
        project_id=project_id, task_id=task_id, payload=payload,
        asset_algorithm=asset_algorithm,
        reference_version_id=reference_version_id,
        confirmed_iteration_action=confirmed_iteration_action,
        requested_split=requested_split, raw_request=raw_request,
        request_identity=request_identity,
        reference_request_identity=reference_request_identity,
        prepare_task_id=prepare_task_id, frozen_robustness=frozen_robustness,
        framework=framework, target=target, resource_key=resource_key,
    )
    with _storage_source_fence(), _algorithm_version_reference_fence(
        project_id,
        str(asset_algorithm.get("id") or ""),
        reference_version_id,
        require_current=True,
    ), material_annotation_lifecycle_fence(project_dir(project_id)):
        try:
            confirmation_block, compatibility = prepare_training_create_admission(
                project_id=project_id,
                task_id=task_id,
                payload=payload,
                asset_algorithm=asset_algorithm,
                requested_split=requested_split,
                raw_request=raw_request,
                request_identity=request_identity,
                review_actor_id=review_actor_id,
                project_path=project_dir(project_id),
                admission=_TRAINING_CREATE_ADMISSION,
            )
            if confirmation_block:
                request_payload["training_background_confirmation"] = confirmation_block
            from platform_core.training_selection_reference import mark_selection_submitted
            for reference in (payload.train_selection_ref,payload.validation_selection_ref,payload.test_selection_ref):
                if reference:mark_selection_submitted(DATA_DIR,reference,task_id)
            from platform_core.task_runtime.payload_publications import PayloadPublicationIdentity
            initial_payload = shared_task_artifacts().prepare_payload_publication(PayloadPublicationIdentity(
                task_id=task_id,project_id=project_id,kind='TRAINING',phase='create',expected_ref='',
                expected_parent_attempt=0,intent={'request_id':task_id}),request_payload)
            record = shared_task_repository().create(
                replace(
                    TaskRecord.new(
                        task_id,
                        project_id,
                        TaskKind.TRAINING,
                        initial_payload.version.payload_ref,
                        resource_key,
                        priority=int(payload.queue_priority),
                        required_capabilities=("training.input.ready",),
                    ),
                    stage="training_input_pending",
                    current_item="正在后台准备训练输入",
                )
            )
        except BaseException:
            if shared_task_repository().get(task_id) is None:
                from platform_core.training_selection_reference import release_unpersisted_selection_claim
                for reference in (payload.train_selection_ref,payload.validation_selection_ref,payload.test_selection_ref):
                    if reference:release_unpersisted_selection_claim(DATA_DIR,reference,task_id)
            raise
    try:
        # A queued training parent remains unclaimable until its prepare child
        # completes; publish the original job projection before that child.
        _ensure_training_create_job(project_id, task_id, record, request_payload)
        preparation_record = _ensure_training_prepare_child(
            project_id, task_id, prepare_task_id, int(payload.queue_priority),
        )
    except Exception as error:
        shared_task_repository().fail_queued_precondition(
            task_id,
            f"TRAINING_PREP_TASK_CREATE_FAILED: {error}",
            status=TaskStatus.BLOCKED_BY_ENVIRONMENT,
            stage="training_input_preparation_failed",
        )
        raise
    return JSONResponse(
        status_code=202,
        content={
            "ok": True,
            "task": _public_task(record),
            "preparation_task_id": preparation_record.task_id,
            "training_input_state": "PREPARING",
            **({"remote_input_state": "PREPARING"} if target == "remote" else {}),
        },
    )


def check_ultralytics_train_runtime(python_path: str):
    """Quick import test before creating a job. It catches broken external environments immediately."""
    try:
        cp = subprocess.run(
            [python_path, "-c", "import torch, torchvision, ultralytics; from ultralytics import YOLO; print(torch.__version__, torchvision.__version__, ultralytics.__version__)"],
            cwd=str(BASE_DIR), capture_output=True, text=True, errors="replace", timeout=30,
            env={**os.environ.copy(), "PYTHONUTF8":"1", "PYTHONIOENCODING":"utf-8"},
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"训练环境检查失败：{e}")
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or "未知错误").strip().splitlines()
        raise HTTPException(status_code=400, detail="训练环境不可用：" + " | ".join(detail[-5:]))
    return (cp.stdout or "").strip()


def _safe_paddle_lr(payload_lr: float, image_count: int = 0, is_cpu: bool = True) -> float:
    """PaddleDetection 原始 COCO 配置学习率通常偏高；小数据/CPU默认降到安全值。"""
    try:
        lr = float(payload_lr or 0)
    except Exception:
        lr = 0.0
    # 用户未设置、设置过高、或数据量很小时，一律用保守学习率，避免 NaN。
    if lr <= 0 or lr >= 0.01 or image_count < 200 or is_cpu:
        return 0.001
    return max(1e-5, min(lr, 0.005))


def _paddle_family_key(alg: Optional[Dict[str, Any]]) -> str:
    return str((alg or {}).get("family_key") or (alg or {}).get("family") or "").lower().replace("-", "_")


def resolve_server(payload: TrainReq) -> Dict[str, Any]:
    servers = read_json(SERVERS_FILE, [])
    if payload.server_id:
        server = next((s for s in servers if s.get("id") == payload.server_id), None)
        if not server:
            raise HTTPException(status_code=400, detail="训练服务器不存在")
        return server
    if payload.remote_url:
        return {"id": "manual", "name": "手动地址", "base_url": payload.remote_url.strip().rstrip("/"), "api_key": payload.api_key or ""}
    raise HTTPException(status_code=400, detail="请选择或填写远程训练服务器")


def add_job_to_index(project_id: str, job: Dict[str, Any]):
    jobs_index_file = project_dir(project_id) / "jobs" / "index.json"
    jobs = read_json(jobs_index_file, [])
    jobs.insert(0, job)
    write_json(jobs_index_file, jobs[:50])


from platform_core.training_management_service import TrainingManagementDependencies, TrainingManagementService
from platform_core.training_management_api import create_training_management_router_1, create_training_management_router_2


def _training_management_service() -> TrainingManagementService:
    return TrainingManagementService(TrainingManagementDependencies(
        PROCESS_REGISTRY=lambda: PROCESS_REGISTRY,
        V56_PRIORITY_SCHEME=lambda: V56_PRIORITY_SCHEME,
        _TRAINING_DURABLE_TERMINAL_STATUSES=lambda: _TRAINING_DURABLE_TERMINAL_STATUSES,
        _TRAINING_LEGACY_TERMINAL_STATUSES=lambda: _TRAINING_LEGACY_TERMINAL_STATUSES,
        _TRAINING_STREAM_ACTIVE_STATUSES=lambda: _TRAINING_STREAM_ACTIVE_STATUSES,
        _cancel_training_prepare_child=lambda *args, **kwargs: _cancel_training_prepare_child(*args, **kwargs),
        _durable_process_identity=lambda *args, **kwargs: _durable_process_identity(*args, **kwargs),
        _durable_training_task=lambda *args, **kwargs: _durable_training_task(*args, **kwargs),
        _parse_dt_value=lambda *args, **kwargs: _parse_dt_value(*args, **kwargs),
        _pid_alive=lambda *args, **kwargs: _pid_alive(*args, **kwargs),
        _terminate_pid_tree=lambda *args, **kwargs: _terminate_pid_tree(*args, **kwargs),
        _v48_all_job_files=lambda *args, **kwargs: _v48_all_job_files(*args, **kwargs),
        _v48_archive_training_version=lambda *args, **kwargs: _v48_archive_training_version(*args, **kwargs),
        _v48_dispatch_training_queues=lambda *args, **kwargs: _v48_dispatch_training_queues(*args, **kwargs),
        _v48_resource_key=lambda *args, **kwargs: _v48_resource_key(*args, **kwargs),
        _v48_suspend_tree=lambda *args, **kwargs: _v48_suspend_tree(*args, **kwargs),
        _v53_fast_jobs_summary=lambda *args, **kwargs: _v53_fast_jobs_summary(*args, **kwargs),
        _v53_job_summary=lambda *args, **kwargs: _v53_job_summary(*args, **kwargs),
        _v56_normalize_priority=lambda *args, **kwargs: _v56_normalize_priority(*args, **kwargs),
        _write_job_json=lambda *args, **kwargs: _write_job_json(*args, **kwargs),
        enrich_job_runtime=lambda *args, **kwargs: enrich_job_runtime(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        read_json=lambda *args, **kwargs: read_json(*args, **kwargs),
        shared_task_artifacts=lambda *args, **kwargs: shared_task_artifacts(*args, **kwargs),
        shared_task_repository=lambda *args, **kwargs: shared_task_repository(*args, **kwargs),
        sync_jobs_index=lambda *args, **kwargs: sync_jobs_index(*args, **kwargs),
        sync_remote_job=lambda *args, **kwargs: sync_remote_job(*args, **kwargs),
    ))


app.include_router(create_training_management_router_1(_training_management_service))


def list_jobs(project_id: str, summary_only: bool=False):
    return _training_management_service().list_jobs(project_id, summary_only)



_TRAINING_STREAM_ACTIVE_STATUSES = (
    TaskStatus.QUEUED,
    TaskStatus.RUNNING,
    TaskStatus.CANCEL_REQUESTED,
)


def _training_event_row(project_id: str, task: TaskRecord) -> Dict[str, Any]:
    return _training_management_service()._training_event_row(project_id, task)


def _training_event_rows(project_id: str, repository: Optional[TaskRepository]=None) -> List[Dict[str, Any]]:
    return _training_management_service()._training_event_rows(project_id, repository)


def _training_event_signature(row: Mapping[str, Any]) -> Tuple[Any, ...]:
    return _training_management_service()._training_event_signature(row)


def _training_sse_message(row: Mapping[str, Any]) -> str:
    return _training_management_service()._training_sse_message(row)


async def v64_training_events(project_id: str, request: Request):
    return await _training_management_service().v64_training_events(project_id, request)


def job_status(project_id: str, job_id: str, include_history: bool=False):
    return _training_management_service().job_status(project_id, job_id, include_history)


def _tail_training_log_text(path: Path, max_chars: int=120000) -> str:
    return _training_management_service()._tail_training_log_text(path, max_chars)


def job_log(project_id: str, job_id: str):
    return _training_management_service().job_log(project_id, job_id)


def stop_job(project_id: str, job_id: str):
    return _training_management_service().stop_job(project_id, job_id)


def sync_remote_job(project_id: str, job_id: str) -> Dict[str, Any]:
    p = project_dir(project_id)
    job_file = p / "jobs" / job_id / "job.json"
    job = read_json(job_file, {})
    remote = job.get("remote") or {}
    if not remote.get("base_url") or not remote.get("job_id"):
        return job
    base_url = remote["base_url"].rstrip("/")
    headers = {"X-API-Key": remote.get("api_key", "")}
    log_file = p / "jobs" / job_id / "train.log"
    try:
        r = requests.get(f"{base_url}/api/remote/jobs/{remote['job_id']}", headers=headers, timeout=10)
        r.raise_for_status()
        remote_job = r.json()
        job.update({
            "status": remote_job.get("status", job.get("status")),
            "message": remote_job.get("message", job.get("message")),
            "updated_at": now_iso(),
            "remote_status": remote_job,
        })
        lr = requests.get(f"{base_url}/api/remote/jobs/{remote['job_id']}/log", headers=headers, timeout=15)
        if lr.ok:
            log_file.write_text(lr.text, encoding="utf-8", errors="ignore")
        if job["status"] == "done" and not job.get("remote_models_pulled"):
            pulled = []
            for model_name in remote_job.get("models", []):
                try:
                    mr = requests.get(f"{base_url}/api/remote/jobs/{remote['job_id']}/models/{Path(model_name).name}", headers=headers, timeout=120)
                    if mr.ok and mr.content:
                        dst = p / "models" / f"{job['run_name']}_remote_{Path(model_name).name}"
                        dst.write_bytes(mr.content)
                        pulled.append(str(dst))
                except Exception:
                    pass
            job["models"] = pulled
            job["remote_models_pulled"] = True
            if pulled:
                job["message"] = "远程训练完成，模型已拉回本机"
        _write_job_json(job_file, job)
    except Exception as e:
        log_file.write_text((log_file.read_text(encoding="utf-8", errors="ignore") if log_file.exists() else "") + f"\n[{now_iso()}] 同步远程任务失败：{e}\n", encoding="utf-8")
    return job


_TRAINING_JOB_ACTIVE_STATUSES = {
    "queued", "waiting", "pending", "starting", "running",
    "pausing", "paused", "resuming", "stopping", "cancel_requested",
}
_TRAINING_TASK_ACTIVE_STATUSES = {
    "QUEUED", "WAITING_RESOURCE", "PENDING", "STARTING", "RUNNING",
    "PAUSING", "PAUSED", "RESUMING", "STOPPING", "CANCEL_REQUESTED",
}


def _training_job_is_active(job: Mapping[str, Any]) -> bool:
    status = str(job.get("status") or "").strip().lower()
    task_status = str(
        job.get("task_status") or job.get("persisted_status") or ""
    ).strip().upper()
    return status in _TRAINING_JOB_ACTIVE_STATUSES or task_status in _TRAINING_TASK_ACTIVE_STATUSES


def _training_job_index_rows(
    jobs: Sequence[Mapping[str, Any]],
    *,
    history_limit: int = 50,
) -> List[Dict[str, Any]]:
    """Retain every live task plus a bounded terminal history."""
    canonical: Dict[str, Dict[str, Any]] = {}
    for source in jobs:
        if not isinstance(source, Mapping):
            continue
        row = dict(source)
        task_id = str(row.get("task_id") or row.get("id") or "").strip()
        if not task_id:
            continue
        current = canonical.get(task_id)
        if current is None:
            canonical[task_id] = row
            continue
        current_is_parent = str(current.get("id") or "") == task_id
        row_is_parent = str(row.get("id") or "") == task_id
        if row_is_parent and not current_is_parent:
            canonical[task_id] = row
        elif row_is_parent == current_is_parent and str(row.get("updated_at") or row.get("created_at") or "") > str(
            current.get("updated_at") or current.get("created_at") or ""
        ):
            canonical[task_id] = row
    ordered = sorted(
        canonical.values(),
        key=lambda row: str(row.get("created_at") or ""),
        reverse=True,
    )
    active = [row for row in ordered if _training_job_is_active(row)]
    history = [row for row in ordered if not _training_job_is_active(row)]
    if history_limit >= 0:
        history = history[:history_limit]
    rows = active + history
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return rows


from platform_core.training_history_projection import TrainingHistoryProjection, successful_training_counts

_TRAINING_HISTORY_PROJECTION = TrainingHistoryProjection()
_TRAINING_JOB_PROJECTION_LOCK = threading.RLock()
_TRAINING_JOB_PROJECTIONS = {}
_TRAINING_COUNT_PAYLOADS = {}


@performance_stage("training_history")
def _training_history_context(project_id: str):
    rows = _TRAINING_HISTORY_PROJECTION.read(
        project_dir(project_id) / "jobs", lambda path: read_json(path, {}),
    )
    repository = shared_task_repository()
    retired=repository.deleted_task_ids((row.get('task_id') or row.get('id') for row in rows),project_id=project_id)
    rows=[row for row in rows if str(row.get('task_id') or row.get('id')) not in retired]
    durable = {}
    cursor = None
    while True:
        page = repository.list(project_id=project_id, kinds=(TaskKind.TRAINING,), limit=100, cursor=cursor)
        durable.update((task.task_id, task) for task in page.items)
        cursor = page.next_cursor
        if not cursor:
            break
    performance_count("history_job_rows", len(rows))
    performance_count("history_task_rows", len(durable))
    return rows, repository, durable


def _successful_training_counts(project_id: str, *, history_context=None):
    rows, _repository, durable = history_context if history_context is not None else _training_history_context(project_id)
    rows = [row for row in rows if not row.get("project_id") or str(row["project_id"]) == str(project_id)]
    identities = {str(row.get("task_id") or row.get("id") or "") for row in rows}
    for identity, task in durable.items():
        if identity in identities or task.status not in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS} or not task.result_ref:
            continue
        # Payloads are task-owned immutable creation evidence. Cache by revision
        # to retain archived tasks even when no legacy job.json remains.
        key = (str(_repository.path), identity)
        with _TRAINING_JOB_PROJECTION_LOCK:
            cached = _TRAINING_COUNT_PAYLOADS.get(key)
            if cached is None or cached[0] != task.updated_at:
                payload = shared_task_artifacts().read_json(identity, task.payload_ref, default={})
                _TRAINING_COUNT_PAYLOADS[key] = (task.updated_at, payload)
            else:
                payload = cached[1]
        if isinstance(payload, dict):
            rows.append({**payload, "id": identity, "task_id": identity})
    return successful_training_counts(rows, {
        identity: {"status": task.status.value, "kind": task.kind.value, "result_ref": task.result_ref}
        for identity, task in durable.items()
    })


@performance_stage("training_index")
def sync_jobs_index(project_id: str, *, history_context=None, read_only: bool = False):
    jobs_dir = project_dir(project_id) / "jobs"
    # Serialise only the read projection, never worker publication or scheduling.
    with _TRAINING_JOB_PROJECTION_LOCK:
        raw_rows, repository, durable = history_context if history_context is not None else _training_history_context(project_id)
        key = str(jobs_dir.resolve())
        previous = _TRAINING_JOB_PROJECTIONS.get(key, {})
        current = {}
        worker_runtime = WorkerInstanceService(repository).list_runtime()
        queued_candidates = repository.queued_candidates()
        jobs = []
        for raw in raw_rows:
            identity = str(raw.get("task_id") or raw.get("id") or "")
            task = durable.get(identity)
            revision = (task.updated_at, task.status.value, task.result_ref) if task else None
            old = previous.get(str(raw.get("id") or identity))
            pending_legacy_archive = (
                not read_only and task is None
                and str(raw.get("status") or "").lower() in {"done", "finished", "completed", "succeeded", "success"}
                and raw.get("artifact_verified") is True and bool(raw.get("asset_algorithm_id"))
                and not raw.get("auto_version_id")
            )
            if old is not None and old[0] == raw and old[1] == revision and not _training_job_is_active(old[2]) and not pending_legacy_archive:
                job = old[2]
            else:
                projection_task = durable.get(str(raw.get("id") or ""))
                if projection_task is None or projection_task.status not in {
                    TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED,
                }:
                    # Active leases and newly adopted legacy identities retain
                    # the original fresh get; only known terminal rows use the
                    # already-read record for this response projection.
                    projection_task = _TRAINING_TASK_NOT_LOADED
                job = enrich_job_runtime(
                    project_id, dict(raw), repository=repository,
                    worker_runtime=worker_runtime, queued_candidates=queued_candidates,
                    # Pre-Durable workers still complete their idempotent
                    # version receipt here. Current Durable handlers own their
                    # own finalized version; never rebuild that on GET.
                    allow_version_archive=not read_only and task is None,
                    durable_task=projection_task,
                )
            current[str(raw.get("id") or identity)] = (raw, revision, job)
            jobs.append(job)
        index = _training_job_index_rows(jobs)
        # Unchanged terminal history needs neither JSON serialization nor writes.
        old_index = [entry[2] for entry in previous.values()]
        if not read_only and (not (jobs_dir / "index.json").exists() or index != _training_job_index_rows(old_index)):
            write_json(jobs_dir / "index.json", index)
        _TRAINING_JOB_PROJECTIONS[key] = current
        return index


def list_models_internal(project_id: str) -> List[Dict[str, Any]]:
    p = project_dir(project_id)
    models_dir = p / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    # 建立模型文件 -> 训练任务映射，便于发布为算法版本时自动绑定训练报告。
    model_to_job: Dict[str, Dict[str, Any]] = {}
    jobs_dir = p / "jobs"
    for jf in jobs_dir.glob("*/job.json") if jobs_dir.exists() else []:
        job = read_json(jf, {})
        for m in job.get("models", []) or []:
            try:
                model_to_job[str(Path(m).resolve()).lower()] = job
                model_to_job[Path(m).name.lower()] = job
            except Exception:
                pass
    rows = []
    for f in sorted([x for x in models_dir.iterdir() if x.is_file() and x.suffix.lower() in MODEL_EXTS], key=lambda x: x.stat().st_mtime, reverse=True):
        job = model_to_job.get(str(f.resolve()).lower()) or model_to_job.get(f.name.lower()) or {}
        typ = f.suffix.lower().lstrip('.')
        cfg_path = ""
        if typ in {"pdparams", "pdmodel", "pdiparams"}:
            # 优先使用训练任务记录的算法配置；否则尝试找同名前缀的 yml/yaml。
            cfg_path = job.get("generated_config_path") or job.get("algorithm_config_path", "")
            for cand in [f.with_suffix(".yml"), f.with_suffix(".yaml")]:
                if not cfg_path and cand.exists():
                    cfg_path = str(cand)
        rows.append({
            "name": f.name,
            "path": str(f),
            "url": _authorized_model_url(project_id, f),
            "download_note": "" if job else "仅已登记业务产物支持下载；未登记文件需恢复来源记录。",
            "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
            "type": typ,
            "updated_at": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "job_id": job.get("id", ""),
            "job_name": job.get("algorithm_name", ""),
            "framework": job.get("framework", ""),
            "config_path": cfg_path,
            "family_key": job.get("algorithm_family", "") or job.get("family_key", ""),
            "num_classes": job.get("num_classes", 0),
            "report_ready": bool(job),
        })
    return rows


from platform_core.model_inference_service import ModelInferenceDependencies, ModelInferenceService
from platform_core.model_inference_api import create_model_inference_router_1, create_model_inference_router_2, create_model_inference_router_3


def _model_inference_service() -> ModelInferenceService:
    return ModelInferenceService(ModelInferenceDependencies(
        IMAGE_EXTS=lambda: IMAGE_EXTS,
        LOCAL_MODELS_FILE=lambda: LOCAL_MODELS_FILE,
        _authorize_business_file_project=lambda *args, **kwargs: _authorize_business_file_project(*args, **kwargs),
        _business_file_response=lambda *args, **kwargs: _business_file_response(*args, **kwargs),
        _business_file_url=lambda *args, **kwargs: _business_file_url(*args, **kwargs),
        _labels_b64=lambda *args, **kwargs: _labels_b64(*args, **kwargs),
        _module_available=lambda *args, **kwargs: _module_available(*args, **kwargs),
        _project_label_names=lambda *args, **kwargs: _project_label_names(*args, **kwargs),
        _register_prediction_files=lambda *args, **kwargs: _register_prediction_files(*args, **kwargs),
        _resolve_business_file=lambda *args, **kwargs: _resolve_business_file(*args, **kwargs),
        _testable_version_pt_path=lambda *args, **kwargs: _testable_version_pt_path(*args, **kwargs),
        _write_job_json=lambda *args, **kwargs: _write_job_json(*args, **kwargs),
        algorithms_file=lambda *args, **kwargs: algorithms_file(*args, **kwargs),
        get_active_paddle_env=lambda *args, **kwargs: get_active_paddle_env(*args, **kwargs),
        get_active_ultralytics_env=lambda *args, **kwargs: get_active_ultralytics_env(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        image_info=lambda *args, **kwargs: image_info(*args, **kwargs),
        list_algorithms_internal=lambda *args, **kwargs: list_algorithms_internal(*args, **kwargs),
        list_models_internal=lambda *args, **kwargs: list_models_internal(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        read_json=lambda *args, **kwargs: read_json(*args, **kwargs),
        resolve_any_model_path=lambda *args, **kwargs: resolve_any_model_path(*args, **kwargs),
        resolve_inference_python=lambda *args, **kwargs: resolve_inference_python(*args, **kwargs),
        resolve_ultralytics_model_path=lambda *args, **kwargs: resolve_ultralytics_model_path(*args, **kwargs),
        run_predict_by_env=lambda *args, **kwargs: run_predict_by_env(*args, **kwargs),
        safe_filename=lambda *args, **kwargs: safe_filename(*args, **kwargs),
        shared_task_artifacts=lambda *args, **kwargs: shared_task_artifacts(*args, **kwargs),
        shared_task_repository=lambda *args, **kwargs: shared_task_repository(*args, **kwargs),
        v39_list_deploy_artifacts=lambda *args, **kwargs: v39_list_deploy_artifacts(*args, **kwargs),
    ))


app.include_router(create_model_inference_router_1(_model_inference_service))


def list_models(project_id: str):
    return _model_inference_service().list_models(project_id)


def download_model(project_id: str, model_name: str):
    return _model_inference_service().download_model(project_id, model_name)


async def predict_image(project_id: str, model_name: str=Form(...), conf: float=Form(0.25), file: UploadFile=File(...)):
    return await _model_inference_service().predict_image(project_id, model_name, conf, file)


def export_onnx(project_id: str, model_name: str=Form(...)):
    return _model_inference_service().export_onnx(project_id, model_name)

# ============================================================
# v12 产品化接口：数据集分组、训练任务删除、算法版本、模型测试耗时
# ============================================================

APP_DISPLAY_NAME = "算法训练"

from platform_core.material_governance_contracts import ImagePatchReq

from platform_core.material_governance_contracts import BatchSplitReq

from platform_core.annotation_governance_contracts import LabelUpdateReq

from platform_core.algorithm_catalog_contracts import (
    AlgorithmReq, AlgorithmVersionReq, VersionPatchReq, AlgorithmVersionRollbackReq,
)






def algorithms_file(project_id: str) -> Path:
    return project_dir(project_id) / "algorithms.json"


def algorithm_repository(project_id: str):
    """The provider that owns algorithm-domain reads/writes for this project.

    SQLite is the default and behaves exactly as before. A PostgreSQL admission
    switches this to the PostgreSQL provider; it never falls back silently, and
    an unresolved cutover refuses both sides. Callers must go through this
    accessor instead of constructing AlgorithmSqlStore directly, so a single
    place decides the authoritative writer.
    """
    from platform_core.algorithm_repository import open_algorithm_repository

    return open_algorithm_repository(algorithms_file(project_id))


def algorithm_presentation_store(project_id: str):
    """Algorithm views for this project, served by the authoritative provider.

    A project has exactly one authoritative algorithm fact source: while SQLite
    is the default this is the existing store (all projections implemented),
    and after a PostgreSQL cutover it is the PostgreSQL provider. Asking for a
    projection the chosen provider cannot serve fails closed instead of quietly
    reading a possibly stale SQLite file, which is why this helper no longer
    constructs AlgorithmSqlStore itself.
    """
    return algorithm_repository(project_id)


from platform_core.algorithm_catalog_service import AlgorithmCatalogDependencies, AlgorithmCatalogService
from platform_core.algorithm_catalog_api import create_algorithm_catalog_router


def _publish_algorithm_catalog_snapshot(project_id, revision, algorithms):
    # The original bootstrap Owner and lock remain here; no second snapshot.
    global _V53_BOOTSTRAP_SNAPSHOT
    with _V53_BOOTSTRAP_LOCK:
        existing = _V53_BOOTSTRAP_SNAPSHOT
        if (str((existing.get("project") or {}).get("id") or "") == str(project_id)
                and int(existing.get("algorithm_revision") or 0) == revision
                and algorithm_store_revision(algorithms_file(project_id)) == revision):
            _V53_BOOTSTRAP_SNAPSHOT = {
                **existing, "algorithms": algorithms, "algorithms_deferred": False,
                "algorithms_generated_at": now_iso(),
            }


def _algorithm_catalog_service() -> AlgorithmCatalogService:
    return AlgorithmCatalogService(AlgorithmCatalogDependencies(
        authorize_business_file_project=lambda *args, **kwargs: _authorize_business_file_project(*args, **kwargs),
        business_file_response=lambda *args, **kwargs: _business_file_response(*args, **kwargs),
        algorithms_file=lambda *args, **kwargs: algorithms_file(*args, **kwargs),
        artifact_service=lambda *args, **kwargs: _delivery_model_artifact_service(*args, **kwargs),
        catalog=lambda *args, **kwargs: list_algorithms_internal(*args, **kwargs),
        conversion_catalog=lambda *args, **kwargs: _conversion_catalog_repository(*args, **kwargs),
        data_dir=lambda: DATA_DIR,
        deploy_root=lambda *args, **kwargs: deploy_root(*args, **kwargs),
        deployment_job_dir=lambda *args, **kwargs: _deploy_job_dir(*args, **kwargs),
        feedback_repository=lambda *args, **kwargs: _online_feedback_repository(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        job_report=lambda *args, **kwargs: job_report(*args, **kwargs),
        list_models=lambda *args, **kwargs: list_models_internal(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        presentation_store=lambda *args, **kwargs: algorithm_presentation_store(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        read_json=lambda *args, **kwargs: read_json(*args, **kwargs),
        repository=lambda *args, **kwargs: algorithm_repository(*args, **kwargs),
        secret_store=lambda *args, **kwargs: _v35_secret_store(*args, **kwargs),
        storage_credentials=lambda *args, **kwargs: storage_credentials(*args, **kwargs),
        storage_sources=lambda *args, **kwargs: storage_source_repository(*args, **kwargs),
        successful_training_counts=lambda *args, **kwargs: _successful_training_counts(*args, **kwargs),
        task_artifacts=lambda *args, **kwargs: shared_task_artifacts(*args, **kwargs),
        task_repository=lambda *args, **kwargs: shared_task_repository(*args, **kwargs),
        training_history=lambda *args, **kwargs: _training_history_context(*args, **kwargs),
        version_delivery_quality=lambda *args, **kwargs: _version_delivery_quality(*args, **kwargs),
        version_storage_provider=lambda *args, **kwargs: _version_cleanup_storage_provider(*args, **kwargs),
        write_job_json=lambda *args, **kwargs: _write_job_json(*args, **kwargs),
        write_json=lambda *args, **kwargs: write_json(*args, **kwargs),
        bootstrap_snapshot=lambda: globals().get("_V53_BOOTSTRAP_SNAPSHOT"),
        publish_bootstrap_snapshot=_publish_algorithm_catalog_snapshot,
    ))


def list_algorithms_internal(project_id: str, *, summary_only: bool=False, algorithm_id: Optional[str]=None) -> List[Dict[str, Any]]:
    return _algorithm_catalog_service().list_algorithms_internal(project_id, summary_only=summary_only, algorithm_id=algorithm_id)


def _algorithm_version_reference_fence(project_id: str, algorithm_id: str, version_id: str, *, require_current: bool=False):
    return _algorithm_catalog_service()._algorithm_version_reference_fence(project_id, algorithm_id, version_id, require_current=require_current)


def _deploy_job_version_identity(job: Mapping[str, Any]) -> tuple[str, str]:
    return _algorithm_catalog_service()._deploy_job_version_identity(job)


def _version_cleanup_storage_provider(project_id: str, ref: Mapping[str, Any]):
    return _algorithm_catalog_service()._version_cleanup_storage_provider(project_id, ref)


def _algorithm_version_active_references(project_id: str, algorithm: Mapping[str, Any], version: Mapping[str, Any]) -> List[Dict[str, str]]:
    return _algorithm_catalog_service()._algorithm_version_active_references(project_id, algorithm, version)


def resolve_any_model_path(project_id: str, model_name: str = "", model_source: str = "project", local_path: str = "") -> Tuple[Path, str, str]:
    p = project_dir(project_id)
    model_source = model_source or "project"
    if model_source == "local":
        path = Path(local_path or model_name or "").expanduser()
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="本机模型文件不存在")
        return path, path.name, f"local::{path}"
    if model_name.startswith("local::"):
        path = Path(model_name.split("local::", 1)[1])
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="本机模型文件不存在")
        return path, path.name, f"local::{path}"
    path = p / "models" / safe_filename(model_name)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="项目模型不存在")
    return path, path.name, f"project::{path.name}"


def job_report(project_id: str, job_id: str = "", model_path: Optional[Path] = None) -> Dict[str, Any]:
    report: Dict[str, Any] = {"来源": "手动归属"}
    if job_id:
        jf = project_dir(project_id) / "jobs" / job_id / "job.json"
        job = read_json(jf, {})
        if job:
            report = {
                "训练任务": job.get("id") or job_id,
                "训练框架": "Ultralytics" if job.get("framework") == "ultralytics" else "飞桨",
                "训练算法": job.get("algorithm_name") or job.get("algorithm") or "-",
                "基础模型": Path(str(job.get("model", ""))).name if job.get("model") else "-",
                "数据集": job.get("dataset_name") or job.get("dataset_id") or "-",
                "训练图片": job.get("dataset_counts", {}).get("train", "-"),
                "试验图片": job.get("dataset_counts", {}).get("val", "-"),
                "评测图片": job.get("dataset_counts", {}).get("test", "-"),
                "标注框": job.get("dataset_counts", {}).get("boxes", "-"),
                "轮次": job.get("epochs"),
                "图片尺寸": job.get("imgsz"),
                "批大小": job.get("batch"),
                "设备": job.get("device"),
                "进阶参数": json.dumps(job.get("advanced_params", {}), ensure_ascii=False) if job.get("advanced_params") else "-",
                "开始时间": job.get("created_at"),
                "结束时间": job.get("finished_at") or job.get("updated_at"),
                "训练状态": job.get("status"),
            }
            try:
                if job.get("created_at") and job.get("finished_at"):
                    t1 = datetime.strptime(job["created_at"], "%Y-%m-%d %H:%M:%S")
                    t2 = datetime.strptime(job["finished_at"], "%Y-%m-%d %H:%M:%S")
                    report["训练耗时"] = str(t2 - t1)
            except Exception:
                pass
            # 尝试读取 Ultralytics results.csv 的最后一行指标
            run_dir = Path(job.get("run_dir", "")) if job.get("run_dir") else None
            results_csv = run_dir / "results.csv" if run_dir else None
            if results_csv and results_csv.exists():
                try:
                    lines = results_csv.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
                    if len(lines) >= 2:
                        headers = [h.strip() for h in lines[0].split(',')]
                        values = [v.strip() for v in lines[-1].split(',')]
                        metrics = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}
                        # 常见关键指标，字段名不同版本可能带空格
                        for key in list(metrics.keys()):
                            low = key.lower()
                            if "map50" in low or "precision" in low or "recall" in low or "box_loss" in low:
                                report[key] = metrics[key]
                except Exception:
                    pass
    if model_path and model_path.exists():
        report["模型文件"] = model_path.name
        report["模型大小"] = f"{model_path.stat().st_size / 1024 / 1024:.2f} MB"
        report["更新时间"] = datetime.fromtimestamp(model_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return report


def project_label_items(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    labels = project.get("labels", [])
    meta = project.get("label_meta", [])
    items = []
    for i, code in enumerate(labels):
        m = meta[i] if i < len(meta) and isinstance(meta[i], dict) else {}
        display_name = m.get("display_name") or code
        items.append({
            "class_id": i,
            "code": code,
            "display_name": display_name,
            "display_name_zh": display_name,
            "color": m.get("color") or default_label_color(i),
            "type": m.get("type") or "bbox",
            "hotkey": m.get("hotkey") or (str(i+1) if i < 9 else ""),
            "status": m.get("status") or "active",
            "active": m.get("active", True),
            "merged_into": str(m.get("merged_into") or ""),
            "merged_at": str(m.get("merged_at") or ""),
            "aliases": normalize_label_aliases(m.get("aliases") or []),
        })
    return items


def _ensure_project_label_meta(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    labels = project.setdefault("labels", [])
    meta = project.setdefault("label_meta", [])
    while len(meta) < len(labels):
        idx = len(meta)
        code = labels[idx]
        meta.append({
            "code": code,
            "display_name": code,
            "color": default_label_color(idx),
            "type": "bbox",
            "hotkey": str(idx + 1) if idx < 9 else "",
            "aliases": [],
        })
    for idx, code in enumerate(labels):
        if not isinstance(meta[idx], dict):
            meta[idx] = {}
        meta[idx]["code"] = code
        meta[idx]["aliases"] = normalize_label_aliases(meta[idx].get("aliases") or [])
    return meta


def _validate_label_aliases(
    project: Dict[str, Any],
    aliases,
    *,
    target_class_id: Optional[int],
    target_code: str,
    target_display_name: str,
) -> List[str]:
    normalized = normalize_label_aliases(aliases)
    target_identity = {str(target_code or "").strip(), str(target_display_name or "").strip()}
    target_identity.discard("")
    canonical_owners: Dict[str, set] = {}
    for item in project_label_items(project):
        if target_class_id is not None and int(item.get("class_id", -1)) == int(target_class_id):
            continue
        for value in label_identity_values(item):
            canonical_owners.setdefault(value, set()).add(str(item.get("code")))
    result = []
    for alias in normalized:
        if alias in target_identity:
            continue
        owners = canonical_owners.get(alias, set())
        if owners:
            raise ValueError(
                f"标签别名 {alias} 与正式标签身份冲突：{'、'.join(sorted(owners))}"
            )
        result.append(alias)
    return result


def _set_project_label_aliases(
    project: Dict[str, Any],
    target_code: str,
    aliases,
    *,
    replace: bool,
) -> List[str]:
    labels = project.get("labels", [])
    if target_code not in labels:
        raise ValueError(f"平台标签不存在：{target_code}")
    meta = _ensure_project_label_meta(project)
    target_idx = labels.index(target_code)
    incoming = normalize_label_aliases(aliases)
    incoming_set = set(incoming)
    for idx, row in enumerate(meta):
        existing = normalize_label_aliases(row.get("aliases") or [])
        if idx == target_idx:
            continue
        row["aliases"] = [alias for alias in existing if alias not in incoming_set]
    base = [] if replace else normalize_label_aliases(meta[target_idx].get("aliases") or [])
    meta[target_idx]["aliases"] = normalize_label_aliases([*base, *incoming])
    return meta[target_idx]["aliases"]


def _prune_canonical_label_alias_conflicts(project: Dict[str, Any]) -> bool:
    canonical = set()
    for item in project_label_items(project):
        canonical.update(label_identity_values(item))
    changed = False
    for row in _ensure_project_label_meta(project):
        aliases = normalize_label_aliases(row.get("aliases") or [])
        filtered = [alias for alias in aliases if alias not in canonical]
        if filtered != aliases:
            row["aliases"] = filtered
            changed = True
    return changed


def remember_project_label_aliases(
    project_id: str,
    external_classes,
    label_mapping,
) -> Dict[str, List[str]]:
    with label_governance_fence(project_dir(project_id)):
        return _remember_project_label_aliases_locked(
            project_id, external_classes, label_mapping,
        )


def _remember_project_label_aliases_locked(
    project_id: str,
    external_classes,
    label_mapping,
) -> Dict[str, List[str]]:
    project = get_project(project_id)
    updates = confirmed_alias_updates(
        external_classes or [],
        label_mapping or {},
        project_label_items(project),
    )
    remembered: Dict[str, List[str]] = {}
    for target, aliases in updates.items():
        target_idx = project.get("labels", []).index(target)
        target_item = project_label_items(project)[target_idx]
        safe_aliases: List[str] = []
        for alias in aliases:
            try:
                validated = _validate_label_aliases(
                    project,
                    [alias],
                    target_class_id=target_idx,
                    target_code=target,
                    target_display_name=str(target_item.get("display_name") or target),
                )
            except ValueError:
                # A canonical label identity always wins over reusable aliases.
                # Skip only the conflicting source name; other confirmed aliases
                # in the same batch remain safe to learn.
                continue
            safe_aliases.extend(validated)
        if not safe_aliases:
            continue
        remembered[target] = _set_project_label_aliases(
            project, target, safe_aliases, replace=False,
        )
    if remembered:
        save_project(project)
    return remembered


def normalize_box_for_project(
    project_id: str,
    img: Dict[str, Any],
    box: Dict[str, Any],
    create_label: bool = True,
    *,
    project_state: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """把前端/导入的框统一清洗成可训练框。
    修复常见问题：class_id 缺失、class_id 字符串、只有 label、标签名与编码不一致、坐标反向/越界。
    """
    project = project_state if project_state is not None else get_project(project_id)
    labels = project.setdefault("labels", [])
    try:
        # 优先用 label 反查，避免前端 class_id 与后端标签顺序不一致导致跳过。
        raw_label = normalize_label(str(box.get("label") or box.get("code") or ""))
        raw_class = box.get("class_id", None)
        class_id = None
        if raw_label and raw_label in labels:
            class_id = labels.index(raw_label)
        elif raw_label and create_label:
            class_id = ensure_label(project, raw_label)
            project = get_project(project_id)
            labels = project.get("labels", [])
        else:
            try:
                class_id = int(raw_class)
            except Exception:
                class_id = None
        if class_id is None or class_id < 0 or class_id >= len(labels):
            return None
        x1 = float(box.get("x1")); y1 = float(box.get("y1")); x2 = float(box.get("x2")); y2 = float(box.get("y2"))
    except Exception:
        return None
    w = float(img.get("width") or 1); h = float(img.get("height") or 1)
    x1, x2 = sorted([max(0.0, min(x1, w)), max(0.0, min(x2, w))])
    y1, y2 = sorted([max(0.0, min(y1, h)), max(0.0, min(y2, h))])
    if x2 - x1 < 3 or y2 - y1 < 3:
        return None
    return {
        "id": box.get("id") or uuid.uuid4().hex[:10],
        "class_id": int(class_id),
        "label": labels[int(class_id)],
        "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2),
    }


def dataset_quality_report(project_id: str, dataset_id: Optional[str]=None, include_empty: bool=False) -> Dict[str, Any]:
    return _material_catalog_service().dataset_quality_report(project_id, dataset_id, include_empty)


app.include_router(create_runtime_catalog_router_6(_runtime_catalog_service))


def v12_app_info():
    return _runtime_catalog_service().v12_app_info()


app.include_router(create_label_directory_router(_material_catalog_service))


def v12_list_labels(project_id: str):
    return _material_catalog_service().v12_list_labels(project_id)


app.include_router(create_annotation_governance_router_3(_annotation_governance_service))


def v12_update_label(project_id: str, class_id: int, payload: LabelUpdateReq):
    return _annotation_governance_service().v12_update_label(project_id, class_id, payload)


def _v12_update_label_locked(project_id: str, class_id: int, payload: LabelUpdateReq):
    return _annotation_governance_service()._v12_update_label_locked(project_id, class_id, payload)


def v12_delete_label(project_id: str, class_id: int):
    return _annotation_governance_service().v12_delete_label(project_id, class_id)


def _v12_delete_label_locked(project_id: str, class_id: int):
    return _annotation_governance_service()._v12_delete_label_locked(project_id, class_id)


app.include_router(create_material_governance_router_3(_material_governance_service))


def v12_patch_image(project_id: str, image_id: str, payload: ImagePatchReq):
    return _material_governance_service().v12_patch_image(project_id, image_id, payload)


from platform_core.material_governance_contracts import BatchImageSplitReq


def v20_batch_image_split(project_id: str, payload: BatchImageSplitReq):
    return _material_governance_service().v20_batch_image_split(project_id, payload)


def v12_auto_split(project_id: str, dataset_id: str, payload: BatchSplitReq):
    return _material_governance_service().v12_auto_split(project_id, dataset_id, payload)


def dataset_items_by_split(project_id: str, dataset_id: Optional[str], include_empty: bool=False) -> Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]]:
    return _dataset_export_service().dataset_items_by_split(project_id, dataset_id, include_empty)


def build_yolo_dataset_v12(project_id: str, dataset_id: Optional[str]=None, include_empty: bool=False) -> Dict[str, Any]:
    return _dataset_export_service().build_yolo_dataset_v12(project_id, dataset_id, include_empty)


app.include_router(create_dataset_export_router_2(_dataset_export_service))


def v12_build_dataset(project_id: str, payload: BuildDatasetReq):
    return _dataset_export_service().v12_build_dataset(project_id, payload)


app.include_router(create_dataset_quality_router(_material_catalog_service))


def v17_dataset_quality(project_id: str, dataset_id: str, include_empty: bool=False):
    return _material_catalog_service().v17_dataset_quality(project_id, dataset_id, include_empty)


def build_coco_dataset_v12(project_id: str, dataset_id: Optional[str]=None, include_empty: bool=False) -> Dict[str, Any]:
    return _dataset_export_service().build_coco_dataset_v12(project_id, dataset_id, include_empty)


app.include_router(create_dataset_export_router_3(_dataset_export_service))


def v12_export_dataset(project_id: str, dataset_id: str, fmt: str):
    return _dataset_export_service().v12_export_dataset(project_id, dataset_id, fmt)


app.include_router(create_dataset_summary_router(_material_catalog_service))


def v12_dataset_summary(project_id: str, dataset_id: str):
    return _material_catalog_service().v12_dataset_summary(project_id, dataset_id)



def _v44_labels_in_ann(ann: Dict[str, Any]) -> set:
    return {str(b.get("label") or "").strip() for b in ann.get("boxes", []) if str(b.get("label") or "").strip()}

def build_yolo_dataset_v44(project_id: str, payload: TrainReq) -> Dict[str, Any]:
    return _dataset_export_service().build_yolo_dataset_v44(project_id, payload)



def _v54_validate_iteration_artifact(path: Path, framework: str) -> bool:
    """Validate that a stored checkpoint can actually be loaded by its trainer."""
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    if framework != "ultralytics":
        return True
    py = ultralytics_runtime_python()
    script = "from ultralytics import YOLO; YOLO(r'''%s'''); print('checkpoint-ok')" % str(path.resolve()).replace("'", "''")
    try:
        result = subprocess.run(
            [py, "-c", script],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            env={**os.environ.copy(), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
    except Exception:
        return False
    return result.returncode == 0 and "checkpoint-ok" in (result.stdout or "")


def _v54_iteration_base(
    project_id: str,
    algorithm_id: str,
    framework: str,
    *,
    strict_latest: bool = False,
) -> Optional[Dict[str, Any]]:
    """Use an algorithm version as the next iteration base model.

    Strict mode is used by product training entry points: the mother model is
    allowed only for a first run (no versions), and the immediate latest
    version must be present and loadable once a version exists.
    """
    if not algorithm_id:
        return None
    algo = next((a for a in list_algorithms_internal(project_id) if str(a.get("id")) == str(algorithm_id)), None)
    if not algo:
        return None
    selection = choose_algorithm_iteration_base(
        algo,
        "",
        framework,
        strict_latest=strict_latest,
        artifact_validator=(lambda path: _v54_validate_iteration_artifact(path, framework)) if strict_latest else None,
    )
    if selection["base_selection_reason"] == "mother_model":
        return None
    path = Path(selection["base_model_path"])
    latest = sorted(
        [row for row in (algo.get("versions") or []) if is_trainable_version(row, framework)],
        key=lambda row: str(row.get("finished_at") or row.get("created_at") or row.get("version_name") or ""),
        reverse=True,
    )
    return {
        **selection,
        "algorithm_id": algo.get("id"), "algorithm_name": algo.get("name"),
        "version_id": selection["base_version_id"], "version_name": selection["base_version_name"],
        "path": str(path), "model_name": path.name,
        "is_latest_version": bool(latest and str(latest[0].get("id")) == str(selection["base_version_id"])),
        "is_current_version": True,
        "latest_version_name": (latest[0] if latest else {}).get("version_name") or "",
    }

class ConfirmIterationActionReq(BaseModel):
    decision_id: str
    action: Literal["supplement_data", "continue_training", "business_validation", "manual_review"]


from platform_core.training_evaluation_contracts import SupplementFeedbackCandidateSelection


from platform_core.training_evaluation_contracts import FreezeSupplementFeedbackCandidatesReq


def _algorithm_version_for_action(project_id: str, algorithm_id: str, version_id: str):
    get_project(project_id)
    algorithm = next((row for row in list_algorithms_internal(project_id)
                      if str(row.get("id")) == str(algorithm_id)), None)
    if algorithm is None:
        raise HTTPException(status_code=404, detail="算法不存在")
    version = next((row for row in (algorithm.get("versions") or [])
                    if str(row.get("id")) == str(version_id)), None)
    if version is None:
        raise HTTPException(status_code=404, detail="算法版本不存在")
    return algorithm, version



_EVALUATION_SNAPSHOT_INDEX_CACHE = OrderedDict()
_EVALUATION_SNAPSHOT_INDEX_LOCK = threading.Lock()
# Serialize only the first expensive, cryptographic check of a legacy task
# Snapshot. Concurrent gallery thumbnails otherwise all parse a 20MB JSON.
_EVALUATION_TASK_SNAPSHOT_READ_LOCK = threading.Lock()
_EVALUATION_SNAPSHOT_INDEX_LIMIT = 8


class _EvaluationSnapshotIndexError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _evaluation_snapshot_preview_path(project_id, version, evaluation, snapshot_id):
    return _training_evaluation_service()._evaluation_snapshot_preview_path(project_id, version, evaluation, snapshot_id)


def _evaluation_snapshot_identity_index(path: Path, snapshot_id: str, *, verify_digest=False):
    return _training_evaluation_service()._evaluation_snapshot_identity_index(path, snapshot_id, verify_digest=verify_digest)


def _evaluation_bundle_identity_index(path: Path, snapshot_id: str):
    return _training_evaluation_service()._evaluation_bundle_identity_index(path, snapshot_id)


def _evaluation_legacy_name_index(path: Path, repository, test_ids):
    return _training_evaluation_service()._evaluation_legacy_name_index(path, repository, test_ids)


from platform_core.training_evaluation_service import TrainingEvaluationDependencies, TrainingEvaluationService
from platform_core.training_evaluation_api import create_training_evaluation_router_1, create_training_evaluation_router_2, create_training_evaluation_router_3, create_training_evaluation_router_4


def _training_evaluation_service() -> TrainingEvaluationService:
    return TrainingEvaluationService(TrainingEvaluationDependencies(
        _EVALUATION_SNAPSHOT_INDEX_CACHE=lambda: _EVALUATION_SNAPSHOT_INDEX_CACHE,
        _EVALUATION_SNAPSHOT_INDEX_LIMIT=lambda: _EVALUATION_SNAPSHOT_INDEX_LIMIT,
        _EVALUATION_SNAPSHOT_INDEX_LOCK=lambda: _EVALUATION_SNAPSHOT_INDEX_LOCK,
        _EVALUATION_TASK_SNAPSHOT_READ_LOCK=lambda: _EVALUATION_TASK_SNAPSHOT_READ_LOCK,
        _EvaluationSnapshotIndexError=_EvaluationSnapshotIndexError,
        _TRAINING_COUNT_PAYLOADS=lambda: _TRAINING_COUNT_PAYLOADS,
        _TRAINING_JOB_PROJECTION_LOCK=lambda: _TRAINING_JOB_PROJECTION_LOCK,
        _algorithm_version_for_action=lambda *args, **kwargs: _algorithm_version_for_action(*args, **kwargs),
        _annotation_label_catalog=lambda *args, **kwargs: _annotation_label_catalog(*args, **kwargs),
        _authorize_business_file_project=lambda *args, **kwargs: _authorize_business_file_project(*args, **kwargs),
        _online_feedback_repository=lambda *args, **kwargs: _online_feedback_repository(*args, **kwargs),
        _require_annotation_review_task=lambda *args, **kwargs: _require_annotation_review_task(*args, **kwargs),
        _storage_source_fence=lambda *args, **kwargs: _storage_source_fence(*args, **kwargs),
        _successful_training_counts=lambda *args, **kwargs: _successful_training_counts(*args, **kwargs),
        _testable_version_pt_path=lambda *args, **kwargs: _testable_version_pt_path(*args, **kwargs),
        _training_history_context=lambda *args, **kwargs: _training_history_context(*args, **kwargs),
        algorithms_file=lambda *args, **kwargs: algorithms_file(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        list_algorithms_internal=lambda *args, **kwargs: list_algorithms_internal(*args, **kwargs),
        material_store=lambda *args, **kwargs: material_store(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        public_annotation_task=lambda *args, **kwargs: public_annotation_task(*args, **kwargs),
        read_annotations_many=lambda *args, **kwargs: read_annotations_many(*args, **kwargs),
        read_json=lambda *args, **kwargs: read_json(*args, **kwargs),
        shared_task_artifacts=lambda *args, **kwargs: shared_task_artifacts(*args, **kwargs),
        shared_task_repository=lambda *args, **kwargs: shared_task_repository(*args, **kwargs),
        storage_manager=lambda *args, **kwargs: storage_manager(*args, **kwargs),
    ))


app.include_router(create_training_evaluation_router_1(_training_evaluation_service))


def evaluation_diagnostic_image_v1(project_id: str, algorithm_id: str, version_id: str, image_name: str, expected_evaluation_id: str='', expected_image_id: str='', expected_sha256: str=''):
    return _training_evaluation_service().evaluation_diagnostic_image_v1(project_id, algorithm_id, version_id, image_name, expected_evaluation_id, expected_image_id, expected_sha256)


def _advanced_evaluation_context(project_id: str, algorithm_id: str, version_id: str):
    return _training_evaluation_service()._advanced_evaluation_context(project_id, algorithm_id, version_id)


def _advanced_trust_evidence(project_id, algorithm_id, version, model, *, offset=0, limit=20):
    return _training_evaluation_service()._advanced_trust_evidence(project_id, algorithm_id, version, model, offset=offset, limit=limit)


def evaluation_trust_analysis(project_id: str, algorithm_id: str, version_id: str, offset: int=0, limit: int=20):
    return _training_evaluation_service().evaluation_trust_analysis(project_id, algorithm_id, version_id, offset, limit)


def evaluation_sample_page(project_id: str, algorithm_id: str, version_id: str, offset: int=0, limit: int=24, issue: str='', class_id: Optional[int]=None, sort: str='severity', reader_view: bool=False):
    return _training_evaluation_service().evaluation_sample_page(project_id, algorithm_id, version_id, offset, limit, issue, class_id, sort, reader_view)


def advanced_evaluation_report(project_id: str, algorithm_id: str, version_id: str, reader_view: bool=False, section: str='summary', offset: int=0, limit: int=20, class_id: Optional[int]=None):
    return _training_evaluation_service().advanced_evaluation_report(project_id, algorithm_id, version_id, reader_view, section, offset, limit, class_id)


def compare_version_evaluation(project_id: str, algorithm_id: str, version_id: str, other_version_id: str, reader_view: bool=False, offset: int=0, limit: int=20):
    return _training_evaluation_service().compare_version_evaluation(project_id, algorithm_id, version_id, other_version_id, reader_view, offset, limit)


def deep_compare_evaluation(project_id: str, algorithm_id: str, version_id: str, other_version_id: str, offset: int=0, limit: int=24, category: str=''):
    return _training_evaluation_service().deep_compare_evaluation(project_id, algorithm_id, version_id, other_version_id, offset, limit, category)


from platform_core.training_evaluation_contracts import EvaluationReviewReq


from platform_core.training_evaluation_contracts import ReviewedMiningSelection


from platform_core.training_evaluation_contracts import FreezeReviewedMiningReq


def _reviewed_mining_candidates(project_id, algorithm_id, version_id, task_id, *, offset=0, limit=24, image_ids=None):
    return _training_evaluation_service()._reviewed_mining_candidates(project_id, algorithm_id, version_id, task_id, offset=offset, limit=limit, image_ids=image_ids)


def preview_reviewed_mining(project_id: str, algorithm_id: str, version_id: str, task_id: str, offset: int=0, limit: int=24):
    return _training_evaluation_service().preview_reviewed_mining(project_id, algorithm_id, version_id, task_id, offset, limit)


def adopt_reviewed_mining(project_id: str, algorithm_id: str, version_id: str, task_id: str, payload: FreezeReviewedMiningReq):
    return _training_evaluation_service().adopt_reviewed_mining(project_id, algorithm_id, version_id, task_id, payload)


def review_evaluation_sample(project_id: str, algorithm_id: str, version_id: str, payload: EvaluationReviewReq):
    return _training_evaluation_service().review_evaluation_sample(project_id, algorithm_id, version_id, payload)


@app.post("/api/v12/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/iteration-actions/confirm")
def confirm_iteration_action(project_id: str, algorithm_id: str, version_id: str,
                             payload: ConfirmIterationActionReq):
    from platform_core.iteration_actions import build_confirmed_iteration_action
    algorithm, version = _algorithm_version_for_action(project_id, algorithm_id, version_id)
    if str(algorithm.get("current_version_id") or "") != str(version_id):
        raise HTTPException(status_code=409, detail="只能基于算法当前版本确认下一步动作，请刷新后重试")
    try:
        action = build_confirmed_iteration_action(
            algorithm_id=algorithm_id, version=version,
            requested_action=payload.action, decision_id=payload.decision_id,
            confirmed_at=now_iso(),
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    previous = version.get("confirmed_iteration_action")
    if isinstance(previous, dict):
        previous_id = str(previous.get("action_id") or "")
        if previous_id == action["action_id"]:
            return {"ok": True, "action": previous, "idempotent": True}
        if previous_id:
            raise HTTPException(status_code=409, detail="该版本已确认其他迭代动作，请刷新版本状态")
    stored = update_algorithm_version(
        algorithms_file(project_id), algorithm_id, version_id,
        {"confirmed_iteration_action": action}, now=now_iso(),
    )
    return {"ok": True, "action": stored.get("confirmed_iteration_action") or action}


def _validated_training_iteration_action(algorithm: Dict[str, Any], payload: TrainReq):
    if not payload.iteration_action:
        return None
    from platform_core.iteration_actions import training_action_context
    current_version_id = str(algorithm.get("current_version_id") or "")
    version = next((row for row in (algorithm.get("versions") or [])
                    if str(row.get("id")) == current_version_id), None)
    if version is None:
        raise HTTPException(status_code=409, detail="当前算法版本不存在，请刷新后重试")
    stored = version.get("confirmed_iteration_action")
    if not isinstance(stored, dict):
        raise HTTPException(status_code=409, detail="当前版本没有已确认的继续训练动作")
    try:
        expected = training_action_context(stored)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    submitted = {str(k): str(v or "") for k, v in dict(payload.iteration_action).items()}
    if submitted != expected:
        raise HTTPException(status_code=409, detail="训练动作溯源已变化，请重新从独立评测确认继续训练")
    if expected["version_id"] != current_version_id:
        raise HTTPException(status_code=409, detail="继续训练动作不再指向当前版本")
    decision, evaluation = version.get("iteration_decision"), version.get("evaluation")
    if (not isinstance(decision, dict) or not isinstance(evaluation, dict)
        or expected["decision_id"] != decision.get("decision_id")
        or expected["evaluation_id"] != decision.get("evaluation_id")
        or expected["evaluation_id"] != evaluation.get("evaluation_id")):
        raise HTTPException(status_code=409, detail="当前版本的评测或迭代决策已变化，请重新确认继续训练")
    expected_task_id = str((stored.get("training_draft") or {}).get("task_id") or "")
    submitted_task_id = str(payload.task_id or "")
    if not expected_task_id or submitted_task_id != expected_task_id:
        raise HTTPException(status_code=409, detail="继续训练动作必须使用已确认的固定任务 ID")
    return stored


def _supplement_data_action(project_id: str, algorithm_id: str, version_id: str):
    return _training_evaluation_service()._supplement_data_action(project_id, algorithm_id, version_id)


def _supplement_feedback_candidates(project_id: str, feedback_rows):
    return _training_evaluation_service()._supplement_feedback_candidates(project_id, feedback_rows)


app.include_router(create_training_evaluation_router_2(_training_evaluation_service))


def list_supplement_feedback_candidates(project_id: str, algorithm_id: str, version_id: str):
    return _training_evaluation_service().list_supplement_feedback_candidates(project_id, algorithm_id, version_id)


def freeze_supplement_feedback_candidates(project_id: str, algorithm_id: str, version_id: str, payload: FreezeSupplementFeedbackCandidatesReq):
    return _training_evaluation_service().freeze_supplement_feedback_candidates(project_id, algorithm_id, version_id, payload)


# --- training creation domain (owned by platform_core.training_create_api) ---
# Dependencies are assembled here, once every collaborator exists; the domain
# module never imports app. Both URLs are registered by the same owner.
_TRAINING_CREATE_DEPENDENCIES = TrainingCreateDependencies(
    get_project=get_project,
    algorithm_config=get_algorithm_config,
    list_algorithms=list_algorithms_internal,
    enqueue=_enqueue_explicit_training,
    actor_resolver=_material_governance_actor,
)
app.include_router(build_training_create_router(_TRAINING_CREATE_DEPENDENCIES))


def v12_start_train(project_id: str, payload: TrainReq, request: Optional[Request] = None):
    """In-process creation entry used by automation and tests.

    The HTTP routes live in the training-create router; this binding exposes the
    same owner to existing in-process callers without a second implementation.
    """
    return _start_training(
        project_id, payload, request=request,
        dependencies=_TRAINING_CREATE_DEPENDENCIES,
    )


def _v48_resource_key(job: Dict[str, Any]) -> str:
    return str(job.get("resource_key") or ("remote:" + str((job.get("remote") or {}).get("server_id") or "remote") if job.get("target") == "remote" else "local:default"))


def _v48_all_job_files(project_id: str) -> List[Path]:
    root = project_dir(project_id) / "jobs"
    retired=shared_task_repository().deleted_task_ids((x.name for x in root.iterdir() if x.is_dir()),project_id=project_id) if root.exists() else set()
    return [x / "job.json" for x in root.iterdir() if x.is_dir() and x.name not in retired and (x / "job.json").exists()] if root.exists() else []


def _v48_launch_saved_job(project_id: str, job: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str(job.get("id") or "")
    jf = project_dir(project_id) / "jobs" / job_id / "job.json"
    if not job_id or not jf.exists():
        raise RuntimeError("训练任务文件不存在")
    payload = TrainReq(**(job.get("train_request") or {}))
    payload.ai_intervention_enabled = False
    payload.ai_intervention_epochs = []
    p = project_dir(project_id)
    job_dir = jf.parent
    log_file = job_dir / "train.log"
    model_value = str(job.get("model") or payload.model or "")
    run_name = str(job.get("run_name") or f"train_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{job_id[:4]}")
    data_yaml = str(job.get("data_yaml") or "")
    if not data_yaml or not Path(data_yaml).exists():
        raise RuntimeError("训练快照不存在，无法启动任务")

    if payload.target == "remote":
        server = resolve_server(payload)
        dataset_zip = job_dir / "dataset.zip"
        if not dataset_zip.exists():
            zip_dir(Path(job.get("dataset_snapshot") or Path(data_yaml).parent), dataset_zip)
        with dataset_zip.open("rb") as fp:
            files = {"dataset_zip": ("dataset.zip", fp, "application/zip")}
            model_fp = None
            model_path = Path(model_value)
            if model_path.is_file():
                model_fp = model_path.open("rb")
                files["model_file"] = (model_path.name, model_fp, "application/octet-stream")
            data = {
                "model": model_path.name if model_fp else model_value,
                "epochs": str(job.get("epochs") or payload.epochs), "imgsz": str(job.get("imgsz") or payload.imgsz), "batch": str(job.get("batch") or payload.batch),
                "device": payload.device, "run_name": run_name,
                "patience": str(payload.patience), "workers": str(payload.workers), "optimizer": payload.optimizer or "auto",
                "lr0": str(payload.lr0), "lrf": str(payload.lrf), "weight_decay": str(payload.weight_decay),
                "close_mosaic": str(payload.close_mosaic), "mosaic": str(payload.mosaic), "cache": str(payload.cache),
                "single_cls": str(payload.single_cls).lower(), "pretrained": str(payload.pretrained).lower(), "rect": str(payload.rect).lower(),
                "amp": str(payload.amp).lower(), "cos_lr": str(payload.cos_lr).lower(), "freeze": str(payload.freeze),
                "eval_interval": str(int(payload.eval_interval or 0)), "eval_metric": str(payload.eval_metric or "map50"),
                "continue_threshold": str(float(payload.continue_threshold or 0)), "stop_threshold": str(float(payload.stop_threshold or 0)),
                "val_max_samples": str(int(payload.val_max_samples or 0)),
            }
            headers = {"X-API-Key": server.get("api_key", "")}
            try:
                r = requests.post(f"{server['base_url'].rstrip('/')}/api/remote/train", data=data, files=files, headers=headers, timeout=120)
            finally:
                if model_fp: model_fp.close()
            r.raise_for_status()
            remote = r.json()
        job.update({
            "status":"running", "message":"远程训练已启动", "started_at":now_iso(),
            "remote":{"server_id":server.get("id"),"name":server.get("name"),"base_url":server["base_url"],"api_key":server.get("api_key", ""),"job_id":remote.get("job_id")},
            "updated_at":now_iso(),
        })
        _write_job_json(jf, job)
        return job

    # local Ultralytics worker
    runtime = check_ultralytics_train_runtime(ultralytics_runtime_python())
    cmd = [
        ultralytics_runtime_python(), str(BASE_DIR / "train_worker.py"),
        "--project-dir", str(p), "--data", data_yaml, "--model", model_value,
        "--epochs", str(job.get("epochs") or payload.epochs), "--imgsz", str(job.get("imgsz") or payload.imgsz), "--batch", str(job.get("batch") or payload.batch),
        "--device", payload.device, "--job-id", job_id, "--run-name", run_name,
        "--patience", str(payload.patience), "--workers", str(payload.workers), "--optimizer", payload.optimizer or "auto",
        "--lr0", str(payload.lr0), "--lrf", str(payload.lrf), "--weight-decay", str(payload.weight_decay),
        "--close-mosaic", str(payload.close_mosaic), "--mosaic", str(payload.mosaic), "--cache", str(payload.cache),
        "--single-cls", str(payload.single_cls).lower(), "--pretrained", str(payload.pretrained).lower(), "--rect", str(payload.rect).lower(),
        "--amp", str(payload.amp).lower(), "--cos-lr", str(payload.cos_lr).lower(), "--freeze", str(payload.freeze),
        "--momentum", str(payload.momentum), "--warmup-epochs", str(payload.warmup_epochs), "--save-period", str(payload.save_period),
        "--seed", str(payload.seed), "--deterministic", str(payload.deterministic).lower(), "--multi-scale", str(payload.multi_scale),
        "--hsv-h", str(payload.hsv_h), "--hsv-s", str(payload.hsv_s), "--hsv-v", str(payload.hsv_v),
        "--degrees", str(payload.degrees), "--translate", str(payload.translate), "--scale", str(payload.scale), "--shear", str(payload.shear),
        "--perspective", str(payload.perspective), "--flipud", str(payload.flipud), "--fliplr", str(payload.fliplr), "--mixup", str(payload.mixup),
        "--val-max-samples", str(int(payload.val_max_samples or 0)),
        "--eval-interval", str(int(payload.eval_interval or 0)), "--eval-metric", str(payload.eval_metric or "map50"),
        "--continue-threshold", str(float(payload.continue_threshold or 0)), "--stop-threshold", str(float(payload.stop_threshold or 0)),
        "--auto-supplement", "false", "--supplement-count", "0", "--ai-intervention", "false",
    ]
    job["runtime_check"] = runtime
    with log_file.open("ab") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(BASE_DIR), env={**os.environ.copy(), "PYTHONUTF8":"1", "PYTHONIOENCODING":"utf-8"})
    PROCESS_REGISTRY[job_id] = proc
    job.update({"status":"running","message":"训练已启动","pid":proc.pid,"started_at":now_iso(),"updated_at":now_iso()})
    _write_job_json(jf, job)
    return job


V56_PRIORITY_SCHEME = "lower_number_first"
V56_LEGACY_PRIORITY_MAP = {100: 1, 80: 20, 50: 50}
_LEGACY_V48_TRAIN_QUEUE_LOCK = threading.RLock()


def _v56_normalize_priority(job: Dict[str, Any]) -> int:
    try:
        raw = int(job.get("queue_priority", 50))
    except (TypeError, ValueError):
        raw = 50
    if job.get("priority_scheme") == V56_PRIORITY_SCHEME:
        return max(1, min(999, raw))
    return V56_LEGACY_PRIORITY_MAP.get(raw, max(1, min(999, 101 - raw)))


def _v56_training_queue_sort_key(job: Dict[str, Any]):
    return (
        _v56_normalize_priority(job),
        int(job.get("priority_tiebreaker") or 0),
        str(job.get("queued_at") or job.get("created_at") or ""),
        str(job.get("id") or ""),
    )


def _v56_migrate_queued_priority(job_file: Path, job: Dict[str, Any]) -> Dict[str, Any]:
    if job.get("status") != "queued" or job.get("priority_scheme") == V56_PRIORITY_SCHEME:
        return job
    migrated = dict(job)
    migrated["legacy_queue_priority"] = job.get("queue_priority", 50)
    migrated["queue_priority"] = _v56_normalize_priority(job)
    migrated["priority_scheme"] = V56_PRIORITY_SCHEME
    migrated["priority_migrated_at"] = now_iso()
    try:
        _write_job_json(job_file, migrated)
    except Exception as exc:
        print(f"[priority-migration] {job_file}: {exc}")
    return migrated


@performance_stage("legacy_queue")
def _v48_dispatch_training_queues(project_id: str) -> Optional[tuple]:
    """Explicit legacy maintenance only, fenced across HTTP worker processes."""
    with _LEGACY_V48_TRAIN_QUEUE_LOCK:
        # The old thread lock never protected multiple Uvicorn processes.
        # Hold this short-lived project owner fence across the remote/local
        # launch and persisted status so a second worker cannot double-start.
        lock_path = project_dir(project_id) / "jobs" / ".legacy-dispatch.lock"
        try:
            with FileLock(str(lock_path), timeout=0):
                return _v48_dispatch_training_queues_locked(project_id)
        except Timeout:
            performance_count("legacy_queue.busy")
            return None


def _v48_dispatch_training_queues_locked(project_id: str) -> Optional[tuple]:
    rows = []
    history, repository, durable = _training_history_context(project_id)
    for job in history:
        jf = project_dir(project_id) / "jobs" / str(job.get("id") or "") / "job.json"
        if str(job.get("task_id") or job.get("id") or "") in durable:
            continue
        if job.get("status") == "queued":
            job = _v56_migrate_queued_priority(jf, job)
        rows.append((jf, job))
    busy = {_v48_resource_key(job) for _, job in rows if job.get("status") in {"running", "paused"}}
    queued = sorted(
        [(jf, job) for jf, job in rows if job.get("status") == "queued"],
        key=lambda pair: _v56_training_queue_sort_key(pair[1]),
    )
    for jf, job in queued:
        key = _v48_resource_key(job)
        if key in busy:
            continue
        try:
            _v48_launch_saved_job(project_id, job)
            busy.add(key)
        except Exception as error:
            job.update(status="failed", message=f"训练启动失败：{error}",
                       finished_at=now_iso(), updated_at=now_iso(), never_started=True)
            _write_job_json(jf, job)
    return (history, repository, durable) if not rows else None


def _v48_legacy_needs_maintenance(job: Mapping[str, Any]) -> bool:
    status = str(job.get("status") or "").strip().lower()
    if status in {"queued", "running", "paused"}:
        return True
    return (
        status in {"done", "finished", "completed", "success", "succeeded"}
        and job.get("artifact_verified") is True
        and bool(job.get("asset_algorithm_id"))
        and not job.get("auto_version_id")
        and not job.get("never_started")
    )


def _v48_legacy_maintenance_tick() -> bool:
    """Maintain only pre-Durable tasks, independent of API read frequency.

    A Durable task with a retained legacy job.json is *never* re-dispatched.
    The caller owns the cadence; concurrent service workers share the launch
    file fence, while archival retains its original version CAS guard.
    """
    monitoring = False
    for project in list_projects():
        project_id = str(project.get("id") or "")
        if not project_id:
            continue
        try:
            history, _repository, durable = _training_history_context(project_id)
            pending = any(
                _v48_legacy_needs_maintenance(row)
                for row in history
                if str(row.get("task_id") or row.get("id") or "") not in durable
            )
            if not pending:
                continue
            monitoring = True
            _v48_dispatch_training_queues(project_id)
            sync_jobs_index(project_id)
        except Exception:
            # A transient schema/IO error must not mark unknown queued work
            # complete or stop the maintenance owner permanently.
            performance_count("legacy_queue.failures")
            monitoring = True
    return monitoring


_LEGACY_TRAINING_MAINTENANCE_THREAD: Optional[threading.Thread] = None
_LEGACY_TRAINING_MAINTENANCE_STOP = threading.Event()
_LEGACY_TRAINING_MAINTENANCE_LOCK = threading.Lock()


def _v48_legacy_maintenance_loop() -> None:
    # No new pre-Durable jobs are admitted. Exit after the first empty scan;
    # an old queue discovered on startup stays scheduled through completion.
    while not _LEGACY_TRAINING_MAINTENANCE_STOP.is_set():
        try:
            if not _v48_legacy_maintenance_tick():
                return
        except Exception:
            # A transient failure enumerating projects must not strand old
            # queued jobs. Retry after the same bounded idle cadence.
            performance_count("legacy_queue.failures")
        _LEGACY_TRAINING_MAINTENANCE_STOP.wait(30)


@app.on_event("startup")
def _v48_start_legacy_training_maintenance() -> None:
    global _LEGACY_TRAINING_MAINTENANCE_THREAD
    with _LEGACY_TRAINING_MAINTENANCE_LOCK:
        if _LEGACY_TRAINING_MAINTENANCE_THREAD and _LEGACY_TRAINING_MAINTENANCE_THREAD.is_alive():
            return
        _LEGACY_TRAINING_MAINTENANCE_STOP.clear()
        _LEGACY_TRAINING_MAINTENANCE_THREAD = threading.Thread(
            target=_v48_legacy_maintenance_loop, name="legacy-training-maintenance", daemon=True,
        )
        _LEGACY_TRAINING_MAINTENANCE_THREAD.start()


@app.on_event("shutdown")
def _v48_stop_legacy_training_maintenance() -> None:
    _LEGACY_TRAINING_MAINTENANCE_STOP.set()


app.include_router(create_training_management_router_2(_training_management_service))


def v48_promote_job(project_id: str, job_id: str):
    return _training_management_service().v48_promote_job(project_id, job_id)


def _v48_suspend_tree(pid: Any, resume: bool=False):
    import psutil
    proc=psutil.Process(int(pid)); children=proc.children(recursive=True)
    for x in children + [proc]:
        try: x.resume() if resume else x.suspend()
        except Exception: pass


def _durable_training_task(project_id: str, task_id: str) -> Optional[TaskRecord]:
    task = shared_task_repository().get(task_id)
    if task is None or task.project_id != project_id or task.kind is not TaskKind.TRAINING:
        return None
    return task


def _durable_process_identity(task: TaskRecord) -> ProcessIdentity:
    if (
        task.process_pid is None
        or task.process_create_time is None
        or not task.process_command_hash
    ):
        raise HTTPException(status_code=400, detail="训练进程身份尚未登记")
    return ProcessIdentity(
        pid=task.process_pid,
        create_time=task.process_create_time,
        command_hash=task.process_command_hash,
    )


def v48_pause_job(project_id: str, job_id: str):
    return _training_management_service().v48_pause_job(project_id, job_id)


def v48_resume_job(project_id: str, job_id: str):
    return _training_management_service().v48_resume_job(project_id, job_id)


def v48_stop_job(project_id: str, job_id: str):
    return _training_management_service().v48_stop_job(project_id, job_id)


_TRAINING_LEGACY_TERMINAL_STATUSES = {
    "done", "finished", "completed", "succeeded", "success",
    "failed", "stopped", "cancelled", "canceled",
    "blocked_by_environment", "blocked_by_hardware",
}
_TRAINING_DURABLE_TERMINAL_STATUSES = {
    TaskStatus.PARTIAL_SUCCESS,
    TaskStatus.SUCCEEDED,
    TaskStatus.CANCELLED,
    TaskStatus.FAILED,
    TaskStatus.BLOCKED_BY_ENVIRONMENT,
    TaskStatus.BLOCKED_BY_HARDWARE,
}


from platform_core.training_management_contracts import V48TrainingBatchDeleteReq


def _purge_terminal_training_job_record(project_id: str, job_id: str) -> Dict[str, Any]:
    return _training_management_service()._purge_terminal_training_job_record(project_id, job_id)



def v48_batch_delete_jobs(project_id: str, payload: V48TrainingBatchDeleteReq):
    return _training_management_service().v48_batch_delete_jobs(project_id, payload)


def v12_delete_job(project_id: str, job_id: str):
    return _training_management_service().v12_delete_job(project_id, job_id)




app.include_router(create_algorithm_catalog_router(_algorithm_catalog_service))


def v12_list_algorithms(project_id: str, summary_only: bool=False, asset_view: bool=False, page: int=1, page_size: int=20, query: str='', algorithm_type: str='', industry: str='', source_type: str='', status: str='', sort: str='updated', library_view: bool=False, training_state: str='', category_ids: str=''):
    return _algorithm_catalog_service().v12_list_algorithms(project_id, summary_only, asset_view, page, page_size, query, algorithm_type, industry, source_type, status, sort, library_view, training_state, category_ids)


def v12_create_algorithm(project_id: str, payload: AlgorithmReq, asset_view: bool=False):
    return _algorithm_catalog_service().v12_create_algorithm(project_id, payload, asset_view)


def v12_get_algorithm(project_id: str, algorithm_id: str, asset_view: bool=False, version_id: str='', page: int=1, page_size: int=20, basic_only: bool=False, quality_view: bool=False):
    return _algorithm_catalog_service().v12_get_algorithm(project_id, algorithm_id, asset_view, version_id, page, page_size, basic_only, quality_view)


def v12_update_algorithm(project_id: str, algorithm_id: str, payload: AlgorithmReq, asset_view: bool=False):
    return _algorithm_catalog_service().v12_update_algorithm(project_id, algorithm_id, payload, asset_view)


def v12_delete_algorithm(project_id: str, algorithm_id: str):
    return _algorithm_catalog_service().v12_delete_algorithm(project_id, algorithm_id)


def v12_pending_models(project_id: str):
    return _algorithm_catalog_service().v12_pending_models(project_id)


def v12_assign_version(project_id: str, algorithm_id: str, payload: AlgorithmVersionReq):
    return _algorithm_catalog_service().v12_assign_version(project_id, algorithm_id, payload)


def v12_update_version(project_id: str, algorithm_id: str, version_id: str, payload: VersionPatchReq, asset_view: bool=False):
    return _algorithm_catalog_service().v12_update_version(project_id, algorithm_id, version_id, payload, asset_view)


def _safe_launch_reject_external_version_retirement(project_id: str, algorithm_id: str) -> None:
    return _algorithm_catalog_service()._safe_launch_reject_external_version_retirement(project_id, algorithm_id)


def v12_delete_version(project_id: str, algorithm_id: str, version_id: str):
    return _algorithm_catalog_service().v12_delete_version(project_id, algorithm_id, version_id)


def v12_rollback_version(project_id: str, algorithm_id: str, version_id: str, payload: AlgorithmVersionRollbackReq):
    return _algorithm_catalog_service().v12_rollback_version(project_id, algorithm_id, version_id, payload)






def v12_deployment_activation_dry_run(project_id: str, algorithm_id: str, version_id: str, operation_id: str='', expected_current_version_id: str=''):
    return _algorithm_catalog_service().v12_deployment_activation_dry_run(project_id, algorithm_id, version_id, operation_id, expected_current_version_id)


def v12_rollback_dry_run(project_id: str, algorithm_id: str, version_id: str, operation_id: str='', expected_current_version_id: str=''):
    return _algorithm_catalog_service().v12_rollback_dry_run(project_id, algorithm_id, version_id, operation_id, expected_current_version_id)


def v12_retry_version_cleanup(project_id: str, algorithm_id: str, operation_id: str):
    return _algorithm_catalog_service().v12_retry_version_cleanup(project_id, algorithm_id, operation_id)


def v12_download_version(project_id: str, algorithm_id: str, version_id: str):
    return _algorithm_catalog_service().v12_download_version(project_id, algorithm_id, version_id)


# ============================== v42.8 automatic algorithm versions ==============================
def _v48_version_name_from_job(job: Dict[str, Any]) -> str:
    raw=str(job.get("finished_at") or job.get("updated_at") or now_iso())
    digits="".join(ch for ch in raw if ch.isdigit())
    return (digits[:14] if len(digits)>=14 else datetime.now().strftime("%Y%m%d%H%M%S"))


def _v48_find_job_model(project_id: str, job: Dict[str, Any]) -> Optional[Path]:
    candidates=[]
    for key in ("verified_models","models"):
        for x in job.get(key) or []:
            candidates.append(Path(str(x)))
    run_dir=Path(str(job.get("run_dir") or project_dir(project_id)/"runs"/str(job.get("run_name") or "")))
    candidates += [run_dir/"weights"/"best.pt", run_dir/"weights"/"last.pt"]
    for m in list_models_internal(project_id):
        if m.get("job_id")==job.get("id"):
            candidates.append(Path(str(m.get("path") or "")))
    seen=set()
    for x in candidates:
        try:
            r=x.resolve()
        except Exception:
            r=x
        if str(r) in seen: continue
        seen.add(str(r))
        if x.is_file() and x.suffix.lower() in {".pt",".onnx",".pdparams",".pdmodel",".pdiparams"}:
            return x
    return None


def _v48_metric_from_job(job: Dict[str, Any], metric: str="map50") -> Optional[float]:
    metric=(metric or "map50").lower()
    report=job.get("training_report") or {}
    metrics=report.get("metrics") or {}
    aliases={
        "map50":["metrics/mAP50(B)","metrics/map50(b)","map50"],
        "precision":["metrics/precision(B)","metrics/precision(b)","precision"],
        "recall":["metrics/recall(B)","metrics/recall(b)","recall"],
    }
    for want in aliases.get(metric,aliases["map50"]):
        for k,v in metrics.items():
            if str(k).lower()==want.lower():
                try:return float(v)
                except Exception:pass
    # stage gate events are persisted even when training is manually stopped later.
    for ev in reversed(job.get("gate_events") or []):
        if str(ev.get("metric") or "").lower()==metric and ev.get("value") is not None:
            try:return float(ev.get("value"))
            except Exception:pass
    # fallback to results.csv for interrupted/stopped tasks.
    run_dir=Path(str(job.get("run_dir") or "")); csvp=run_dir/"results.csv" if run_dir else None
    if csvp and csvp.exists():
        try:
            lines=csvp.read_text(encoding="utf-8",errors="ignore").strip().splitlines()
            if len(lines)>=2:
                hs=[x.strip() for x in lines[0].split(',')]; vs=[x.strip() for x in lines[-1].split(',')]
                for i,k in enumerate(hs):
                    low=k.lower().replace(" ","")
                    hit=(metric=="map50" and "map50" in low and "95" not in low) or (metric=="precision" and "precision" in low) or (metric=="recall" and "recall" in low)
                    if hit and i<len(vs): return float(vs[i])
        except Exception: pass
    return None


def _v48_quality_reached(job: Dict[str, Any]) -> bool:
    gate=job.get("quality_gate") or {}; target=float(gate.get("stop_threshold") or 0)
    if target<=0:return False
    value=_v48_metric_from_job(job,str(gate.get("metric") or "map50"))
    return value is not None and value>=target


def _v48_auto_convert_version(project_id: str, algorithm_id: str, version: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    targets=list(job.get("auto_convert_targets") or [])
    summary={"requested":targets,"jobs":[],"errors":[]}
    if not targets or not version.get("stored_path") or not _v48_quality_reached(job):
        return summary
    resources=_builtin_deploy_resources()+_load_saved_deploy_resources()
    for target in targets:
        resource=next((r for r in resources if r.get("status")=="ready" and target in (r.get("targets") or [])),None)
        if not resource:
            summary["errors"].append({"target":target,"message":"没有已检测通过的对应部署资源"});continue
        # Version-source conversion inherits frozen training runtime defaults in
        # _v39_create_deploy_job_under_version_fence, including AMP FP32 fallback.
        # Do not override that contract with an unconditional FP16 here.
        params={}
        if target in {"sophon","rockchip","ascend"}:
            runtime = _deploy_resource_runtime(resource)
            mode = str(runtime.get("mode") or "local").lower()
            try:
                resource = (_detect_remote_deploy_resource(runtime) if mode == "remote"
                            else _detect_agent_deploy_resource(runtime) if mode == "agent"
                            else _detect_local_deploy_resource(runtime))
            except Exception as error:
                summary["errors"].append({"target":target,"message":str(error)})
                continue
            from platform_core.compute_platform_catalog import resolve_conversion_contract, conversion_templates
            catalog=_conversion_catalog_repository(DATA_DIR).conversion_catalog()
            template_ids={t["id"] for t in conversion_templates() if t.get("adapter")==target}
            vendors={v["id"] for v in catalog["vendors"] if v.get("enabled",True) and v.get("template_id") in template_ids}
            candidates=[]
            for chip in catalog["chips"]:
                if chip["vendor_id"] not in vendors:
                    continue
                contract=resolve_conversion_contract(catalog,vendor_id=chip["vendor_id"],chip_id=chip["id"],resource=resource,version=version,params={})
                if contract["ready"]:
                    candidates.append(contract)
            if len(candidates)!=1:
                candidate_codes = ", ".join(c["params"]["chip"].upper() for c in candidates) or "无"
                summary["errors"].append({"target":target,"message":f"自动转换必须有唯一已就绪本地芯片合同；当前候选：{candidate_codes}。请在版本转换中明确选择目标。"})
                continue
            params=candidates[0]["params"]
        try:
            r=v39_create_deploy_job(project_id,DeployJobReq(source_id=f"version::{algorithm_id}::{version.get('id')}",target=target,resource_id=str(resource.get("id")),params=params,dataset_id="default",calibration_split="train",calibration_count=100))
            summary["jobs"].append({"target":target,"job_id":(r.get("job") or {}).get("id"),"resource_name":resource.get("name")})
        except Exception as e:
            summary["errors"].append({"target":target,"message":str(getattr(e,"detail",e))})
    return summary


def _v48_archive_training_version(project_id: str, job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Serialise legacy finalisation even when multiple HTTP workers recover it."""
    identity = str(job.get("id") or "")
    if not identity or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", identity):
        return None
    lock_path = project_dir(project_id) / "jobs" / identity / ".legacy-archive.lock"
    with FileLock(str(lock_path), timeout=30):
        return _v48_archive_training_version_locked(project_id, job)


def _v48_archive_training_version_locked(project_id: str, job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not job or job.get("auto_version_id") or job.get("never_started"):
        return None
    normalized_status = str(job.get("status") or "").strip().upper()
    successful_statuses = {"DONE", "FINISHED", "COMPLETED", "SUCCEEDED", "SUCCESS", "PARTIAL_SUCCESS"}
    if normalized_status not in successful_statuses:
        return None
    algorithm_id=str(job.get("asset_algorithm_id") or "")
    if not algorithm_id:return None
    algos=list_algorithms_internal(project_id); algo=next((a for a in algos if a.get("id")==algorithm_id),None)
    if not algo:return None
    version_name=_v48_version_name_from_job(job)
    # Idempotence across restarts: same training task can archive only once.
    existing=next((v for v in (algo.get("versions") or []) if v.get("job_id")==job.get("id")),None)
    if existing:
        job["auto_version_id"]=existing.get("id");job["auto_version_name"]=existing.get("version_name");
        try:_write_job_json(project_dir(project_id)/"jobs"/str(job.get("id"))/"job.json",job)
        except Exception:pass
        return existing
    model_path=_v48_find_job_model(project_id,job)
    if not (
        bool(job.get("artifact_verified"))
        and model_path
        and model_path.is_file()
        and model_path.stat().st_size > 0
    ):
        return None
    version_id=uuid.uuid4().hex[:12]; stored_path=""; model_name=""; size_mb=0.0; model_type=""
    vd=project_dir(project_id)/"algorithm_versions"/algorithm_id/version_id;vd.mkdir(parents=True,exist_ok=True)
    dst=vd/model_path.name;shutil.copy2(model_path,dst);stored_path=str(dst);model_name=dst.name;size_mb=round(dst.stat().st_size/1024/1024,2);model_type=dst.suffix.lower().lstrip('.')
    rep=job_report(project_id,str(job.get("id") or ""),Path(stored_path) if stored_path else None)
    accuracy=_v48_metric_from_job(job,"map50")
    snapshot_id = str(job.get("snapshot_id") or "")
    snapshot_truth = read_json(project_dir(project_id)/"snapshots"/f"{snapshot_id}.json", {}) if snapshot_id else {}
    dataset_revision_id = str(
        job.get("dataset_revision_id")
        or (snapshot_truth.get("dataset_revision_id") if isinstance(snapshot_truth, dict) else "")
        or ""
    )
    execution_resource = job.get("execution_resource")
    execution_resource = execution_resource if isinstance(execution_resource, dict) else {}
    model_sha256 = sha256_file(dst)
    training_lineage = build_training_lineage(
        task_id=str(job.get("task_id") or job.get("id") or ""),
        snapshot_id=snapshot_id,
        dataset_revision_id=dataset_revision_id,
        framework=str(job.get("framework") or "ultralytics"),
        base_version_id=job.get("base_version_id"),
        base_version_name=job.get("base_version_name"),
        base_model=job.get("base_model_path") or job.get("model"),
        base_selection_reason=job.get("base_selection_reason"),
        model_ancestry=(job.get('history_admission') or {}).get('model_ancestry'),
        execution={
            "mode": execution_resource.get("type") or job.get("target") or "local",
            "worker_id": job.get("worker_id"),
            "requested_device": job.get("requested_device") or job.get("device"),
            "assigned_device": job.get("assigned_device"),
            "actual_device": job.get("actual_device"),
            "resource_id": execution_resource.get("id"),
            "resource_name": execution_resource.get("name"),
        },
        requested_params=job.get("requested_train_params"),
        actual_params=job.get("actual_train_params"),
        supplement_provenance=(
            snapshot_truth.get("supplement_provenance")
            if isinstance(snapshot_truth, dict)
            else job.get("supplement_provenance")
        ),
        artifacts=[{
            "role": "primary",
            "file_name": model_name,
            "sha256": model_sha256,
            "size_bytes": int(dst.stat().st_size),
            "verified": bool(job.get("artifact_verified")),
        }],
        training_status=("PARTIAL_SUCCESS" if normalized_status == "PARTIAL_SUCCESS" else "SUCCEEDED"),
        training_outcome=job.get("training_outcome"),
        completion_reason=job.get("completion_reason"),
        finished_at=job.get("finished_at") or now_iso(),
    )
    from platform_core.training_evaluation import (
        build_evaluation_benchmark_scope,
        build_evaluation_truth,
        build_feedback_adoption_outcome,
        build_iteration_decision,
    )
    training_report = job.get("training_report")
    training_report = training_report if isinstance(training_report, dict) else {}
    evaluation_task_id = str(job.get("task_id") or job.get("id") or "")
    dataset_manifest = {}
    dataset_manifest_ref = str(job.get("dataset_manifest_ref") or "").strip()
    if evaluation_task_id and dataset_manifest_ref:
        manifest_value = shared_task_artifacts().read_json(
            evaluation_task_id, dataset_manifest_ref, default={}
        )
        dataset_manifest = manifest_value if isinstance(manifest_value, dict) else {}
        if not dataset_manifest and dataset_manifest_ref == "work/bundle/manifest.json":
            manifest_value = shared_task_artifacts().read_json(
                evaluation_task_id, "evidence/bundle/manifest.json", default={},
            )
            dataset_manifest = manifest_value if isinstance(manifest_value, dict) else {}
    benchmark_scope = build_evaluation_benchmark_scope(
        snapshot_truth if isinstance(snapshot_truth, dict) else None,
        dataset_manifest=dataset_manifest or None,
    )
    legacy_blind = training_report.get('test_result') or {}
    if isinstance(legacy_blind, dict) and str(legacy_blind.get('status') or '').lower() in {'succeeded', 'passed'}:
        if not benchmark_scope or benchmark_scope.get('binding_level') != 'bundle_verified':
            raise ValueError('TRAINING_TEST_HISTORY_UNKNOWN: formal scoring requires verified frozen Test bundle')
        from platform_core.training_material_usage import TrainingMaterialUsage, assert_formal_test_independence, require_formal_history_admission
        history = require_formal_history_admission(job.get('history_admission'))
        assert_formal_test_independence(TrainingMaterialUsage(shared_task_repository()), snapshot_truth,
            project_id, algorithm_id, parent_task_ids=history.get('parent_task_ids') or (),
            benchmark_reuse=bool(job.get('benchmark_reuse')))
    evaluation = build_evaluation_truth(
        training_report.get("test_result"),
        task_id=str(job.get("task_id") or job.get("id") or ""),
        snapshot_id=snapshot_id,
        dataset_revision_id=dataset_revision_id,
        model_sha256=model_sha256,
        finished_at=job.get("finished_at") or now_iso(),
        benchmark_scope=benchmark_scope,
    )
    iteration_decision = build_iteration_decision(
        evaluation,
        quality_gate=job.get("quality_gate"),
    )
    supplement_provenance = (
        training_lineage.get("supplement_provenance")
        if isinstance(training_lineage, dict)
        else {}
    )
    feedback_adoption_outcome = {}
    if isinstance(supplement_provenance, dict) and supplement_provenance:
        lineage_base = (
            training_lineage.get("base")
            if isinstance(training_lineage.get("base"), dict)
            else {}
        )
        source_version_id = str(lineage_base.get("version_id") or "").strip()
        source_version = next(
            (
                row for row in (algo.get("versions") or [])
                if str(row.get("id") or "") == source_version_id
            ),
            None,
        )
        feedback_adoption_outcome = build_feedback_adoption_outcome(
            source_version.get("evaluation") if isinstance(source_version, dict) else None,
            evaluation,
            supplement_provenance,
            source_version_id=source_version_id,
            new_version_id=version_id,
        )
    version={
        "id":version_id,"version_no":len(algo.get("versions") or [])+1,"version_name":version_name,
        "model_name":model_name,"model_key":f"job::{job.get('id')}::{version_name}","stored_path":stored_path,"type":model_type,"size_mb":size_mb,
        "job_id":job.get("id"),"remark":"训练结束自动生成版本","report":rep,"report_updated_at":now_iso(),
        "accuracy":accuracy,"accuracy_metric":"mAP50","quality_reached":_v48_quality_reached(job),"training_status":("PARTIAL_SUCCESS" if normalized_status == "PARTIAL_SUCCESS" else "SUCCEEDED"),
        "framework": str(job.get("framework") or "ultralytics").strip().lower(),
        "external_analysis_id": str(job.get("external_analysis_id") or ""),
        "trainable": bool(stored_path),
        "artifact_verified": bool(job.get("artifact_verified")) and bool(stored_path),
        "snapshot_id": snapshot_id,
        "dataset_revision_id": dataset_revision_id,
        "training_lineage": training_lineage,
        "evaluation": evaluation,
        "iteration_decision": iteration_decision,
        **(
            {"feedback_adoption_outcome": feedback_adoption_outcome}
            if feedback_adoption_outcome else {}
        ),
        "result_ref": str(job.get("result_ref") or ""),
        "task_id": str(job.get("task_id") or job.get("id") or ""),
        "base_version_id": str(job.get("base_version_id") or "").strip() or None,
        "status":"可用" if stored_path else "无可用模型产物","created_at":job.get("finished_at") or now_iso(),"updated_at":now_iso(),
    }
    # Legacy archive must obey the same frozen base/version CAS as the
    # canonical Durable finalizer. Concurrent winners must not overwrite
    # current_version_id or leave an orphaned copied candidate.
    try:
        committed = attach_algorithm_version_if_current(
            algorithms_file(project_id), algorithm_id, version,
            expected_current_version_id=str(job.get("base_version_id") or "").strip() or None,
        )
    except Exception:
        shutil.rmtree(vd, ignore_errors=True)
        raise
    if str(committed.get("id") or "") != version_id:
        shutil.rmtree(vd, ignore_errors=True)
    version = committed
    version_id = str(version.get("id") or version_id)
    version_name = str(version.get("version_name") or version_name)
    job["auto_version_id"]=version_id;job["auto_version_name"]=version_name
    try:_write_job_json(project_dir(project_id)/"jobs"/str(job.get("id"))/"job.json",job)
    except Exception:pass
    auto_conversion=_v48_auto_convert_version(project_id,algorithm_id,version,job)
    version=update_algorithm_version(
        algorithms_file(project_id),algorithm_id,version_id,
        {"auto_conversion":auto_conversion},now=now_iso(),
    )
    try:
        job["auto_conversion"]=version.get("auto_conversion");_write_job_json(project_dir(project_id)/"jobs"/str(job.get("id"))/"job.json",job)
    except Exception:pass
    request_external_auto_publish_if_enabled(
        data_dir=DATA_DIR,
        algorithms_path=algorithms_file(project_id),
        algorithm_id=algorithm_id,
        version_id=version_id,
        now=now_iso(),
    )
    return version


# v16：测试环境选择。测试不再强制使用平台自身 Python，支持指定 Ultralytics / 飞桨环境。
def _module_available(python_path: str, module_name: str) -> Dict[str, Any]:
    try:
        cp = subprocess.run(
            [python_path, "-c", f"import {module_name}, json; print(json.dumps({{'ok': True, 'version': getattr({module_name}, '__version__', ''), 'path': getattr({module_name}, '__file__', '')}}, ensure_ascii=False))"],
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="ignore",
        )
        out = (cp.stdout or cp.stderr or "").strip()
        if cp.returncode != 0:
            return {"ok": False, "error": out or f"无法导入 {module_name}"}
        return json.loads(out.splitlines()[-1]) if out else {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def inference_env_items(probe_modules: bool = True) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    # 平台内置环境：只有装了对应包才可用。
    u = _module_available(sys.executable, "ultralytics") if probe_modules else {"ok": True, "version": ""}
    items.append({
        "id": "platform_ultralytics",
        "name": "平台内置 Ultralytics",
        "framework": "ultralytics",
        "python_path": sys.executable,
        "status": "ready" if u.get("ok") else "missing",
        "version": u.get("version", ""),
        "note": "使用当前平台 .venv。" if u.get("ok") else "当前平台环境未安装 ultralytics，测试时请选择已安装的 Ultralytics 环境。",
    })
    active_u = get_active_ultralytics_env()
    if active_u and active_u.get("python_path"):
        py = str(active_u.get("python_path"))
        ok = Path(py).exists()
        items.insert(0, {
            "id": "active_ultralytics",
            "name": active_u.get("name") or "已检测 Ultralytics 环境",
            "framework": "ultralytics",
            "python_path": py,
            "root": active_u.get("root"),
            "status": "ready" if ok else "missing",
            "version": active_u.get("version", ""),
            "note": f"{active_u.get('root','')}" if ok else "python.exe 不存在，请重新检测环境。",
        })
    p_env = get_active_paddle_env()
    if p_env and p_env.get("python_path"):
        py = str(p_env.get("python_path"))
        ok = Path(py).exists()
        paddledet_dir = p_env.get("paddledet_dir") or ""
        infer_py = Path(paddledet_dir) / "tools" / "infer.py" if paddledet_dir else Path("")
        ppdet = _module_available(py, "ppdet") if ok and probe_modules else {"ok": bool(ok and infer_py.exists()), "error": "启动阶段未执行模块探测"}
        paddlex = _module_available(py, "paddlex") if ok and probe_modules else {"ok": False, "error": "启动阶段未执行模块探测"}
        pdet_ready = ok and (ppdet.get("ok") or infer_py.exists())
        px_ready = ok and paddlex.get("ok")
        if pdet_ready and px_ready:
            status, note = "ready", "PaddleDetection / PaddleX 均可用，可测试飞桨训练模型和内置模型。"
        elif pdet_ready:
            status, note = "ready", "PaddleDetection 可用，可测试平台训练出的 .pdparams；未检测到 paddlex，PaddleX 内置模型可能不可用。"
        elif px_ready:
            status, note = "ready", "PaddleX 可用，可测试 PaddleX 内置模型；未检测到 PaddleDetection 推理入口。"
        else:
            status, note = "missing", f"飞桨推理环境不可用：ppdet={ppdet.get('error','未检测到')}；paddlex={paddlex.get('error','未检测到')}"
        items.append({
            "id": "active_paddle",
            "name": p_env.get("name") or "本机飞桨环境",
            "framework": "paddle",
            "python_path": py,
            "paddledet_dir": paddledet_dir,
            "paddlex_dir": p_env.get("paddlex_dir"),
            "status": status,
            "version": ppdet.get("version", "") or paddlex.get("version", ""),
            "note": note,
        })
    # 训练服务器作为可选项展示，但当前测试接口先不调用远程推理；避免误导，标记为 coming。
    for s in read_json(SERVERS_FILE, []):
        items.append({
            "id": f"server:{s.get('id')}",
            "name": s.get("name") or s.get("base_url") or "训练服务器",
            "framework": "server",
            "status": "coming",
            "base_url": s.get("base_url"),
            "note": "已登记训练服务器；模型测试请先使用本机 Ultralytics / 飞桨环境。",
        })
    return items


app.include_router(create_runtime_catalog_router_7(_runtime_catalog_service))


def v16_inference_envs():
    return _runtime_catalog_service().v16_inference_envs()


def resolve_inference_python(framework: str, env_id: str = "") -> str:
    framework = (framework or "ultralytics").lower()
    env_id = env_id or ""
    envs = inference_env_items()
    # 指定环境优先。
    if env_id:
        hit = next((e for e in envs if e.get("id") == env_id), None)
        if not hit:
            raise HTTPException(status_code=400, detail="测试环境不存在，请重新选择。")
        if hit.get("framework") != framework:
            raise HTTPException(status_code=400, detail="测试环境与模型框架不匹配，请重新选择。")
        if hit.get("status") not in {"ready", "warning"}:
            raise HTTPException(status_code=400, detail=hit.get("note") or "测试环境不可用。")
        py = hit.get("python_path")
        if not py or not Path(py).exists():
            raise HTTPException(status_code=400, detail="测试环境 python.exe 不存在。")
        return py
    # 没指定时：优先选已检测 Ultralytics，再选平台内置。
    for e in envs:
        if e.get("framework") == framework and e.get("status") == "ready" and e.get("python_path"):
            return e["python_path"]
    raise HTTPException(status_code=400, detail="没有可用的测试环境。请先在训练资源中检测 Ultralytics 或配置飞桨环境。")


def run_predict_by_env(framework: str, python_path: str, model_value: str, input_path: Path, output_path: Path, conf: float) -> Dict[str, Any]:
    framework = (framework or "ultralytics").lower()
    runner = BASE_DIR / ("predict_paddle_runner.py" if framework == "paddle" else "predict_ultralytics_runner.py")
    if not runner.exists():
        raise HTTPException(status_code=500, detail=f"测试执行器不存在：{runner.name}")
    cmd = [python_path, str(runner), "--model", str(model_value), "--input", str(input_path), "--output", str(output_path), "--conf", str(conf)]
    try:
        env = os.environ.copy()
        penv = get_active_paddle_env() if framework == "paddle" else {}
        if framework == "paddle" and penv.get("paddledet_dir"):
            env["PADDLEDETECTION_DIR"] = penv.get("paddledet_dir", "")
        if framework == "paddle" and penv.get("paddlex_dir"):
            env["PADDLEX_DIR"] = penv.get("paddlex_dir", "")
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=600, encoding="utf-8", errors="ignore", env=env)
        out = (cp.stdout or "").strip()
        err = (cp.stderr or "").strip()
        if cp.returncode != 0:
            raise HTTPException(status_code=500, detail=(err or out or f"测试进程退出码：{cp.returncode}")[-2000:])
        if not out:
            raise HTTPException(status_code=500, detail="测试执行器没有返回结果。")
        # 输出中可能混有框架日志，取最后一个 JSON 行。
        data = None
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                data = json.loads(line)
                break
        if not data:
            raise HTTPException(status_code=500, detail=(out + "\n" + err)[-2000:])
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"测试失败：{e}")


app.include_router(create_model_inference_router_2(_model_inference_service))


async def v12_predict_image(project_id: str, model_name: str=Form(''), model_source: str=Form('project'), local_path: str=Form(''), algorithm_id: str=Form(''), version_id: str=Form(''), conf: float=Form(0.25), inference_framework: str=Form('ultralytics'), inference_env_id: str=Form(''), file: UploadFile=File(...)):
    return await _model_inference_service().v12_predict_image(project_id, model_name, model_source, local_path, algorithm_id, version_id, conf, inference_framework, inference_env_id, file)


# Online feedback (v63) business implementation now lives in
# platform_core/online_feedback_service.py (rules/orchestration) and
# platform_core/online_feedback_api.py (router). The thin bindings below stay in
# app.py only as legacy compatibility for callers/tests that patch these names.
from platform_core.online_feedback_service import (
    OnlineFeedbackService,
    prediction_evidence as _online_feedback_prediction_evidence_impl,
    version_model_sha256 as _online_feedback_version_model_sha256_impl,
)
from platform_core.online_feedback_api import create_online_feedback_router


def _online_feedback_repository(project_id: str):
    from platform_core.online_feedback import OnlineFeedbackRepository
    return OnlineFeedbackRepository(project_dir(project_id))


def _online_feedback_version_model_sha256(version: Mapping[str, Any]) -> str:
    return _online_feedback_version_model_sha256_impl(version, sha256_file)


def _online_prediction_evidence(project_id: str, prediction_id: str):
    return _online_feedback_prediction_evidence_impl(
        project_id,
        prediction_id,
        project_dir=project_dir,
        sha256_file=sha256_file,
        read_json=read_json,
        algorithm_version_for_action=_algorithm_version_for_action,
        version_model_sha256_fn=_online_feedback_version_model_sha256,
    )


_ONLINE_FEEDBACK_SERVICE = OnlineFeedbackService(
    get_project=get_project,
    project_dir=project_dir,
    material_store=material_store,
    data_dir=DATA_DIR,
    now_iso=now_iso,
    sha256_file=sha256_file,
    read_json=read_json,
    write_json=write_json,
    safe_filename=safe_filename,
    business_file_url=_business_file_url,
    project_label_items=project_label_items,
    algorithm_version_for_action=_algorithm_version_for_action,
    active_image_batch=_v50_active_image_batch,
    begin_image_batch=_v50_begin_image_batch,
    end_image_batch=_v50_end_image_batch,
    add_image_record=add_image_record,
    write_annotation=write_annotation,
    ensure_default_datasets=ensure_default_datasets,
    material_governance_actor=_material_governance_actor,
    image_exts=IMAGE_EXTS,
    version_model_sha256_fn=_online_feedback_version_model_sha256,
    # Late-bound wrapper: the app module keeps owning label_governance_fence,
    # so a caller that replaces it still governs this service.
    label_fence=lambda project_path: label_governance_fence(project_path),
)
app.include_router(create_online_feedback_router(_ONLINE_FEEDBACK_SERVICE))


def _project_label_names(project: Dict[str, Any]) -> List[str]:
    out = []
    for i, x in enumerate(project.get("labels", []) or []):
        if isinstance(x, dict):
            name = x.get("name") or x.get("display_name") or x.get("code") or str(i)
        else:
            name = str(x)
        name = str(name).strip()
        if name:
            out.append(name)
    return out


def _labels_b64(labels: List[str]) -> str:
    try:
        raw = json.dumps(labels or [], ensure_ascii=False).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    except Exception:
        return ""


def _testable_version_pt_path(version: Mapping[str, Any]) -> Optional[Path]:
    """Return only an existing, nonempty trained PT for this exact algorithm version.

    The stored copy may retain an original filename other than best.pt; training
    versions carry the authoritative model identity, not the filename alone.
    """
    for key in ("best_path", "stored_path"):
        raw = str(version.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw)
        if path.suffix.lower() != ".pt" or path.name.casefold() == "last.pt":
            continue
        try:
            if path.is_file() and path.stat().st_size > 0:
                return path
        except OSError:
            continue
    return None


app.include_router(create_model_inference_router_3(_model_inference_service))


def v12_test_models(project_id: str, probe_optional: bool=True, model_scope: str=''):
    return _model_inference_service().v12_test_models(project_id, probe_optional, model_scope)


# -----------------------------
# v18 robust annotated dataset import
# -----------------------------

def _v19_check_zip_compression(archive, limits=None):
    from platform_core.storage.zip_import import inspect_zip_archive, UnsupportedZipCompression
    try:
        return inspect_zip_archive(archive, limits)
    except UnsupportedZipCompression as error:
        raise HTTPException(status_code=400, detail=error.message + " " + error.solution) from error


def _v18_safe_extract(
    zip_path: Path,
    dest: Path,
    progress_cb=None,
    *,
    selected_image_paths: Optional[Sequence[str]] = None,
):
    """Safely extract one ZIP, optionally filtering image payloads at source.

    When selected_image_paths is provided, only those image members are written;
    all non-image members (annotations/configuration) remain available so the
    existing COCO/VOC/YOLO parsers keep the same semantics. This avoids the old
    full-extract -> second-copy selected_root I/O path.
    """
    import stat
    from platform_core.storage.zip_import import (
        ActualSizeExceeded, CHUNK_BYTES, InsufficientDiskSpace,
        UnsafeArchive, read_limits, required_disk_bytes,
    )

    dest = dest.absolute()
    limits = read_limits()
    selected = None
    if selected_image_paths is not None:
        selected = {
            safe_member_path(v19_normalize_zip_path(value)).as_posix()
            for value in selected_image_paths
            if v19_normalize_zip_path(value)
        }
    with zipfile.ZipFile(zip_path, 'r') as zf:
        archive_plan, _ = _v19_check_zip_compression(zf, limits)
        planned = []
        for member, relative, directory in archive_plan:
            if directory:
                continue
            name = relative.as_posix()
            target = dest / name
            is_image = Path(name).suffix.lower() in IMAGE_EXTS
            if selected is not None and is_image and name not in selected:
                continue
            planned.append((member, name, target))

        def check_target(target):
            # Inspect the original path before resolve can hide a reparse hop.
            for path in reversed((target, *target.parents)):
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x0400:
                    raise UnsafeArchive('ZIP destination contains a link or reparse point')
            if target.exists() and not target.is_file():
                raise UnsafeArchive('ZIP destination is not a regular file')

        declared = sum(member.file_size for member, _, _ in planned)
        written = 0
        def check_disk():
            existing = dest
            while not existing.exists():
                existing = existing.parent
            free = shutil.disk_usage(existing).free
            required = required_disk_bytes(declared, limits, written_bytes=written)
            if free < required:
                raise InsufficientDiskSpace('Insufficient free space for ZIP extraction',
                    context={'free_bytes': free, 'required_bytes': required, 'written_bytes': written})

        for _, _, target in planned:
            check_target(target)
        check_disk()
        total = len(planned)
        for idx, (member, name, target) in enumerate(planned, 1):
            check_target(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f'.part-{uuid.uuid4().hex}.tmp')
            owns_temporary = False
            try:
                with temporary.open('xb') as out:
                    owns_temporary = True
                    actual = 0
                    with zf.open(member) as src:
                        while True:
                            if progress_cb:
                                progress_cb(idx - 1, total, f'正在解压 {idx}/{total} 个文件')
                            chunk = src.read(CHUNK_BYTES)
                            if not chunk:
                                break
                            if actual + len(chunk) > min(member.file_size, limits.max_single_bytes) or written + len(chunk) > min(declared, limits.max_total_bytes):
                                raise ActualSizeExceeded('Streamed ZIP data exceeds its size ceiling')
                            check_disk()
                            out.write(chunk)
                            actual += len(chunk)
                            written += len(chunk)
                    if actual != member.file_size:
                        raise UnsafeArchive('ZIP member ended before its declared size', code='ZIP_INVALID_ARCHIVE')
                    out.flush()
                check_target(target)
                os.replace(temporary, target)
            except OSError as error:
                import errno
                if error.errno in {errno.ENOSPC, getattr(errno, 'EDQUOT', errno.ENOSPC)}:
                    raise InsufficientDiskSpace('Insufficient free space for ZIP extraction') from error
                raise
            finally:
                if owns_temporary:
                    temporary.unlink(missing_ok=True)
            if progress_cb:
                progress_cb(idx, total, f'正在解压 {idx}/{total} 个文件')
        if progress_cb and total == 0:
            progress_cb(0, 0, 'ZIP 中没有需要解压的文件')


def _v18_split_from_path(path: Path) -> str:
    parts = [x.lower() for x in path.parts]
    if any(x in parts for x in ['valid', 'val', 'validation']):
        return 'val'
    if 'test' in parts or 'testing' in parts:
        return 'test'
    return 'train'


def _v18_set_image_split(project_id: str, image_id: str, split: str):
    patch = {
        'split': split if split in {'train','val','test'} else 'train',
        'updated_at': now_iso(),
    }
    if not _v50_queue_image_patch(project_id, image_id, patch):
        material_store(project_id).patch({str(image_id): patch})


def _v18_read_names_from_text_file(path: Path) -> List[str]:
    try:
        lines = [normalize_label(x) for x in path.read_text(encoding='utf-8', errors='ignore').splitlines()]
        return [x for x in lines if x]
    except Exception:
        return []


def _v18_collect_class_names(root: Path, label_files: Optional[List[Path]] = None) -> List[str]:
    # 常见格式：data.yaml / classes.txt / obj.names / _darknet.labels
    for yf in list(root.rglob('data.yaml')) + list(root.rglob('*.yaml')) + list(root.rglob('*.yml')):
        names = read_yaml_names(yf)
        if names:
            return [normalize_label(x) for x in names]
    for fn in ['classes.txt', 'obj.names', '_darknet.labels']:
        for cf in root.rglob(fn):
            names = _v18_read_names_from_text_file(cf)
            if names:
                return names
    # 无类别文件时，从 YOLO txt 最大 class_id 自动生成 class_0..class_n
    max_cls = -1
    for lf in label_files or []:
        try:
            for line in lf.read_text(encoding='utf-8', errors='ignore').splitlines():
                ps = line.strip().split()
                if len(ps) >= 5:
                    max_cls = max(max_cls, int(float(ps[0])))
        except Exception:
            pass
    if max_cls >= 0:
        return [f'class_{i}' for i in range(max_cls + 1)]
    return []


def _v19_record_folder_source(project_id, root, source, image_id, context):
    if not context or not context.get('folder_confirmation'):
        return False
    confirmation = context['folder_confirmation']
    source_path = source.relative_to(root).as_posix()
    key = zip_folders.folder_key(source_path)
    rule = confirmation['rules'].get(key)
    if rule is None or source_path not in context['folder_image_paths']:
        raise RuntimeError('导入素材不属于已冻结的文件夹范围')
    evidence = {
        'job_id': confirmation['job_id'], 'source_zip_sha256': confirmation['source_zip_sha256'],
        'source_scan_digest': confirmation['scan_digest'], 'source_path': source_path,
        'rule_digest': context['folder_confirmation_digest'], **rule,
        'classification_status': 'pending' if rule['sample_type'] == 'negative' else 'applied',
    }
    patch = {'zip_folder_source': evidence}
    if rule['sample_type'] == 'positive':
        patch['upload_intended_label_codes'] = rule['intended_label_codes']
    if not _v50_queue_image_patch(project_id, image_id, patch):
        raise RuntimeError('ZIP 素材来源未能与素材索引一起提交')
    return True


def _v18_image_lookup(root: Path):
    imgs = [x for x in root.rglob('*') if x.is_file() and x.suffix.lower() in IMAGE_EXTS]
    by_name: Dict[str, Path] = {}
    by_stem: Dict[str, List[Path]] = {}
    by_rel: Dict[str, Path] = {}
    for x in imgs:
        by_name.setdefault(x.name, x)
        by_stem.setdefault(x.stem, []).append(x)
        try:
            by_rel[str(x.relative_to(root)).replace('\\','/')] = x
        except Exception:
            pass
    return imgs, by_name, by_stem, by_rel


def _v18_resolve_import_label_id(
    project: Dict[str, Any],
    source_key: str,
    source_name: str,
    label_mapping: Optional[Dict[str, str]],
) -> int:
    normalized_name = normalize_label(source_name)
    if label_mapping is None:
        return ensure_label(project, normalized_name)
    target = str(
        label_mapping.get(str(source_key))
        or label_mapping.get(normalized_name)
        or ""
    ).strip()
    if not target:
        raise ValueError(f"外部标签 {source_name or source_key} 尚未映射到平台标签")
    labels = project.get("labels") or []
    if target not in labels:
        raise ValueError(f"已确认的平台标签已失效：{target}")
    return labels.index(target)


def _v18_confirmed_import_scope(
    label_mapping: Optional[Dict[str, str]],
) -> Optional[List[str]]:
    if label_mapping is None:
        return None
    return sorted({
        str(target).strip()
        for target in label_mapping.values()
        if str(target).strip()
    })


def _v19_import_box_provenance(
    import_context: Optional[Dict[str, Any]],
    *,
    source_format: str,
    source_class_id: Any,
    source_label_name: str,
    canonical_label: str,
    canonical_project_class_id: int,
) -> Dict[str, Any]:
    if not import_context:
        return {}
    return {
        "source": "imported",
        "source_task_id": str(import_context.get("source_task_id") or import_context.get("import_batch_id") or ""),
        "import_batch_id": str(import_context.get("import_batch_id") or ""),
        "source_format": str(source_format or "").lower(),
        "source_class_id": str(source_class_id),
        "source_label_name": str(source_label_name or ""),
        "canonical_label_id": str(canonical_label or ""),
        "canonical_project_class_id": int(canonical_project_class_id),
        "mapping_method": "manual",
        "confirmed_at": str(import_context.get("confirmed_at") or ""),
    }


def _v18_import_coco(
    project_id: str,
    root: Path,
    dataset_id: str,
    report: Dict[str, Any],
    progress_cb=None,
    label_mapping: Optional[Dict[str, str]] = None,
    import_context: Optional[Dict[str, Any]] = None,
) -> bool:
    json_files = []
    for jp in root.rglob('*.json'):
        try:
            data = json.loads(jp.read_text(encoding='utf-8', errors='ignore'))
            if isinstance(data, dict) and isinstance(data.get('images'), list) and isinstance(data.get('annotations'), list) and isinstance(data.get('categories'), list):
                json_files.append((jp, data))
        except Exception:
            continue
    if not json_files:
        return False
    project = get_project(project_id)
    import_scope = _v18_confirmed_import_scope(label_mapping)
    image_files, by_name, by_stem, by_rel = _v18_image_lookup(root)
    total_expected=sum(len(coco.get('images',[])) for _,coco in json_files) or 1
    progress_done=0
    seen_sources: set[str] = set()
    for ann_json, coco in json_files:
        split = _v18_split_from_path(ann_json)
        cats = sorted(coco.get('categories', []), key=lambda c: int(c.get('id', 0)))
        if import_context is not None and not import_scope and coco.get('annotations'):
            raise ValueError("structured annotation has no confirmed platform label scope")
        cat_to_class = {}
        cat_source_names = {}
        for c in cats:
            label = normalize_label(c.get('name') or f'class_{c.get("id")}')
            cid = int(c.get('id'))
            cat_source_names[cid] = label
            if import_scope or import_context is None:
                cat_to_class[cid] = _v18_resolve_import_label_id(
                    project, str(cid), label, label_mapping,
                )
        anns_by_img: Dict[int, List[Dict[str, Any]]] = {}
        for a in coco.get('annotations', []):
            try:
                anns_by_img.setdefault(int(a.get('image_id')), []).append(a)
            except Exception:
                pass
        for im in coco.get('images', []):
            file_name = str(im.get('file_name') or '').replace('\\','/')
            if import_context and import_context.get('folder_confirmation'):
                source_path = zip_folders.structured_image(file_name, ann_json.relative_to(root).as_posix(),
                    import_context['scan_image_paths'], import_context['image_stems'])
                src = by_rel.get(source_path)
            else:
                src = by_rel.get(file_name) or by_name.get(Path(file_name).name)
                if not src and Path(file_name).stem in by_stem:
                    src = by_stem[Path(file_name).stem][0]
            if not src or not src.exists():
                report['missing_images'] += 1
                continue
            source_ref = str(src.relative_to(root))
            if source_ref in seen_sources:
                continue
            boxes=[]
            image_annotations = anns_by_img.get(int(im.get('id')), [])

            def build_final_annotation(record):
                for a in image_annotations:
                    cid = int(a.get('category_id', -1))
                    if cid not in cat_to_class:
                        continue
                    bbox = a.get('bbox') or []
                    if len(bbox) < 4:
                        continue
                    x,y,w,h = [float(v) for v in bbox[:4]]
                    if w < 2 or h < 2:
                        report['invalid_boxes'] += 1
                        continue
                    cls = cat_to_class[cid]
                    canonical = project['labels'][cls]
                    boxes.append({
                        'id': uuid.uuid4().hex[:10],
                        'class_id': cls,
                        'label': canonical,
                        'x1': round(max(0, x), 2),
                        'y1': round(max(0, y), 2),
                        'x2': round(min(record['width'], x + w), 2),
                        'y2': round(min(record['height'], y + h), 2),
                        **_v19_import_box_provenance(
                            import_context,
                            source_format='coco',
                            source_class_id=cid,
                            source_label_name=cat_source_names.get(cid, ''),
                            canonical_label=canonical,
                            canonical_project_class_id=cls,
                        ),
                    })
                return boxes

            # An image explicitly listed in a structured COCO manifest with a
            # confirmed class mapping is a verified empty example when it has
            # no boxes for those classes. An unmapped/raw ZIP remains unknown.
            if import_context is not None and not import_scope:
                if image_annotations:
                    raise ValueError("structured annotation has no confirmed platform label scope")
                rec = add_image_record(
                    project_id, src, Path(file_name).name or src.name, 'imported_coco', dataset_id,
                )
            else:
                rec = add_image_record(
                    project_id, src, Path(file_name).name or src.name, 'imported_coco', dataset_id,
                    annotation_builder=build_final_annotation,
                    annotation_scope=import_scope,
                    empty_annotation_state="confirmed_empty",
                )
            if not rec:
                report['skipped_images'] += 1
                continue
            seen_sources.add(source_ref)
            if not _v19_record_folder_source(project_id, root, src, rec['id'], import_context):
                _v18_set_image_split(project_id, rec['id'], split)
            report.setdefault('imported_image_ids', []).append(rec['id'])
            report.setdefault('_imported_source_paths', []).append(str(src.relative_to(root)))
            for _b in boxes:
                _lab = str(_b.get('label') or '').strip()
                if _lab: report.setdefault('label_box_counts', {})[_lab] = report.setdefault('label_box_counts', {}).get(_lab, 0) + 1
            report['imported_images'] += 1
            report['boxes'] += len(boxes)
            if boxes: report['annotated_images'] += 1
            progress_done += 1
            if progress_cb:
                progress_cb(
                    progress_done, total_expected,
                    f'正在转换 COCO 标签并写入标注 {progress_done}/{total_expected}',
                )
    report['detected_format'] = 'COCO'
    return True


def _v18_import_voc(
    project_id: str,
    root: Path,
    dataset_id: str,
    report: Dict[str, Any],
    progress_cb=None,
    label_mapping: Optional[Dict[str, str]] = None,
    import_context: Optional[Dict[str, Any]] = None,
) -> bool:
    import xml.etree.ElementTree as ET
    xml_files = list(root.rglob('*.xml'))
    if not xml_files:
        return False
    image_files, by_name, by_stem, by_rel = _v18_image_lookup(root)
    project = get_project(project_id)
    import_scope = _v18_confirmed_import_scope(label_mapping)
    any_imported = False
    total_expected=max(1,len(xml_files)); progress_done=0
    seen_sources: set[str] = set()
    for xp in xml_files:
        try:
            r = ET.parse(xp).getroot()
        except Exception:
            continue
        filename = (r.findtext('filename') or '').strip()
        if import_context and import_context.get('folder_confirmation'):
            source_path = zip_folders.structured_image(filename or xp.stem, xp.relative_to(root).as_posix(),
                import_context['scan_image_paths'], import_context['image_stems'])
            src = by_rel.get(source_path)
        else:
            src = by_name.get(filename) or by_stem.get(Path(filename).stem if filename else xp.stem, [None])[0]
        if not src:
            report['missing_images'] += 1
            continue
        source_ref = str(src.relative_to(root))
        if source_ref in seen_sources:
            continue
        split = _v18_split_from_path(xp)
        boxes=[]
        objects = list(r.findall('object'))
        if import_context is not None and not import_scope and objects:
            raise ValueError("structured annotation has no confirmed platform label scope")

        def build_final_annotation(record):
            for obj in objects:
                label = normalize_label(obj.findtext('name') or 'object')
                if not label: continue
                cls = _v18_resolve_import_label_id(
                    project, label, label, label_mapping,
                )
                bb = obj.find('bndbox')
                if bb is None: continue
                try:
                    x1=float(bb.findtext('xmin')); y1=float(bb.findtext('ymin')); x2=float(bb.findtext('xmax')); y2=float(bb.findtext('ymax'))
                except Exception:
                    report['invalid_boxes'] += 1
                    continue
                if x2-x1<2 or y2-y1<2:
                    report['invalid_boxes'] += 1
                    continue
                canonical = project['labels'][cls]
                boxes.append({
                    'id': uuid.uuid4().hex[:10],
                    'class_id': cls,
                    'label': canonical,
                    'x1': round(max(0, x1), 2),
                    'y1': round(max(0, y1), 2),
                    'x2': round(min(record['width'], x2), 2),
                    'y2': round(min(record['height'], y2), 2),
                    **_v19_import_box_provenance(
                        import_context,
                        source_format='voc',
                        source_class_id=label,
                        source_label_name=label,
                        canonical_label=canonical,
                        canonical_project_class_id=cls,
                    ),
                })
            return boxes

        # A present, parsed VOC sidecar with no <object> is a confirmed
        # negative for explicitly mapped source classes, not an unknown raw
        # image. Without a confirmed mapping, preserve unannotated status.
        if import_context is not None and not import_scope:
            rec = add_image_record(
                project_id, src, src.name, 'imported_voc', dataset_id,
            )
        else:
            rec = add_image_record(
                project_id, src, src.name, 'imported_voc', dataset_id,
                annotation_builder=build_final_annotation,
                annotation_scope=import_scope,
                empty_annotation_state="confirmed_empty",
            )
        if not rec:
            report['skipped_images'] += 1
            continue
        seen_sources.add(source_ref)
        if not _v19_record_folder_source(project_id, root, src, rec['id'], import_context):
            _v18_set_image_split(project_id, rec['id'], split)
        report.setdefault('imported_image_ids', []).append(rec['id'])
        report.setdefault('_imported_source_paths', []).append(str(src.relative_to(root)))
        for _b in boxes:
            _lab = str(_b.get('label') or '').strip()
            if _lab: report.setdefault('label_box_counts', {})[_lab] = report.setdefault('label_box_counts', {}).get(_lab, 0) + 1
        report['imported_images'] += 1; report['boxes'] += len(boxes)
        if boxes: report['annotated_images'] += 1
        any_imported = True
        progress_done += 1
        if progress_cb:
            progress_cb(
                progress_done, total_expected,
                f'正在转换 VOC 标签并写入标注 {progress_done}/{total_expected}',
            )
    if any_imported:
        report['detected_format'] = 'Pascal VOC'
    return any_imported


def _v18_import_yolo(
    project_id: str,
    root: Path,
    dataset_id: str,
    report: Dict[str, Any],
    progress_cb=None,
    label_mapping: Optional[Dict[str, str]] = None,
    import_context: Optional[Dict[str, Any]] = None,
) -> bool:
    label_files = [x for x in root.rglob('*.txt') if x.name.lower() not in {'classes.txt','obj.names','_darknet.labels','train.txt','val.txt','test.txt'}]
    image_files, by_name, by_stem, by_rel = _v18_image_lookup(root)
    if not image_files:
        return False
    names = _v18_collect_class_names(root, label_files)
    project = get_project(project_id)
    import_scope = _v18_confirmed_import_scope(label_mapping)
    invalid_only = import_context is not None and import_context.get("scan_kind") == "ANNOTATION_INVALID"
    if import_context is not None and not import_scope and names and not invalid_only and any(
        lf.read_text(encoding='utf-8', errors='ignore').strip() for lf in label_files
    ):
        raise ValueError("structured annotation has no confirmed platform label scope")
    if label_mapping is None and import_context is None:
        if names:
            for n in names:
                ensure_label(project, n)
        elif label_files and not project.get('labels'):
            ensure_label(project, 'object')
            names = ['object']
    imported_names = names or project.get('labels', [])
    label_by_stem: Dict[str, List[Path]] = {}
    for lf in label_files:
        label_by_stem.setdefault(lf.stem, []).append(lf)
    folder_mode = bool(import_context and import_context.get('folder_confirmation'))
    label_paths = {file.relative_to(root).as_posix(): file for file in label_files} if folder_mode else {}
    label_stems = zip_folders.sources_by_stem(label_paths) if folder_mode else {}
    any_imported = False
    total_expected=max(1,len(image_files)); progress_done=0
    for img in image_files:
        split = _v18_split_from_path(img)
        cands = label_by_stem.get(img.stem, [])
        label_file = None
        if folder_mode:
            path = zip_folders.yolo_sidecar(img.relative_to(root).as_posix(), label_paths, label_stems, import_context['image_stems'])
            label_file = label_paths.get(path)
        elif cands:
            # 优先选与图片同 split 且路径包含 labels 的 txt
            same_split = [x for x in cands if _v18_split_from_path(x) == split]
            label_file = next((x for x in same_split if any(part.lower()=='labels' for part in x.parts)), same_split[0] if same_split else cands[0])
        boxes=[]

        has_label_truth = bool(label_file and label_file.exists())
        label_text = (
            label_file.read_text(encoding='utf-8', errors='ignore')
            if has_label_truth else ""
        )
        if import_context is not None and not label_text.strip():
            # An empty sidecar is not an affirmative manual review of no
            # target. A mixed ZIP still imports this image as unannotated.
            has_label_truth = False
        if invalid_only and has_label_truth:
            # Nonempty, malformed sidecars are not positive evidence and are
            # not authoritative negatives. Preserve the image for manual
            # correction with an explicit warning rather than fail the ZIP.
            has_label_truth = False
            report['invalid_annotation_files'] = report.get('invalid_annotation_files', 0) + 1
            if len(report.get('warnings') or []) < 20:
                report.setdefault('warnings', []).append(f'{img.name} 的标注异常，已作为未标注原图导入，须修复后再训练')
        if import_context is not None and has_label_truth and not import_scope:
            if label_text.strip():
                raise ValueError("structured annotation has no confirmed platform label scope")
            has_label_truth = False

        def build_final_annotation(record):
            if has_label_truth:
                for line in label_text.splitlines():
                    box = yolo_line_to_box(line, record['width'], record['height'])
                    if not box:
                        report['invalid_boxes'] += 1
                        continue
                    old_cls = int(box.get('class_id', -1))
                    if old_cls < 0:
                        report['invalid_boxes'] += 1
                        continue
                    source_label = (
                        normalize_label(imported_names[old_cls])
                        if old_cls < len(imported_names)
                        else f'class_{old_cls}'
                    )
                    if label_mapping is not None:
                        try:
                            new_cls = _v18_resolve_import_label_id(
                                project, str(old_cls), source_label, label_mapping,
                            )
                        except ValueError:
                            report['skipped_labels'] += 1
                            raise
                    elif old_cls < len(imported_names):
                        new_cls = get_label_id(project, source_label)
                    elif old_cls < len(project.get('labels', [])):
                        new_cls = old_cls
                    else:
                        report['skipped_labels'] += 1
                        continue
                    canonical = project['labels'][new_cls]
                    box['class_id'] = new_cls
                    box['label'] = canonical
                    box['id'] = uuid.uuid4().hex[:10]
                    box.update(_v19_import_box_provenance(
                        import_context,
                        source_format='yolo',
                        source_class_id=old_cls,
                        source_label_name=source_label,
                        canonical_label=canonical,
                        canonical_project_class_id=new_cls,
                    ))
                    boxes.append(box)
            return boxes

        if has_label_truth:
            rec = add_image_record(
                project_id, img, img.name, 'imported_yolo', dataset_id,
                annotation_builder=build_final_annotation,
                annotation_scope=import_scope,
                empty_annotation_state="unannotated" if import_context else "confirmed_empty",
            )
        else:
            report['unmatched_labels'] += 1
            rec = add_image_record(
                project_id, img, img.name, 'imported_yolo', dataset_id,
            )
        if not rec:
            report['skipped_images'] += 1
            continue
        if not _v19_record_folder_source(project_id, root, img, rec['id'], import_context):
            _v18_set_image_split(project_id, rec['id'], split)
        report.setdefault('imported_image_ids', []).append(rec['id'])
        report.setdefault('_imported_source_paths', []).append(str(img.relative_to(root)))
        for _b in boxes:
            _lab = str(_b.get('label') or '').strip()
            if _lab: report.setdefault('label_box_counts', {})[_lab] = report.setdefault('label_box_counts', {}).get(_lab, 0) + 1
        report['imported_images'] += 1; report['boxes'] += len(boxes)
        if boxes: report['annotated_images'] += 1
        any_imported = True
        progress_done += 1
        if progress_cb:
            progress_cb(
                progress_done, total_expected,
                f'正在转换 YOLO 标签并写入标注 {progress_done}/{total_expected}',
            )
    if any_imported:
        report['detected_format'] = 'YOLO'
    return any_imported


def _v19_import_unreferenced_images(
    project_id: str, root: Path, dataset_id: str, report: Dict[str, Any], import_context=None,
) -> None:
    """Import raw images omitted by a partial COCO/VOC annotation manifest.

    A structured annotation manifest defines labels, not the complete list of
    images that the user uploaded. Never discard unreferenced photos.
    """
    imported = set(report.pop('_imported_source_paths', []) or [])
    image_files, _, _, _ = _v18_image_lookup(root)
    for src in image_files:
        key = str(src.relative_to(root))
        if key in imported:
            continue
        rec = add_image_record(project_id, src, src.name, 'imported_raw', dataset_id)
        if rec is None:
            report['skipped_images'] += 1
            continue
        if not _v19_record_folder_source(project_id, root, src, rec['id'], import_context):
            _v18_set_image_split(project_id, rec['id'], _v18_split_from_path(src))
        report.setdefault('imported_image_ids', []).append(rec['id'])
        report['imported_images'] += 1
        report['unreferenced_raw_images'] = int(report.get('unreferenced_raw_images') or 0) + 1


@app.post('/api/v18/projects/{project_id}/datasets/{dataset_id}/import')
async def v18_import_dataset_auto(project_id: str, dataset_id: str, file: UploadFile = File(...)):
    _reject_legacy_annotated_import(project_id)
    get_project(project_id)
    p = project_dir(project_id)
    filename = safe_filename(file.filename or 'dataset.zip')
    ext = Path(filename).suffix.lower()
    if ext != '.zip':
        raise HTTPException(status_code=400, detail='请上传 zip 压缩包。支持 YOLO / COCO / Pascal VOC 常见数据集结构。')
    import_id = uuid.uuid4().hex[:10]
    temp_dir = p / 'imports' / f'v18_{import_id}'
    temp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = p / 'imports' / f'v18_{import_id}.zip'
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail='上传文件为空')
    zip_path.write_bytes(raw)
    report = {
        'ok': True,
        'file_name': filename,
        'file_size_mb': round(len(raw)/1024/1024, 2),
        'detected_format': '未知',
        'imported_images': 0,
        'annotated_images': 0,
        'boxes': 0,
        'missing_images': 0,
        'skipped_images': 0,
        'invalid_boxes': 0,
        'skipped_labels': 0,
        'unmatched_labels': 0,
        'labels': [],
        'warnings': [],
        'imported_image_ids': [],
        'label_box_counts': {},
    }
    try:
        _v18_safe_extract(zip_path, temp_dir)
        files_count = sum(1 for x in temp_dir.rglob('*') if x.is_file())
        if files_count == 0:
            raise HTTPException(status_code=400, detail='压缩包里没有文件')
        # 优先 COCO，其次 VOC，最后 YOLO。Roboflow YOLO 会走 YOLO；Roboflow COCO 会走 COCO。
        imported = _v18_import_coco(project_id, temp_dir, dataset_id, report)
        if not imported:
            imported = _v18_import_voc(project_id, temp_dir, dataset_id, report)
        if not imported:
            imported = _v18_import_yolo(project_id, temp_dir, dataset_id, report)
        if not imported or report['imported_images'] == 0:
            raise HTTPException(status_code=400, detail='没有识别到可导入的数据集。请确认压缩包里包含图片，以及 YOLO txt / COCO json / VOC xml 标注文件。')
        if report['boxes'] == 0:
            report['warnings'].append('已导入图片，但没有导入到有效标注框。请检查类别文件、txt/json/xml 标注是否存在，或在页面中重新标注。')
        report['labels'] = get_project(project_id).get('labels', [])
        return report
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        zip_path.unlink(missing_ok=True)


# -----------------------------
# v19 background import jobs + selectable parsing
# -----------------------------
from platform_core.material_ingestion_contracts import V19ImportStartReq


def v19_import_jobs_dir(project_id: str) -> Path:
    d = project_dir(project_id) / "import_jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def v19_job_dir(project_id: str, job_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(job_id)):
        raise HTTPException(status_code=422, detail="非法 ZIP 任务标识")
    return v19_import_jobs_dir(project_id) / job_id


def v19_job_file(project_id: str, job_id: str) -> Path:
    active = v19_job_dir(project_id, job_id) / "job.json"
    archived = v19_import_jobs_dir(project_id) / ".history" / str(job_id) / "job.json"
    return archived if not active.exists() and archived.is_file() else active


def v19_scan_images_file(project_id: str, job_id: str) -> Path:
    return v19_job_dir(project_id, job_id) / "scan-images.json"


def v19_report_file(project_id: str, job_id: str) -> Path:
    active = v19_job_dir(project_id, job_id) / "report.json"
    archived = v19_import_jobs_dir(project_id) / ".history" / str(job_id) / "report.json"
    return archived if not active.exists() and archived.is_file() else active


def v19_write_import_report(project_id: str, job_id: str, report: Dict[str, Any]):
    path = v19_report_file(project_id, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, dict(report or {}))


def v19_read_import_report(project_id: str, job_id: str, job: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    with _v19_stop_fence(project_id, job_id):
        return _v19_read_import_report_locked(project_id, job_id, job)


def _v19_read_import_report_locked(project_id: str, job_id: str, job: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    current = dict(job or v19_read_job(project_id, job_id) or {})
    if current.get("report_ref"):
        value = read_json(v19_report_file(project_id, job_id), {})
        if isinstance(value, dict):
            return value
    value = current.get("report")
    return dict(value) if isinstance(value, dict) else {}


app.include_router(create_material_ingestion_router_2(_material_ingestion_service))


def v19_unannotated_import_page(project_id: str, job_id: str, cursor: int=0, limit: int=150):
    return _material_ingestion_service().v19_unannotated_import_page(project_id, job_id, cursor, limit)


def v19_write_scan_images(project_id: str, job_id: str, images: List[Dict[str, Any]]):
    path = v19_scan_images_file(project_id, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, list(images or []))


def v19_class_samples_file(project_id: str, job_id: str) -> Path:
    return v19_job_dir(project_id, job_id) / "scan-class-samples.json"


def v19_write_class_samples(project_id: str, job_id: str, samples: Dict[str, List[Dict[str, Any]]]):
    atomic_write_json(v19_class_samples_file(project_id, job_id), dict(samples or {}))


def v19_read_class_samples(project_id: str, job_id: str) -> Dict[str, List[Dict[str, Any]]]:
    value = read_json(v19_class_samples_file(project_id, job_id), {})
    return value if isinstance(value, dict) else {}


def v19_read_scan_images(project_id: str, job_id: str) -> List[Dict[str, Any]]:
    path = v19_scan_images_file(project_id, job_id)
    if path.is_file():
        value = read_json(path, [])
        return value if isinstance(value, list) else []
    # Backward compatibility for historical jobs created before the manifest split.
    legacy = read_json(v19_job_file(project_id, job_id), {})
    value = legacy.get("images") if isinstance(legacy, dict) else []
    return value if isinstance(value, list) else []


def v19_normalize_zip_path(name: str) -> str:
    return str(name or "").replace("\\", "/").lstrip("/")


def v19_read_job(project_id: str, job_id: str) -> Dict[str, Any]:
    f = v19_job_file(project_id, job_id)
    # A read failure is not an empty successful task. In particular, Windows
    # may briefly deny a reader during atomic replacement of job.json.
    for attempt in range(4):
        f = v19_job_file(project_id, job_id)
        try:
            job = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(job, dict) or str(job.get("id") or "") != str(job_id):
                raise ValueError("invalid ZIP job identity")
            return job
        except FileNotFoundError as error:
            if attempt < 3 and v19_job_file(project_id, job_id) != f:
                continue  # terminal evidence was atomically archived during read
            raise HTTPException(status_code=404, detail="导入任务不存在") from error
        except PermissionError as error:
            # CRT file opens can report EACCES without a winerror attribute
            # for the same short sharing conflict. Persistent denial returns503.
            retryable = getattr(error, "winerror", None) in {5, 32, 33} or error.errno == errno.EACCES
            if retryable and attempt < 3:
                time.sleep(0.005 * (attempt + 1))
                continue
            raise HTTPException(status_code=503, detail="ZIP_JOB_READ_UNAVAILABLE: 导入任务状态暂时不可读取，请稍后重新查询。") from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=503, detail="ZIP_JOB_STATE_UNAVAILABLE: 导入任务状态不可读取或无效，请稍后重新查询。") from error


def v19_write_job(project_id: str, job: Dict[str, Any], *, allow_restart=False):
    job_id = str(job["id"])
    v19_job_dir(project_id, job_id).mkdir(parents=True, exist_ok=True)
    with _v19_stop_fence(project_id, job_id):
        try:
            previous = v19_read_job(project_id, job_id)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            previous = {}
        terminal = {"done", "failed", "cancelled", "canceled"}
        if str(previous.get("status") or "").lower() in terminal and str(job.get("status") or "").lower() not in terminal:
            if not (allow_restart and previous.get("status") == "failed" and not previous.get("history_hidden")):
                raise HTTPException(status_code=409, detail="ZIP 任务已结束，拒绝迟到状态覆盖")
        if previous.get("cancel_requested"):
            job["cancel_requested"] = True
        if previous.get("history_hidden"):
            job["history_hidden"] = True
            job["history_hidden_at"] = previous.get("history_hidden_at")
        _v19_write_job_locked(project_id, job)


def _v19_write_job_locked(project_id: str, job: Dict[str, Any]):
    job["updated_at"] = now_iso()
    f = v19_job_file(project_id, job["id"])
    f.parent.mkdir(parents=True, exist_ok=True)
    persisted = dict(job)
    images = persisted.pop("images", None)
    if isinstance(images, list):
        v19_write_scan_images(project_id, str(job["id"]), images)
        persisted["scan_images_ref"] = "scan-images.json"
    report = persisted.get("report")
    if isinstance(report, dict) and "imported_image_ids" in report:
        v19_write_import_report(project_id, str(job["id"]), report)
        compact_report = dict(report)
        compact_report.pop("imported_image_ids", None)
        persisted["report"] = compact_report
        persisted["report_ref"] = "report.json"
    # v19 job.json is the browser-visible progress truth. Never expose a
    # truncated JSON document while the worker is updating progress.
    atomic_write_json(f, persisted)


V19_ZIP_PHASE_WINDOWS: Dict[str, Tuple[float, float]] = {
    "UPLOAD": (0.0, 35.0),
    "MERGE": (35.0, 40.0),
    "VERIFY": (40.0, 42.0),
    "SCAN": (42.0, 48.0),
    "WAITING_CONFIRMATION": (48.0, 48.0),
    "READY": (48.0, 48.0),
    "QUEUE": (48.0, 48.0),
    "EXTRACT": (48.0, 68.0),
    "ANNOTATION_PARSE": (68.0, 96.0),
    "DB_COMMIT": (96.0, 99.0),
    "DONE": (100.0, 100.0),
}
V19_ZIP_PHASE_LABELS = {
    "UPLOAD": "上传 ZIP",
    "MERGE": "合并 ZIP 分片",
    "VERIFY": "校验 ZIP 结构",
    "SCAN": "扫描 ZIP 内容",
    "WAITING_CONFIRMATION": "等待确认标签",
    "READY": "等待启动后台导入",
    "QUEUE": "等待项目导入资源",
    "EXTRACT": "解压导入范围",
    "ANNOTATION_PARSE": "解析图片与标注",
    "DB_COMMIT": "提交素材与标注",
    "DONE": "导入完成",
    "FAILED": "导入失败",
}


def _v19_phase_metrics(phase: str, completed: int | float | None, total: int | float | None, *, started_at: float | None=None) -> Dict[str, Any]:
    return _material_ingestion_service()._v19_phase_metrics(phase, completed, total, started_at=started_at)


def v19_zip_display_progress(job: Mapping[str, Any]) -> Dict[str, Any]:
    return _material_ingestion_service().v19_zip_display_progress(job)


def v19_public_job(project_id: str, job: Dict[str, Any], image_limit: int=0) -> Dict[str, Any]:
    return _material_ingestion_service().v19_public_job(project_id, job, image_limit)


def v19_update_job(project_id: str, job_id: str, **kwargs):
    try:
        with _v19_stop_fence(project_id, job_id):
            job = v19_read_job(project_id, job_id)
            if str(job.get("status") or "").lower() in {"done", "failed", "cancelled", "canceled"}:
                raise RuntimeError("ZIP_JOB_ALREADY_TERMINAL: 已结束任务不能接受迟到进度")
            job.update(kwargs)
            v19_write_job(project_id, job)
            return job
    except Exception as error:
        _v19_job_diagnostic(project_id, job_id, error, operation="state_update")
        raise


def _v19_job_record_token(project_id, job_id):
    try:
        stat = v19_job_file(project_id, job_id).stat()
        return {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size, "inode": stat.st_ino}
    except OSError:
        return None


def _v19_unresolved_diagnostic(project_id, job_id):
    return _material_ingestion_service()._v19_unresolved_diagnostic(project_id, job_id)


def _v19_job_diagnostic(project_id: str, job_id: str, error: Exception, *, operation: str, job=None, report=None, committed=False):
    return _material_ingestion_service()._v19_job_diagnostic(project_id, job_id, error, operation=operation, job=job, report=report, committed=committed)


def _v19_fail_worker(project_id, job_id, error, *, job, report, started, committed=False):
    # Do not reread a missing record in an unprotected exception handler, and
    # never synthesize a successful record or delete committed formal data.
    try:
        with _v19_stop_fence(project_id, job_id):
            current = v19_read_job(project_id, job_id)
            if current.get("status") in {"done", "cancelled", "canceled"}:
                return
            current.update(
                status="failed", stage="导入异常，需核验" if committed else "导入失败",
                phase="FAILED", error=str(getattr(error, "detail", error)),
                report=report, formal_commit_completed=bool(committed),
                processing_seconds=round(max(0.0, time.time()-started), 2),
                finished_at=now_iso(), message="正式素材未被删除；请根据任务证据核验" if committed else str(getattr(error, "detail", error)),
            )
            v19_write_job(project_id, current)
    except Exception as state_error:
        _v19_job_diagnostic(project_id, job_id, state_error, operation="worker_failure_record",
                            job=job, report=report, committed=committed)
    _v19_job_diagnostic(project_id, job_id, error, operation="worker_failure",
                        job=job, report=report, committed=committed)


def v19_scan_zip(zip_path: Path, progress_cb=None, folder_confirmation=False) -> Dict[str, Any]:
    import xml.etree.ElementTree as ET

    images: List[Dict[str, Any]] = []
    hints = set()
    file_count = 0
    total_size = 0
    external_classes: List[Dict[str, Any]] = []
    detected_format = "images"
    annotation_box_count = 0
    annotated_image_stems: set[str] = set()
    annotated_paths = set()
    source_classes = {}
    nonempty_yolo_paths = set()
    annotation_sources = set()
    mapping_conflict = False
    last_scan_checkpoint = 0.0
    def scan_checkpoint(name):
        nonlocal last_scan_checkpoint
        tick = time.monotonic()
        if progress_cb and tick - last_scan_checkpoint >= 0.5:
            last_scan_checkpoint = tick
            try:
                progress_cb("SCAN", None, None, name)
            except (ServerZipImportError, _V19ImportStopped):
                raise
            except Exception:
                pass
    with zipfile.ZipFile(zip_path, "r") as zf:
        planned, _ = _v19_check_zip_compression(zf)
        canonical = {info.filename: path.as_posix() for info, path, is_dir in planned if not is_dir} if folder_confirmation else {}
        members = []
        infos = [
            (canonical.get(info.filename, v19_normalize_zip_path(info.filename)), info)
            for info in zf.infolist()
            if info.filename
            and not v19_normalize_zip_path(info.filename).endswith("/")
        ]
        scan_total = len(infos)
        for scan_index, (name, info) in enumerate(infos, 1):
            if not name:
                continue
            members.append((name, info))
            file_count += 1
            total_size += max(0, int(getattr(info, "file_size", 0) or 0))
            low = name.lower()
            suffix = Path(low).suffix
            if suffix in IMAGE_EXTS:
                images.append({
                    "path": name,
                    "name": Path(name).name,
                    "split": _v18_split_from_path(Path(name)),
                    "size_kb": round((info.file_size or 0) / 1024, 1),
                })
            if low.endswith("data.yaml") or low.endswith("data.yml") or "/labels/" in low:
                hints.add("YOLO")
            if low.endswith(".json") and ("coco" in low or "annotation" in low or "_annotations" in low):
                hints.add("COCO")
            if low.endswith(".xml"):
                hints.add("VOC")
            if progress_cb and (
                scan_index == 1
                or scan_index == scan_total
                or scan_index % 250 == 0
            ):
                try:
                    progress_cb("VERIFY", scan_index, scan_total, name)
                except (ServerZipImportError, _V19ImportStopped):
                    raise
                except Exception:
                    pass

        if progress_cb:
            try:
                progress_cb(
                    "SCAN",
                    None,
                    None,
                    "ZIP 目录校验完成，正在识别图片与外部标注",
                )
            except (ServerZipImportError, _V19ImportStopped):
                raise
            except Exception:
                pass

        image_paths = {row['path'] for row in images}
        image_stems = zip_folders.sources_by_stem(image_paths) if folder_confirmation else {}
        # Match the worker's import priority: COCO -> VOC -> YOLO.
        for name, info in members:
            scan_checkpoint(name)
            if Path(name).suffix.lower() != ".json":
                continue
            try:
                data = json.loads(zf.read(info).decode("utf-8", errors="ignore"))
            except (ServerZipImportError, _V19ImportStopped):
                raise
            except Exception:
                continue
            if not (
                isinstance(data, dict)
                and isinstance(data.get("images"), list)
                and isinstance(data.get("annotations"), list)
                and isinstance(data.get("categories"), list)
            ):
                continue
            counts: Dict[str, int] = {}
            image_sets: Dict[str, set] = {}
            for ann in data.get("annotations") or []:
                key = str(ann.get("category_id"))
                counts[key] = counts.get(key, 0) + 1
                image_sets.setdefault(key, set()).add(str(ann.get("image_id")))
            coco_files = {str(row.get("id")): Path(str(row.get("file_name") or "")).stem
                          for row in data.get("images") or [] if isinstance(row, dict)}
            annotated_image_stems.update(coco_files.get(str(row.get("image_id")), "")
                                         for row in data.get("annotations") or [] if isinstance(row, dict))
            rows = []
            for category in sorted(data.get("categories") or [], key=lambda row: int(row.get("id", 0))):
                key = str(int(category.get("id", 0)))
                label = normalize_label(category.get("name") or f"class_{key}")
                if label:
                    rows.append({
                        "class_id": key,
                        "name": label,
                        "box_count": counts.get(key, 0),
                        "image_count": len(image_sets.get(key, set())),
                    })
            if rows:
                if not folder_confirmation:
                    external_classes = rows
                    annotation_box_count = sum(int(row['box_count']) for row in rows)
                    detected_format = 'COCO'
                    break
                detected_format = 'COCO'
                if data['annotations']:
                    annotation_sources.add('COCO')
                for row in rows:
                    prior = source_classes.setdefault(row['class_id'], dict(row, box_count=0, image_count=0))
                    mapping_conflict |= prior['name'] != row['name']
                    prior['box_count'] += row['box_count']
                    prior['image_count'] += row['image_count']
                for image in data['images']:
                    path = zip_folders.structured_image(image.get('file_name'), name, image_paths, image_stems)
                    if path:
                        mapping_conflict |= path in annotated_paths
                        annotated_paths.add(path)
        if source_classes:
            external_classes = list(source_classes.values())
            annotation_box_count = sum(row['box_count'] for row in external_classes)

        if not external_classes:
            stats: Dict[str, Dict[str, Any]] = {}
            for name, info in members:
                scan_checkpoint(name)
                if Path(name).suffix.lower() != ".xml":
                    continue
                try:
                    root = ET.fromstring(zf.read(info))
                except (ServerZipImportError, _V19ImportStopped):
                    raise
                except Exception:
                    continue
                seen = set()
                for obj in root.findall("object"):
                    label = normalize_label(obj.findtext("name") or "")
                    if not label:
                        continue
                    row = stats.setdefault(label, {"class_id": label, "name": label, "box_count": 0, "image_count": 0})
                    row["box_count"] += 1
                    annotated_image_stems.add(Path(name).stem)
                    if label not in seen:
                        row["image_count"] += 1
                        seen.add(label)
                if folder_confirmation:
                    path = zip_folders.structured_image(root.findtext('filename') or Path(name).stem, name, image_paths, image_stems)
                    if path:
                        mapping_conflict |= path in annotated_paths
                        annotated_paths.add(path)
            if stats:
                external_classes = sorted(stats.values(), key=lambda row: str(row["name"]))
                annotation_box_count = sum(int(row["box_count"]) for row in external_classes)
                detected_format = "Pascal VOC"

        if not external_classes:
            names: List[str] = []
            dictionaries = []
            for name, info in members:
                scan_checkpoint(name)
                low = name.lower()
                base = Path(low).name
                if base in {"data.yaml", "data.yml"} or low.endswith(".yaml") or low.endswith(".yml"):
                    try:
                        parsed = yaml.safe_load(zf.read(info).decode("utf-8", errors="ignore")) or {}
                        raw_names = parsed.get("names", [])
                        if isinstance(raw_names, dict):
                            names = [
                                normalize_label(raw_names[key])
                                for key in sorted(raw_names, key=lambda value: int(value) if str(value).isdigit() else str(value))
                            ]
                        elif isinstance(raw_names, list):
                            names = [normalize_label(value) for value in raw_names]
                    except (ServerZipImportError, _V19ImportStopped):
                        raise
                    except Exception:
                        names = []
                    if names:
                        if not folder_confirmation:
                            break
                        dictionaries.append(names)
            if not names or folder_confirmation:
                for name, info in members:
                    if Path(name).name.lower() not in {"classes.txt", "obj.names", "_darknet.labels"}:
                        continue
                    try:
                        names = [
                            normalize_label(value)
                            for value in zf.read(info).decode("utf-8", errors="ignore").splitlines()
                            if normalize_label(value)
                        ]
                    except (ServerZipImportError, _V19ImportStopped):
                        raise
                    except Exception:
                        names = []
                    if names:
                        if not folder_confirmation:
                            break
                        dictionaries.append(names)
            if dictionaries:
                names = dictionaries[0]
                seen_names = {}
                for dictionary in dictionaries:
                    for class_id, name in enumerate(dictionary):
                        if name:
                            mapping_conflict |= seen_names.setdefault(class_id, name) != name

            counts: Dict[int, int] = {}
            image_sets: Dict[int, set] = {}
            for name, info in members:
                scan_checkpoint(name)
                low = name.lower()
                if Path(low).suffix != ".txt":
                    continue
                if Path(low).name in {"classes.txt", "obj.names", "_darknet.labels", "train.txt", "val.txt", "test.txt"}:
                    continue
                try:
                    lines = zf.read(info).decode("utf-8", errors="ignore").splitlines()
                except (ServerZipImportError, _V19ImportStopped):
                    raise
                except Exception:
                    continue
                if folder_confirmation and Path(name).stem not in image_stems and 'labels' not in Path(name).parts:
                    continue
                if folder_confirmation and any(line.strip() for line in lines):
                    nonempty_yolo_paths.add(name)
                for line in lines:
                    parts = line.strip().split()
                    if len(parts) < 5:
                        continue
                    try:
                        class_id = int(float(parts[0]))
                    except Exception:
                        continue
                    if class_id < 0:
                        continue
                    counts[class_id] = counts.get(class_id, 0) + 1
                    image_sets.setdefault(class_id, set()).add(Path(name).stem)
                    annotated_image_stems.add(Path(name).stem)
            if names or counts:
                max_class = max([len(names) - 1, *counts.keys()], default=-1)
                external_classes = [{
                    "class_id": str(index),
                    "name": names[index] if index < len(names) and names[index] else f"class_{index}",
                    "box_count": counts.get(index, 0),
                    "image_count": len(image_sets.get(index, set())),
                } for index in range(max_class + 1)]
                annotation_box_count = sum(int(row["box_count"]) for row in external_classes)
                detected_format = "YOLO"

        # A class dictionary is not annotation evidence. In particular, ZIPs
        # exported for future labeling often include data.yaml and one empty
        # .txt per image. Do not mistake these for verified background GT.
        nonempty_annotations = 0
        unreadable_annotations = 0
        annotation_sidecars = 0
        for name, info in members:
            scan_checkpoint(name)
            suffix = Path(name).suffix.lower()
            base = Path(name).name.lower()
            if suffix == ".txt":
                if base in {"classes.txt", "obj.names", "_darknet.labels", "train.txt", "val.txt", "test.txt"}:
                    continue
                if folder_confirmation and Path(name).stem not in image_stems and 'labels' not in Path(name).parts:
                    continue
                annotation_sidecars += 1
                try:
                    if info.file_size > 32 * 1024 * 1024:
                        unreadable_annotations += 1
                        continue
                    if zf.read(info).strip():
                        nonempty_annotations += 1
                        annotation_sources.add('YOLO')
                except (ServerZipImportError, _V19ImportStopped):
                    raise
                except Exception:
                    unreadable_annotations += 1
            elif suffix == ".xml":
                annotation_sidecars += 1
                try:
                    if info.file_size > 32 * 1024 * 1024:
                        unreadable_annotations += 1
                        continue
                    if ET.fromstring(zf.read(info)).find("object") is not None:
                        nonempty_annotations += 1
                        annotation_sources.add('Pascal VOC')
                except (ServerZipImportError, _V19ImportStopped):
                    raise
                except Exception:
                    unreadable_annotations += 1
            elif suffix == ".json" and ("coco" in name.lower() or "annotation" in name.lower()):
                try:
                    if info.file_size > 64 * 1024 * 1024:
                        unreadable_annotations += 1
                        continue
                    raw = json.loads(zf.read(info).decode("utf-8"))
                    if isinstance(raw, dict) and isinstance(raw.get("annotations"), list):
                        annotation_sidecars += 1
                        if raw["annotations"]:
                            nonempty_annotations += 1
                            annotation_sources.add('COCO')
                except (ServerZipImportError, _V19ImportStopped):
                    raise
                except Exception:
                    unreadable_annotations += 1

        associated_stems = {Path(row["path"]).stem for row in images}
        annotated_count = len(associated_stems.intersection(annotated_image_stems))
        if folder_confirmation:
            mapping_conflict |= bool(annotation_sources - {detected_format})
            if detected_format == 'YOLO':
                label_paths = {name for name, _ in members if name.lower().endswith('.txt')
                               and Path(name).name.lower() not in {'classes.txt', 'obj.names', '_darknet.labels', 'train.txt', 'val.txt', 'test.txt'}}
                label_stems = zip_folders.sources_by_stem(label_paths)
                matched = {path: zip_folders.yolo_sidecar(path, label_paths, label_stems, image_stems) for path in image_paths}
                annotated_paths = {path for path, sidecar in matched.items() if sidecar in nonempty_yolo_paths}
                mapping_conflict |= bool(nonempty_yolo_paths - set(matched.values()))
            if annotation_sources:
                nonempty_annotations = max(1, nonempty_annotations)
            else:
                annotated_paths.clear()
            annotated_count = len(annotated_paths)
            for row in images:
                if row['path'] in annotated_paths:
                    row['annotation_format'] = detected_format
        scan_kind = (
            "ANNOTATION_INVALID" if unreadable_annotations and not nonempty_annotations
            else "RAW_UNANNOTATED" if not nonempty_annotations
            else "MIXED" if annotation_box_count and annotated_count < (len(images) if folder_confirmation else len(associated_stems))
            else "ANNOTATED_VALID" if annotation_box_count else "ANNOTATION_INVALID"
        )

        # Only bounded per-class source refs are stored, never preview image
        # bytes or guessed target labels. The API serves images from source.zip
        # before any AnnotationRepository/MaterialRepository mutation.
        class_samples = build_zip_class_samples(zf, images, external_classes, detected_format, limit=8, normalize_name=normalize_label)
        if progress_cb:
            try:
                progress_cb(
                    "SCAN",
                    None,
                    None,
                    f"扫描完成：{len(images)} 张图片，格式 {detected_format}",
                )
            except (ServerZipImportError, _V19ImportStopped):
                raise
            except Exception:
                pass

    return {
        "class_samples": class_samples,
        **({'folder_mapping_conflict': mapping_conflict} if folder_confirmation else {}),
        "file_count": file_count,
        "image_count": len(images),
        "images": images,
        "format_hints": sorted(hints) or ["未知"],
        "detected_format": detected_format,
        "external_classes": external_classes,
        "annotation_box_count": annotation_box_count,
        "annotated_source_images": annotated_count,
        "unannotated_source_images": max(0, len(images) - annotated_count),
        "scan_kind": scan_kind,
        "annotation_sidecars": annotation_sidecars,
        "nonempty_annotation_files": nonempty_annotations,
        "unreadable_annotation_files": unreadable_annotations,
        "uncompressed_size_mb": round(total_size / 1024 / 1024, 2),
    }


def _v19_prepare_scan(project_id: str, scan: Dict[str, Any]) -> Dict[str, Any]:
    prepared = dict(scan or {})
    classes = list(prepared.get("external_classes") or [])
    if prepared.get("scan_kind") == "RAW_UNANNOTATED":
        # A data.yaml/classes.txt describes possible *classes*, not proof that
        # any image was annotated. Keep it as a hint for the following AI task.
        prepared["external_class_hints"] = external_label_facts(classes) if classes else []
        prepared["external_classes"] = []
        prepared["label_confirmation_required"] = False
    elif classes:
        prepared["external_classes"] = external_label_facts(classes)
        prepared["label_confirmation_required"] = True
    else:
        prepared["external_classes"] = []
        prepared["label_confirmation_required"] = False
    return prepared


def _v19_folder_archive_digest(path: Path, check_stop=None) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
            if check_stop:
                check_stop()
            digest.update(chunk)
    return digest.hexdigest()


def _v19_store_folder_scan(project_id, job_id, zip_path, scan, check_stop=None):
    source_sha = _v19_folder_archive_digest(zip_path, check_stop)
    images = scan['images']
    if len({row['path'] for row in images}) != len(images):
        raise ValueError('ZIP 中存在重复规范化图片路径')
    scan_digest = zip_folders.scan_identity(project_id, job_id, source_sha, images, scan)
    scan.update(source_zip_sha256=source_sha, source_scan_digest=scan_digest,
                folder_confirmation_required=True)
    atomic_write_json(v19_job_dir(project_id, job_id) / 'scan-folders.json', {
        'source_scan_digest': scan_digest, 'items': zip_folders.folder_rows(images),
    })


def v19_import_folders(project_id: str, job_id: str, offset: int=Query(0, ge=0), limit: int=Query(50, ge=1, le=100)):
    return _material_ingestion_service().v19_import_folders(project_id, job_id, offset, limit)


def v19_build_report_base(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": True,
        "batch_id": job.get("batch_id") or job.get("id"),
        "file_name": job.get("file_name", ""),
        "file_size_mb": job.get("file_size_mb", 0),
        "detected_format": "未知",
        "imported_images": 0,
        "annotated_images": 0,
        "boxes": 0,
        "missing_images": 0,
        "skipped_images": 0,
        "invalid_boxes": 0,
        "skipped_labels": 0,
        "unmatched_labels": 0,
        "labels": [],
        "warnings": [],
        "imported_image_ids": [],
        "label_box_counts": {},
    }


def _v19_assert_frozen_mapping_targets_active(project_id: str, label_mapping: Optional[Dict[str, str]]) -> None:
    return _material_ingestion_service()._v19_assert_frozen_mapping_targets_active(project_id, label_mapping)


class _V19ImportStopped(RuntimeError):
    pass


def _v19_stop_fence(project_id: str, job_id: str) -> FileLock:
    # The same original lock must be reentrant for state updates inside commit,
    # start and cancel; never unlink its inode during history cleanup.
    return FileLock(str(v19_job_dir(project_id, job_id) / ".stop.lock"), timeout=120, is_singleton=True)


def _v19_check_stop(project_id: str, job_id: str) -> None:
    if v19_read_job(project_id, job_id).get("cancel_requested"):
        raise _V19ImportStopped("用户中断了尚未提交的 ZIP 素材导入")


def _v19_cleanup_uncommitted_job(project_id: str, job_id: str, *, preserve_report=False) -> Dict[str, Any]:
    """Delete only files owned by one pre-commit ZIP job; keep job.json audit."""
    jobs_root = v19_import_jobs_dir(project_id).resolve()
    job_root = (jobs_root / str(job_id)).resolve()
    if job_root.parent != jobs_root:
        raise RuntimeError("非法 ZIP 导入任务标识，已拒绝清理")

    released = 0
    removed: List[str] = []
    for name in (
        "source.zip", "source.zip.assembling", "scan-images.json", "scan-folders.json",
        "scan-class-samples.json", "report.json",
    ):
        if preserve_report and name == "report.json":
            continue
        path = job_root / name
        if not path.exists():
            continue
        try:
            if path.is_file():
                released += path.stat().st_size
            path.unlink(missing_ok=True)
            removed.append(name)
        except OSError as error:
            raise RuntimeError(f"无法清理任务文件 {name}: {error}") from error

    for name in ("extracted", "staging", "previews", "thumbnails"):
        path = job_root / name
        if not path.exists():
            continue
        try:
            for owned in path.rglob("*"):
                if owned.is_file():
                    try:
                        released += owned.stat().st_size
                    except OSError:
                        pass
            shutil.rmtree(path)
            removed.append(name + "/")
        except OSError as error:
            raise RuntimeError(f"无法清理任务目录 {name}: {error}") from error

    upload_root = project_dir(project_id) / "import_uploads" / str(job_id)
    if upload_root.exists():
        try:
            released += _v19_multipart_repository(project_id).discard(job_id)
            removed.append("multipart-session/")
        except (OSError, ValueError) as error:
            raise RuntimeError(f"无法清理任务分片会话: {error}") from error
    return {"released_bytes": int(released), "removed": removed}


def _v19_finish_cancel(project_id: str, job_id: str, *, message: str) -> Dict[str, Any]:
    """Finish a pre-commit cancellation or persist a visible retryable failure."""
    try:
        cleanup = _v19_cleanup_uncommitted_job(project_id, job_id)
    except Exception as error:
        job = v19_read_job(project_id, job_id)
        job.update(
            status="failed", stage="取消清理失败，可重试", phase="FAILED",
            cleanup_status="failed", cleanup_error=str(error),
            error=str(error), message="未删除任何正式素材；请重试取消清理",
            finished_at=now_iso(),
        )
        v19_write_job(project_id, job)
        return job
    job = v19_read_job(project_id, job_id)
    job.update(
        status="cancelled", stage="已取消并清理未提交缓存",
        phase="CANCELLED", progress=0, cancel_requested=True,
        cleanup_status="complete", cleanup_error="",
        cleanup_released_bytes=int(cleanup["released_bytes"]),
        cleanup_removed=list(cleanup["removed"]),
        error="", message=message, finished_at=now_iso(),
    )
    v19_write_job(project_id, job)
    return job



def _v19_fifo_import_jobs(project_id: str) -> List[Dict[str, Any]]:
    """Read existing v19 durable job files; no separate queue store or scheduler."""
    jobs = []
    for filename in v19_import_jobs_dir(project_id).glob("*/job.json"):
        job = read_json(filename, {})
        if isinstance(job, dict) and str(job.get("status") or "").lower() == "running":
            diagnostic = _v19_unresolved_diagnostic(project_id, str(job.get("id") or filename.parent.name))
            if diagnostic and diagnostic.get("operation") in {"worker_failure", "worker_exit"}:
                # The original worker has unwound the formal-import lock.
                # Do not let an unwritable stale record strand other ZIPs.
                continue
            jobs.append(job)

    def order(job):
        # Pre-FIFO running jobs take precedence: a migration must not overtake
        # work that was accepted under the previous contract.
        sequence = int(job.get("enqueue_sequence") or 0)
        return (
            0 if sequence <= 0 else 1,
            sequence if sequence > 0 else 0,
            str(job.get("enqueued_at") or job.get("created_at") or ""),
            str(job.get("id") or ""),
        )

    return sorted(jobs, key=order)


def _v19_fifo_queue_position(project_id: str, job_id: str) -> Optional[int]:
    return next(
        (number for number, job in enumerate(_v19_fifo_import_jobs(project_id), 1)
         if str(job.get("id") or "") == str(job_id)),
        None,
    )


def _v19_wait_fifo_turn(project_id: str, job_id: str) -> None:
    """The earliest *confirmed* durable job runs; an unconfirmed ZIP never blocks."""
    while True:
        _v19_check_stop(project_id, job_id)
        job = v19_read_job(project_id, job_id)
        if str(job.get("status") or "").lower() in {"cancelled", "canceled", "done", "failed"}:
            raise _V19ImportStopped("该 ZIP 导入任务已结束，禁止再次正式写入")
        queue = _v19_fifo_import_jobs(project_id)
        if not queue or str(queue[0].get("id") or "") == str(job_id):
            return
        time.sleep(0.2)


def _v19_finalize_report_messages(report, *, scan_kind):
    """Classify expected raw absence independently of integrity/import failures."""
    raw = str(scan_kind or "") == "RAW_UNANNOTATED"
    report["scan_kind"] = str(scan_kind or "")
    report["result_kind"] = "raw_unannotated" if raw else "annotation_import"
    if not raw and report.get("boxes", 0) == 0:
        report.setdefault("warnings", []).append("图片已入库，但未识别到有效标注；如预期带标注，请检查 YOLO txt / COCO json / VOC xml 结构。")
    if report.get("missing_images", 0):
        report.setdefault("warnings", []).append(f"有 {report.get('missing_images')} 条标注找不到对应图片。")
    if not raw and report.get("unmatched_labels", 0):
        report.setdefault("warnings", []).append(f"有 {report.get('unmatched_labels')} 张图片未匹配到对应标注文件。")
    if report.get("invalid_boxes", 0):
        report.setdefault("warnings", []).append(f"忽略了 {report.get('invalid_boxes')} 个无效标注框。")
    if report.get("skipped_images", 0):
        report.setdefault("warnings", []).append(f"有 {report.get('skipped_images')} 张图片导入失败或被跳过。")


def v19_import_worker(project_id: str, dataset_id: str, job_id: str, selected_paths: List[str]):
    try:
        _v19_import_worker_impl(project_id, dataset_id, job_id, selected_paths)
    except Exception as error:
        # Includes initial read failure and failures inside cancellation recovery.
        _v19_job_diagnostic(project_id, job_id, error, operation="worker_exit")


def _v19_apply_folder_classification(project_id, job, report):
    return _material_ingestion_service()._v19_apply_folder_classification(project_id, job, report)


def v19_retry_folder_classification(project_id: str, job_id: str):
    return _material_ingestion_service().v19_retry_folder_classification(project_id, job_id)


def _v19_import_worker_impl(project_id: str, dataset_id: str, job_id: str, selected_paths: List[str]):
    job = v19_read_job(project_id, job_id)
    if job.get("status") in {"done", "cancelled", "canceled", "failed"}:
        return
    processing_started = time.time()
    committed = False
    job_dir = v19_job_dir(project_id, job_id)
    zip_path = job_dir / "source.zip"
    extracted = job_dir / "extracted"
    selected_paths = [v19_normalize_zip_path(x) for x in selected_paths if x]
    total_selected = len(selected_paths) or int(job.get("image_count", 0) or 0)
    report = v19_build_report_base(job)
    frozen_mapping = dict(job.get("label_mapping") or {}) or None
    lock = _v50_project_import_lock(project_id)
    try:
        # Queue precedence is durable, while FileLock serializes writes across
        # web/worker processes. The former in-process RLock remains in place.
        _v19_wait_fifo_turn(project_id, job_id)
        with FileLock(str(v19_import_jobs_dir(project_id) / ".formal-import.lock"), timeout=-1), lock:
            _v19_wait_fifo_turn(project_id, job_id)
            _v19_check_stop(project_id, job_id)
            _v19_assert_frozen_mapping_targets_active(project_id, frozen_mapping)
            _v50_begin_image_batch(project_id)
            try:
                extract_started = time.time()
                v19_update_job(
                    project_id, job_id,
                    status="running", stage="正在解压数据集", progress=48,
                    phase="EXTRACT", phase_completed=0, phase_total=0, phase_unit="files",
                    phase_progress=0, phase_elapsed_seconds=0, eta_seconds=None,
                    total_selected=total_selected, processed=0,
                    message="已获得项目导入锁，开始按导入范围解压",
                    processing_started_at=now_iso(),
                )
                if extracted.exists():
                    shutil.rmtree(extracted, ignore_errors=True)
                extracted.mkdir(parents=True, exist_ok=True)
                last_extract_emit = 0.0
                def extract_progress(done,total,msg):
                    nonlocal last_extract_emit
                    _v19_check_stop(project_id, job_id)
                    tick = time.monotonic()
                    if done != total and tick - last_extract_emit < 0.6:
                        return
                    last_extract_emit = tick
                    metrics = _v19_phase_metrics("EXTRACT", done, total, started_at=extract_started)
                    v19_update_job(
                        project_id, job_id,
                        stage="正在解压数据集",
                        progress=round(48 + metrics["phase_progress"] * 0.20, 2),
                        phase_unit="files",
                        processed=done,
                        total_files=total,
                        message=msg,
                        processing_seconds=round(max(0.0, time.time()-processing_started), 1),
                        **metrics,
                    )
                folder_plan = job.get('folder_confirmation')
                if folder_plan and (zip_folders.digest(folder_plan) != job.get('folder_confirmation_digest')
                                    or _v19_folder_archive_digest(zip_path, lambda: _v19_check_stop(project_id, job_id)) != folder_plan['source_zip_sha256']):
                    raise ValueError('ZIP 来源或冻结规则已变化，不能导入')
                _v18_safe_extract(
                    zip_path,
                    extracted,
                    extract_progress,
                    selected_image_paths=selected_paths if selected_paths else None,
                )
                v19_update_job(
                    project_id,
                    job_id,
                    stage="正在识别标注格式",
                    progress=68,
                    phase="ANNOTATION_PARSE", phase_completed=0,
                    phase_total=total_selected, phase_unit="images",
                    phase_progress=0, phase_elapsed_seconds=0, eta_seconds=None,
                    processed=0,
                    message=(
                        f"已按选择范围解压 {len(selected_paths)} 张图片，正在识别标注格式"
                        if selected_paths
                        else "数据集解压完成，正在识别标注格式"
                    ),
                )
                parse_root = extracted
                imported = False
                import_context = {
                    "import_batch_id": job_id,
                    "source_task_id": job_id,
                    "confirmed_at": str(job.get("label_confirmed_at") or ""),
                    "scan_kind": str(job.get("scan_kind") or ""),
                }
                if folder_plan:
                    images = v19_read_scan_images(project_id, job_id)
                    if zip_folders.scan_identity(project_id, job_id, folder_plan['source_zip_sha256'], images, job) != folder_plan['scan_digest']:
                        raise ValueError('ZIP 图片扫描证据已变化')
                    paths = {row['path'] for row in images}
                    import_context.update(folder_confirmation=folder_plan,
                                          folder_confirmation_digest=job['folder_confirmation_digest'],
                                          scan_image_paths=paths, image_stems=zip_folders.sources_by_stem(paths),
                                          folder_image_paths=set(selected_paths) if selected_paths else paths)
                annotation_started = time.time()
                last_import_emit = 0.0
                def import_progress(done,total,msg):
                    nonlocal last_import_emit
                    _v19_check_stop(project_id, job_id)
                    tick = time.monotonic()
                    if done != total and tick - last_import_emit < 0.6:
                        return
                    last_import_emit = tick
                    metrics = _v19_phase_metrics("ANNOTATION_PARSE", done, total, started_at=annotation_started)
                    visible_msg = (
                        f"正在统一标签并写入标注 · {msg}"
                        if frozen_mapping else msg
                    )
                    v19_update_job(
                        project_id, job_id,
                        stage=visible_msg,
                        progress=round(68 + metrics["phase_progress"] * 0.28, 2),
                        phase_unit="images",
                        processed=done,
                        total_selected=total,
                        message=visible_msg,
                        processing_seconds=round(max(0.0, time.time()-processing_started), 1),
                        **metrics,
                    )
                v19_update_job(
                    project_id, job_id,
                    stage=("正在统一标签并写入标注" if frozen_mapping else "正在解析 COCO / VOC / YOLO 标注"),
                    progress=68,
                    phase="ANNOTATION_PARSE", phase_completed=0,
                    phase_total=total_selected, phase_unit="images",
                    phase_progress=0, phase_elapsed_seconds=0, eta_seconds=None,
                    processed=0,
                )
                imported = _v18_import_coco(
                    project_id, parse_root, dataset_id, report, import_progress,
                    label_mapping=frozen_mapping,
                    import_context=import_context,
                )
                if not imported:
                    v19_update_job(project_id, job_id, stage="正在解析 VOC 标注", progress=68, phase="ANNOTATION_PARSE", processed=0)
                    imported = _v18_import_voc(
                        project_id, parse_root, dataset_id, report, import_progress,
                        label_mapping=frozen_mapping,
                        import_context=import_context,
                    )
                if not imported:
                    v19_update_job(project_id, job_id, stage="正在解析 YOLO / 原始图片", progress=68, phase="ANNOTATION_PARSE", processed=0)
                    imported = _v18_import_yolo(
                        project_id, parse_root, dataset_id, report, import_progress,
                        label_mapping=frozen_mapping,
                        import_context=import_context,
                    )
                if imported:
                    if folder_plan:
                        _v19_import_unreferenced_images(project_id, parse_root, dataset_id, report, import_context)
                    else:
                        _v19_import_unreferenced_images(project_id, parse_root, dataset_id, report)
                if not imported or report.get("imported_images", 0) == 0:
                    raise RuntimeError("没有识别到可导入的数据。请确认 ZIP 内包含图片，并检查目录结构是否正确。")
                # Material provenance is independent of annotation provenance:
                # raw images have no boxes to carry the trusted batch identity.
                # Queue into the original image batch so commit/rollback stays atomic.
                for imported_id in report.get("imported_image_ids", []):
                    if not _v50_queue_image_patch(project_id, imported_id, {
                        "import_batch_id": job_id, "source_task_id": job_id,
                    }):
                        raise RuntimeError("ZIP material batch closed before provenance commit")
                _v19_finalize_report_messages(report, scan_kind=job.get("scan_kind"))
                report["labels"] = get_project(project_id).get("labels", [])
                report["label_mapping"] = dict(job.get("label_mapping") or {})
                report["label_confirmed_at"] = str(job.get("label_confirmed_at") or "")
            except BaseException:
                # Importers persist image bytes and annotation truth before the
                # buffered material projection is committed. A failed import must
                # remove those durable side effects instead of publishing a partial
                # dataset under a failed job.
                if _v50_active_image_batch(project_id):
                    _v50_end_image_batch(save=False)
                raise
            else:
                # 图片与摘要先按 ID 缓冲，在这里基于最新索引一次性提交。
                with _v19_stop_fence(project_id, job_id):
                    _v19_check_stop(project_id, job_id)
                    commit_started = time.time()
                    commit_total = int(report.get("imported_images") or total_selected or 0)
                    v19_update_job(
                        project_id, job_id,
                        stage="正在提交素材与标注",
                        progress=96,
                        phase="DB_COMMIT", phase_completed=0,
                        phase_total=commit_total, phase_unit="images",
                        phase_progress=0, phase_elapsed_seconds=0, eta_seconds=None,
                        message="解析完成，正在一次性提交素材索引与标注投影",
                    )
                    try:
                        with label_governance_fence(project_dir(project_id)):
                            _v19_assert_frozen_mapping_targets_active(
                                project_id, frozen_mapping,
                            )
                            if folder_plan:
                                active = {str(row['code']) for row in active_label_options(project_label_items(get_project(project_id)))}
                                if any(not set(rule['intended_label_codes']) <= active for rule in folder_plan['rules'].values()):
                                    raise ValueError('已确认目标标签失效，不能提交素材')
                                # Keep recovery IDs before the original material commit. The
                                # retry path still verifies each ID against committed provenance.
                                v19_update_job(project_id, job_id, report=report)
                            _v50_end_image_batch(save=True)
                            committed = True
                    except BaseException:
                        if _v50_active_image_batch(project_id):
                            _v50_end_image_batch(save=False)
                        raise
                    metrics = _v19_phase_metrics("DB_COMMIT", commit_total, commit_total, started_at=commit_started)
                    v19_update_job(
                        project_id, job_id,
                        progress=99,
                        phase_unit="images",
                        message="素材索引与标注投影已提交",
                        **metrics,
                    )
        if committed and job.get('folder_confirmation'):
            with _v19_stop_fence(project_id, job_id):
                _v19_apply_folder_classification(project_id, job, report)
        if committed and not job.get('folder_confirmation') and job.get('upload_sample_type') in {'positive', 'negative'}:
            # Original ZIP bytes and formal annotations have already committed.
            # Classification is a separate idempotent association: a failure
            # must never roll back, re-import, or duplicate those materials.
            try:
                from platform_core.negative_pool import NegativePool
                pool = NegativePool(material_store(project_id))
                if job.get('upload_algorithm_id') and not any(str(row.get('id')) == str(job['upload_algorithm_id']) for row in list_algorithms_internal(project_id)):
                    raise ValueError('目标算法已不存在，保留导入素材并等待修复池关联')
                imported_ids = list(dict.fromkeys(str(v) for v in report.get('imported_image_ids') or [] if str(v)))
                for offset in range(0, len(imported_ids), 500):
                    chunk = imported_ids[offset:offset + 500]
                    if job['upload_sample_type'] == 'negative':
                        pool.members(chunk, action='add', category_ids=job.get('upload_negative_category_ids') or [], algorithm_id=job.get('upload_algorithm_id') or '')
                    else:
                        pool.set_positive_upload_intent(chunk, job.get('upload_intended_label_codes') or [])
                report['upload_classification_status'] = 'applied'
            except Exception as classify_error:
                report['upload_classification_status'] = 'pending'
                report.setdefault('warnings', []).append(
                    '图片与原始标注已安全入库，但正负样本归类尚未完成：'
                    + str(classify_error)[:180] + '。可在素材库或负样本池重新归类。'
                )
        processing_seconds = round(max(0.0, time.time() - processing_started), 2)
        v19_update_job(
            project_id, job_id, status="done", stage="导入完成", progress=100,
            phase="DONE", phase_completed=1, phase_total=1, phase_unit="step",
            phase_progress=100, eta_seconds=0,
            processed=report.get("imported_images", 0), report=report,
            processing_seconds=processing_seconds, finished_at=now_iso(),
            message=f"导入完成：{report.get('imported_images',0)} 图，{report.get('annotated_images',0)} 张带标注，{report.get('boxes',0)} 框",
        )
    except _V19ImportStopped as stopped:
        # A stop can land between the parser's successful return and DB_COMMIT.
        # In that window the image batch is still live and MUST be discarded.
        if _v50_active_image_batch(project_id):
            try:
                _v50_end_image_batch(save=False)
            except Exception as cleanup_error:
                v19_update_job(
                    project_id, job_id, status="failed", stage="停止清理失败：需完整性修复",
                    phase="FAILED", report=report, finished_at=now_iso(),
                    error=f"停止回滚失败，保留源文件与索引：{cleanup_error}",
                )
                return
        # No commit was permitted past the stop fence. Fail closed if any
        # unexpected Material rows are already indexed; never delete sources.
        indexed = False
        imported_ids = list(report.get("imported_image_ids") or [])
        store = material_store(project_id)
        for offset in range(0, len(imported_ids), 500):
            if store.get_many(imported_ids[offset:offset + 500]):
                indexed = True
                break
        if indexed:
            v19_update_job(
                project_id, job_id, status="failed", stage="停止失败：需完整性修复",
                phase="FAILED", error="停止请求时已有素材进入正式索引，已保留源文件与索引",
                report=report, finished_at=now_iso(),
            )
        else:
            v19_update_job(project_id, job_id, report=report)
            _v19_finish_cancel(project_id, job_id, message=str(stopped))
    except Exception as e:
        if _v50_active_image_batch(project_id):
            try:
                _v50_end_image_batch(save=False)
            except Exception as rollback_error:
                _v19_job_diagnostic(project_id, job_id, rollback_error, operation="rollback", job=job, report=report)
        _v19_fail_worker(project_id, job_id, e, job=job, report=report,
                          started=processing_started, committed=committed)
    finally:
        try:
            if extracted.exists():
                shutil.rmtree(extracted)
        except OSError as error:
            _v19_job_diagnostic(project_id, job_id, error, operation="extracted_cleanup", job=job, report=report, committed=committed)



from platform_core.material_ingestion_contracts import V19MultipartUploadReq


def _v19_multipart_repository(project_id: str) -> ZipMultipartRepository:
    return ZipMultipartRepository(project_dir(project_id))


def v19_create_multipart_upload(project_id: str, dataset_id: str, payload: V19MultipartUploadReq):
    return _material_ingestion_service().v19_create_multipart_upload(project_id, dataset_id, payload)


async def v19_upload_multipart_part(project_id: str, upload_id: str, part_number: int, request: Request):
    return await _material_ingestion_service().v19_upload_multipart_part(project_id, upload_id, part_number, request)


def v19_pause_multipart_upload(project_id: str, upload_id: str):
    return _material_ingestion_service().v19_pause_multipart_upload(project_id, upload_id)


def v19_cancel_multipart_upload(project_id: str, upload_id: str):
    return _material_ingestion_service().v19_cancel_multipart_upload(project_id, upload_id)


_V19_UPLOAD_FINALIZE_GUARD = threading.Lock()
_V19_UPLOAD_FINALIZE_ACTIVE: set[Tuple[str, str]] = set()


def _v19_finalize_multipart_upload(project_id: str, upload_id: str):
    try:
        _v19_finalize_multipart_upload_impl(project_id, upload_id)
    except Exception as error:
        # Even a failed secondary read in the existing finalize/cancel handler
        # leaves independent evidence instead of terminating a daemon silently.
        _v19_job_diagnostic(project_id, upload_id, error, operation="finalize_exit")


def _v19_finalize_multipart_upload_impl(project_id: str, upload_id: str):
    key = (str(project_id), str(upload_id))
    jd = v19_job_dir(project_id, upload_id)
    jd.mkdir(parents=True, exist_ok=True)
    finalize_lock = FileLock(str(jd / ".finalize.lock"), timeout=-1)
    finalize_lock_acquired = False
    try:
        # The in-memory guard only coordinates threads in this process.  The
        # file lock is the durable ownership fence when more than one API
        # process observes the same completed multipart upload.
        finalize_lock.acquire()
        finalize_lock_acquired = True
        initial = v19_read_job(project_id, upload_id)
        if str(initial.get("status") or "").strip().lower() in {
            "cancelled", "canceled", "done", "failed",
        }:
            return
        _v19_check_stop(project_id, upload_id)
        repository = _v19_multipart_repository(project_id)
        session = repository.get(upload_id)
        job = v19_read_job(project_id, upload_id)
        zip_path = jd / "source.zip"

        merge_started = time.time()
        _v19_check_stop(project_id, upload_id)
        v19_update_job(
            project_id, upload_id,
            status="merging", stage="正在合并 ZIP 分片", progress=35,
            upload_progress=100,
            phase="MERGE", phase_completed=0,
            phase_total=int(session.get("file_size") or 0), phase_unit="bytes",
            phase_progress=0, phase_elapsed_seconds=0, eta_seconds=None,
            message="文件已上传，服务器正在后台合并 ZIP；页面可以关闭",
        )
        if not (
            str(session.get("status") or "") == "completed"
            and zip_path.is_file()
        ):
            last_merge_emit = 0.0
            def merge_progress(written, total_bytes, part_number, total_parts):
                nonlocal last_merge_emit
                tick = time.monotonic()
                if written != total_bytes and tick - last_merge_emit < 0.5:
                    return
                last_merge_emit = tick
                metrics = _v19_phase_metrics("MERGE", written, total_bytes, started_at=merge_started)
                v19_update_job(
                    project_id,
                    upload_id,
                    status="merging",
                    stage="正在合并 ZIP 分片",
                    progress=round(35 + metrics["phase_progress"] * 0.05, 2),
                    phase_unit="bytes",
                    message=f"正在合并分片 {part_number}/{total_parts}",
                    **metrics,
                )
            repository.assemble(
                upload_id, zip_path, on_progress=merge_progress,
                cancel_check=lambda: _v19_check_stop(project_id, upload_id),
            )
            session = repository.get(upload_id)

        verify_started = time.time()
        scan_started: Optional[float] = None
        _v19_check_stop(project_id, upload_id)
        v19_update_job(
            project_id, upload_id,
            status="validating", stage="正在校验 ZIP 结构", progress=40,
            upload_progress=100, uploaded_bytes=zip_path.stat().st_size,
            phase="VERIFY", phase_completed=None, phase_total=None, phase_unit="files",
            phase_progress=None, phase_elapsed_seconds=0, eta_seconds=None,
            message="ZIP 合并完成，正在校验压缩包目录结构",
        )
        last_verify_emit = 0.0
        def scan_progress(phase, done, total_files, current_name):
            nonlocal last_verify_emit, scan_started
            _v19_check_stop(project_id, upload_id)
            if phase == "VERIFY":
                tick = time.monotonic()
                if done != total_files and tick - last_verify_emit < 0.5:
                    return
                last_verify_emit = tick
                metrics = _v19_phase_metrics("VERIFY", done, total_files, started_at=verify_started)
                phase_progress = metrics["phase_progress"]
                v19_update_job(
                    project_id,
                    upload_id,
                    status="validating",
                    stage="正在校验 ZIP 结构",
                    progress=round(40 + float(phase_progress or 0) * 0.02, 2),
                    phase_unit="files",
                    message=f"正在校验目录 {done}/{total_files} · {current_name}",
                    **metrics,
                )
                return

            if scan_started is None:
                scan_started = time.time()
            metrics = _v19_phase_metrics("SCAN", None, None, started_at=scan_started)
            v19_update_job(
                project_id,
                upload_id,
                status="validating",
                stage="正在扫描图片与外部标注",
                progress=42,
                phase_unit="",
                message=str(current_name or "正在识别图片与外部标注"),
                **metrics,
            )

        scan_total_started = time.time()
        folder_confirmation = bool(v19_read_job(project_id, upload_id).get('folder_confirmation_requested'))
        scan = _v19_prepare_scan(project_id, v19_scan_zip(zip_path, scan_progress, folder_confirmation=True)
                                 if folder_confirmation else v19_scan_zip(zip_path, scan_progress))
        if folder_confirmation:
            _v19_store_folder_scan(project_id, upload_id, zip_path, scan, check_stop=lambda: _v19_check_stop(project_id, upload_id))
        _v19_check_stop(project_id, upload_id)
        scan_seconds = round(max(0.0, time.time() - scan_total_started), 2)
        if scan.get("image_count", 0) == 0:
            raise ValueError("ZIP 内容不匹配：压缩包内没有识别到支持的图片文件。")
        scan_images = list(scan.pop("images", []) or [])
        scan_class_samples = dict(scan.pop("class_samples", {}) or {})
        v19_write_scan_images(project_id, upload_id, scan_images)
        v19_write_class_samples(project_id, upload_id, scan_class_samples)
        latest = v19_read_job(project_id, upload_id)
        finished = {
            **latest, **scan,
            "id": upload_id, "project_id": project_id,
            "dataset_id": latest.get("dataset_id") or session.get("dataset_id") or "default",
            "batch_id": upload_id,
            "file_name": latest.get("file_name") or session.get("file_name") or "dataset.zip",
            "file_size_mb": round(zip_path.stat().st_size / 1024 / 1024, 2),
            "uploaded_bytes": zip_path.stat().st_size,
            "upload_progress": 100,
            "scan_seconds": scan_seconds,
            "status": "selecting",
            "sample_classification_required": scan.get("scan_kind") != "RAW_UNANNOTATED" or bool(latest.get("upload_algorithm_id")),
            "stage": "上传与校验完成",
            "progress": 48,
            "phase": "WAITING_CONFIRMATION",
            "phase_completed": 1,
            "phase_total": 1,
            "phase_unit": "step",
            "phase_progress": 100,
            "phase_elapsed_seconds": scan_seconds,
            "eta_seconds": None,
            "message": (
                "后台扫描完成，等待确认标签并开始正式导入"
                if scan.get("label_confirmation_required")
                else "后台扫描完成，未检测到标注，可按原图直接入库" if scan.get("scan_kind") == "RAW_UNANNOTATED"
                else "后台扫描完成，请选择正样本标签或负样本分类后导入"
            ),
            "scan_images_ref": "scan-images.json",
            "class_samples_ref": "scan-class-samples.json",
            "uploaded_at": latest.get("uploaded_at") or now_iso(),
            "updated_at": now_iso(),
        }
        with _v19_stop_fence(project_id, upload_id):
            _v19_check_stop(project_id, upload_id)
            v19_write_job(project_id, finished)
    except _V19ImportStopped as stopped:
        _v19_finish_cancel(project_id, upload_id, message=str(stopped))
    except zipfile.BadZipFile:
        with _v19_stop_fence(project_id, upload_id):
            current = v19_read_job(project_id, upload_id)
            terminal = str(current.get("status") or "").strip().lower()
            if terminal not in {"cancelled", "canceled", "done"}:
                if current.get("cancel_requested"):
                    _v19_finish_cancel(project_id, upload_id, message="已取消 ZIP 校验并清理未提交缓存")
                else:
                    failed_progress = v19_zip_display_progress(current)["overall_progress"]
                    current.update(
                        status="failed", stage="ZIP 校验失败", progress=failed_progress,
                        phase="FAILED", upload_progress=100,
                        error="压缩包已损坏、格式不正确或不是有效 ZIP。",
                        message="ZIP 校验失败", finished_at=now_iso(),
                    )
                    v19_write_job(project_id, current)
    except Exception as error:
        with _v19_stop_fence(project_id, upload_id):
            current = v19_read_job(project_id, upload_id)
            terminal = str(current.get("status") or "").strip().lower()
            if terminal not in {"cancelled", "canceled", "done"}:
                if current.get("cancel_requested"):
                    _v19_finish_cancel(project_id, upload_id, message="已取消 ZIP 处理并清理未提交缓存")
                else:
                    failed_progress = v19_zip_display_progress(current)["overall_progress"]
                    current.update(
                        status="failed", stage="ZIP 处理失败", progress=failed_progress,
                        phase="FAILED", upload_progress=100, error=str(error), message=str(error),
                        finished_at=now_iso(),
                    )
                    v19_write_job(project_id, current)
    finally:
        if finalize_lock_acquired:
            finalize_lock.release()
        with _V19_UPLOAD_FINALIZE_GUARD:
            _V19_UPLOAD_FINALIZE_ACTIVE.discard(key)


def _v19_schedule_multipart_finalize(project_id: str, upload_id: str) -> bool:
    key = (str(project_id), str(upload_id))
    with _V19_UPLOAD_FINALIZE_GUARD:
        if key in _V19_UPLOAD_FINALIZE_ACTIVE:
            return False
        _V19_UPLOAD_FINALIZE_ACTIVE.add(key)
    thread = threading.Thread(
        target=_v19_finalize_multipart_upload,
        args=(str(project_id), str(upload_id)),
        daemon=True,
        name=f"zip-finalize-{str(upload_id)[:12]}",
    )
    thread.start()
    return True


def _v19_recover_multipart_finalize(project_id: str, job: Mapping[str, Any]) -> None:
    if str(job.get("status") or "").strip().lower() in {"merging", "validating"}:
        _v19_schedule_multipart_finalize(project_id, str(job.get("id") or ""))


def v19_complete_multipart_upload(project_id: str, upload_id: str):
    return _material_ingestion_service().v19_complete_multipart_upload(project_id, upload_id)


async def v19_create_import_job(project_id: str, dataset_id: str, file: UploadFile=File(...), folder_confirmation: bool=Form(False)):
    return await _material_ingestion_service().v19_create_import_job(project_id, dataset_id, file, folder_confirmation)


def _v19_cancel_import_job(project_id: str, job_id: str) -> Dict[str, Any]:
    return _material_ingestion_service()._v19_cancel_import_job(project_id, job_id)


def v19_cancel_import_job(project_id: str, job_id: str):
    return _material_ingestion_service().v19_cancel_import_job(project_id, job_id)


def v19_stop_import_job(project_id: str, job_id: str):
    return _material_ingestion_service().v19_stop_import_job(project_id, job_id)


def v19_start_import_job(project_id: str, job_id: str, payload: V19ImportStartReq):
    return _material_ingestion_service().v19_start_import_job(project_id, job_id, payload)


def _v19_confirm_folder_rules(project_id, job_id, job, payload):
    return _material_ingestion_service()._v19_confirm_folder_rules(project_id, job_id, job, payload)


def _v19_start_import_job_locked(project_id: str, job_id: str, payload: V19ImportStartReq):
    return _material_ingestion_service()._v19_start_import_job_locked(project_id, job_id, payload)


def _v19_zip_class_sample(project_id: str, job_id: str, class_id: str, index: int) -> Dict[str, Any]:
    return _material_ingestion_service()._v19_zip_class_sample(project_id, job_id, class_id, index)


def v19_label_samples(project_id: str, job_id: str, class_id: str):
    return _material_ingestion_service().v19_label_samples(project_id, job_id, class_id)


def v19_label_sample_content(project_id: str, job_id: str, class_id: str, index: int=Query(ge=0, le=11)):
    return _material_ingestion_service().v19_label_sample_content(project_id, job_id, class_id, index)


def v19_list_import_jobs(project_id: str):
    return _material_ingestion_service().v19_list_import_jobs(project_id)


def v19_get_import_job(project_id: str, job_id: str, include_images: bool=False, image_limit: int=500):
    return _material_ingestion_service().v19_get_import_job(project_id, job_id, include_images, image_limit)


def v19_clear_terminal_import_jobs(project_id: str, job_ids: str=''):
    return _material_ingestion_service().v19_clear_terminal_import_jobs(project_id, job_ids)


def _v19_hide_terminal_job(project_id: str, job_id: str):
    return _material_ingestion_service()._v19_hide_terminal_job(project_id, job_id)


def v19_delete_import_job(project_id: str, job_id: str):
    return _material_ingestion_service().v19_delete_import_job(project_id, job_id)

# ============================================================
# v30: 模型/算法导出包 + 部署环境选择
# ============================================================
from platform_core.conversion_management_contracts import ModelExportReq


def _find_model_meta(project_id: str, model_path: Path, model_name: str = "") -> Dict[str, Any]:
    for m in list_models_internal(project_id):
        try:
            if Path(m.get("path", "")).resolve() == model_path.resolve() or m.get("name") == model_name or m.get("name") == model_path.name:
                return m
        except Exception:
            if m.get("name") == model_name or m.get("name") == model_path.name:
                return m
    return {}


def _copy_if_exists(src: Any, dst: Path):
    try:
        p = Path(str(src))
        if src and p.exists() and p.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            return True
    except Exception:
        pass
    return False


def _zip_dir(src_dir: Path, zip_path: Path):
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(src_dir))


def _export_label_name(x: Any, i: int) -> str:
    return _conversion_management_service()._export_label_name(x, i)


def _export_labels(project: Dict[str, Any], meta: Dict[str, Any], job: Dict[str, Any]) -> List[str]:
    return _conversion_management_service()._export_labels(project, meta, job)


def _find_job_for_model(project_id: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    jid = meta.get("job_id") or ""
    if not jid:
        return {}
    jf = project_dir(project_id) / "jobs" / jid / "job.json"
    return read_json(jf, {}) if jf.exists() else {}


def _copy_model_related_files(model_path: Path, model_dir: Path) -> List[str]:
    return _conversion_management_service()._copy_model_related_files(model_path, model_dir)


def _write_export_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", errors="ignore")


def _write_export_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_export_yaml(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _build_export_config(payload: ModelExportReq, model_path: Path, framework: str, labels: List[str]) -> Dict[str, Any]:
    return _conversion_management_service()._build_export_config(payload, model_path, framework, labels)


def _try_export_paddledet_infer(project_id: str, python_path: str, model_path: Path, meta: Dict[str, Any], out_dir: Path, export_conf: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    penv = get_active_paddle_env()
    paddledet_dir = Path(str(penv.get("paddledet_dir", "")))
    cfg = Path(str(meta.get("config_path") or meta.get("generated_config_path") or meta.get("algorithm_config_path") or ""))
    result = {"ok": False, "note": "", "outputs": []}
    if not python_path or not Path(python_path).exists():
        result["note"] = "未转换：飞桨 python.exe 不存在。已保留 PaddleDetection 权重部署包。"
        return result
    if not paddledet_dir.exists():
        result["note"] = "未转换：PaddleDetection 目录不存在。已保留 PaddleDetection 权重部署包。"
        return result
    export_py = paddledet_dir / "tools" / "export_model.py"
    if not export_py.exists():
        result["note"] = "未转换：PaddleDetection tools/export_model.py 不存在。已保留 PaddleDetection 权重部署包。"
        return result
    if not cfg.exists() or not cfg.is_file():
        result["note"] = "未转换：没有找到该模型训练时使用的 yml 配置。已保留 PaddleDetection 权重部署包。"
        return result
    infer_out = out_dir / "inference_model"
    infer_out.mkdir(parents=True, exist_ok=True)
    num_classes = int(meta.get("num_classes") or 0)
    fam = (meta.get("family_key") or "").lower()
    class_opts = []
    if num_classes > 0:
        class_opts.append(f"num_classes={num_classes}")
        if "picodet" in fam:
            class_opts.append(f"PicoHead.num_classes={num_classes}")
        elif "ppyoloe" in fam:
            class_opts.append(f"PPYOLOEHead.num_classes={num_classes}")
        elif "ppyolo" in fam or "yolov3" in fam:
            class_opts.append(f"YOLOv3Head.num_classes={num_classes}")
    cmd = [python_path, str(export_py), "-c", str(cfg), "-o", f"weights={str(model_path)}", "use_gpu=False", f"save_dir={str(infer_out)}"] + class_opts
    try:
        cp = subprocess.run(cmd, cwd=str(paddledet_dir), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        _write_export_text(out_dir / "export_model_command.txt", " ".join(cmd) + "\n\nSTDOUT:\n" + (cp.stdout or "") + "\n\nSTDERR:\n" + (cp.stderr or ""))
        outs = [str(x.relative_to(out_dir)) for x in infer_out.rglob("*") if x.is_file()]
        result["outputs"] = outs
        if cp.returncode == 0 and outs:
            result["ok"] = True
            result["note"] = "已生成 Paddle 推理模型。可在 PaddleDetection/Paddle Inference 方向继续部署。"
        elif cp.returncode == 0:
            result["note"] = "export_model.py 已执行成功，但未发现推理模型文件，请查看转换日志。"
        else:
            tail = ((cp.stderr or "") + "\n" + (cp.stdout or ""))[-1200:]
            result["note"] = "推理模型转换失败，已保留原始权重和转换日志。原因摘要：" + tail
        return result
    except Exception as e:
        result["note"] = f"推理模型转换异常，已保留原始权重包：{e}"
        return result


def _try_export_ultralytics_onnx(project_id: str, model_path: Path, out_dir: Path, export_conf: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"ok": False, "note": "", "outputs": []}
    if model_path.suffix.lower() != ".pt":
        result["note"] = "未转换：只有 Ultralytics .pt 支持导出 ONNX。已生成平台模型包。"
        return result
    conf = export_conf or {}
    py = ultralytics_runtime_python()
    script = out_dir / "export_onnx.py"
    imgsz = int(conf.get("input_size") or 640)
    opset = int(conf.get("onnx_opset") or 12)
    dynamic = "True" if conf.get("onnx_dynamic") else "False"
    simplify = "True" if conf.get("onnx_simplify") else "False"
    _write_export_text(script, f'''
from pathlib import Path
from ultralytics import YOLO
model_path = r"{str(model_path)}"
out_dir = Path(r"{str(out_dir)}")
out_dir.mkdir(parents=True, exist_ok=True)
model = YOLO(model_path)
res = model.export(format="onnx", imgsz={imgsz}, opset={opset}, dynamic={dynamic}, simplify={simplify})
print(res)
''')
    try:
        cp = subprocess.run([py, str(script)], cwd=str(out_dir), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        _write_export_text(out_dir / "export_onnx_command.txt", f'"{py}" "{script}"\n\nSTDOUT:\n{cp.stdout or ""}\n\nSTDERR:\n{cp.stderr or ""}')
        candidates = []
        for root in [out_dir, model_path.parent]:
            if root.exists():
                candidates += [x for x in root.glob("*.onnx") if x.is_file()]
        candidates = sorted(set(candidates), key=lambda x: x.stat().st_mtime, reverse=True)
        for ep in candidates[:3]:
            dst = out_dir / ep.name
            if ep.resolve() != dst.resolve():
                shutil.copy2(ep, dst)
        outs = [str(x.relative_to(out_dir)) for x in out_dir.glob("*.onnx")]
        result["outputs"] = outs
        if cp.returncode == 0 and outs:
            result["ok"] = True
            result["note"] = "已生成 Ultralytics ONNX 推理包。"
        elif cp.returncode == 0:
            result["note"] = "ONNX 导出命令已执行，但没有找到 .onnx 输出文件，请查看转换日志。"
        else:
            tail = ((cp.stderr or "") + "\n" + (cp.stdout or ""))[-1200:]
            result["note"] = "ONNX 转换失败，已保留原始 .pt 和转换日志。原因摘要：" + tail
        return result
    except Exception as e:
        result["note"] = f"ONNX 转换异常，已保留原始 .pt 包：{e}"
        return result


def _create_target_deploy_files(work: Path, target: str, metadata: Dict[str, Any], export_conf: Dict[str, Any], convert_result: Dict[str, Any]):
    cfg_dir = work / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    _write_export_json(cfg_dir / "deployment_config.json", export_conf)
    _write_export_yaml(cfg_dir / "deployment_config.yaml", export_conf)
    if target == "platform_package":
        _write_export_text(cfg_dir / "平台验证说明.md", "# 平台验证包\n\n用于本机检测台、项目归档和后续转换。导入时请使用 model_meta.json、labels/ 和 model/。\n")
    elif target == "paddledet_weight":
        _write_export_yaml(cfg_dir / "paddledet_weight_deploy.yaml", {
            "runtime": "PaddleDetection",
            "model": metadata.get("model_file", f"model/{metadata.get('model_name')}"),
            "config": metadata.get("config_file", "config/原始训练配置缺失"),
            "labels": "labels/label_list.txt",
            "num_classes": metadata.get("num_classes"),
            "device": export_conf.get("device", "cpu"),
        })
    elif target == "paddledet_infer":
        _write_export_yaml(cfg_dir / "paddle_inference_deploy.yaml", {
            "runtime": "Paddle Inference / PaddleDetection export_model",
            "source_weight": metadata.get("model_file"),
            "inference_model_dir": "inference_model/",
            "labels": "labels/label_list.txt",
            "conversion_ok": bool(convert_result.get("ok")),
            "conversion_outputs": convert_result.get("outputs", []),
        })
    elif target == "ultralytics_onnx":
        _write_export_yaml(cfg_dir / "onnx_deploy.yaml", {
            "runtime": "ONNXRuntime / OpenVINO / TensorRT 可继续适配",
            "source_pt": metadata.get("model_file"),
            "onnx_outputs": convert_result.get("outputs", []),
            "input_size": export_conf.get("input_size"),
            "confidence": export_conf.get("confidence"),
            "conversion_ok": bool(convert_result.get("ok")),
        })
    elif target == "sophon_prepare":
        _write_export_yaml(cfg_dir / "sophon_prepare.yaml", {
            "runtime": "Sophon/BM/NPU conversion prepare package",
            "source_model": metadata.get("model_file"),
            "labels": "labels/label_list.txt",
            "target_chip": export_conf.get("target_chip"),
            "precision": export_conf.get("precision"),
            "quantization": export_conf.get("quantization"),
            "input_size": export_conf.get("input_size"),
            "next_step": "使用算能官方转换工具链生成 bmodel，并在目标盒子上校验输入输出、类别和阈值。",
        })


def _do_export_model_package(project_id: str, payload: ModelExportReq):
    return _conversion_management_service()._do_export_model_package(project_id, payload)


from platform_core.conversion_management_service import ConversionManagementDependencies, ConversionManagementService
from platform_core.conversion_management_api import create_conversion_management_router_1, create_conversion_management_router_2, create_conversion_management_router_3, create_conversion_management_router_4, create_conversion_management_router_5


def _conversion_management_service() -> ConversionManagementService:
    return ConversionManagementService(ConversionManagementDependencies(
        BASE_DIR=lambda: BASE_DIR,
        DATA_DIR=lambda: DATA_DIR,
        DEPLOY_PROCESS_REGISTRY=lambda: DEPLOY_PROCESS_REGISTRY,
        DEPLOY_REMOTE_THREADS=lambda: DEPLOY_REMOTE_THREADS,
        DEPLOY_RESOURCES_FILE=lambda: DEPLOY_RESOURCES_FILE,
        IMAGE_EXTS=lambda: IMAGE_EXTS,
        V423_DEPLOY_TARGET_NAMES=lambda: V423_DEPLOY_TARGET_NAMES,
        _CONVERSION_HISTORY_PROJECTION=lambda: _CONVERSION_HISTORY_PROJECTION,
        _DEPLOY_BUILTIN_RESOURCE_CACHE=lambda: _DEPLOY_BUILTIN_RESOURCE_CACHE,
        _DEPLOY_RESOURCES_WRITE_LOCK=lambda: _DEPLOY_RESOURCES_WRITE_LOCK,
        _algorithm_version_reference_fence=lambda *args, **kwargs: _algorithm_version_reference_fence(*args, **kwargs),
        _authorize_business_file_project=lambda *args, **kwargs: _authorize_business_file_project(*args, **kwargs),
        _builtin_deploy_resource_cache_meta=lambda *args, **kwargs: _builtin_deploy_resource_cache_meta(*args, **kwargs),
        _builtin_deploy_resource_summary=lambda *args, **kwargs: _builtin_deploy_resource_summary(*args, **kwargs),
        _builtin_deploy_resources=lambda *args, **kwargs: _builtin_deploy_resources(*args, **kwargs),
        _business_file_url=lambda *args, **kwargs: _business_file_url(*args, **kwargs),
        _conversion_contract_for_source=lambda *args, **kwargs: _conversion_contract_for_source(*args, **kwargs),
        _copy_if_exists=lambda *args, **kwargs: _copy_if_exists(*args, **kwargs),
        _create_target_deploy_files=lambda *args, **kwargs: _create_target_deploy_files(*args, **kwargs),
        _deploy_job_version_identity=lambda *args, **kwargs: _deploy_job_version_identity(*args, **kwargs),
        _deploy_resource_by_id=lambda *args, **kwargs: _deploy_resource_by_id(*args, **kwargs),
        _deploy_resource_public=lambda *args, **kwargs: _deploy_resource_public(*args, **kwargs),
        _deploy_resource_runtime=lambda *args, **kwargs: _deploy_resource_runtime(*args, **kwargs),
        _detect_agent_deploy_resource=lambda *args, **kwargs: _detect_agent_deploy_resource(*args, **kwargs),
        _detect_local_deploy_resource=lambda *args, **kwargs: _detect_local_deploy_resource(*args, **kwargs),
        _find_job_for_model=lambda *args, **kwargs: _find_job_for_model(*args, **kwargs),
        _find_model_meta=lambda *args, **kwargs: _find_model_meta(*args, **kwargs),
        _finish_background_conversion_detection=lambda *args, **kwargs: _finish_background_conversion_detection(*args, **kwargs),
        _inspect_conversion_resource=lambda *args, **kwargs: _inspect_conversion_resource(*args, **kwargs),
        _load_saved_deploy_resources=lambda *args, **kwargs: _load_saved_deploy_resources(*args, **kwargs),
        _remote_conversion_resource_online=lambda *args, **kwargs: _remote_conversion_resource_online(*args, **kwargs),
        _remote_execution_transport_service=lambda *args, **kwargs: _remote_execution_transport_service(*args, **kwargs),
        _resolve_business_file=lambda *args, **kwargs: _resolve_business_file(*args, **kwargs),
        _resolve_deploy_source=lambda *args, **kwargs: _resolve_deploy_source(*args, **kwargs),
        _run_background_conversion_detection=lambda *args, **kwargs: _run_background_conversion_detection(*args, **kwargs),
        _save_deploy_resources=lambda *args, **kwargs: _save_deploy_resources(*args, **kwargs),
        _storage_source_fence=lambda *args, **kwargs: _storage_source_fence(*args, **kwargs),
        _storage_source_runtime_generation=lambda *args, **kwargs: _storage_source_runtime_generation(*args, **kwargs),
        _try_export_paddledet_infer=lambda *args, **kwargs: _try_export_paddledet_infer(*args, **kwargs),
        _try_export_ultralytics_onnx=lambda *args, **kwargs: _try_export_ultralytics_onnx(*args, **kwargs),
        _v35_secret_store=lambda *args, **kwargs: _v35_secret_store(*args, **kwargs),
        _version_deploy_conversion_defaults=lambda *args, **kwargs: _version_deploy_conversion_defaults(*args, **kwargs),
        _write_export_json=lambda *args, **kwargs: _write_export_json(*args, **kwargs),
        _write_export_text=lambda *args, **kwargs: _write_export_text(*args, **kwargs),
        _write_job_json=lambda *args, **kwargs: _write_job_json(*args, **kwargs),
        _zip_dir=lambda *args, **kwargs: _zip_dir(*args, **kwargs),
        algorithm_presentation_store=lambda *args, **kwargs: algorithm_presentation_store(*args, **kwargs),
        algorithm_repository=lambda *args, **kwargs: algorithm_repository(*args, **kwargs),
        algorithms_file=lambda *args, **kwargs: algorithms_file(*args, **kwargs),
        deploy_root=lambda *args, **kwargs: deploy_root(*args, **kwargs),
        get_active_paddle_env=lambda *args, **kwargs: get_active_paddle_env(*args, **kwargs),
        get_active_ultralytics_env=lambda *args, **kwargs: get_active_ultralytics_env(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        job_report=lambda *args, **kwargs: job_report(*args, **kwargs),
        list_algorithms_internal=lambda *args, **kwargs: list_algorithms_internal(*args, **kwargs),
        list_models_internal=lambda *args, **kwargs: list_models_internal(*args, **kwargs),
        load_images=lambda *args, **kwargs: load_images(*args, **kwargs),
        material_store=lambda *args, **kwargs: material_store(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        public_deployment_test=lambda *args, **kwargs: public_deployment_test(*args, **kwargs),
        read_json=lambda *args, **kwargs: read_json(*args, **kwargs),
        resolve_any_model_path=lambda *args, **kwargs: resolve_any_model_path(*args, **kwargs),
        resolve_material_path=lambda *args, **kwargs: resolve_material_path(*args, **kwargs),
        safe_filename=lambda *args, **kwargs: safe_filename(*args, **kwargs),
        shared_task_artifacts=lambda *args, **kwargs: shared_task_artifacts(*args, **kwargs),
        shared_task_repository=lambda *args, **kwargs: shared_task_repository(*args, **kwargs),
        storage_credentials=lambda *args, **kwargs: storage_credentials(*args, **kwargs),
        storage_source_repository=lambda *args, **kwargs: storage_source_repository(*args, **kwargs),
        write_json=lambda *args, **kwargs: write_json(*args, **kwargs),
    ))


app.include_router(create_conversion_management_router_1(_conversion_management_service))


def v30_export_model_package(project_id: str, payload: ModelExportReq):
    return _conversion_management_service().v30_export_model_package(project_id, payload)


def v32_export_model_package(project_id: str, payload: ModelExportReq):
    return _conversion_management_service().v32_export_model_package(project_id, payload)


# -----------------------------
# v33 视频切帧任务 + 素材库自动标注任务
# -----------------------------
import threading
import math

VIDEO_EXTS_V33 = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".mpeg", ".mpg", ".webm", ".m4v"}
_v33_task_lock = threading.RLock()


def _v33_tasks_file(project_id: str, kind: str) -> Path:
    ensure_project_dirs(project_id)
    return project_dir(project_id) / f"{kind}.json"


def _v33_load_tasks(project_id: str, kind: str) -> List[Dict[str, Any]]:
    if kind == 'clean_tasks' and '_v47_list_durable_clean_tasks' in globals():
        return _v47_list_durable_clean_tasks(project_id)
    with _v33_task_lock:
        return read_json(_v33_tasks_file(project_id, kind), [])


def _v33_save_tasks(project_id: str, kind: str, tasks: List[Dict[str, Any]]):
    with _v33_task_lock:
        write_json(_v33_tasks_file(project_id, kind), tasks)


def _v33_update_task(project_id: str, kind: str, task_id: str, **updates):
    with _v33_task_lock:
        tasks = read_json(_v33_tasks_file(project_id, kind), [])
        found = False
        for t in tasks:
            if t.get("id") == task_id:
                t.update(updates)
                t["updated_at"] = now_iso()
                found = True
                break
        if found:
            write_json(_v33_tasks_file(project_id, kind), tasks)


def _v33_get_task(project_id: str, kind: str, task_id: str) -> Optional[Dict[str, Any]]:
    return next((x for x in _v33_load_tasks(project_id, kind) if x.get("id") == task_id), None)


def _v33_set_image_split(project_id: str, image_id: str, split: str):
    material_store(project_id).patch({
        str(image_id): {
            "split": split or "unassigned",
            "updated_at": now_iso(),
        }
    })


def _v33_run_video_frame_task(project_id: str, task_id: str):
    task = _v33_get_task(project_id, "video_frame_tasks", task_id)
    if not task:
        return
    try:
        try:
            import cv2  # type: ignore
        except Exception as e:
            raise RuntimeError(f"当前平台环境缺少 OpenCV，无法切帧。请安装 opencv-python。原始错误：{e}")

        video_path = Path(task["video_path"])
        if not video_path.exists():
            raise RuntimeError("视频文件不存在，可能已被删除")
        _v33_update_task(project_id, "video_frame_tasks", task_id, status="running", status_text="切帧中", started_at=now_iso(), progress=0)
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError("视频无法打开，请确认格式是否为 mp4/avi/mov/mkv 等常见视频格式")
        source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = round(total_frames / source_fps, 2) if total_frames else 0
        requested_fps = float(task.get("extract_fps") or 0)
        interval_seconds = float(task.get("interval_seconds") or 1.0)
        max_frames = int(task.get("max_frames") or 0)
        if requested_fps > 0:
            step = max(1, int(round(source_fps / requested_fps)))
            frequency_text = f"每秒 {requested_fps:g} 帧"
        else:
            step = max(1, int(round(source_fps * max(0.05, interval_seconds))))
            frequency_text = f"每 {interval_seconds:g} 秒 1 帧"
        dataset_id = task.get("dataset_id") or "default"
        split = task.get("split") or "unassigned"
        out_dir = project_dir(project_id) / "frame_tasks" / task_id / "frames"
        out_dir.mkdir(parents=True, exist_ok=True)
        saved = 0
        processed = 0
        started_ts = time.time()
        frame_indices: List[int]
        if total_frames > 0:
            frame_indices = list(range(0, total_frames, step))
            if max_frames > 0:
                frame_indices = frame_indices[:max_frames]
            iterator = frame_indices
            total_to_visit = len(frame_indices)
            for frame_idx in iterator:
                cur = _v33_get_task(project_id, "video_frame_tasks", task_id) or {}
                if cur.get("stop_requested"):
                    _v33_update_task(project_id, "video_frame_tasks", task_id, status="stopped", status_text="已停止", finished_at=now_iso())
                    cap.release()
                    return
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_idx))
                ok, frame = cap.read()
                processed += 1
                if not ok or frame is None:
                    continue
                ts = frame_idx / source_fps
                fname = f"{video_path.stem}_frame_{frame_idx:08d}_{ts:.2f}s.jpg".replace(":", "_")
                temp = out_dir / fname
                cv2.imwrite(str(temp), frame)
                rec = add_image_record(project_id, temp, fname, source_type="video_frame", dataset_id=dataset_id)
                if rec:
                    rec["video_task_id"] = task_id
                    rec["frame_index"] = int(frame_idx)
                    rec["frame_time_seconds"] = round(ts, 3)
                    _v33_set_image_split(project_id, rec["id"], split)
                    saved += 1
                progress = int(processed / max(1, total_to_visit) * 100)
                if saved % 5 == 0 or processed == total_to_visit:
                    elapsed=max(0.001,time.time()-started_ts);eta_seconds=int(max(0,elapsed/max(1,processed)*(total_to_visit-processed)))
                    _v33_update_task(project_id, "video_frame_tasks", task_id, progress=progress, extracted_frames=saved, processed_frames=processed, source_fps=round(source_fps, 3), duration_seconds=duration, frequency_text=frequency_text, elapsed_seconds=int(elapsed), eta_seconds=eta_seconds)
        else:
            frame_idx = 0
            while True:
                cur = _v33_get_task(project_id, "video_frame_tasks", task_id) or {}
                if cur.get("stop_requested"):
                    _v33_update_task(project_id, "video_frame_tasks", task_id, status="stopped", status_text="已停止", finished_at=now_iso())
                    cap.release()
                    return
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                if frame_idx % step == 0:
                    ts = frame_idx / source_fps
                    fname = f"{video_path.stem}_frame_{frame_idx:08d}_{ts:.2f}s.jpg".replace(":", "_")
                    temp = out_dir / fname
                    cv2.imwrite(str(temp), frame)
                    rec = add_image_record(project_id, temp, fname, source_type="video_frame", dataset_id=dataset_id)
                    if rec:
                        _v33_set_image_split(project_id, rec["id"], split)
                        saved += 1
                        if max_frames > 0 and saved >= max_frames:
                            break
                frame_idx += 1
                processed += 1
                if saved % 5 == 0:
                    _v33_update_task(project_id, "video_frame_tasks", task_id, extracted_frames=saved, processed_frames=processed, source_fps=round(source_fps, 3), frequency_text=frequency_text)
        cap.release()
        _v33_update_task(project_id, "video_frame_tasks", task_id, status="done", status_text="已完成", progress=100, extracted_frames=saved, processed_frames=processed, source_fps=round(source_fps, 3), duration_seconds=duration, frequency_text=frequency_text, finished_at=now_iso())
    except Exception as e:
        _v33_update_task(project_id, "video_frame_tasks", task_id, status="failed", status_text="失败", error=str(e), finished_at=now_iso())


def _public_task(
    task: TaskRecord,
    *,
    worker_runtime=None,
    queued_candidates=None,
) -> Dict[str, Any]:
    repository = shared_task_repository()
    truth = task_to_public(
        task,
        repository,
        worker_runtime=worker_runtime,
        queued_candidates=queued_candidates,
    )
    return {
        **truth,
        "id": task.task_id,
        "task_id": task.task_id,
        "task_status": truth["status"],
        "progress": truth["progress_percent"],
        "stage": truth["phase"],
    }


def _public_video_task(task: TaskRecord, *, worker_runtime=None, queued_candidates=None) -> Dict[str, Any]:
    return _video_tasks_service()._public_video_task(task, worker_runtime=worker_runtime, queued_candidates=queued_candidates)


def _require_shared_task(project_id: str, task_id: str, kind: TaskKind) -> TaskRecord:
    task = shared_task_repository().get(task_id)
    if task is None or task.project_id != project_id or task.kind is not kind:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


from platform_core.video_tasks_service import VideoTasksDependencies, VideoTasksService
from platform_core.video_tasks_api import create_video_tasks_router_1


def _video_tasks_service() -> VideoTasksService:
    return VideoTasksService(VideoTasksDependencies(
        VIDEO_EXTS_V33=lambda: VIDEO_EXTS_V33,
        _public_task=lambda *args, **kwargs: _public_task(*args, **kwargs),
        _require_shared_task=lambda *args, **kwargs: _require_shared_task(*args, **kwargs),
        ensure_project_dirs=lambda *args, **kwargs: ensure_project_dirs(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        safe_filename=lambda *args, **kwargs: safe_filename(*args, **kwargs),
        shared_task_artifacts=lambda *args, **kwargs: shared_task_artifacts(*args, **kwargs),
        shared_task_repository=lambda *args, **kwargs: shared_task_repository(*args, **kwargs),
    ))


app.include_router(create_video_tasks_router_1(_video_tasks_service, _material_governance_actor))


def v33_list_video_tasks(project_id: str, limit: int=50, cursor: Optional[str]=None):
    return _video_tasks_service().v33_list_video_tasks(project_id, limit, cursor)


def v33_get_video_task(project_id: str, task_id: str):
    return _video_tasks_service().v33_get_video_task(project_id, task_id)


def v33_stop_video_task(project_id: str, task_id: str):
    return _video_tasks_service().v33_stop_video_task(project_id, task_id)


async def v33_create_video_task(project_id: str, video: UploadFile=File(...), dataset_id: str=Form('default'), split: str=Form('unassigned'), mode: str=Form('interval_seconds'), interval_seconds: Optional[float]=Form(None), extract_fps: Optional[float]=Form(None), fixed_count: Optional[int]=Form(None), max_frames: Optional[int]=Form(None), backend: str=Form('auto'), priority: int=Form(50)):
    return await _video_tasks_service().v33_create_video_task(project_id, video, dataset_id, split, mode, interval_seconds, extract_fps, fixed_count, max_frames, backend, priority)


class V33PrelabelTaskReq(BaseModel):
    service_id: Optional[str] = None
    detect_url: Optional[str] = None
    request_mode: str = "json_base64"
    image_field: str = "image"
    threshold: float = 0.5
    target_label: str = "person"
    image_ids: Optional[List[str]] = None
    overwrite: bool = False
    task_name: Optional[str] = "自动标注任务"


def _v33_run_prelabel_task(project_id: str, task_id: str, payload: Dict[str, Any]):
    try:
        _v33_update_task(project_id, "prelabel_tasks", task_id, status="running", status_text="自动标注中", started_at=now_iso())
        cfg = resolve_prelabel_config(PrelabelRunReq(**payload))
        project = get_project(project_id)
        target_label = normalize_label(cfg.get("target_label") or payload.get("target_label") or "person")
        class_id = ensure_label(project, target_label)
        project = get_project(project_id)
        ids = set(payload.get("image_ids") or [])
        images = load_images(project_id)
        dataset_id = str(payload.get("dataset_id") or "").strip()
        if dataset_id and dataset_id not in {"__all__", "all"}:
            images = [img for img in images if img.get("dataset_id", "default") == dataset_id]
        if ids:
            images = [img for img in images if img.get("id") in ids]
        total = len(images)
        if not total:
            raise RuntimeError("没有可自动标注的图片")
        boxes_added = 0
        processed = 0
        started_ts = time.time()
        errors: List[Dict[str, Any]] = []
        for img in images:
            cur = _v33_get_task(project_id, "prelabel_tasks", task_id) or {}
            if cur.get("stop_requested"):
                _v33_update_task(project_id, "prelabel_tasks", task_id, status="stopped", status_text="已停止", finished_at=now_iso())
                return
            try:
                img_path = resolve_material_path(project_id, img)
                raw = call_prelabel_service(cfg, img_path)
                detections = parse_detection_objects(raw, target_label, float(cfg.get("threshold", 0.5)))
                new_boxes = []
                for det in detections:
                    x1 = max(0, min(float(det["x1"]), img["width"]))
                    y1 = max(0, min(float(det["y1"]), img["height"]))
                    x2 = max(0, min(float(det["x2"]), img["width"]))
                    y2 = max(0, min(float(det["y2"]), img["height"]))
                    if x2 - x1 < 3 or y2 - y1 < 3:
                        continue
                    new_boxes.append({
                        "id": uuid.uuid4().hex[:10], "class_id": class_id, "label": target_label,
                        "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2),
                        "source": "prelabel_task", "confidence": round(float(det.get("confidence", 0)), 4),
                    })
                old = read_annotation(project_id, img["id"]).get("boxes", [])
                if payload.get("overwrite"):
                    merged = [b for b in old if int(b.get("class_id", -1)) != class_id] + new_boxes
                else:
                    merged = old + new_boxes
                write_annotation(project_id, img["id"], merged)
                boxes_added += len(new_boxes)
            except Exception as e:
                errors.append({"image": img.get("filename"), "error": str(e)})
            processed += 1
            if processed % 2 == 0 or processed == total:
                elapsed = max(0.001, time.time() - started_ts)
                eta_seconds = int(max(0, elapsed / max(1, processed) * (total - processed)))
                _v33_update_task(project_id, "prelabel_tasks", task_id, processed_images=processed, total_images=total, boxes_added=boxes_added, progress=int(processed / max(1, total) * 100), elapsed_seconds=int(elapsed), eta_seconds=eta_seconds, errors=errors[-20:])
        _v33_update_task(project_id, "prelabel_tasks", task_id, status="done", status_text="已完成", progress=100, processed_images=processed, total_images=total, boxes_added=boxes_added, errors=errors[-20:], finished_at=now_iso(), labels=get_project(project_id).get("labels", []))
    except Exception as e:
        _v33_update_task(project_id, "prelabel_tasks", task_id, status="failed", status_text="失败", error=str(e), finished_at=now_iso())


@app.get("/api/v33/projects/{project_id}/prelabel-tasks")
def v33_list_prelabel_tasks(project_id: str):
    get_project(project_id)
    return {"items": _v33_load_tasks(project_id, "prelabel_tasks")}


@app.post("/api/v33/projects/{project_id}/prelabel-tasks/{task_id}/stop")
def v33_stop_prelabel_task(project_id: str, task_id: str):
    get_project(project_id)
    if not _v33_get_task(project_id, "prelabel_tasks", task_id):
        raise HTTPException(status_code=404, detail="自动标注任务不存在")
    _v33_update_task(project_id, "prelabel_tasks", task_id, stop_requested=True, status_text="正在停止")
    return {"ok": True}


@app.post("/api/v33/projects/{project_id}/prelabel-tasks")
def v33_create_prelabel_task(project_id: str, payload: V33PrelabelTaskReq):
    _reject_legacy_direct_prelabel(project_id)
    get_project(project_id)
    data = payload.dict()
    # 先解析一次，尽早发现服务不存在或地址为空。
    resolve_prelabel_config(PrelabelRunReq(**data))
    task_id = uuid.uuid4().hex[:12]
    task = {
        "id": task_id,
        "name": data.get("task_name") or "自动标注任务",
        "target_label": normalize_label(data.get("target_label") or "person"),
        "threshold": float(data.get("threshold") or 0.5),
        "status": "queued",
        "status_text": "排队中",
        "progress": 0,
        "processed_images": 0,
        "total_images": len(data.get("image_ids") or []),
        "boxes_added": 0,
        "stop_requested": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "dataset_id": data.get("dataset_id") or "default",
        "request_payload": data,
    }
    tasks = _v33_load_tasks(project_id, "prelabel_tasks")
    tasks.insert(0, task)
    _v33_save_tasks(project_id, "prelabel_tasks", tasks[:100])
    th = threading.Thread(target=_v33_run_prelabel_task, args=(project_id, task_id, data), daemon=True)
    th.start()
    return task

# ============================================================
# v35: model configuration + prompt library + framework-aware auto labeling
# ============================================================
from platform_core.ai_configuration_contracts import V35ModelConfigReq


from platform_core.ai_configuration_contracts import V35PromptTemplateReq


from platform_core.ai_configuration_contracts import V35PromptPreviewReq


class V35PrelabelTaskReq(BaseModel):
    model_config_id: Optional[str] = None
    prompt_template_id: Optional[str] = None
    detect_url: Optional[str] = None
    request_mode: str = "json_base64"
    image_field: str = "image"
    prompt: Optional[str] = ""
    prompt_field: str = "prompt"
    threshold: float = 0.5
    target_label: str = "person"
    image_ids: Optional[List[str]] = None
    overwrite: bool = False
    task_name: Optional[str] = "自动标注任务"
    training_framework: str = "internal"  # internal / ultralytics / paddle
    dataset_id: Optional[str] = "default"
    include_empty: bool = False


def _v35_items(file_path: Path) -> List[Dict[str, Any]]:
    return read_json(file_path, [])


def _v35_save_items(file_path: Path, items: List[Dict[str, Any]]):
    write_json(file_path, items)


def _v35_prompt_items() -> List[Dict[str, Any]]:
    items = _v35_items(PROMPT_LIBRARY_FILE)
    changed = False
    migrated: List[Dict[str, Any]] = []
    for item in items:
        if item.get("version_id") and item.get("version"):
            migrated.append(item)
            continue
        migrated.append(version_template(
            item,
            template_id=str(item.get("id") or uuid.uuid4().hex[:12]),
            now=str(item.get("updated_at") or item.get("created_at") or now_iso()),
        ))
        changed = True
    if changed:
        _v35_save_items(PROMPT_LIBRARY_FILE, migrated)
    return migrated


def _v35_validate_prompt(prompt: str):
    try:
        render_prompt(prompt, labels=[], width=1, height=1, business_instruction="")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _v35_secret_store():
    global MODEL_SECRET_STORE
    if MODEL_SECRET_STORE is not None:
        return MODEL_SECRET_STORE
    try:
        MODEL_SECRET_STORE = KeyringSecretStore()
        return MODEL_SECRET_STORE
    except Exception as error:
        raise PlatformError(
            code="SECRET_STORE_UNAVAILABLE",
            message="系统无法安全保存模型密钥",
            detail=str(error),
            solution="请执行依赖安装后重启平台；Windows 将使用系统凭据管理器保存 API Key。",
            status_code=503,
        ) from error


def _v35_clean_headers(headers: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    sensitive = {"authorization", "x-api-key", "api-key", "apikey"}
    return {str(key): value for key, value in (headers or {}).items() if str(key).lower() not in sensitive}


def _v35_model_items() -> List[Dict[str, Any]]:
    items = _v35_items(MODEL_CONFIGS_FILE)
    changed = False
    for item in items:
        legacy = str(item.pop("api_key", "") or "")
        if legacy:
            reference = str(item.get("secret_ref") or secret_ref("model-config", str(item.get("id") or uuid.uuid4().hex[:12])))
            _v35_secret_store().set(reference, legacy)
            item["secret_ref"] = reference
            changed = True
        # Resolve account identity from the actual credential, including legacy
        # references and environment overrides. This is an in-memory projection;
        # no read-side identity migration rewrites the configuration file.
        reference = str(item.get("secret_ref") or "")
        credential = _v35_secret_store().get(reference) if reference else ""
        if credential:
            item["inference_account_identity"] = hashlib.sha256(credential.encode()).hexdigest()
        elif reference:
            item.pop("inference_account_identity", None)
        cleaned = _v35_clean_headers(item.get("headers_json"))
        if cleaned != (item.get("headers_json") or {}):
            item["headers_json"] = cleaned
            changed = True
    if changed:
        _v35_save_items(MODEL_CONFIGS_FILE, items)
    return items


def _v35_sanitize_secret(item: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(item)
    out.pop("api_key", None)
    reference = str(out.get("secret_ref") or "")
    masked = _v35_secret_store().masked(reference) if reference else ""
    out.pop("secret_ref", None)
    out.pop("inference_account_identity", None)
    from platform_core.inference_policy import resolve_inference_policy
    out["inference_capacity"] = resolve_inference_policy(item)
    out["has_api_key"] = bool(masked)
    out["api_key_masked"] = masked
    out.setdefault("api_protocol", "auto")
    out.setdefault("structured_output", "auto")
    out.setdefault("coordinate_validation", {"status": "unverified", "reason": "尚未用真实样本核验坐标"})
    out.setdefault("coordinate_space", "legacy_auto")
    out.setdefault("coordinate_order", "xyxy")
    out.setdefault("output_protocol", "json_boxes")
    out.setdefault("enabled", True)
    if (out.get("provider_adapter") or out.get("provider_type")) == "wevisone_vl":
        out["capabilities"] = ["detect", "segment", "matting"]
    if (out.get("provider_adapter") or out.get("provider_type")) in {"volcengine_ark", "aliyun_qwen", "local_openai"}:
        from platform_core.providers.openai_vision import resolve_api_endpoint, PRESETS, ProviderRequestError
        kind = out.get("provider_adapter") or out.get("provider_type")
        try:
            _, out["resolved_api_protocol"] = resolve_api_endpoint(
                out.get("base_url") or out.get("detect_url") or PRESETS[kind]["base_url"], out["api_protocol"],
            )
        except (ValueError, ProviderRequestError):
            out["protocol_warning"] = "请确认高级设置中的 API 协议及接口地址。"
    return out


def _v35_normalize_adapter(item: Dict[str, Any]) -> None:
    kind = str(item.get("provider_adapter") or item.get("provider_type") or "")
    if kind not in {"", "cloud", "local", "volcengine_ark", "aliyun_qwen", "local_openai", "ollama", "wevisone_vl"}:
        raise HTTPException(status_code=400, detail="不支持的模型适配方式")
    if kind == "wevisone_vl":
        from platform_core.providers.wevisone_vision import _endpoint, normalize_label_queries
        try:
            _endpoint(item.get("base_url") or item.get("detect_url") or "", "detect")
            item["wevisone_label_queries"] = normalize_label_queries(item.get("wevisone_label_queries"))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if not str(item.get("model_name") or "").strip():
            raise HTTPException(status_code=400, detail="WeVisOne 模型 ID 不能为空")
        item.update({"provider_adapter": kind, "provider_type": kind,
                     "output_protocol": "json_boxes", "api_protocol": "auto", "structured_output": "auto"})
    else:
        item.pop("wevisone_label_queries", None)
    if item.get("enabled") is False and item.get("default_for_annotation"):
        raise HTTPException(status_code=400, detail="停用的模型不能设为默认自动标注模型")


def _v35_unique_default(items: List[Dict[str, Any]], chosen: Dict[str, Any]) -> None:
    if chosen.get("default_for_annotation"):
        for other in items:
            if other.get("id") != chosen.get("id"):
                other["default_for_annotation"] = False


def _v35_publish_model_config(item=None, *, removed_id=""):
    # Mutation results update the existing Bootstrap projection. No full rebuild
    # or second cache: refresh/re-edit must see the same saved configuration.
    public = _v35_sanitize_secret(item) if item is not None else None
    snapshot = globals().get("_V53_BOOTSTRAP_SNAPSHOT")
    if isinstance(snapshot, dict) and snapshot and not snapshot.get("core_only"):
        identity = str(item.get("id") if item is not None else removed_id)
        rows = snapshot.get("model_configs") or []
        found = any(str(row.get("id")) == identity for row in rows)
        snapshot["model_configs"] = [public if str(row.get("id")) == identity else row for row in rows if public is not None or str(row.get("id")) != identity]
        if public is not None and not found:
            snapshot["model_configs"] = [public, *snapshot["model_configs"]]
        if public is not None and public.get("default_for_annotation"):
            for row in snapshot["model_configs"]:
                if str(row.get("id")) != identity:
                    row["default_for_annotation"] = False
    return public


app.include_router(create_ai_configuration_router_2(_ai_configuration_service))


def v35_list_model_configs():
    return _ai_configuration_service().v35_list_model_configs()


def v35_save_model_config(payload: V35ModelConfigReq):
    return _ai_configuration_service().v35_save_model_config(payload)


def v35_update_model_config(config_id: str, payload: V35ModelConfigReq):
    return _ai_configuration_service().v35_update_model_config(config_id, payload)


def v35_check_model_capacity(config_id: str):
    return _ai_configuration_service().v35_check_model_capacity(config_id)


def v35_delete_model_config(config_id: str):
    return _ai_configuration_service().v35_delete_model_config(config_id)


from platform_core.ai_configuration_contracts import V35ModelAvailabilityReq


def v35_set_model_availability(config_id: str, payload: V35ModelAvailabilityReq):
    return _ai_configuration_service().v35_set_model_availability(config_id, payload)


def _v35_is_vision_provider(config):
    return config.get("model_kind") == "vlm" or config.get("request_mode") == "openai_vision" or (config.get("provider_adapter") or config.get("provider_type")) in {"volcengine_ark", "aliyun_qwen", "local_openai", "ollama", "wevisone_vl"}


def v35_test_model_config(payload: V35ModelConfigReq):
    return _ai_configuration_service().v35_test_model_config(payload)


def v35_test_saved_model_annotation(config_id: str):
    return _ai_configuration_service().v35_test_saved_model_annotation(config_id)


from platform_core.ai_configuration_contracts import V35CoordinateSampleReq


def v35_verify_model_coordinates(config_id: str, payload: V35CoordinateSampleReq):
    return _ai_configuration_service().v35_verify_model_coordinates(config_id, payload)


from platform_core.ai_configuration_contracts import V35CoordinateConfirmationReq


def v35_confirm_model_coordinates(config_id: str, payload: V35CoordinateConfirmationReq):
    return _ai_configuration_service().v35_confirm_model_coordinates(config_id, payload)


def _v35_test_annotation(runtime_cfg, *, image_bytes=None, sample_prompt=None, sample_labels=None, sample_size=(128, 128)):
    from platform_core.providers.base import ProviderRequestError
    api_key = str(runtime_cfg.get("_api_key") or "")

    def redact(value):
        return value.replace(api_key, "[已隐藏凭据]") if api_key and isinstance(value, str) else value

    try:
        provider = auto_label_core.provider_factory(runtime_cfg)
        dedicated = (runtime_cfg.get("provider_adapter") or runtime_cfg.get("provider_type")) == "wevisone_vl"
        identity = provider.inspect_model() if dedicated and callable(getattr(provider, "inspect_model", None)) else {}
        buffer = BytesIO()
        Image.new("RGB", (128, 128), "white").save(buffer, format="JPEG")
        provider_args = dict(
            image_bytes=image_bytes or buffer.getvalue(),
            prompt=sample_prompt or (
                "请仅返回 JSON，检测图片中的 fire。"
                "输出格式必须为 boxes 数组，每个框包含 label、confidence、x1、y1、x2、y2。"
            ),
            output_schema=auto_label_core.CANDIDATE_OUTPUT_SCHEMA,
        )
        if dedicated:
            provider_args["labels"] = sample_labels or ["fire"]
        response = provider.annotate(**provider_args)
        text = str(response.get("text") or "")
        try:
            contract = auto_label_core.coordinate_contract(runtime_cfg, legacy=True)
            if dedicated:
                # The native adapter validates the saved wire contract and
                # always returns canonical input-image pixels to this parser.
                contract = {"coordinate_space": "pixel", "coordinate_order": "xyxy",
                            "coordinate_origin": "top_left", "coordinate_image_space": "original_input"}
            mapping = response.get("geometry") if contract.get("coordinate_image_space") == "processed_image" else None
            if contract.get("coordinate_image_space") == "processed_image" and not isinstance(mapping, dict):
                raise ValueError("unknown provider preprocessing geometry")
            boxes = auto_label_core.parse_candidate_response(text, width=sample_size[0], height=sample_size[1], label_ids={label: i for i, label in enumerate(sample_labels or ["fire"])}, coordinate_space=contract["coordinate_space"], coordinate_order=contract["coordinate_order"], coordinate_origin=contract.get("coordinate_origin", "top_left"), geometry=mapping, allow_missing_confidence=dedicated)
        except ValueError:
            raise ProviderRequestError(
                "模型标注输出未通过平台字段、类别或坐标校验", code="MODEL_OUTPUT_PARSE_ERROR",
                request_id=str(response.get("request_id") or ""), status_code=200,
            ) from None
        return {
            "ok": True,
            "status_code": 200,
            "reachable": True,
            "model_loaded": identity.get("model_loaded") if dedicated else None,
            "protocol_valid": True,
            "coordinate_confirmed": runtime_cfg.get("coordinate_validation", {}).get("status") == "verified",
            "no_target": not bool(boxes),
            "latency_ms": int(response.get("latency_ms") or 0),
            "provider": redact(response.get("provider") or runtime_cfg.get("provider_type")),
            "model": redact(response.get("model") or runtime_cfg.get("model_name")),
            "request_id": redact(response.get("request_id") or ""),
            "api_protocol": redact(response.get("api_protocol") or "auto"),
            "raw_preview": redact(text)[:20000 if sample_prompt else 500],
            "parsed_boxes": boxes,
        }
    except Exception as error:
        code = str(getattr(error, "code", "MODEL_CONNECTION_TEST_FAILED"))
        solution = str(getattr(error, "solution", "请检查服务地址、API Key、模型名称和模型输出协议。"))
        raise PlatformError(
            code=code,
            message="模型标注连接测试失败",
            detail=redact(str(error)),
            solution=redact(solution),
            status_code=400,
            request_id=redact(str(getattr(error, "request_id", ""))),
            server_error_code=redact(str(getattr(error, "server_error_code", ""))),
            upstream_status=int(getattr(error, "status_code", 0)),
        ) from error


def v35_list_prompt_templates():
    return _ai_configuration_service().v35_list_prompt_templates()


def v35_save_prompt_template(payload: V35PromptTemplateReq):
    return _ai_configuration_service().v35_save_prompt_template(payload)


def v35_update_prompt_template(template_id: str, payload: V35PromptTemplateReq):
    return _ai_configuration_service().v35_update_prompt_template(template_id, payload)


def v35_delete_prompt_template(template_id: str):
    return _ai_configuration_service().v35_delete_prompt_template(template_id)


def v35_preview_prompt_template(payload: V35PromptPreviewReq):
    return _ai_configuration_service().v35_preview_prompt_template(payload)


def _v35_resolve_model_and_prompt(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    configs = _v35_model_items()
    templates = _v35_prompt_items()
    cfg: Dict[str, Any] = {}
    tpl: Dict[str, Any] = {}
    if payload.get("prompt_template_snapshot"):
        tpl = dict(payload.get("prompt_template_snapshot") or {})
    elif payload.get("prompt_template_id"):
        tpl = next((x for x in templates if x.get("id") == payload.get("prompt_template_id")), {})
        if not tpl:
            raise HTTPException(status_code=400, detail="模型标注模板不存在")
    config_id = payload.get("model_config_id") or tpl.get("model_config_id")
    if config_id:
        cfg = next((x for x in configs if x.get("id") == config_id), {})
        if not cfg:
            raise HTTPException(status_code=400, detail="模型配置不存在")
    else:
        detect_url = (payload.get("detect_url") or "").strip()
        if not detect_url:
            raise HTTPException(status_code=400, detail="请选择模型配置或填写临时检测接口")
        cfg = {
            "id": "manual", "name": "临时接口", "detect_url": detect_url,
            "request_mode": payload.get("request_mode") or "json_base64",
            "image_field": payload.get("image_field") or "image",
            "prompt_field": payload.get("prompt_field") or "prompt",
            "threshold_field": "threshold",
        }
    # template values override if user did not explicitly set.
    return cfg, tpl


def _v35_call_model(cfg: Dict[str, Any], image_path: Path, payload: Dict[str, Any], prompt_text: str, threshold: float) -> Dict[str, Any]:
    url = (cfg.get("detect_url") or cfg.get("base_url") or "").strip()
    if not url:
        raise ValueError("模型检测接口为空")
    headers = dict(cfg.get("headers_json") or {})
    if cfg.get("api_key"):
        headers.setdefault("Authorization", f"Bearer {cfg.get('api_key')}")
    mode = payload.get("request_mode") or cfg.get("request_mode") or "json_base64"
    image_field = payload.get("image_field") or cfg.get("image_field") or "image"
    prompt_field = payload.get("prompt_field") or cfg.get("prompt_field") or "prompt"
    threshold_field = cfg.get("threshold_field") or "threshold"
    if mode == "multipart_file":
        data = {threshold_field: str(threshold)}
        if prompt_text:
            data[prompt_field] = prompt_text
        if cfg.get("model_name"):
            data["model"] = cfg.get("model_name")
        with image_path.open("rb") as fp:
            r = requests.post(url, headers=headers, files={image_field: (image_path.name, fp, "application/octet-stream")}, data=data, timeout=180)
    else:
        raw = image_path.read_bytes()
        body = {
            image_field: base64.b64encode(raw).decode("utf-8"),
            threshold_field: threshold,
        }
        if prompt_text:
            body[prompt_field] = prompt_text
        if cfg.get("model_name"):
            body["model"] = cfg.get("model_name")
        r = requests.post(url, headers=headers, json=body, timeout=180)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


def _v35_framework_build_after_prelabel(project_id: str, framework: str, dataset_id: Optional[str], include_empty: bool) -> Dict[str, Any]:
    fw = (framework or "internal").lower()
    if fw in {"ultralytics", "yolo"}:
        res = build_yolo_dataset_v12(project_id, dataset_id, include_empty)
        return {"framework": "ultralytics", "format": "YOLO", "path": res.get("dataset"), "data_yaml": res.get("data_yaml"), "counts": res.get("counts")}
    if fw in {"paddle", "paddledetection", "paddlex"}:
        res = build_paddle_dataset_internal(project_id, dataset_id=dataset_id, include_empty=include_empty)  # type: ignore[arg-type]
        return {"framework": "paddle", "format": "COCO/Paddle", "path": res.get("dataset"), "train_json": res.get("train_json"), "val_json": res.get("val_json"), "counts": res.get("counts")}
    return {"framework": "internal", "format": "平台内部标注", "path": str(project_dir(project_id) / "annotations")}


def _v35_run_prelabel_task(project_id: str, task_id: str, payload: Dict[str, Any]):
    try:
        _v33_update_task(project_id, "prelabel_tasks", task_id, status="running", status_text="自动标注中", started_at=now_iso())
        cfg, tpl = _v35_resolve_model_and_prompt(payload)
        prompt_text = payload.get("prompt") or tpl.get("prompt") or ""
        threshold = float(payload.get("threshold") if payload.get("threshold") is not None else tpl.get("threshold", 0.5))
        target_label = normalize_label(payload.get("target_label") or (tpl.get("labels") or ["person"])[0] or "person")
        project = get_project(project_id)
        class_id = ensure_label(project, target_label)
        ids = set(payload.get("image_ids") or [])
        images = load_images(project_id)
        dataset_id = payload.get("dataset_id") or "default"
        if ids:
            images = [img for img in images if img.get("id") in ids]
        else:
            images = [img for img in images if (img.get("dataset_id", "default") == dataset_id)]
        total = len(images)
        if not total:
            raise RuntimeError("没有可自动标注的图片")
        boxes_added = 0
        processed = 0
        started_ts = time.time()
        errors: List[Dict[str, Any]] = []
        for img in images:
            cur = _v33_get_task(project_id, "prelabel_tasks", task_id) or {}
            if cur.get("stop_requested"):
                _v33_update_task(project_id, "prelabel_tasks", task_id, status="stopped", status_text="已停止", finished_at=now_iso())
                return
            try:
                img_path = resolve_material_path(project_id, img)
                raw = _v35_call_model(cfg, img_path, payload, prompt_text, threshold)
                detections = parse_detection_objects(raw, target_label, threshold)
                new_boxes = []
                for det in detections:
                    x1 = max(0, min(float(det["x1"]), img["width"]))
                    y1 = max(0, min(float(det["y1"]), img["height"]))
                    x2 = max(0, min(float(det["x2"]), img["width"]))
                    y2 = max(0, min(float(det["y2"]), img["height"]))
                    if x2 - x1 < 3 or y2 - y1 < 3:
                        continue
                    lbl = normalize_label(det.get("label") or target_label)
                    cid = ensure_label(get_project(project_id), lbl)
                    new_boxes.append({
                        "id": uuid.uuid4().hex[:10], "class_id": cid, "label": lbl,
                        "x1": round(x1, 2), "y1": round(y1, 2), "x2": round(x2, 2), "y2": round(y2, 2),
                        "source": "model_prelabel", "confidence": round(float(det.get("confidence", 0)), 4),
                        "model_config_id": cfg.get("id"), "prompt_template_id": tpl.get("id", ""),
                    })
                old = read_annotation(project_id, img["id"]).get("boxes", [])
                if payload.get("overwrite"):
                    target_cids = {b.get("class_id") for b in new_boxes}
                    merged = [b for b in old if b.get("class_id") not in target_cids] + new_boxes
                else:
                    merged = old + new_boxes
                write_annotation(project_id, img["id"], merged)
                boxes_added += len(new_boxes)
            except Exception as e:
                errors.append({"image": img.get("filename"), "error": str(e)})
            processed += 1
            if processed % 2 == 0 or processed == total:
                elapsed = max(0.001, time.time() - started_ts)
                eta_seconds = int(max(0, elapsed / max(1, processed) * (total - processed)))
                _v33_update_task(project_id, "prelabel_tasks", task_id, processed_images=processed, total_images=total, boxes_added=boxes_added, progress=int(processed / max(1, total) * 100), elapsed_seconds=int(elapsed), eta_seconds=eta_seconds, errors=errors[-20:])
        if processed and len(errors) >= processed and boxes_added == 0:
            first_error = errors[0].get("error") if errors else "模型没有返回可用标注"
            _v33_update_task(project_id, "prelabel_tasks", task_id, status="failed", status_text="失败", progress=100, processed_images=processed, total_images=total, boxes_added=0, errors=errors[-20:], error=first_error, finished_at=now_iso())
            return
        export_result = {}
        try:
            export_result = _v35_framework_build_after_prelabel(project_id, payload.get("training_framework") or tpl.get("save_format") or "internal", dataset_id, bool(payload.get("include_empty", False)))
        except Exception as e:
            export_result = {"error": str(e), "framework": payload.get("training_framework") or "internal"}
        _v33_update_task(project_id, "prelabel_tasks", task_id, status="done", status_text="已完成", progress=100, processed_images=processed, total_images=total, boxes_added=boxes_added, errors=errors[-20:], export_result=export_result, finished_at=now_iso(), labels=get_project(project_id).get("labels", []))
    except Exception as e:
        _v33_update_task(project_id, "prelabel_tasks", task_id, status="failed", status_text="失败", error=str(e), finished_at=now_iso())


@app.post("/api/v35/projects/{project_id}/prelabel-tasks")
def v35_create_prelabel_task(project_id: str, payload: V35PrelabelTaskReq):
    _reject_legacy_direct_prelabel(project_id)
    get_project(project_id)
    data = payload.dict()
    cfg, tpl = _v35_resolve_model_and_prompt(data)
    if tpl:
        data["prompt_template_snapshot"] = tpl
    task_id = uuid.uuid4().hex[:12]
    name = data.get("task_name") or tpl.get("name") or "自动标注任务"
    task = {
        "id": task_id,
        "name": name,
        "model_name": cfg.get("name"),
        "prompt_template_name": tpl.get("name", ""),
        "prompt_template_id": tpl.get("id", ""),
        "prompt_template_version": tpl.get("version"),
        "prompt_template_version_id": tpl.get("version_id", ""),
        "target_label": normalize_label(data.get("target_label") or (tpl.get("labels") or ["person"])[0] or "person"),
        "threshold": float(data.get("threshold") or tpl.get("threshold", 0.5)),
        "training_framework": data.get("training_framework") or tpl.get("save_format") or "internal",
        "status": "queued",
        "status_text": "排队中",
        "progress": 0,
        "processed_images": 0,
        "total_images": len(data.get("image_ids") or []),
        "boxes_added": 0,
        "stop_requested": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "dataset_id": data.get("dataset_id") or "default",
        "request_payload": data,
    }
    tasks = _v33_load_tasks(project_id, "prelabel_tasks")
    tasks.insert(0, task)
    _v33_save_tasks(project_id, "prelabel_tasks", tasks[:100])
    th = threading.Thread(target=_v35_run_prelabel_task, args=(project_id, task_id, data), daemon=True)
    th.start()
    return task

# ============================================================
# v36: path / URL source import for local folders, servers, zip/images
# ============================================================
from platform_core.material_ingestion_contracts import V36SourceImportScanReq


from platform_core.material_ingestion_contracts import V36SourceImportStartReq


def _v36_source_jobs_dir(project_id: str) -> Path:
    d = project_dir(project_id) / "source_import_tasks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _v36_source_job_file(project_id: str, job_id: str) -> Path:
    return _v36_source_jobs_dir(project_id) / f"{job_id}.json"


def _v36_load_source_jobs(project_id: str) -> List[Dict[str, Any]]:
    d = _v36_source_jobs_dir(project_id)
    items = []
    for f in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            items.append(read_json(f, {}))
        except Exception:
            pass
    return items


def _v36_write_source_job(project_id: str, job: Dict[str, Any]):
    job["updated_at"] = now_iso()
    write_json(_v36_source_job_file(project_id, job["id"]), job)


def _v36_update_source_job(project_id: str, job_id: str, **kwargs):
    f = _v36_source_job_file(project_id, job_id)
    if not f.exists():
        return
    job = read_json(f, {})
    job.update(kwargs)
    _v36_write_source_job(project_id, job)


def _v36_normalize_source(source: str) -> str:
    return str(source or "").strip().strip('"').strip("'")


def _v36_is_url(source: str) -> bool:
    return bool(re.match(r"^https?://", source.strip(), re.I))


def _v36_suffix_from_url(url: str) -> str:
    path = url.split("?", 1)[0].split("#", 1)[0]
    return Path(path).suffix.lower()


def _v36_scan_local_root(root: Path, max_items: int = 5000) -> Dict[str, Any]:
    if not root.exists():
        raise HTTPException(status_code=400, detail=f"路径不存在：{root}")
    files: List[Path] = []
    if root.is_file():
        files = [root]
    else:
        for f in root.rglob("*"):
            if f.is_file():
                files.append(f)
                if len(files) >= max_items:
                    break
    image_files = [f for f in files if f.suffix.lower() in IMAGE_EXTS]
    yolo_labels = [f for f in files if f.suffix.lower() == ".txt" and f.name.lower() not in {'classes.txt','obj.names','_darknet.labels','train.txt','val.txt','test.txt'}]
    coco_files = []
    for f in files:
        if f.suffix.lower() != ".json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8", errors="ignore"))
            if isinstance(data, dict) and isinstance(data.get("images"), list) and isinstance(data.get("annotations"), list) and isinstance(data.get("categories"), list):
                coco_files.append(f)
        except Exception:
            pass
    voc_files = [f for f in files if f.suffix.lower() == ".xml"]
    stems_with_labels = {x.stem for x in yolo_labels} | {x.stem for x in voc_files}
    annotated_by_name = 0
    if coco_files:
        # COCO 可能标注图不与文件同名，先粗略认为 COCO 内图片为已标注候选。
        try:
            coco = json.loads(coco_files[0].read_text(encoding="utf-8", errors="ignore"))
            ann_ids = {int(a.get("image_id")) for a in coco.get("annotations", []) if a.get("image_id") is not None}
            annotated_by_name = len(ann_ids)
        except Exception:
            annotated_by_name = 0
    else:
        annotated_by_name = sum(1 for im in image_files if im.stem in stems_with_labels)
    hints = []
    if coco_files: hints.append("COCO")
    if voc_files: hints.append("VOC")
    if yolo_labels or list(root.rglob("data.yaml")) if root.is_dir() else False: hints.append("YOLO")
    if not hints and image_files: hints.append("普通图片")
    def rel(f: Path) -> str:
        try:
            return str(f.relative_to(root if root.is_dir() else root.parent)).replace("\\", "/")
        except Exception:
            return f.name
    samples = [{"path": rel(f), "name": f.name, "split": _v18_split_from_path(f), "annotated_guess": f.stem in stems_with_labels} for f in image_files[:200]]
    return {
        "source": str(root),
        "source_type": "local_path",
        "exists": True,
        "is_file": root.is_file(),
        "file_count": len(files),
        "image_count": len(image_files),
        "annotated_guess": min(annotated_by_name, len(image_files)),
        "unannotated_guess": max(0, len(image_files) - min(annotated_by_name, len(image_files))),
        "yolo_label_files": len(yolo_labels),
        "coco_files": len(coco_files),
        "voc_files": len(voc_files),
        "format_hints": hints or ["未知"],
        "samples": samples,
        "truncated": len(files) >= max_items,
    }


def _v36_scan_url(source: str) -> Dict[str, Any]:
    url = _v36_normalize_source(source)
    suffix = _v36_suffix_from_url(url)
    try:
        h = requests.head(url, timeout=8, allow_redirects=True)
        content_type = h.headers.get("content-type", "")
        size = int(h.headers.get("content-length") or 0)
    except Exception:
        content_type = ""
        size = 0
    hints: List[str] = []
    if suffix == ".zip" or "zip" in content_type.lower(): hints.append("ZIP数据集")
    elif suffix in IMAGE_EXTS or "image/" in content_type.lower(): hints.append("单张图片")
    elif suffix in {".json"}: hints.append("COCO/JSON")
    else: hints.append("HTTP资源")
    return {"source": url, "source_type": "url", "exists": True, "is_file": True, "file_count": 1, "image_count": 0 if suffix not in IMAGE_EXTS else 1, "annotated_guess": 0, "unannotated_guess": 0 if suffix not in IMAGE_EXTS else 1, "format_hints": hints, "content_type": content_type, "size_mb": round(size/1024/1024, 2) if size else 0, "samples": []}


def _v36_base_report() -> Dict[str, Any]:
    return {"ok": True, "detected_format": "未知", "imported_images": 0, "annotated_images": 0, "unannotated_images": 0, "boxes": 0, "missing_images": 0, "skipped_images": 0, "invalid_boxes": 0, "skipped_labels": 0, "unmatched_labels": 0, "labels": [], "warnings": []}


def _v36_download_source_to_file(url: str, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def _v36_import_single_image(project_id: str, src: Path, dataset_id: str, report: Dict[str, Any]):
    rec = add_image_record(project_id, src, src.name, "source_path", dataset_id)
    if rec:
        _v18_set_image_split(project_id, rec["id"], "test")
        report["imported_images"] += 1
        report["unannotated_images"] += 1
        report["detected_format"] = "普通图片"


V36_ANNOTATED_IMPORT_BLOCKED_DETAIL = (
    "地址读取只允许导入未标注图片；检测到 YOLO/COCO/VOC 标注时，"
    "请改用“上传并检查标注”统一入口，先确认标签映射再正式入库"
)


def _v36_detect_annotated_formats(root: Path) -> List[str]:
    """Detect annotation-bearing sources without mutating platform labels or annotations."""
    import xml.etree.ElementTree as ET

    found = set()
    if not root.exists():
        return []
    files = [root] if root.is_file() else root.rglob("*")
    ignored_txt = {"classes.txt", "obj.names", "_darknet.labels", "train.txt", "val.txt", "test.txt"}
    for file_path in files:
        if not file_path.is_file():
            continue
        name = file_path.name.lower()
        suffix = file_path.suffix.lower()

        if name in {"data.yaml", "data.yml"}:
            try:
                parsed = yaml.safe_load(file_path.read_text(encoding="utf-8", errors="ignore")) or {}
                if isinstance(parsed, dict) and parsed.get("names"):
                    found.add("YOLO")
            except Exception:
                pass

        elif suffix == ".txt" and name not in ignored_txt:
            try:
                for raw in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    parts = raw.strip().split()
                    if len(parts) < 5:
                        continue
                    try:
                        int(float(parts[0]))
                        [float(value) for value in parts[1:5]]
                    except Exception:
                        continue
                    found.add("YOLO")
                    break
            except Exception:
                pass

        elif suffix == ".json":
            try:
                data = json.loads(file_path.read_text(encoding="utf-8", errors="ignore"))
                if (
                    isinstance(data, dict)
                    and isinstance(data.get("images"), list)
                    and isinstance(data.get("annotations"), list)
                    and isinstance(data.get("categories"), list)
                ):
                    found.add("COCO")
            except Exception:
                pass

        elif suffix == ".xml":
            try:
                xml_root = ET.parse(file_path).getroot()
                if any(obj.find("bndbox") is not None for obj in xml_root.findall("object")):
                    found.add("VOC")
            except Exception:
                pass

        if len(found) == 3:
            break
    return [name for name in ("COCO", "VOC", "YOLO") if name in found]


def _v36_detect_source_annotation_formats(root: Path) -> List[str]:
    if root.is_file() and root.suffix.lower() == ".zip":
        scan = v19_scan_zip(root)
        classes = list(scan.get("external_classes") or [])
        if classes or int(scan.get("annotation_box_count") or 0) > 0:
            detected = str(scan.get("detected_format") or "")
            if detected == "Pascal VOC":
                return ["VOC"]
            if detected in {"COCO", "YOLO"}:
                return [detected]
            return ["ANNOTATED"]
        return []
    return _v36_detect_annotated_formats(root)


def _v36_import_from_root(project_id: str, root: Path, dataset_id: str, report: Dict[str, Any]) -> bool:
    formats = _v36_detect_annotated_formats(root)
    if formats:
        raise RuntimeError(
            f"{V36_ANNOTATED_IMPORT_BLOCKED_DETAIL}（检测到：{' / '.join(formats)}）"
        )

    image_files = (
        [root]
        if root.is_file() and root.suffix.lower() in IMAGE_EXTS
        else [
            file_path
            for file_path in root.rglob("*")
            if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTS
        ]
        if root.is_dir()
        else []
    )
    for src in sorted(image_files, key=lambda value: str(value).lower()):
        _v36_import_single_image(project_id, src, dataset_id, report)
    return bool(image_files)


def _v36_apply_split_policy(project_id: str, imported_ids: List[str], policy: str, train_ratio: float, val_ratio: float, test_ratio: float) -> Dict[str, int]:
    if not imported_ids:
        return {"train": 0, "val": 0, "test": 0}
    images = load_images(project_id)
    img_map = {x.get("id"): x for x in images if x.get("id") in set(imported_ids)}
    annotated_ids = []
    unannotated_ids = []
    for iid in imported_ids:
        ann = read_annotation(project_id, iid).get("boxes", [])
        if ann:
            annotated_ids.append(iid)
        else:
            unannotated_ids.append(iid)
    counts = {"train": 0, "val": 0, "test": 0}
    patches = {}
    policy = (policy or "annotated_train_unannotated_test").lower()
    if policy == "source":
        for iid in imported_ids:
            sp = img_map.get(iid, {}).get("split") or "train"
            if sp not in counts: sp = "train"
            counts[sp] += 1
        return counts
    if policy == "ratio":
        ordered = sorted(imported_ids)
        total = len(ordered)
        tr = max(0.0, min(float(train_ratio or 0.8), 1.0))
        vr = max(0.0, min(float(val_ratio or 0.2), 1.0))
        n_train = min(total, int(total * tr))
        n_val = min(total - n_train, int(total * vr))
        for idx, iid in enumerate(ordered):
            split = "train" if idx < n_train else "val" if idx < n_train + n_val else "test"
            if iid in img_map:
                patches[str(iid)] = {"split": split}
                counts[split] += 1
    else:
        # 默认：有标注的进入训练/评测；无标注的进入试验集，避免误把无标注图用于训练。
        ordered = sorted(annotated_ids)
        n_train = min(len(ordered), max(1, int(len(ordered) * float(train_ratio or 0.8)))) if ordered else 0
        for idx, iid in enumerate(ordered):
            split = "train" if idx < n_train else "val"
            if iid in img_map:
                patches[str(iid)] = {"split": split}
                counts[split] += 1
        for iid in unannotated_ids:
            if iid in img_map:
                patches[str(iid)] = {"split": "test"}
                counts["test"] += 1
    material_store(project_id).patch(patches)
    return counts


def _v36_run_source_import(project_id: str, dataset_id: str, job_id: str, payload: Dict[str, Any]):
    job_dir = project_dir(project_id) / "imports" / f"source_{job_id}"
    work_root = job_dir / "work"
    try:
        _v36_update_source_job(project_id, job_id, status="running", status_text="读取中", stage="正在准备来源", progress=5)
        source = _v36_normalize_source(payload.get("source") or "")
        if not source:
            raise RuntimeError("来源地址不能为空")
        before_ids = {x.get("id") for x in load_images(project_id)}
        report = _v36_base_report()
        job_dir.mkdir(parents=True, exist_ok=True)
        work_root.mkdir(parents=True, exist_ok=True)
        if _v36_is_url(source):
            _v36_update_source_job(project_id, job_id, stage="正在下载服务器文件", progress=18)
            suffix = _v36_suffix_from_url(source) or ".bin"
            src_file = job_dir / f"download{suffix}"
            _v36_download_source_to_file(source, src_file)
            if src_file.suffix.lower() == ".zip":
                _v36_update_source_job(project_id, job_id, stage="正在解压数据集", progress=35)
                _v18_safe_extract(src_file, work_root)
                _v36_update_source_job(project_id, job_id, stage="正在解析标注与素材", progress=55)
                ok = _v36_import_from_root(project_id, work_root, dataset_id, report)
                if not ok:
                    raise RuntimeError("没有识别到可导入图片或标注")
            elif src_file.suffix.lower() in IMAGE_EXTS:
                _v36_import_single_image(project_id, src_file, dataset_id, report)
            else:
                raise RuntimeError("当前 URL 仅支持 zip 数据集或单张图片文件")
        else:
            root = Path(source).expanduser()
            _v36_update_source_job(project_id, job_id, stage="正在扫描本机路径", progress=20)
            if not root.exists():
                raise RuntimeError(f"路径不存在：{root}")
            if root.is_file() and root.suffix.lower() == ".zip":
                _v36_update_source_job(project_id, job_id, stage="正在解压数据集", progress=35)
                _v18_safe_extract(root, work_root)
                _v36_update_source_job(project_id, job_id, stage="正在解析标注与素材", progress=55)
                ok = _v36_import_from_root(project_id, work_root, dataset_id, report)
            elif root.is_file() and root.suffix.lower() in IMAGE_EXTS:
                ok = True
                _v36_import_single_image(project_id, root, dataset_id, report)
            elif root.is_dir():
                _v36_update_source_job(project_id, job_id, stage="正在解析目录", progress=45)
                ok = _v36_import_from_root(project_id, root, dataset_id, report)
            else:
                ok = False
            if not ok:
                raise RuntimeError("没有识别到可导入图片或标注。支持目录、zip、图片、YOLO/COCO/VOC 数据集。")
        after = load_images(project_id)
        imported_ids = [x.get("id") for x in after if x.get("id") not in before_ids]
        _v36_update_source_job(project_id, job_id, stage="正在分类训练/评测/试验集", progress=82)
        split_counts = _v36_apply_split_policy(project_id, imported_ids, payload.get("split_policy") or "annotated_train_unannotated_test", float(payload.get("train_ratio") or 0.8), float(payload.get("val_ratio") or 0.2), float(payload.get("test_ratio") or 0.0))
        report["labels"] = get_project(project_id).get("labels", [])
        report["split_counts"] = split_counts
        report["imported_ids"] = imported_ids
        _v36_update_source_job(project_id, job_id, status="done", status_text="已完成", stage="导入完成", progress=100, report=report, imported_images=report.get("imported_images", 0), annotated_images=report.get("annotated_images", 0), boxes=report.get("boxes", 0), split_counts=split_counts, finished_at=now_iso())
    except Exception as e:
        _v36_update_source_job(project_id, job_id, status="failed", status_text="失败", stage="导入失败", progress=100, error=str(e), finished_at=now_iso())
    finally:
        shutil.rmtree(job_dir / "work", ignore_errors=True)


app.include_router(create_material_ingestion_router_3(_material_ingestion_service))


def v36_scan_source_import(project_id: str, dataset_id: str, payload: V36SourceImportScanReq):
    return _material_ingestion_service().v36_scan_source_import(project_id, dataset_id, payload)


def v36_list_source_import_jobs(project_id: str, dataset_id: str):
    return _material_ingestion_service().v36_list_source_import_jobs(project_id, dataset_id)


def v36_start_source_import_job(project_id: str, dataset_id: str, payload: V36SourceImportStartReq):
    return _material_ingestion_service().v36_start_source_import_job(project_id, dataset_id, payload)

# ============================================================
# v39: 部署转换中心（真实工具链）
# - 训练/导出与部署编译分离
# - 支持 ONNX / Paddle Inference / TensorRT / SOPHGO BMODEL / Ascend OM
# - 转换工具不存在时明确阻断，不模拟生成
# - 支持本机资源与 remote_deploy_server 远程转换资源
# ============================================================
import threading

DEPLOY_RESOURCES_FILE = DATA_DIR / "deploy_resources.json"
if not DEPLOY_RESOURCES_FILE.exists():
    DEPLOY_RESOURCES_FILE.write_text("[]", encoding="utf-8")
_DEPLOY_RESOURCES_WRITE_LOCK = FileLock(str(DEPLOY_RESOURCES_FILE) + ".lock", timeout=30)
DEPLOY_PROCESS_REGISTRY: Dict[str, subprocess.Popen] = {}
DEPLOY_REMOTE_THREADS: Dict[str, threading.Thread] = {}


def deploy_root(project_id: str) -> Path:
    get_project(project_id)
    root = project_dir(project_id) / "deployment"
    for d in ["jobs", "artifacts", "tmp"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    return root


def _deploy_which(*candidates: str) -> str:
    for c in candidates:
        if not c:
            continue
        try:
            p = Path(str(c))
            if p.exists() and p.is_file():
                return str(p)
        except Exception:
            pass
        found = shutil.which(str(c))
        if found:
            return found
    return ""


def _deploy_cmd_version(cmd: str) -> str:
    if not cmd:
        return ""
    for args in ([cmd, "--version"], [cmd, "-v"], [cmd, "--help"]):
        try:
            cp = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=8)
            txt = (cp.stdout or cp.stderr or "").strip().splitlines()
            if txt:
                return txt[0][:240]
        except Exception:
            pass
    return ""


def _deploy_ultra_info(py: str) -> Dict[str, Any]:
    if not py or not Path(py).exists():
        return {"ok": False, "error": "Python 不存在"}
    try:
        cp = subprocess.run([py, "-c", "import ultralytics,json;print(json.dumps({'version':ultralytics.__version__,'path':ultralytics.__file__},ensure_ascii=False))"], capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=15)
        if cp.returncode != 0:
            return {"ok": False, "error": (cp.stdout or cp.stderr or "无法导入 ultralytics")[-1200:]}
        return {"ok": True, **json.loads((cp.stdout or "{}").splitlines()[-1])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _deploy_paddle_info(py: str) -> Dict[str, Any]:
    if not py or not Path(py).exists():
        return {"ok": False, "error": "Python 不存在"}
    try:
        cp = subprocess.run([py, "-c", "import paddle,json;print(json.dumps({'version':paddle.__version__,'device':paddle.device.get_device()},ensure_ascii=False))"], capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=15)
        if cp.returncode != 0:
            return {"ok": False, "error": (cp.stdout or cp.stderr or "无法导入 paddle")[-1200:]}
        return {"ok": True, **json.loads((cp.stdout or "{}").splitlines()[-1])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_DEPLOY_BUILTIN_RESOURCE_CACHE = ResourceCache(ttl_seconds=300)


def _scan_builtin_deploy_resources() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    ultra = get_active_ultralytics_env() or {}
    upy = str(ultra.get("python_path") or "")
    ui = _deploy_ultra_info(upy) if upy else {"ok": False}
    rows.append({
        "id": "builtin_ultralytics", "name": "Ultralytics 导出环境", "kind": "ultralytics", "mode": "local", "builtin": True,
        "python_path": upy, "status": "ready" if ui.get("ok") else "missing", "version": ui.get("version", ""),
        "targets": ["onnx"] if ui.get("ok") else [], "message": "可将 .pt 真实导出为 ONNX" if ui.get("ok") else "请先在训练资源启用 Ultralytics 环境",
        "last_checked_at": now_iso(),
    })
    penv = get_active_paddle_env() or {}
    ppy = str(penv.get("python_path") or "")
    pd_dir = str(penv.get("paddledet_dir") or "")
    pi = _deploy_paddle_info(ppy) if ppy else {"ok": False}
    pd_ok = bool(pi.get("ok") and pd_dir and (Path(pd_dir) / "tools" / "export_model.py").exists())
    p2o = _deploy_which(str(Path(ppy).parent / "paddle2onnx.exe") if ppy else "", "paddle2onnx")
    rows.append({
        "id": "builtin_paddle", "name": "PaddleDetection 导出环境", "kind": "paddle", "mode": "local", "builtin": True,
        "python_path": ppy, "paddledet_dir": pd_dir, "paddle2onnx_path": p2o,
        "status": "ready" if pd_ok else "missing", "version": pi.get("version", ""),
        "targets": (["paddle_inference"] + (["onnx"] if p2o else [])) if pd_ok else [],
        "message": "可将 .pdparams 导出为 Paddle Inference" + ("，并可转 ONNX" if p2o else "") if pd_ok else "请先在训练资源配置 PaddleDetection",
        "last_checked_at": now_iso(),
    })
    return rows


def _builtin_deploy_resource_summary() -> List[Dict[str, Any]]:
    """Return a cheap status snapshot while optional SDK imports run in background."""
    ultra = read_json(ULTRALYTICS_ENV_FILE, {})
    ultra = ultra if isinstance(ultra, dict) else {}
    upy = str(ultra.get("python_path") or sys.executable)
    ultra_path_ok = bool(upy and Path(upy).exists())
    ultra_verified = bool(ultra.get("version") and (ultra.get("package_path") or ultra.get("updated_at")))
    rows: List[Dict[str, Any]] = [{
        "id": "builtin_ultralytics",
        "name": "Ultralytics 导出环境",
        "kind": "ultralytics",
        "mode": "local",
        "builtin": True,
        "python_path": upy,
        "status": "ready" if ultra_verified else ("unchecked" if ultra_path_ok else "missing"),
        "version": str(ultra.get("version") or ""),
        "targets": ["onnx"] if ultra_verified else [],
        "message": "可将 .pt 真实导出为 ONNX" if ultra_verified else ("正在后台检测 Ultralytics 导出环境" if ultra_path_ok else "请先配置可用的 Ultralytics Python"),
    }]
    paddle = read_json(PADDLE_ENV_FILE, {})
    paddle = paddle if isinstance(paddle, dict) else {}
    ppy = str(paddle.get("python_path") or "")
    pd_dir = str(paddle.get("paddledet_dir") or "")
    paddle_configured = bool(ppy and Path(ppy).exists() and pd_dir and Path(pd_dir).exists())
    rows.append({
        "id": "builtin_paddle",
        "name": "PaddleDetection 导出环境",
        "kind": "paddle",
        "mode": "local",
        "builtin": True,
        "python_path": ppy,
        "paddledet_dir": pd_dir,
        "paddle2onnx_path": str(paddle.get("paddle2onnx_path") or ""),
        "status": "unchecked" if paddle_configured else "missing",
        "version": "",
        "targets": [],
        "message": "正在后台检测 PaddleDetection 导出环境" if paddle_configured else "请先在训练资源配置 PaddleDetection",
    })
    return rows


def _builtin_deploy_resources(force: bool = False) -> List[Dict[str, Any]]:
    """Return resource status without blocking the request on SDK imports."""
    if force:
        return _DEPLOY_BUILTIN_RESOURCE_CACHE.get_or_refresh(_scan_builtin_deploy_resources)["items"]
    snapshot = _DEPLOY_BUILTIN_RESOURCE_CACHE.snapshot()
    if snapshot["items"] and not snapshot["stale"]:
        return snapshot["items"]
    _DEPLOY_BUILTIN_RESOURCE_CACHE.refresh_in_background(_scan_builtin_deploy_resources)
    return snapshot["items"] or _builtin_deploy_resource_summary()


def _builtin_deploy_resource_cache_meta() -> Dict[str, Any]:
    snapshot = _DEPLOY_BUILTIN_RESOURCE_CACHE.snapshot()
    return {
        "stale": bool(snapshot.get("stale")),
        "refreshing": bool(snapshot.get("refreshing")),
        "updated_at": snapshot.get("updated_at") or "",
        "age_seconds": snapshot.get("age_seconds"),
        "error": snapshot.get("error") or "",
    }


def _load_saved_deploy_resources() -> List[Dict[str, Any]]:
    data = read_json(DEPLOY_RESOURCES_FILE, [])
    items = data if isinstance(data, list) else []
    if any(item.get("api_key") for item in items):
        # Legacy inline-secret migration is also a write operation. Serialize
        # it with resource edits and re-read under the lock so it cannot
        # overwrite a newer SDK result or configuration from another worker.
        with _DEPLOY_RESOURCES_WRITE_LOCK:
            data = read_json(DEPLOY_RESOURCES_FILE, [])
            items = data if isinstance(data, list) else []
            changed = False
            for item in items:
                legacy = str(item.pop("api_key", "") or "")
                if legacy:
                    reference = str(item.get("secret_ref") or secret_ref("deploy-resource", str(item.get("id") or uuid.uuid4().hex[:12])))
                    _v35_secret_store().set(reference, legacy)
                    item["secret_ref"] = reference
                    changed = True
            if changed:
                _save_deploy_resources(items)
    for item in items:
        item.pop("api_key", None)
    return items


def _save_deploy_resources(items: List[Dict[str, Any]]):
    # Readers may run in another Web worker while a detector writes. Keep the
    # existing JSON owner, but replace its bytes atomically instead of exposing
    # a partially truncated file.
    atomic_write_json(DEPLOY_RESOURCES_FILE, items)


def _deploy_resource_runtime(item: Dict[str, Any]) -> Dict[str, Any]:
    runtime = dict(item)
    reference = str(item.get("secret_ref") or "")
    runtime["api_key"] = _v35_secret_store().get(reference) if reference else ""
    return runtime


def _deploy_resource_public(item: Dict[str, Any]) -> Dict[str, Any]:
    public = dict(item)
    public.pop("api_key", None)
    # Internal worker ownership/PID is never part of the public capability
    # contract. The queryable detection.run_id and state are sufficient.
    public.pop("detection_run", None)
    reference = str(public.pop("secret_ref", "") or "")
    masked = _v35_secret_store().masked(reference) if reference else ""
    public["has_api_key"] = bool(masked)
    public["api_key_masked"] = masked
    return public


def _detect_local_deploy_resource(item: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(item.get("kind") or "").lower()
    item = dict(item)
    item["last_checked_at"] = now_iso()
    item["targets"] = []
    item["status"] = "missing"
    if kind == "tensorrt":
        root = Path(str(item.get("tool_root") or "")) if item.get("tool_root") else None
        trt = _deploy_which(str(item.get("trtexec_path") or ""), str(root / "bin" / "trtexec") if root else "", "trtexec")
        item["trtexec_path"] = trt
        if trt:
            item.update(status="ready", targets=["tensorrt"], version=_deploy_cmd_version(trt), message="TensorRT trtexec 可用；FP32/FP16 可直接编译")
        else:
            item["message"] = "未检测到 trtexec"
    elif kind == "sophon":
        from platform_core.sophon_runtime import probe_sophon_toolchain
        probe = probe_sophon_toolchain(item)
        tools = probe.get("tools") or {}
        item.update(
            model_transform_path=tools.get("model_transform", ""),
            model_deploy_path=tools.get("model_deploy", ""),
            run_calibration_path=tools.get("run_calibration", ""),
            model_tool_path=tools.get("model_tool", ""),
            supported_chips=list(probe.get("supported_chips") or []),
            supported_precisions=list(probe.get("supported_precisions") or []),
            version=probe.get("version", ""), sophon_probe=probe,
            error_code=probe.get("error_code", ""),
        )
        if probe.get("available"):
            item.update(status="ready", targets=["sophon"], message="TPU-MLIR CLI probe passed")
        else:
            item["message"] = probe.get("error") or "TPU-MLIR unavailable"
    elif kind == "ascend":
        root = Path(str(item.get("tool_root") or "")) if item.get("tool_root") else None
        ascend_home = str(os.environ.get("ASCEND_HOME_PATH") or os.environ.get("ASCEND_TOOLKIT_HOME") or "").strip()
        home = Path(ascend_home) if ascend_home else None
        candidates = [str(item.get("atc_path") or "")]
        if root:
            candidates += [str(root / "bin" / "atc"), str(root / "bin" / "atc.bin")]
        if home:
            candidates += [str(home / "bin" / "atc"), str(home / "bin" / "atc.bin")]
        candidates += ["atc", "atc.bin"]
        atc = _deploy_which(*candidates)
        item["atc_path"] = atc
        env_candidates = [str(item.get("env_script") or "")]
        if root:
            env_candidates += [str(root / "set_env.sh"), str(root.parent / "set_env.sh")]
        if home:
            env_candidates += [str(home / "set_env.sh"), str(home.parent / "set_env.sh")]
        env_script = next((x for x in env_candidates if x and Path(x).exists()), str(item.get("env_script") or ""))
        item["env_script"] = env_script
        nsmi = _deploy_which("npu-smi")
        item["npu_smi_path"] = nsmi
        item["cann_home"] = ascend_home or (str(root) if root else "")
        socs=[]
        device_text=""
        if nsmi:
            try:
                cp = subprocess.run([nsmi, "info"], capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=10)
                device_text = (cp.stdout or cp.stderr or "")[-5000:]
                # Different npu-smi releases show names in slightly different forms. Keep only concrete processor names.
                for m in re.findall(r"(?:Chip\s*Name\s*[:：]?\s*|Name\s*[:：]\s*)(?:Ascend\s*)?([0-9A-Za-z_-]+)", device_text, re.I):
                    v = "Ascend" + m.replace(" ", "")
                    if re.search(r"310|910", v, re.I) and v not in socs:
                        socs.append(v)
                for m in re.findall(r"Ascend\s*([0-9]{3,4}[A-Za-z0-9_-]*)", device_text, re.I):
                    v="Ascend"+m.replace(" ","")
                    if v not in socs:socs.append(v)
            except Exception:
                pass
        item["device_info"] = device_text
        item["detected_soc_versions"] = socs
        item["atlas_products"] = ["Atlas 300I Pro", "Atlas 300V", "Atlas 300V Pro", "Atlas 300I Duo", "Atlas 200I SoC A1", "Atlas A2 / 其他"]
        if atc:
            ver=_deploy_cmd_version(atc)
            msg="CANN ATC 可用，可真实编译 Atlas/Ascend OM"
            if socs: msg += "；检测到 " + "、".join(socs[:3])
            elif not nsmi: msg += "；转换机无 NPU 也可转换，部署 SoC 需手工指定"
            item.update(status="ready", targets=["ascend"], version=ver, message=msg, conversion_ready=True, hardware_detected=bool(nsmi and device_text))
        else:
            item.update(message="未检测到 CANN ATC；请安装 CANN Toolkit 或配置 ATC 路径", conversion_ready=False, hardware_detected=bool(nsmi and device_text))
    elif kind == "ultralytics":
        py = str(item.get("python_path") or sys.executable)
        info = _deploy_ultra_info(py)
        item.update(status="ready" if info.get("ok") else "missing", targets=["onnx"] if info.get("ok") else [], version=info.get("version", ""), message="Ultralytics 导出可用" if info.get("ok") else info.get("error", "Ultralytics 不可用"))
    elif kind == "paddle":
        py = str(item.get("python_path") or sys.executable)
        info = _deploy_paddle_info(py)
        pd_raw = str(item.get("paddledet_dir") or "").strip()
        pd = Path(pd_raw) if pd_raw else None
        p2o = _deploy_which(str(item.get("paddle2onnx_path") or ""), "paddle2onnx")
        ok = bool(info.get("ok") and pd and pd.exists() and (pd / "tools" / "export_model.py").exists())
        item.update(status="ready" if ok else "missing", targets=(['paddle_inference'] + (['onnx'] if p2o else [])) if ok else [], version=info.get("version", ""), paddle2onnx_path=p2o, message="PaddleDetection 导出可用" if ok else "PaddleDetection 导出环境不完整")
    else:
        item["message"] = "未知部署资源类型"
    return item


def _detect_remote_deploy_resource(item: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(item)
    base = str(item.get("base_url") or "").rstrip("/")
    if str(item.get("kind") or "").lower() == "sophon":
        item.update(targets=[], supported_chips=[], supported_precisions=[])
    item.pop("remote_health", None)
    if not base:
        item.update(status="missing", targets=[], message="未填写远程服务地址", last_checked_at=now_iso())
        return item
    try:
        r = requests.get(base + "/api/deploy/health", headers={"X-API-Key": str(item.get("api_key") or "")}, timeout=12)
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        item.update(status="ready", targets=data.get("targets", []), version=data.get("version", ""), message="远程部署转换服务可用", remote_health=data, last_checked_at=now_iso())
        if str(item.get("kind") or "").lower() == "sophon":
            probe = (data.get("tools") or {}).get("sophon") or {}
            from platform_core.sophon_runtime import sophon_chip_capabilities
            capabilities=sophon_chip_capabilities(probe)
            item["sophon_probe"]={**probe,"chip_capabilities":capabilities}
            item["supported_chips"] = sorted(capabilities)
            item["supported_precisions"] = sorted({p for c in capabilities.values() for p in c["precisions"]})
            item["version"] = str(probe.get("version") or "")
            if not probe.get("available") or "sophon" not in item["targets"] or not item["supported_chips"] or not item["supported_precisions"]:
                item.update(status="missing", targets=[], supported_chips=[], supported_precisions=[], message=probe.get("error") or "TPU-MLIR remote probe unavailable")
            else:
                item["message"] = "远程算能资源可用：" + " / ".join(chip.upper() for chip in item["supported_chips"]) + " · " + "/".join(item["supported_precisions"])
        if str(item.get("kind") or "").lower() == "rockchip":
            item["supported_chips"] = list(data.get("supported_chips") or [])
    except Exception as e:
        item.update(status="missing", targets=[], supported_chips=[], message=f"远程资源不可用：{e}", last_checked_at=now_iso())
    return item


def _detect_agent_deploy_resource(item: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(item)
    kind = str(item.get("kind") or "").strip().lower()
    if kind not in {"rockchip", "onnx", "ultralytics", "paddle"}:
        item.update(
            status="missing",
            targets=[],
            message="服务节点 Agent 当前只开放 ONNX 与瑞芯微 RKNN 转换",
            agent_nodes=[],
            supported_chips=[],
            supported_precisions=[],
            last_checked_at=now_iso(),
        )
        return item

    required_capability = "conversion.rknn" if kind == "rockchip" else "conversion"
    target = "rockchip" if kind == "rockchip" else "onnx"
    nodes = ServiceNodeRepository(shared_task_repository()).list_public()
    eligible = []
    supported_chips = set()
    supported_precisions = set()
    for node in nodes:
        if (
            str(node.get("connection_mode") or "") != "agent"
            or not bool(node.get("online"))
            or required_capability not in set(node.get("effective_capabilities") or [])
        ):
            continue
        node_runtime = node.get("runtime")
        node_runtime = dict(node_runtime) if isinstance(node_runtime, Mapping) else {}
        node_chips = []
        node_precisions = ["fp32"] if kind != "rockchip" else []
        if kind == "rockchip":
            rknn = node_runtime.get("rknn_toolkit2")
            rknn = dict(rknn) if isinstance(rknn, Mapping) else {}
            node_chips = [
                str(chip).strip().lower()
                for chip in (rknn.get("supported_chips") or [])
                if str(chip).strip().lower() in SUPPORTED_PORTABLE_RKNN_CHIPS
            ]
            if not bool(rknn.get("available")) or not node_chips:
                continue
            node_precisions = ["fp16", "int8"]
            supported_chips.update(node_chips)
        supported_precisions.update(node_precisions)
        node_row = {
            "node_id": str(node.get("node_id") or ""),
            "display_name": str(node.get("display_name") or ""),
            "build_id": str(node.get("build_id") or ""),
            "capability": required_capability,
            "supported_chips": sorted(set(node_chips)),
        }
        if kind == "rockchip":
            node_row["supported_precisions"] = sorted(set(node_precisions))
        eligible.append(node_row)

    if eligible:
        detail = (
            f"检测到 {len(eligible)} 个在线 Agent 可执行 RKNN 转换"
            if kind == "rockchip"
            else f"检测到 {len(eligible)} 个在线 Agent 可执行 ONNX 转换"
        )
        item.update(
            status="ready",
            targets=[target],
            message=detail,
            agent_nodes=eligible,
            supported_chips=sorted(supported_chips),
            last_checked_at=now_iso(),
        )
        if kind == "rockchip":
            item["supported_precisions"] = sorted(supported_precisions)
        else:
            item.pop("supported_precisions", None)
    else:
        detail = (
            "没有在线且已授权 conversion.rknn、并通过 RKNN-Toolkit2 探测的 Agent 节点"
            if kind == "rockchip"
            else "没有在线且已授权 conversion 能力的 Agent 节点"
        )
        item.update(
            status="missing",
            targets=[],
            message=detail,
            agent_nodes=[],
            supported_chips=[],
            last_checked_at=now_iso(),
        )
        if kind == "rockchip":
            item["supported_precisions"] = []
        else:
            item.pop("supported_precisions", None)
    return item


from platform_core.conversion_management_contracts import DeployResourceReq


app.include_router(create_conversion_management_router_2(_conversion_management_service))


def v39_list_deploy_resources(detect_missing: bool=True):
    return _conversion_management_service().v39_list_deploy_resources(detect_missing=detect_missing)


def v39_create_deploy_resource(payload: DeployResourceReq):
    return _conversion_management_service().v39_create_deploy_resource(payload)


def v39_update_deploy_resource(resource_id: str, payload: DeployResourceReq):
    return _conversion_management_service().v39_update_deploy_resource(resource_id, payload)


def v39_delete_deploy_resource(resource_id: str):
    return _conversion_management_service().v39_delete_deploy_resource(resource_id)


def v39_detect_deploy_resource(resource_id: str, force: bool=True):
    return _conversion_management_service().v39_detect_deploy_resource(resource_id, force)


def _finish_background_conversion_detection(resource_id: str, run_id: str, error=None):
    """Finalize the resource's own durable observation with a run-ID CAS."""
    from platform_core.conversion_resource_detection import (
        resource_configuration_key, environment_fingerprint,
    )
    with _DEPLOY_RESOURCES_WRITE_LOCK:
        items = _load_saved_deploy_resources()
        current = next((row for row in items if row.get('id') == resource_id), None)
        if current is None:
            return
        running = current.get('detection_run') or {}
        if running.get('id') != run_id or running.get('config_key') != resource_configuration_key(current):
            return  # Edited resource, deleted/replaced run, or abandoned worker.
        current.pop('detection_run', None)
        if error is not None:
            current.update(status='error', targets=[], supported_chips=[],
                supported_precisions=[], detection_error=str(error)[:1200],
                last_checked_at=now_iso(),
                detection_config_key=resource_configuration_key(current),
                detection_environment_fingerprint=environment_fingerprint(current))
        _save_deploy_resources(items)


def _run_background_conversion_detection(resource_id: str, run_id: str):
    error = None
    try:
        v39_detect_deploy_resource(resource_id)
    except Exception as exc:
        error = exc
    finally:
        _finish_background_conversion_detection(resource_id, run_id, error)


def v39_start_deploy_resource_detection(resource_id: str):
    return _conversion_management_service().v39_start_deploy_resource_detection(resource_id)


def v39_conversion_resource_detection_status(resource_id: str):
    return _conversion_management_service().v39_conversion_resource_detection_status(resource_id)


def _inspect_conversion_resource(resource, *, force=False):
    from platform_core.conversion_resource_detection import detect
    mode = str(resource.get("mode") or "local").lower()
    detector = (_detect_remote_deploy_resource if mode=="remote" else
        _detect_agent_deploy_resource if mode=="agent" else _detect_local_deploy_resource)
    return detect(resource, detector, force=force)


def v39_detect_local_deploy_resources():
    return _conversion_management_service().v39_detect_local_deploy_resources()


def _deploy_source_models(project_id: str) -> List[Dict[str, Any]]:
    return _conversion_management_service()._deploy_source_models(project_id)


def _deploy_selected_algorithm_version(project_id: str, algorithm_id: str, version_id: str):
    return _conversion_management_service()._deploy_selected_algorithm_version(project_id, algorithm_id, version_id)


def v39_deploy_source_models(project_id: str):
    return _conversion_management_service().v39_deploy_source_models(project_id)


@performance_stage("conversion.source_lookup")
def _resolve_deploy_source(project_id: str, source_id: str) -> Dict[str, Any]:
    row = None
    if source_id.startswith("version::"):
        identity = source_id.split("::")
        if len(identity) == 3 and identity[1] and identity[2]:
            algorithm, version = _deploy_selected_algorithm_version(project_id, identity[1], identity[2])
            if algorithm and version:
                path = Path(str(version.get("stored_path") or ""))
                current = str(version.get("id") or "") == str(algorithm.get("current_version_id") or "")
                row = {"id": source_id, "kind": "algorithm_version",
                       "name": version.get("model_name") or path.name, "path": str(path),
                       "type": path.suffix.lower().lstrip("."),
                       "framework": (version.get("report") or {}).get("framework", ""),
                       "job_id": version.get("job_id", ""), "config_path": "",
                       "size_mb": version.get("size_mb", 0), "algorithm_id": algorithm.get("id"),
                       "algorithm_name": algorithm.get("name"), "version_id": version.get("id"),
                       "version_name": version.get("version_name"), "is_current_version": current,
                       "label": f"{algorithm.get('name')} / {version.get('version_name')}{'（当前）' if current else ''} / {path.name}",
                       # Request-local only; do not persist in job source_meta.
                       "_resolved_version": version}
    else:
        # Legacy free-model identities still use their original provenance
        # projection; a version identity never takes this expensive path.
        row = next((x for x in _deploy_source_models(project_id) if x.get("id") == source_id), None)
    if not row: raise HTTPException(status_code=404, detail="源模型不存在")
    p=Path(str(row.get("path") or ""))
    if not p.exists(): raise HTTPException(status_code=404, detail=f"源模型文件不存在：{p}")
    if not row.get("config_path") and row.get("job_id"):
        jf=project_dir(project_id)/"jobs"/str(row.get("job_id"))/"job.json"
        job=read_json(jf,{})
        row["config_path"] = job.get("generated_config_path") or job.get("algorithm_config_path") or ""
    return row


@performance_stage("conversion.resource_read")
def _deploy_resource_by_id(resource_id: str) -> Dict[str, Any]:
    for r in (_DEPLOY_BUILTIN_RESOURCE_CACHE.snapshot()["items"] or _builtin_deploy_resource_summary()):
        if r.get("id") == resource_id: return r
    for r in _load_saved_deploy_resources():
        if r.get("id") == resource_id: return _deploy_resource_runtime(r)
    raise HTTPException(status_code=404, detail="部署资源不存在")


def _deploy_job_dir(project_id: str, job_id: str) -> Path:
    return _conversion_management_service()._deploy_job_dir(project_id, job_id)


def _deploy_prepare_calibration(project_id: str, dataset_id: str, split: str, limit: int, dst: Path) -> int:
    return _conversion_management_service()._deploy_prepare_calibration(project_id, dataset_id, split, limit, dst)


from platform_core.conversion_management_contracts import DeployJobReq


from functools import lru_cache


@lru_cache(maxsize=4)
def _conversion_catalog_repository(data_dir):
    from platform_core.model_artifacts import ModelArtifactRepository
    return ModelArtifactRepository(data_dir)


from platform_core.deployment.catalog_api import create_conversion_catalog_router

_conversion_catalog_api_router = create_conversion_catalog_router(
    repository_provider=lambda: _conversion_catalog_repository(DATA_DIR),
    list_resources=lambda **kwargs: v39_list_deploy_resources(**kwargs),
    detect_resource=lambda identity: v39_detect_deploy_resource(identity),
)
app.include_router(_conversion_catalog_api_router)


from functools import lru_cache as _conversion_lru_cache


@_conversion_lru_cache(maxsize=64)
def _conversion_onnx_shape_preview(path, file_signature):
    # Preview only: admission passes preview=False and always reopens the source.
    import onnx
    model=onnx.load(str(path),load_external_data=False)
    initializers={value.name for value in model.graph.initializer}
    return tuple(tuple(d.dim_value for d in item.type.tensor_type.shape.dim)
        for item in model.graph.input if item.name not in initializers)


@performance_stage("conversion.contract_resolution")
def _conversion_contract_for_source(project_id, source, resource, params, target, *, preview=False):
    from platform_core.compute_platform_catalog import (resolve_conversion_contract,
        resolve_chip_capability, conversion_templates, conversion_chip_status_label)
    catalog=_conversion_catalog_repository(DATA_DIR).conversion_catalog()
    vendor_id=str(params.get("local_vendor_id") or "")
    chip_id=str(params.get("local_chip_id") or "")
    # Existing API clients may use SDK code only, but still require one enabled local identity.
    if not vendor_id and not chip_id:
        template_ids={t["id"] for t in conversion_templates() if t.get("adapter")==target}
        vendors={v["id"] for v in catalog["vendors"] if v.get("enabled",True) and v.get("template_id") in template_ids}
        candidates=[c for c in catalog["chips"] if c["vendor_id"] in vendors and c.get("enabled",True)
                    and c["sdk_code"].lower()==str(params.get("chip") or params.get("soc_version") or "").lower()]
        if len(candidates)==1: vendor_id,chip_id=candidates[0]["vendor_id"],candidates[0]["id"]
    version=source.get("_resolved_version") or {}
    if not version and source.get("algorithm_id") and source.get("version_id"):
        # Legacy in-process callers can supply an unfrozen source projection.
        # The real resolve endpoint uses _resolved_version from the indexed
        # lookup above and does not enter this compatibility path.
        algorithm=next((a for a in list_algorithms_internal(project_id)
                        if str(a.get("id"))==str(source["algorithm_id"])),{})
        version=next((v for v in algorithm.get("versions",[])
                      if str(v.get("id"))==str(source["version_id"])),{})
    onnx_shapes=None
    shape_from_onnx=False
    path=Path(str(source.get("path") or ""))
    if path.suffix.lower()==".onnx" and path.is_file():
        try:
            import onnx
            if preview:
                stat=path.stat()
                onnx_shapes=[list(shape) for shape in _conversion_onnx_shape_preview(str(path.resolve()),
                    (stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,stat.st_ino))]
            else:
                model=onnx.load(str(path),load_external_data=False)
                onnx_shapes=[[d.dim_value for d in item.type.tensor_type.shape.dim] for item in model.graph.input
                             if item.name not in {i.name for i in model.graph.initializer}]
            if not any(k in params for k in ("input_height","input_width","input_size")) and len(onnx_shapes)==1 and len(onnx_shapes[0])==4:
                params={**params,"input_height":onnx_shapes[0][2],"input_width":onnx_shapes[0][3]}
                shape_from_onnx=True
        except Exception as error:
            return {"ready":False,"status":"not_convertible","errors":["无法核验ONNX输入合同："+str(error)],"params":{},"allowed_precisions":[],"chip_options":[]}
    training_job=_version_deploy_training_job(project_id,version)
    result=resolve_conversion_contract(catalog,vendor_id=vendor_id,chip_id=chip_id,resource=resource,version=version,params=params,training_job=training_job)
    result["chip_options"]=[]
    for entry in catalog["chips"]:
        if entry["vendor_id"]!=vendor_id:
            continue
        capability=resolve_chip_capability(catalog,vendor_id=vendor_id,chip_id=entry["id"],resource=resource)
        result["chip_options"].append({"id":entry["id"],"name":entry["name"],"enabled":entry.get("enabled",True),
            "status":capability["status"],"status_label":conversion_chip_status_label(capability["status"]),
            "reason":"；".join(capability["errors"])})
    if result["ready"] and result["template"].get("adapter")!=target:
        result.update(ready=False,status="not_convertible",errors=["厂商模板与请求target不一致"])
    if result["ready"]:
        from platform_core.model_metadata import model_metadata
        result["source_metadata"]=model_metadata(DATA_DIR,version)
        if onnx_shapes is not None:
            from platform_core.conversion import conversion_input_shape
            height,width=conversion_input_shape(result["params"])
            result["source_input_shapes"]=onnx_shapes
            if onnx_shapes!=[[int(result["params"].get("batch") or 1),3,height,width]]:
                result.update(ready=False,status="not_convertible",errors=["现有ONNX真实输入Shape与所选参数不一致，需重新导出"])
            elif shape_from_onnx:
                result["parameter_sources"]["input_shape"]="真实ONNX输入Shape"
    return result


app.include_router(create_conversion_management_router_3(_conversion_management_service))


def v39_resolve_conversion(project_id: str, payload: DeployJobReq):
    return _conversion_management_service().v39_resolve_conversion(project_id, payload)




def _write_deploy_job(project_id: str, job: Dict[str, Any]):
    return _conversion_management_service()._write_deploy_job(project_id, job)


def _read_deploy_job(project_id: str, job_id: str) -> Dict[str, Any]:
    return _conversion_management_service()._read_deploy_job(project_id, job_id)


def _overlay_durable_deploy_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return _conversion_management_service()._overlay_durable_deploy_job(job)


def _safe_extract_zip(zf: zipfile.ZipFile, dst: Path) -> None:
    return _conversion_management_service()._safe_extract_zip(zf, dst)


def _sync_remote_deploy_job(project_id: str, job_id: str):
    return _conversion_management_service()._sync_remote_deploy_job(project_id, job_id)


def v39_create_deploy_job(project_id: str, payload: DeployJobReq):
    return _conversion_management_service().v39_create_deploy_job(project_id, payload)


def _deploy_request_job_id(project_id: str, request_id: str) -> str:
    return _conversion_management_service()._deploy_request_job_id(project_id, request_id)


def _deploy_request_identity(payload: DeployJobReq) -> str:
    return _conversion_management_service()._deploy_request_identity(payload)


def v39_conversion_job_by_request(project_id: str, request_id: str):
    return _conversion_management_service().v39_conversion_job_by_request(project_id, request_id)


def _v39_create_deploy_job_with_version_fence(project_id: str, payload: DeployJobReq):
    return _conversion_management_service()._v39_create_deploy_job_with_version_fence(project_id, payload)


@performance_stage('conversion.remote_online_admission')
def _remote_conversion_resource_online(resource):
    """Check service and config identity without re-running the SDK detector.

    An older remote server lacks /ping, so only that compatibility path calls
    the old costly /health. Once remote server is updated, every conversion
    admission uses the scan-free authenticated ping.
    """
    base = str(resource.get('base_url') or '').rstrip('/')
    if not base:
        raise HTTPException(status_code=409, detail='远程转换资源地址缺失')
    headers = {'X-API-Key':str(resource.get('api_key') or '')}
    try:
        response = requests.get(base+'/api/deploy/ping', headers=headers, timeout=(3,5))
        if response.status_code == 404:
            response = requests.get(base+'/api/deploy/health', headers=headers, timeout=(3,12))
        response.raise_for_status()
        health = response.json()
        if not isinstance(health,dict) or health.get('ok') is not True or health.get('server')!='mc-deploy-server':
            raise ValueError('服务身份响应无效')
    except (requests.RequestException, ValueError) as error:
        raise HTTPException(status_code=503, detail='远程转换服务在线/鉴权检查失败，请检查服务或网络后重试') from error
    previous = resource.get('remote_health') or {}
    if previous.get('config_revision') and health.get('config_revision') and previous['config_revision']!=health['config_revision']:
        raise HTTPException(status_code=409, detail='远程转换服务配置已变化，需重新检测SDK能力')
    if previous.get('version') and health.get('version') and previous['version']!=health['version']:
        raise HTTPException(status_code=409, detail='远程转换服务版本已变化，需重新检测SDK能力')


def _v39_create_deploy_job_under_version_fence(project_id: str, payload: DeployJobReq):
    return _conversion_management_service()._v39_create_deploy_job_under_version_fence(project_id, payload)


def _eligible_rknn_board_nodes(chip: str) -> list[dict[str, Any]]:
    return _conversion_management_service()._eligible_rknn_board_nodes(chip)


def _rknn_hardware_validation_context(project_id: str, job_id: str) -> dict[str, Any]:
    return _conversion_management_service()._rknn_hardware_validation_context(project_id, job_id)


def v39_rknn_hardware_test_preflight(project_id: str, job_id: str):
    return _conversion_management_service().v39_rknn_hardware_test_preflight(project_id, job_id)


def _rknn_hardware_acceptance_report(project_id: str, job_id: str) -> dict[str, Any]:
    return _conversion_management_service()._rknn_hardware_acceptance_report(project_id, job_id)


def v39_rknn_hardware_acceptance_report(project_id: str, job_id: str, download: bool=Query(False)):
    return _conversion_management_service().v39_rknn_hardware_acceptance_report(project_id, job_id, download)


async def v39_create_rknn_hardware_test(project_id: str, job_id: str, file: UploadFile=File(...)):
    return await _conversion_management_service().v39_create_rknn_hardware_test(project_id, job_id, file)


async def _v39_create_rknn_hardware_test_under_version_fence(project_id: str, job_id: str, file: UploadFile):
    return await _conversion_management_service()._v39_create_rknn_hardware_test_under_version_fence(project_id, job_id, file)


from platform_core.conversion_history import ConversionHistoryProjection
_CONVERSION_HISTORY_PROJECTION = ConversionHistoryProjection()


def _conversion_history_csc(job):
    return _conversion_management_service()._conversion_history_csc(job)


def _conversion_history_page(project_id, **query):
    return _conversion_management_service()._conversion_history_page(project_id, **query)


def v39_list_deploy_jobs(project_id: str):
    return _conversion_management_service().v39_list_deploy_jobs(project_id)


def _delivery_model_artifact_service() -> ModelArtifactService:
    return _conversion_management_service()._delivery_model_artifact_service()


def _model_artifact_quality_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return _conversion_management_service()._model_artifact_quality_row(row)


def _version_delivery_quality(project_id: str, algorithm_id: str, version_id: str) -> Dict[str, Any]:
    return _conversion_management_service()._version_delivery_quality(project_id, algorithm_id, version_id)


def _conversion_delivery_quality_projection(project_id: str, job: Mapping[str, Any]) -> Dict[str, Any]:
    return _conversion_management_service()._conversion_delivery_quality_projection(project_id, job)


def v39_get_deploy_job(project_id: str, job_id: str):
    return _conversion_management_service().v39_get_deploy_job(project_id, job_id)


def _numeric_conversion_dir(project_id: str, verification_id: str) -> Path:
    return _conversion_management_service()._numeric_conversion_dir(project_id, verification_id)


def _numeric_frozen_imgsz(params: dict) -> list:
    return _conversion_management_service()._numeric_frozen_imgsz(params)


def _numeric_conversion_artifact(job_dir: Path, manifest: dict, suffix: str, *, required: bool) -> tuple[Path | None, str]:
    return _conversion_management_service()._numeric_conversion_artifact(job_dir, manifest, suffix, required=required)


def _numeric_conversion_public(project_id: str, verification_id: str) -> dict:
    return _conversion_management_service()._numeric_conversion_public(project_id, verification_id)


def v39_list_numeric_validations(project_id: str, job_id: str):
    return _conversion_management_service().v39_list_numeric_validations(project_id, job_id)


def v39_get_numeric_validation(project_id: str, job_id: str, verification_id: str):
    return _conversion_management_service().v39_get_numeric_validation(project_id, job_id, verification_id)


def v39_create_numeric_validation(project_id: str, job_id: str, files: List[UploadFile]=File(...), request_id: str=Form(''), confidence: float=Form(0.25), nms_iou: float=Form(0.7)):
    return _conversion_management_service().v39_create_numeric_validation(project_id, job_id, files, request_id, confidence, nms_iou)


def v39_deploy_job_log(project_id: str, job_id: str):
    return _conversion_management_service().v39_deploy_job_log(project_id, job_id)


def v39_stop_deploy_job(project_id: str, job_id: str):
    return _conversion_management_service().v39_stop_deploy_job(project_id, job_id)


def v39_delete_deploy_job(project_id: str, job_id: str):
    return _conversion_management_service().v39_delete_deploy_job(project_id, job_id)


from platform_core.deployment.artifacts_api import (
    create_deploy_artifact_router,
    list_deploy_artifacts as _list_deploy_artifacts,
)


def v39_list_deploy_artifacts(project_id: str):
    """Compatibility query over the canonical artifact reader and file authority."""
    return _list_deploy_artifacts(
        project_id,
        list_jobs=lambda identity: v39_list_deploy_jobs(identity)["items"],
        resolve_business_file=_resolve_business_file,
    )


app.include_router(create_deploy_artifact_router(
    list_jobs=lambda project_id: v39_list_deploy_jobs(project_id)["items"],
    resolve_business_file=_resolve_business_file,
    business_file_response=_business_file_response,
))


app.include_router(create_conversion_management_router_4(_conversion_management_service))


def v39_download_deploy_package(project_id: str, job_id: str):
    return _conversion_management_service().v39_download_deploy_package(project_id, job_id)


# ============================================================
# v40: 组件检测中心
# - 真正检查 Python 包、训练框架、导出工具、芯片编译器与远程转换资源
# - 检测任务后台执行，前端显示真实进度
# ============================================================
COMPONENT_SCAN_DIR = DATA_DIR / "component_scans"
COMPONENT_SCAN_DIR.mkdir(parents=True, exist_ok=True)
COMPONENT_SCAN_THREADS: Dict[str, threading.Thread] = {}


def _v40_component_item(key: str, name: str, status: str, required: bool, version: str = "", path: str = "", detail: str = "", fix: str = "") -> Dict[str, Any]:
    return {"key": key, "name": name, "status": status, "required": required, "version": version, "path": path, "detail": detail, "fix": fix}


def _v40_python_module(py: str, module: str, required: bool = True, dist_name: str = "") -> Dict[str, Any]:
    py = str(py or sys.executable)
    if not Path(py).exists():
        return _v40_component_item(module, module, "missing", required, path=py, detail="Python 路径不存在", fix="配置正确的 Python 环境")
    code=("import importlib,json; m=importlib.import_module(%r); "
          "print(json.dumps({'version':getattr(m,'__version__',''),'path':getattr(m,'__file__','')},ensure_ascii=False))") % module
    try:
        cp=subprocess.run([py,"-c",code],capture_output=True,text=True,encoding="utf-8",errors="ignore",timeout=18)
        if cp.returncode==0:
            data=json.loads((cp.stdout or "{}").splitlines()[-1])
            return _v40_component_item(module, dist_name or module, "ready", required, version=str(data.get("version") or ""), path=str(data.get("path") or ""))
        return _v40_component_item(module, dist_name or module, "missing", required, detail=(cp.stderr or cp.stdout or "导入失败")[-800:], fix=f"在对应环境安装 {dist_name or module}")
    except Exception as e:
        return _v40_component_item(module, dist_name or module, "missing", required, detail=str(e), fix=f"检查 {dist_name or module} 安装")


def _v40_file_check(key: str, name: str, path: str, required: bool=True, fix: str="") -> Dict[str, Any]:
    p=Path(str(path or "")) if path else None
    ok=bool(p and p.exists())
    return _v40_component_item(key,name,"ready" if ok else "missing",required,path=str(p or ""),detail="已找到" if ok else "未找到",fix=fix if not ok else "")


def _v40_capability(name: str, keys: List[str], components: List[Dict[str, Any]], optional_keys: Optional[List[str]]=None) -> Dict[str, Any]:
    optional_keys=set(optional_keys or [])
    mp={x.get("key"):x for x in components}
    required=[mp[k] for k in keys if k in mp and k not in optional_keys]
    optional=[mp[k] for k in keys if k in mp and k in optional_keys]
    if required and all(x.get("status")=="ready" for x in required):
        status="ready"
    elif any(x.get("status")=="ready" for x in required):
        status="warning"
    else:
        status="missing"
    return {"name":name,"status":status,"required":keys,"optional":list(optional_keys),"ready":sum(1 for x in required+optional if x.get("status")=="ready"),"total":len(required)+len(optional)}


def _v40_scan_write(scan_id: str, data: Dict[str, Any]):
    write_json(COMPONENT_SCAN_DIR / f"{scan_id}.json", data)
    if data.get("status")=="done":
        write_json(COMPONENT_SCAN_DIR / "latest.json", data)


def _v40_run_component_scan(scan_id: str):
    jf=COMPONENT_SCAN_DIR/f"{scan_id}.json"
    scan=read_json(jf,{})
    components=[]
    def update(progress:int,stage:str):
        scan.update(status="running",progress=progress,stage=stage,updated_at=now_iso(),components=components)
        _v40_scan_write(scan_id,scan)
    try:
        update(4,"检查平台运行环境")
        pyver=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        components.append(_v40_component_item("python","Python >= 3.10","ready" if sys.version_info >= (3,10) else "missing",True,version=pyver,path=sys.executable,fix="安装 Python 3.10 或更高版本"))
        for mod,label in [("fastapi","FastAPI"),("uvicorn","Uvicorn"),("requests","Requests"),("yaml","PyYAML"),("PIL","Pillow")]:
            components.append(_v40_python_module(sys.executable,mod,True,label))
        update(14,"检查数据与视频组件")
        components.append(_v40_python_module(sys.executable,"cv2",True,"OpenCV"))

        update(25,"检查 Ultralytics 训练与 ONNX 导出")
        ultra=get_active_ultralytics_env() or {}
        upy=str(ultra.get("python_path") or "")
        if upy:
            u=_deploy_ultra_info(upy)
            components.append(_v40_component_item("ultralytics","Ultralytics","ready" if u.get("ok") else "missing",False,version=str(u.get("version") or ""),path=upy,detail=str(u.get("error") or ""),fix="到训练资源配置可用的 Ultralytics Python" if not u.get("ok") else ""))
            components.append(_v40_python_module(upy,"onnx",False,"ONNX"))
            components.append(_v40_python_module(upy,"onnxruntime",False,"ONNX Runtime"))
        else:
            components += [_v40_component_item("ultralytics","Ultralytics","missing",False,detail="未启用训练资源",fix="到训练资源检测并启用 Ultralytics"),_v40_component_item("onnx","ONNX","missing",False,fix="在 Ultralytics 环境安装 onnx"),_v40_component_item("onnxruntime","ONNX Runtime","missing",False,fix="在 Ultralytics 环境安装 onnxruntime")]

        update(40,"检查飞桨训练与推理导出")
        penv=get_active_paddle_env() or {}
        ppy=str(penv.get("python_path") or "")
        pdd=str(penv.get("paddledet_dir") or "")
        if ppy:
            pi=_deploy_paddle_info(ppy)
            components.append(_v40_component_item("paddle","PaddlePaddle","ready" if pi.get("ok") else "missing",False,version=str(pi.get("version") or ""),path=ppy,detail=str(pi.get("error") or ""),fix="到训练资源配置 Paddle 环境" if not pi.get("ok") else ""))
        else:
            components.append(_v40_component_item("paddle","PaddlePaddle","missing",False,detail="未启用飞桨环境",fix="到训练资源配置 Paddle 环境"))
        train_py=str(Path(pdd)/"tools"/"train.py") if pdd else ""
        export_py=str(Path(pdd)/"tools"/"export_model.py") if pdd else ""
        components.append(_v40_file_check("paddledet_train","PaddleDetection train.py",train_py,False,"配置完整 PaddleDetection 源码目录"))
        components.append(_v40_file_check("paddledet_export","PaddleDetection export_model.py",export_py,False,"配置完整 PaddleDetection 源码目录"))
        p2o=_deploy_which(str(Path(ppy).parent/"paddle2onnx.exe") if ppy else "","paddle2onnx")
        components.append(_v40_component_item("paddle2onnx","paddle2onnx","ready" if p2o else "missing",False,path=p2o,detail="跨硬件部署时用于 Paddle → ONNX" if p2o else "未检测到",fix="需要把飞桨模型转 ONNX 时安装 paddle2onnx" if not p2o else ""))

        update(58,"检查本机芯片编译器")
        saved=_load_saved_deploy_resources()
        checked=[]
        for r in saved:
            if str(r.get("mode")) in {"remote", "agent"}:
                continue
            try:
                cr=v39_detect_deploy_resource(str(r["id"]))
            except Exception as e:
                cr={**r,"status":"missing","message":str(e),"targets":[]}
            checked.append(cr)
        # Also discover common commands even when the user has not created resource cards yet.
        trt=_deploy_which("trtexec")
        # Sophon availability comes exclusively from the shared CLI probe of
        # an explicitly configured isolated Python environment.
        transform="";deploy="";cali="";sophon_version=""
        atc=_deploy_which("atc","atc.bin")
        nsmi=_deploy_which("npu-smi")
        for r in checked:
            if r.get("kind")=="tensorrt" and r.get("trtexec_path"):trt=r.get("trtexec_path")
            if r.get("kind")=="sophon" and r.get("status")=="ready":
                transform=r.get("model_transform_path") or transform;deploy=r.get("model_deploy_path") or deploy;cali=(r.get("run_calibration_path") or "") if (r.get("sophon_probe") or {}).get("calibration_available") else cali
                sophon_version=r.get("version") or sophon_version
            if r.get("kind")=="ascend":
                atc=r.get("atc_path") or atc;nsmi=r.get("npu_smi_path") or nsmi
        components.append(_v40_component_item("trtexec","TensorRT trtexec","ready" if trt else "missing",False,version=_deploy_cmd_version(str(trt or "")),path=str(trt or ""),fix="在 NVIDIA 部署机安装 TensorRT" if not trt else ""))
        local_sophon=[r for r in checked if r.get("kind")=="sophon"]
        local_sophon_detail=("本机未配置独立 TPU-MLIR；不影响远程资源使用" if not local_sophon else "；".join(str(r.get("message") or "") for r in local_sophon))
        components.append(_v40_component_item("tpu_transform","本机 TPU-MLIR model_transform","ready" if transform else "missing",False,path=str(transform or ""),detail=local_sophon_detail,fix="配置本机独立 TPU-MLIR 资源，或使用已就绪远程算能资源" if not transform else ""))
        components.append(_v40_component_item("tpu_deploy","本机 TPU-MLIR model_deploy","ready" if deploy else "missing",False,version=sophon_version,path=str(deploy or ""),detail=local_sophon_detail,fix="配置本机独立 TPU-MLIR 资源，或使用已就绪远程算能资源" if not deploy else ""))
        components.append(_v40_component_item("tpu_calibration","本机 TPU-MLIR run_calibration","ready" if cali else "missing",False,path=str(cali or ""),detail=local_sophon_detail+"；仅 INT8 校准需要，FP16 不依赖此项",fix="配置 TPU-MLIR calibration 工具" if not cali else ""))
        components.append(_v40_component_item("atc","CANN ATC","ready" if atc else "missing",False,version=_deploy_cmd_version(str(atc or "")),path=str(atc or ""),detail="Atlas/Ascend OM 编译器",fix="在华为转换机安装 CANN Toolkit 或配置 ATC 路径" if not atc else ""))
        npu_text="";socs=[]
        if nsmi:
            try:
                cp=subprocess.run([nsmi,"info"],capture_output=True,text=True,encoding="utf-8",errors="ignore",timeout=10)
                npu_text=(cp.stdout or cp.stderr or "")[-5000:]
                for m in re.findall(r"Ascend\\s*([0-9]{3,4}[A-Za-z0-9_-]*)",npu_text,re.I):
                    v="Ascend"+m.replace(" ","")
                    if v not in socs:socs.append(v)
            except Exception:pass
        components.append(_v40_component_item("npu_smi","npu-smi","ready" if nsmi else "warning",False,path=str(nsmi or ""),detail=("检测到："+"、".join(socs)) if socs else ("已安装，可查询 Atlas 芯片" if nsmi else "仅转换 OM 时不是必需；连接真实 Atlas 时用于读取 Chip Name"),fix="连接 Atlas 硬件验证时安装驱动/npu-smi" if not nsmi else ""))

        update(76,"检查远程部署资源")
        remote_rows=[]
        for r in saved:
            if str(r.get("mode"))!="remote":continue
            try: cr=v39_detect_deploy_resource(str(r["id"]))
            except Exception as e: cr={**r,"status":"missing","message":str(e),"targets":[]}
            remote_rows.append(cr)
            components.append(_v40_component_item("remote_"+str(r.get("id")),"远程部署 · "+str(r.get("name") or r.get("id")),"ready" if cr.get("status")=="ready" else "missing",False,version=str(cr.get("version") or ""),path=str(cr.get("base_url") or ""),detail=str(cr.get("message") or ""),fix="检查远程转换服务与网络/API Key" if cr.get("status")!="ready" else ""))

        update(90,"汇总可用能力")
        capabilities=[]
        capabilities.append(_v40_capability("平台基础运行",["python","fastapi","uvicorn","requests","yaml","PIL","cv2"],components))
        capabilities.append(_v40_capability("Ultralytics 训练",["ultralytics"],components))
        capabilities.append(_v40_capability("Ultralytics → ONNX",["ultralytics","onnx"],components,optional_keys=["onnxruntime"]))
        capabilities.append(_v40_capability("PaddleDetection 训练",["paddle","paddledet_train"],components))
        capabilities.append(_v40_capability("Paddle → Inference",["paddle","paddledet_export"],components))
        capabilities.append(_v40_capability("Paddle → ONNX",["paddle","paddledet_export","paddle2onnx"],components))
        capabilities.append(_v40_capability("算能 BMODEL (FP16)",["tpu_transform","tpu_deploy"],components))
        capabilities.append(_v40_capability("华为 Atlas / Ascend OM",["atc"],components,optional_keys=["npu_smi"]))
        capabilities.append(_v40_capability("NVIDIA TensorRT",["trtexec"],components))
        # Remote resource capabilities can make a target usable even when the platform host lacks local compilers.
        remote_targets=[]
        for r in remote_rows:
            if r.get("status")=="ready":remote_targets += list(r.get("targets") or [])
        for cap in capabilities:
            if cap["name"].startswith("华为") and "ascend" in remote_targets:cap.update(status="ready",remote=True)
            if cap["name"].startswith("算能"):
                configured=[r for r in checked+remote_rows if r.get("kind")=="sophon"]
                available=[r for r in configured if r.get("status")=="ready" and "sophon" in (r.get("targets") or [])]
                remote_sophon=[r for r in available if r.get("mode")=="remote"]
                local_ready=any(r.get("mode")!="remote" for r in available)
                detail="本机工具可用" if local_ready else ("本机工具未就绪" if local_sophon else "本机未配置")
                if remote_sophon:
                    detail+="；远程算能资源可用："+"；".join(str(r.get("name") or r.get("id"))+" · "+str(r.get("version") or "")+" · "+" / ".join(str(c).upper() for c in r.get("supported_chips") or [])+" · FP16" for r in remote_sophon)
                elif not available:
                    detail+="；"+("已配置算能资源检测未通过，请查看资源错误" if configured else "未配置算能转换资源")
                cap.update(status="ready" if available else "missing",remote=bool(remote_sophon),ready=len(available),total=len(configured),detail=detail)
            if cap["name"].startswith("NVIDIA") and "tensorrt" in remote_targets:cap.update(status="ready",remote=True)
        ready=sum(1 for x in components if x.get("status")=="ready")
        missing=sum(1 for x in components if x.get("status")=="missing")
        warning=sum(1 for x in components if x.get("status")=="warning")
        scan.update(status="running",progress=98,stage="正在汇总 RKNN 能力",updated_at=now_iso(),components=components,capabilities=capabilities,summary={"ready":ready,"warning":warning,"missing":missing,"total":len(components)},atlas={"atc_ready":bool(atc),"npu_smi_ready":bool(nsmi),"detected_soc_versions":socs,"note":"OM 转换不要求转换机安装 Atlas NPU，但 --soc_version 必须与最终部署芯片一致"})
        _v40_scan_write(scan_id,scan)
    except Exception as e:
        scan.update(status="failed",stage="检测失败",error=str(e),message=str(e),updated_at=now_iso(),components=components)
        _v40_scan_write(scan_id,scan)
    finally:
        COMPONENT_SCAN_THREADS.pop(scan_id,None)


@app.post("/api/v40/system/components/scan")
def v40_start_component_scan():
    scan_id=uuid.uuid4().hex[:12]
    data={"id":scan_id,"status":"queued","progress":0,"stage":"等待检测","created_at":now_iso(),"updated_at":now_iso(),"components":[],"capabilities":[]}
    _v40_scan_write(scan_id,data)
    th=threading.Thread(target=_v40_run_component_scan,args=(scan_id,),daemon=True)
    COMPONENT_SCAN_THREADS[scan_id]=th;th.start()
    return data


@app.get("/api/v40/system/components/scan/{scan_id}")
def v40_get_component_scan(scan_id: str):
    p=COMPONENT_SCAN_DIR/f"{scan_id}.json"
    if not p.exists():raise HTTPException(status_code=404,detail="检测任务不存在")
    return read_json(p,{})


@app.get("/api/v40/system/components/latest")
def v40_latest_component_scan():
    p=COMPONENT_SCAN_DIR/"latest.json"
    return read_json(p,{"status":"never","progress":0,"components":[],"capabilities":[],"summary":{"ready":0,"warning":0,"missing":0,"total":0}})

# ============================================================
# v41: 部署插件框架 + 瑞芯微 RKNN-Toolkit2
# ============================================================
from deploy_plugins import plugin_catalog as _v41_plugin_catalog
from platform_core.rknn_runtime import probe_rknn_toolkit


def _v41_rknn_info(py: str) -> Dict[str, Any]:
    from platform_core.compute_platform_catalog import conversion_templates
    catalog=_conversion_catalog_repository(DATA_DIR).conversion_catalog()
    vendors={v["id"] for v in catalog["vendors"] if v.get("template_id")=="rknn" and v.get("enabled",True)}
    candidates=[c["sdk_code"].lower() for c in catalog["chips"] if c["vendor_id"] in vendors and c.get("enabled",True)]
    result=probe_rknn_toolkit(py,**({"target_chips":candidates} if candidates else {}))
    return {
        'ok':bool(result.get('available')),
        'version':str(result.get('version') or ''),
        'supported_chips':list(result.get('supported_chips') or []),
        'error':str(result.get('error') or ''),
    }

_v41_old_detect_local_deploy_resource = _detect_local_deploy_resource

def _detect_local_deploy_resource(item: Dict[str, Any]) -> Dict[str, Any]:
    if str(item.get('kind') or '').lower()!='rockchip':
        return _v41_old_detect_local_deploy_resource(item)
    row=dict(item); row['last_checked_at']=now_iso(); row['targets']=[]
    py=str(row.get('python_path') or sys.executable)
    info=_v41_rknn_info(py)
    row['rknn_python']=py
    row['rknn_version']=str(info.get('version') or '')
    row['supported_chips']=list(info.get('supported_chips') or [])
    if info.get('ok'):
        row.update(status='ready',targets=['rockchip'],supported_precisions=['fp16','int8'],version=row['rknn_version'],message='RKNN-Toolkit2 可用；无需开发板即可把 ONNX 转为 RKNN')
    else:
        row.update(status='missing',message='未检测到 RKNN-Toolkit2：'+str(info.get('error') or ''))
    return row


@app.get('/api/v41/deploy/plugins')
def v41_deploy_plugins():
    from platform_core.conversion_resource_detection import observe
    saved=_load_saved_deploy_resources()
    # Do not even schedule the builtin SDK scanner on a catalog GET. The
    # ordinary resource endpoint may refresh its existing background snapshot;
    # the plugin catalog itself only projects already-known evidence.
    builtin=_DEPLOY_BUILTIN_RESOURCE_CACHE.snapshot()["items"] or _builtin_deploy_resource_summary()
    # GET is a read-only catalog. SDK import, remote health probing and saving
    # observations belong to the explicit /deploy/resources/{id}/detect POST.
    resources=[_deploy_resource_public(observe(r)) for r in builtin+saved]
    rows=[]
    from platform_core.compute_platform_catalog import conversion_templates
    catalog=_conversion_catalog_repository(DATA_DIR).conversion_catalog()
    templates={t['id']:t.get('adapter') for t in conversion_templates()}
    for p in _v41_plugin_catalog():
        vendor_ids={v['id'] for v in catalog['vendors'] if v.get('enabled',True) and templates.get(v.get('template_id'))==p['id']}
        p['chips']=[c['name'] for c in catalog['chips'] if c['vendor_id'] in vendor_ids]
        matches=[r for r in resources if str(r.get('kind'))==p['id'] or (p['id']=='onnx' and str(r.get('kind')) in {'ultralytics','paddle'})]
        ready=[]
        for r in matches:
            chk=r
            if chk.get('detection',{}).get('state')!='available':
                continue
            if p['id']=='rockchip':
                if chk.get('status')=='ready' and 'rockchip' in (chk.get('targets') or []) and chk.get('supported_chips'):
                    ready.append(chk)
            elif chk.get('status')=='ready' and (p['id'] in (chk.get('targets') or []) or (p['id']=='onnx' and 'onnx' in (chk.get('targets') or []))):
                ready.append(chk)
        p['status']='ready' if ready else ('unchecked' if matches and any(
            r.get('detection',{}).get('state') in {'checking','not_checked','expired'} for r in matches
        ) else 'missing')
        p['resources']=ready; p['configured_count']=len(matches)
        rows.append(p)
    return {'ok':True,'items':rows,'version':APP_VERSION,'host_os':'windows' if os.name=='nt' else 'linux'}


class V41SdkInstallReq(BaseModel):
    resource_id: str
    wheel_path: str


@app.post('/api/v41/deploy/plugins/rockchip/install-sdk')
def v41_install_rockchip_sdk(payload: V41SdkInstallReq):
    item=next((x for x in _load_saved_deploy_resources() if x.get('id')==payload.resource_id),None)
    if not item or str(item.get('kind'))!='rockchip':
        raise HTTPException(status_code=404,detail='请先新增一个瑞芯微本机部署资源')
    if str(item.get('mode'))!='local':
        raise HTTPException(status_code=400,detail='远程资源请在远程转换节点安装 RKNN-Toolkit2')
    if os.name == 'nt':
        raise HTTPException(status_code=400,detail='RKNN-Toolkit2 官方转换工具链使用 Linux wheel，Windows 本机不要直接安装。请在 WSL2/Linux 转换节点安装 RKNN-Toolkit2，并在“部署资源”新增远程资源。')
    py=str(item.get('python_path') or '')
    if not py:
        raise HTTPException(status_code=400,detail='RKNN-Toolkit2 必须使用独立 Python 环境，不能和平台训练环境混装。请先创建独立 venv/conda，并把 Python 路径填到瑞芯微部署资源。')
    try:
        if Path(py).resolve() == Path(sys.executable).resolve():
            raise HTTPException(status_code=400,detail='RKNN-Toolkit2 官方依赖对 Torch/ONNX 有独立版本约束，禁止安装到平台主 Python。请为 RKNN 单独创建 venv/conda 后填写其 Python 路径。')
    except HTTPException:
        raise
    except Exception:
        pass
    wheel=Path(payload.wheel_path.strip())
    if not wheel.exists() or wheel.suffix.lower()!='.whl':
        raise HTTPException(status_code=400,detail='请选择已下载的官方 RKNN-Toolkit2 .whl 文件')
    try:
        cp=subprocess.run([py,'-m','pip','install',str(wheel)],capture_output=True,text=True,encoding='utf-8',errors='ignore',timeout=900)
    except Exception as e:
        raise HTTPException(status_code=500,detail=f'安装执行失败：{e}')
    if cp.returncode!=0:
        raise HTTPException(status_code=500,detail='RKNN-Toolkit2 安装失败：'+(cp.stderr or cp.stdout or '')[-3000:])
    checked=_detect_local_deploy_resource(item)
    items=_load_saved_deploy_resources()
    for i,x in enumerate(items):
        if x.get('id')==item.get('id'):items[i]=checked
    _save_deploy_resources(items)
    return {'ok':True,'resource':checked,'log':(cp.stdout or '')[-3000:]}


_v41_old_component_scan = _v40_run_component_scan

def _v40_run_component_scan(scan_id: str):
    _v41_old_component_scan(scan_id)
    jf=COMPONENT_SCAN_DIR/f'{scan_id}.json'; scan=read_json(jf,{})
    if scan.get('status')!='running' or scan.get('progress')!=98:return
    try:
        comps=list(scan.get('components') or []); caps=list(scan.get('capabilities') or [])
        saved=_load_saved_deploy_resources(); local=[r for r in saved if r.get('kind')=='rockchip' and r.get('mode')!='remote']; remote=[r for r in saved if r.get('kind')=='rockchip' and r.get('mode')=='remote']
        ready=False; version=''; detail='未配置 RKNN-Toolkit2 转换资源'
        for r in local:
            mode=str(r.get('mode') or 'local')
            chk=_detect_agent_deploy_resource(r) if mode=='agent' else _detect_local_deploy_resource(r)
            if chk.get('status')=='ready' and 'rockchip' in (chk.get('targets') or []):
                ready=True;version=chk.get('version','')
                chips=[str(x).upper() for x in (chk.get('supported_chips') or [])]
                detail=('Agent' if mode=='agent' else '本机')+' RKNN-Toolkit2 可转换：'+(' / '.join(chips) or '未上报芯片')
                break
        if not ready:
            for r in remote:
                chk=_detect_remote_deploy_resource(r)
                if chk.get('status')=='ready' and 'rockchip' in (chk.get('targets') or []) and chk.get('supported_chips'):
                    ready=True;version=chk.get('version','')
                    detail='远程 RKNN 转换节点可用：'+' / '.join(str(x).upper() for x in chk.get('supported_chips') or [])
                    break
        comps.append(_v40_component_item('rknn_toolkit2','RKNN-Toolkit2','ready' if ready else 'missing',False,version=version,detail=detail,fix='配置 Linux 转换节点或为瑞芯微部署资源指定安装了 RKNN-Toolkit2 的 Python 环境' if not ready else ''))
        caps.append({'name':'瑞芯微 RKNN','status':'ready' if ready else 'missing','required':['rknn_toolkit2'],'optional':[],'ready':1 if ready else 0,'total':1,'remote':bool(ready and remote and not local)})
        ready_n=sum(1 for x in comps if x.get('status')=='ready');missing=sum(1 for x in comps if x.get('status')=='missing');warning=sum(1 for x in comps if x.get('status')=='warning')
        scan.update(status='done',progress=100,stage='检测完成',finished_at=now_iso(),components=comps,capabilities=caps,summary={'ready':ready_n,'warning':warning,'missing':missing,'total':len(comps)},updated_at=now_iso())
        _v40_scan_write(scan_id,scan)

    except Exception as error:
        scan.update(status='failed',stage='RKNN 检测失败',error=str(error),
                    message=str(error),updated_at=now_iso())
        _v40_scan_write(scan_id,scan)

@app.get('/api/v41/system/deploy-matrix')
def v41_deploy_matrix():
    return {'ok':True,'plugins':_v41_plugin_catalog(),'rule':'源模型 → 通用中间模型 → 厂商插件编译 → 芯片模型；Runtime/Lite2/AscendCL/BMRuntime 属于运行阶段，不是第二次模型转换。'}

# ============================================================
# v42: 算法持续迭代闭环
# - 素材源：目录 / RTSP(含视频URL) / 通用HTTP JSON
# - 自动迭代策略：数据门槛 + 模型指标门槛 + 自动补样 + 自动标注 + 自动重训
# - 所有任务均使用真实数据/真实训练结果；缺少外部源或标注模型时明确停在待处理阶段
# ============================================================
V42_INDUSTRY_TEMPLATES = [
    {"id":"helmet","industry":"工地 / 工业","name":"未佩戴安全帽检测","labels":["person","helmet"],"focus":"人员头部、小目标、遮挡、逆光、远距离","negative":"正确佩戴、帽子/雨伞等相似物、背影","recommended_model":"yolo11s.pt"},
    {"id":"fire_smoke","industry":"消防 / 安防","name":"明火烟雾检测","labels":["fire","smoke"],"focus":"小火苗、早期烟雾、夜间、反光、雾气","negative":"灯光、红色物体、蒸汽、云雾","recommended_model":"yolo11s.pt"},
    {"id":"waterlogging","industry":"防汛 / 城市治理","name":"积水内涝检测","labels":["waterlogging"],"focus":"路面反光、不同水深、夜间、雨天","negative":"正常湿地、阴影、玻璃反射","recommended_model":"yolo11m.pt"},
    {"id":"falling","industry":"养老 / 监所 / 安防","name":"人员倒地检测素材模型","labels":["person_down"],"focus":"侧躺、趴卧、遮挡、不同机位","negative":"坐地、弯腰、床上正常躺卧","recommended_model":"yolo11s.pt"},
    {"id":"intrusion","industry":"园区 / 电力 / 仓储","name":"重点区域人员入侵检测","labels":["person"],"focus":"远距离、小目标、夜间、雨雪、遮挡","negative":"区域外人员、海报人像、屏幕人像","recommended_model":"yolo11s.pt"},
    {"id":"custom","industry":"自定义行业","name":"自定义行业算法","labels":[],"focus":"由业务场景定义","negative":"必须补充容易误报的反例","recommended_model":"yolo11s.pt"},
]


def _v42_file(project_id: str, name: str) -> Path:
    d = project_dir(project_id) / "v42"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{name}.json"


def _v42_list(project_id: str, name: str) -> List[Dict[str, Any]]:
    return read_json(_v42_file(project_id, name), [])


def _v42_save(project_id: str, name: str, rows: List[Dict[str, Any]]) -> None:
    write_json(_v42_file(project_id, name), rows)


def _v42_get(project_id: str, name: str, item_id: str) -> Optional[Dict[str, Any]]:
    return next((x for x in _v42_list(project_id, name) if x.get("id") == item_id), None)


from platform_core.legacy_automation_contracts import V42AlgorithmBlueprintReq


from platform_core.legacy_automation_service import LegacyAutomationDependencies, LegacyAutomationService
from platform_core.legacy_automation_api import create_legacy_automation_router_1, create_legacy_automation_router_2, create_legacy_automation_router_3, create_legacy_automation_router_4, create_legacy_automation_router_5, create_legacy_automation_router_6


def _legacy_automation_service() -> LegacyAutomationService:
    return LegacyAutomationService(LegacyAutomationDependencies(
        MODEL_CONFIGS_FILE=lambda: MODEL_CONFIGS_FILE,
        V42_INDUSTRY_TEMPLATES=lambda: V42_INDUSTRY_TEMPLATES,
        _parse_dt_value=lambda *args, **kwargs: _parse_dt_value(*args, **kwargs),
        _v35_is_vision_provider=lambda *args, **kwargs: _v35_is_vision_provider(*args, **kwargs),
        _v35_items=lambda *args, **kwargs: _v35_items(*args, **kwargs),
        _v42_get=lambda *args, **kwargs: _v42_get(*args, **kwargs),
        _v42_latest_algorithm_job=lambda *args, **kwargs: _v42_latest_algorithm_job(*args, **kwargs),
        _v42_list=lambda *args, **kwargs: _v42_list(*args, **kwargs),
        _v42_metrics_from_job=lambda *args, **kwargs: _v42_metrics_from_job(*args, **kwargs),
        _v42_run_collect=lambda *args, **kwargs: _v42_run_collect(*args, **kwargs),
        _v42_save=lambda *args, **kwargs: _v42_save(*args, **kwargs),
        _v42_source_test=lambda *args, **kwargs: _v42_source_test(*args, **kwargs),
        dataset_quality_report=lambda *args, **kwargs: dataset_quality_report(*args, **kwargs),
        ensure_default_datasets=lambda *args, **kwargs: ensure_default_datasets(*args, **kwargs),
        ensure_label=lambda *args, **kwargs: ensure_label(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        list_algorithms_internal=lambda *args, **kwargs: list_algorithms_internal(*args, **kwargs),
        load_images=lambda *args, **kwargs: load_images(*args, **kwargs),
        normalize_label=lambda *args, **kwargs: normalize_label(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        resolve_material_path=lambda *args, **kwargs: resolve_material_path(*args, **kwargs),
        v12_create_algorithm=lambda *args, **kwargs: v12_create_algorithm(*args, **kwargs),
        v35_test_model_config=lambda *args, **kwargs: v35_test_model_config(*args, **kwargs),
        v35_test_saved_model_annotation=lambda *args, **kwargs: v35_test_saved_model_annotation(*args, **kwargs),
    ))


app.include_router(create_legacy_automation_router_1(_legacy_automation_service))


def v42_industry_templates():
    return _legacy_automation_service().v42_industry_templates()


def v42_list_algorithm_blueprints(project_id: str):
    return _legacy_automation_service().v42_list_algorithm_blueprints(project_id)


def v42_create_algorithm_blueprint(project_id: str, payload: V42AlgorithmBlueprintReq):
    return _legacy_automation_service().v42_create_algorithm_blueprint(project_id, payload)


V423_DEPLOY_TARGET_NAMES = {
    "onnx": "ONNX 通用模型",
    "paddle_inference": "Paddle Inference",
    "tensorrt": "NVIDIA TensorRT",
    "sophon": "算能 Sophon / BModel",
    "ascend": "华为 Atlas / Ascend OM",
    "rockchip": "瑞芯微 RKNN",
}


def _version_deploy_training_job(project_id: str, version: Mapping[str, Any]) -> dict[str, Any]:
    job_id = str(version.get("job_id") or version.get("task_id") or "").strip()
    return read_json(project_dir(project_id) / "jobs" / job_id / "job.json", {}) if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id) else {}


def _version_deploy_conversion_defaults(project_id: str, version: Mapping[str, Any]) -> dict[str, Any]:
    defaults = derive_version_conversion_defaults(version, _version_deploy_training_job(project_id,version))
    defaults["source_format"] = Path(str(version.get("stored_path") or version.get("model_name") or "")).suffix.lower().lstrip(".")
    return defaults


app.include_router(create_conversion_management_router_5(_conversion_management_service))


def v423_version_deployments(project_id: str, algorithm_id: str, version_id: str, page: int=1, page_size: int=100, status: str='', target: str='', chip: str='', precision: str='', csc: str='', created_from: str='', created_to: str='', force: bool=False, asset_view: bool=False):
    return _conversion_management_service().v423_version_deployments(project_id, algorithm_id, version_id, page, page_size, status, target, chip, precision, csc, created_from, created_to, force, asset_view)


from platform_core.legacy_automation_contracts import V42SourceReq


from platform_core.legacy_automation_contracts import V42CollectReq


def _v42_source_last_run(project_id: str, source_id: str) -> Optional[Dict[str, Any]]:
    return _legacy_automation_service()._v42_source_last_run(project_id, source_id)

def _v42_source_next_run(item: Dict[str, Any], last_run: Optional[Dict[str, Any]]=None, now: Optional[datetime]=None) -> Optional[str]:
    return _legacy_automation_service()._v42_source_next_run(item, last_run, now)

def _v42_enrich_source(project_id: str, item: Dict[str, Any]) -> Dict[str, Any]:
    return _legacy_automation_service()._v42_enrich_source(project_id, item)

app.include_router(create_legacy_automation_router_2(_legacy_automation_service))


def v42_list_sources(project_id: str):
    return _legacy_automation_service().v42_list_sources(project_id)


def v42_create_source(project_id: str, payload: V42SourceReq):
    return _legacy_automation_service().v42_create_source(project_id, payload)


def v42_update_source(project_id: str, source_id: str, payload: V42SourceReq):
    return _legacy_automation_service().v42_update_source(project_id, source_id, payload)


def v42_delete_source(project_id: str, source_id: str):
    return _legacy_automation_service().v42_delete_source(project_id, source_id)


def _v42_json_path(data: Any, path: str) -> Any:
    cur=data
    for part in [x for x in str(path or '').split('.') if x]:
        if isinstance(cur,dict):cur=cur.get(part)
        else:return None
    return cur


def _v42_source_test(item: Dict[str, Any]) -> Dict[str, Any]:
    typ=item.get('type');src=str(item.get('source') or '').strip()
    if typ=='folder':
        p=Path(src).expanduser(); ok=p.exists(); return {"ok":ok,"message":f"路径可用：{p}" if ok else f"路径不存在：{p}"}
    if typ=='http_json':
        headers={}
        try: headers=json.loads(item.get('headers_json') or '{}')
        except Exception: return {"ok":False,"message":"headers_json 不是合法 JSON"}
        try:
            r=requests.get(src,headers=headers,timeout=8);r.raise_for_status();data=r.json();items=_v42_json_path(data,item.get('items_path') or 'items')
            count=len(items) if isinstance(items,list) else (1 if isinstance(items,dict) else 0)
            return {"ok":True,"message":f"接口可用，读取到 {count} 条候选记录"}
        except Exception as e:return {"ok":False,"message":f"接口连接失败：{e}"}
    if typ=='rtsp':
        try:
            import cv2
            cap=cv2.VideoCapture(src);ok,frame=cap.read();cap.release();return {"ok":bool(ok and frame is not None),"message":"视频流可读取" if ok and frame is not None else "视频流无法读取"}
        except Exception as e:return {"ok":False,"message":f"视频流检测失败：{e}"}
    return {"ok":False,"message":"不支持的素材源类型"}


def v42_test_source(project_id: str, source_id: str):
    return _legacy_automation_service().v42_test_source(project_id, source_id)


def _v42_collect_status(project_id: str, run_id: str, **kw):
    rows=_v42_list(project_id,'collection_runs')
    for x in rows:
        if x.get('id')==run_id:x.update(**kw,updated_at=now_iso())
    _v42_save(project_id,'collection_runs',rows)


def _v42_run_collect(project_id: str, run_id: str, source: Dict[str, Any], payload: Dict[str, Any]):
    try:
        _v42_collect_status(project_id,run_id,status='running',stage='读取素材',started_at=now_iso())
        typ=source.get('type');src=str(source.get('source') or '').strip();dataset_id=payload.get('dataset_id') or 'default';limit=max(1,min(2000,int(payload.get('max_items') or 50)))
        imported=[];errors=[];tmpdir=project_dir(project_id)/'v42'/'collect_tmp'/run_id;tmpdir.mkdir(parents=True,exist_ok=True)
        if typ=='folder':
            root=Path(src).expanduser()
            if not root.exists():raise RuntimeError(f'路径不存在：{root}')
            files=[root] if root.is_file() else [p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
            for f in files[:limit]:
                rec=add_image_record(project_id,f,f.name,'source_folder',dataset_id)
                if rec: imported.append(rec['id'])
        elif typ=='rtsp':
            import cv2
            cap=cv2.VideoCapture(src)
            if not cap.isOpened():raise RuntimeError('视频/RTSP 无法打开')
            source_fps=float(cap.get(cv2.CAP_PROP_FPS) or 0) or 25.0;interval=max(.1,float(payload.get('interval_seconds') or 2));step=max(1,int(round(source_fps*interval)));idx=0
            while len(imported)<limit:
                ok,frame=cap.read()
                if not ok or frame is None:break
                if idx%step==0:
                    temp=tmpdir/f'frame_{idx:09d}.jpg';cv2.imwrite(str(temp),frame);rec=add_image_record(project_id,temp,temp.name,'source_rtsp',dataset_id)
                    if rec:imported.append(rec['id'])
                idx+=1
            cap.release()
        elif typ=='http_json':
            headers=json.loads(source.get('headers_json') or '{}');r=requests.get(src,headers=headers,timeout=20);r.raise_for_status();data=r.json();items=_v42_json_path(data,source.get('items_path') or 'items')
            if isinstance(items,dict):items=[items]
            if not isinstance(items,list):raise RuntimeError('接口返回中未找到数组，请检查 items_path')
            fld=source.get('image_url_field') or 'image_url'
            for i,row in enumerate(items[:limit]):
                if not isinstance(row,dict):continue
                url=str(row.get(fld) or '').strip()
                if not url:continue
                try:
                    rr=requests.get(url,timeout=20);rr.raise_for_status();ext=Path(url.split('?',1)[0]).suffix.lower();ext=ext if ext in IMAGE_EXTS else '.jpg';temp=tmpdir/f'api_{i:06d}{ext}';temp.write_bytes(rr.content);rec=add_image_record(project_id,temp,temp.name,'source_http',dataset_id)
                    if rec:imported.append(rec['id'])
                except Exception as e:errors.append(str(e))
        else:raise RuntimeError('不支持的素材源类型')
        _v42_collect_status(project_id,run_id,status='done',stage='完成',progress=100,imported=len(imported),image_ids=imported,errors=errors[-20:],finished_at=now_iso())
    except Exception as e:
        _v42_collect_status(project_id,run_id,status='failed',stage='失败',error=str(e),finished_at=now_iso())


def v42_collection_runs(project_id: str):
    return _legacy_automation_service().v42_collection_runs(project_id)


def v42_collect(project_id: str, source_id: str, payload: V42CollectReq):
    return _legacy_automation_service().v42_collect(project_id, source_id, payload)



_V42_SOURCE_SCHEDULER_STARTED=False
_V42_SOURCE_SCHEDULER_LOCK=threading.Lock()

def _v42_source_due(project_id: str, source: Dict[str, Any], now: datetime) -> bool:
    if not source.get('enabled',True) or source.get('collect_mode','manual')!='auto':return False
    last=_v42_source_last_run(project_id,source.get('id') or '')
    if last and last.get('status') in {'queued','running'}:return False
    next_at=_parse_dt_value(_v42_source_next_run(source,last,now))
    return bool(next_at and next_at<=now)

def _v42_source_scheduler_once(now: Optional[datetime]=None) -> int:
    launched=0;now=now or datetime.now()
    for project in read_json(PROJECTS_FILE,[]):
        project_id=project.get('id')
        if not project_id:continue
        for source in _v42_list(project_id,'sources'):
            if not _v42_source_due(project_id,source,now):continue
            try:
                v42_collect(project_id,source.get('id'),V42CollectReq(
                    dataset_id=source.get('dataset_id') or 'default',
                    max_items=int(source.get('max_items') or 50),
                    interval_seconds=float(source.get('interval_seconds') or 2.0),
                ));launched+=1
            except Exception:
                pass
    return launched

def _v42_source_scheduler_loop():
    while True:
        try:_v42_source_scheduler_once()
        except Exception:pass
        time.sleep(20)

def _v42_start_source_scheduler():
    global _V42_SOURCE_SCHEDULER_STARTED
    with _V42_SOURCE_SCHEDULER_LOCK:
        if _V42_SOURCE_SCHEDULER_STARTED:return
        _V42_SOURCE_SCHEDULER_STARTED=True
        threading.Thread(target=_v42_source_scheduler_loop,daemon=True,name='v42-source-scheduler').start()

@app.on_event('startup')
def _v42_startup_scheduler():
    _v42_start_source_scheduler()

def v42_test_saved_model_config(config_id: str):
    return _legacy_automation_service().v42_test_saved_model_config(config_id)

@app.post('/api/v42/projects/{project_id}/prelabel-tasks/{task_id}/retry')
def v42_retry_prelabel_task(project_id: str, task_id: str):
    task=_v33_get_task(project_id,'prelabel_tasks',task_id) or {}
    payload=task.get('request_payload')
    if not payload:raise HTTPException(status_code=400,detail='旧任务没有保存创建参数，请重新创建自动标注任务')
    return v35_create_prelabel_task(project_id,V35PrelabelTaskReq(**payload))

class V42PolicyReq(BaseModel):
    name: str
    algorithm_id: Optional[str] = ''
    dataset_id: str = 'default'
    source_id: Optional[str] = ''
    min_images: int = 300
    min_boxes_per_label: int = 100
    min_precision: float = 0.85
    min_recall: float = 0.80
    min_map50: float = 0.85
    use_online_audit: bool = False
    min_audit_samples: int = 20
    min_online_accuracy: float = 0.90
    collect_each_loop: int = 100
    max_loops: int = 2
    auto_collect: bool = True
    auto_prelabel: bool = False
    model_config_id: Optional[str] = ''
    prompt_template_id: Optional[str] = ''
    target_label: Optional[str] = ''
    auto_retrain: bool = True
    framework: str = 'ultralytics'
    algorithm: str = 'yolo11s_det'
    model: str = 'yolo11s.pt'
    epochs: int = 80
    imgsz: int = 640
    batch: int = 8
    device: str = '0'
    target: str = 'local'
    server_id: Optional[str] = ''
    enabled: bool = True


app.include_router(create_legacy_automation_router_3(_legacy_automation_service))


def v42_policies(project_id: str):
    return _legacy_automation_service().v42_policies(project_id)


def _legacy_iteration_write_disabled() -> None:
    raise HTTPException(
        status_code=410,
        detail=(
            "旧 v42 自动迭代写入口已停用。请使用 v63 线上抽检/反馈完成 review/confirm，"
            "再通过 Dataset Revision → Durable TRAINING → Evaluation → Confirmed Action 链继续迭代。"
        ),
    )


@app.post('/api/v42/projects/{project_id}/iteration-policies')
def v42_create_policy(project_id: str,payload:V42PolicyReq):
    get_project(project_id)
    _legacy_iteration_write_disabled()


@app.put('/api/v42/projects/{project_id}/iteration-policies/{policy_id}')
def v42_update_policy(project_id:str,policy_id:str,payload:V42PolicyReq):
    get_project(project_id)
    _legacy_iteration_write_disabled()


app.include_router(create_legacy_automation_router_4(_legacy_automation_service))


def v42_delete_policy(project_id: str, policy_id: str):
    return _legacy_automation_service().v42_delete_policy(project_id, policy_id)


class V42OnlineFeedbackReq(BaseModel):
    algorithm_id: str
    correct: bool
    score: Optional[float] = None
    category: Optional[str] = ''
    reason: Optional[str] = ''
    image_url: Optional[str] = ''
    dataset_id: Optional[str] = ''
    source: Optional[str] = 'external_audit'
    raw: Optional[Dict[str, Any]] = None


def _v42_audit_summary(project_id: str, algorithm_id: str, limit: int=500) -> Dict[str, Any]:
    return _legacy_automation_service()._v42_audit_summary(project_id, algorithm_id, limit)


def v42_online_feedback(project_id: str, algorithm_id: Optional[str]=None):
    return _legacy_automation_service().v42_online_feedback(project_id, algorithm_id)


@app.post('/api/v42/projects/{project_id}/online-feedback')
def v42_submit_online_feedback(project_id: str, payload: V42OnlineFeedbackReq):
    get_project(project_id)
    _legacy_iteration_write_disabled()


def _v42_hygiene_report(project_id: str, dataset_id: str, max_scan: int=1000) -> Dict[str, Any]:
    return _legacy_automation_service()._v42_hygiene_report(project_id, dataset_id, max_scan)


app.include_router(create_legacy_automation_router_5(_legacy_automation_service))


def v42_dataset_hygiene(project_id: str, dataset_id: str, max_scan: int=1000):
    return _legacy_automation_service().v42_dataset_hygiene(project_id, dataset_id, max_scan)


def _v42_publish_job_version(project_id: str, algorithm_id: str, job_id: str) -> Optional[Dict[str, Any]]:
    if not algorithm_id:return None
    models=[m for m in list_models_internal(project_id) if m.get('job_id')==job_id]
    if not models:return None
    models.sort(key=lambda m:(0 if str(m.get('name','')).lower().startswith('best') else 1,0 if m.get('type') in {'pt','pdparams'} else 1,-float(m.get('size_mb') or 0)))
    for m in models:
        try:
            return v12_assign_version(project_id,algorithm_id,AlgorithmVersionReq(model_name=m.get('name') or '',model_source='project',job_id=job_id,version_name='',remark='v42 自动迭代达标后归档'))
        except HTTPException as e:
            if '已经归属' in str(e.detail):continue
            raise
    return None


def _v42_float(v: Any) -> Optional[float]:
    try:return float(str(v).strip())
    except Exception:return None


def _v42_metrics_from_job(project_id: str, job_id: str) -> Dict[str, Any]:
    rep=job_report(project_id,job_id);out={"report":rep,"precision":None,"recall":None,"map50":None}
    for k,v in rep.items():
        low=str(k).lower().replace(' ','')
        num=_v42_float(v)
        if num is None:continue
        if 'precision' in low and out['precision'] is None:out['precision']=num
        if 'recall' in low and out['recall'] is None:out['recall']=num
        if ('map50' in low and '95' not in low) and out['map50'] is None:out['map50']=num
    return out


def _v42_latest_algorithm_job(project_id: str, algorithm_id: str) -> Optional[str]:
    alg=next((x for x in list_algorithms_internal(project_id) if x.get('id')==algorithm_id),None)
    if not alg:return None
    for v in alg.get('versions',[]) or []:
        if v.get('job_id'):return v.get('job_id')
    return None


def _v42_iteration_update(project_id: str, run_id: str, **kw):
    rows=_v42_list(project_id,'iteration_runs')
    for x in rows:
        if x.get('id')==run_id:x.update(**kw,updated_at=now_iso())
    _v42_save(project_id,'iteration_runs',rows)


def _v42_wait_collection(project_id: str, run_id: str, timeout_sec: int=3600) -> Dict[str, Any]:
    start=time.time()
    while time.time()-start<timeout_sec:
        item=_v42_get(project_id,'collection_runs',run_id) or {}
        if item.get('status') in {'done','failed','stopped'}:return item
        time.sleep(2)
    return {"status":"failed","error":"素材采集等待超时"}


def _v42_wait_prelabel(project_id: str, task_id: str, timeout_sec: int=7200) -> Dict[str, Any]:
    start=time.time()
    while time.time()-start<timeout_sec:
        item=_v33_get_task(project_id,'prelabel_tasks',task_id) or {}
        if item.get('status') in {'done','failed','stopped'}:return item
        time.sleep(2)
    return {"status":"failed","error":"自动标注等待超时"}


def _v42_wait_train(project_id: str, job_id: str, timeout_sec: int=86400) -> Dict[str, Any]:
    start=time.time()
    while time.time()-start<timeout_sec:
        try:
            raw=read_json(project_dir(project_id)/'jobs'/job_id/'job.json',{})
            job=enrich_job_runtime(project_id,raw) if raw else {}
        except Exception:
            job=read_json(project_dir(project_id)/'jobs'/job_id/'job.json',{})
        if job.get('status') in {'done','finished','failed','stopped'}:return job
        time.sleep(5)
    return {"status":"failed","message":"训练等待超时"}


def _v42_run_iteration(project_id: str, run_id: str, policy: Dict[str, Any]):
    history=[]
    try:
        _v42_iteration_update(project_id,run_id,status='running',stage='检查数据与模型质量',started_at=now_iso())
        max_loops=max(1,min(10,int(policy.get('max_loops') or 1)))
        current_job_id=_v42_latest_algorithm_job(project_id,str(policy.get('algorithm_id') or ''))
        for loop in range(1,max_loops+1):
            q=dataset_quality_report(project_id,policy.get('dataset_id') or 'default',False)
            scarce=[k for k,v in (q.get('label_usage') or {}).items() if int(v or 0)<int(policy.get('min_boxes_per_label') or 0)]
            data_pass=q.get('image_count',0)>=int(policy.get('min_images') or 0) and not scarce and q.get('can_train')
            job_id=current_job_id
            metrics=_v42_metrics_from_job(project_id,job_id) if job_id else {"precision":None,"recall":None,"map50":None,"report":{}}
            metric_available=all(metrics.get(k) is not None for k in ['precision','recall','map50'])
            metric_pass=metric_available and metrics['precision']>=float(policy.get('min_precision') or 0) and metrics['recall']>=float(policy.get('min_recall') or 0) and metrics['map50']>=float(policy.get('min_map50') or 0)
            audit=_v42_audit_summary(project_id,str(policy.get('algorithm_id') or '')) if policy.get('use_online_audit') else {"total":0,"accuracy":None,"error_categories":{}}
            audit_pass=(not policy.get('use_online_audit')) or (audit.get('total',0)>=int(policy.get('min_audit_samples') or 0) and audit.get('accuracy') is not None and audit.get('accuracy')>=float(policy.get('min_online_accuracy') or 0))
            step={"loop":loop,"quality":q,"scarce_labels":scarce,"metrics":metrics,"audit":audit,"data_pass":data_pass,"metric_pass":metric_pass,"audit_pass":audit_pass,"job_id":job_id,"actions":[]}
            history.append(step);_v42_iteration_update(project_id,run_id,loop=loop,history=history,stage=f'第 {loop} 轮质量判定')
            if data_pass and metric_pass and audit_pass:
                published=_v42_publish_job_version(project_id,str(policy.get('algorithm_id') or ''),job_id) if job_id else None
                if published:step['actions'].append({'type':'publish_version','version':published.get('version')})
                _v42_iteration_update(project_id,run_id,status='done',stage='已达标',result='pass',history=history,finished_at=now_iso());return
            # 数据不足或指标不达标时，先从真实素材源补样。
            if policy.get('auto_collect') and policy.get('source_id'):
                source=_v42_get(project_id,'sources',str(policy.get('source_id')))
                if source:
                    cr=v42_collect(project_id,source['id'],V42CollectReq(dataset_id=policy.get('dataset_id') or 'default',max_items=int(policy.get('collect_each_loop') or 100),interval_seconds=2.0))
                    step['actions'].append({"type":"collect","run_id":cr['id'],"focus_labels":scarce})
                    _v42_iteration_update(project_id,run_id,stage=f'第 {loop} 轮：补充真实素材',history=history)
                    cdone=_v42_wait_collection(project_id,cr['id']);step['actions'][-1]['result']=cdone
                    if cdone.get('status')!='done':
                        _v42_iteration_update(project_id,run_id,status='needs_attention',stage='素材补充失败',result='blocked',history=history,error=cdone.get('error') or '素材补充失败',finished_at=now_iso());return
                    # 自动标注只在用户明确配置模型后执行，不伪造框。
                    new_ids=cdone.get('image_ids') or []
                    if policy.get('auto_prelabel') and new_ids and policy.get('model_config_id'):
                        label=str(policy.get('target_label') or (scarce[0] if scarce else '')).strip()
                        if label:
                            req=V35PrelabelTaskReq(model_config_id=policy.get('model_config_id') or None,prompt_template_id=policy.get('prompt_template_id') or None,target_label=label,image_ids=new_ids,dataset_id=policy.get('dataset_id') or 'default',training_framework=policy.get('framework') or 'ultralytics',task_name=f"自动迭代第{loop}轮·{label}",overwrite=False,include_empty=False)
                            pt=v35_create_prelabel_task(project_id,req);step['actions'].append({"type":"prelabel","task_id":pt['id'],"target_label":label})
                            _v42_iteration_update(project_id,run_id,stage=f'第 {loop} 轮：模型自动标注',history=history)
                            pdone=_v42_wait_prelabel(project_id,pt['id']);step['actions'][-1]['result']=pdone
                            if pdone.get('status')!='done':
                                _v42_iteration_update(project_id,run_id,status='needs_attention',stage='自动标注失败',result='blocked',history=history,error=pdone.get('error') or '自动标注失败',finished_at=now_iso());return
            # 训练前再次确认有真实有效标注；没配置自动标注时应停下来让用户处理，而不是假装自动完成。
            q2=dataset_quality_report(project_id,policy.get('dataset_id') or 'default',False)
            if not q2.get('can_train'):
                _v42_iteration_update(project_id,run_id,status='needs_attention',stage='等待标注',result='blocked',history=history,error='补充素材后仍没有足够有效标注，请配置自动标注模型或人工复核',finished_at=now_iso());return
            if policy.get('auto_retrain'):
                treq=TrainReq(framework=policy.get('framework') or 'ultralytics',algorithm=policy.get('algorithm') or 'yolo11s_det',model=policy.get('model') or 'yolo11s.pt',epochs=int(policy.get('epochs') or 80),imgsz=int(policy.get('imgsz') or 640),batch=int(policy.get('batch') or 8),device=str(policy.get('device') or '0'),dataset_id=policy.get('dataset_id') or 'default',target=policy.get('target') or 'local',server_id=policy.get('server_id') or None)
                _v42_iteration_update(project_id,run_id,stage=f'第 {loop} 轮：自动重训',history=history)
                started=v12_start_train(project_id,treq);jid=started.get('job',{}).get('id');step['actions'].append({"type":"train","job_id":jid})
                if not jid:raise RuntimeError('训练任务创建失败')
                done=_v42_wait_train(project_id,jid);current_job_id=jid;step['actions'][-1]['result']={"status":done.get('status'),"message":done.get('message')}
                if done.get('status') not in {'done','finished'}:
                    _v42_iteration_update(project_id,run_id,status='needs_attention',stage='自动重训失败',result='blocked',history=history,error=done.get('message') or '训练失败',finished_at=now_iso());return
                # 迭代任务直接使用该真实训练任务的指标继续下一轮判定。
                metrics2=_v42_metrics_from_job(project_id,jid);step['trained_metrics']=metrics2;step['trained_job_id']=jid
                if all(metrics2.get(k) is not None for k in ['precision','recall','map50']) and metrics2['precision']>=float(policy.get('min_precision') or 0) and metrics2['recall']>=float(policy.get('min_recall') or 0) and metrics2['map50']>=float(policy.get('min_map50') or 0) and audit_pass:
                    published=_v42_publish_job_version(project_id,str(policy.get('algorithm_id') or ''),jid)
                    if published:step['actions'].append({'type':'publish_version','version':published.get('version')})
                    _v42_iteration_update(project_id,run_id,status='done',stage='自动重训后已达标',result='pass',history=history,finished_at=now_iso());return
            else:
                _v42_iteration_update(project_id,run_id,status='needs_attention',stage='需要重训',result='blocked',history=history,error='策略关闭了自动重训',finished_at=now_iso());return
        _v42_iteration_update(project_id,run_id,status='done',stage='达到最大迭代轮数',result='not_passed',history=history,finished_at=now_iso())
    except Exception as e:
        _v42_iteration_update(project_id,run_id,status='failed',stage='迭代失败',result='failed',history=history,error=str(e),finished_at=now_iso())


def v42_iteration_runs(project_id: str):
    return _legacy_automation_service().v42_iteration_runs(project_id)


@app.post('/api/v42/projects/{project_id}/iteration-policies/{policy_id}/run')
def v42_run_policy(project_id:str,policy_id:str):
    get_project(project_id)
    _legacy_iteration_write_disabled()


app.include_router(create_legacy_automation_router_6(_legacy_automation_service))


def v42_quality_overview(project_id: str):
    return _legacy_automation_service().v42_quality_overview(project_id)


# ============================================================
# v42.4: single-pool dataset quality + algorithm quality + reports
# ============================================================
from platform_core.quality_analysis_contracts import V44QualityReq


def _v44_image_quality(project_id: str, images: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _quality_analysis_service()._v44_image_quality(project_id, images)


def _v44_dataset_quality(project_id: str, req: Optional[V44QualityReq]=None) -> Dict[str, Any]:
    return _quality_analysis_service()._v44_dataset_quality(project_id, req)

def _training_success_rate_stats(jobs: List[Dict[str, Any]]) -> Dict[str, Any]:
    success_statuses = {"done", "finished", "completed", "succeeded", "success"}
    ended_statuses = success_statuses | {"failed", "stopped", "cancelled", "canceled"}
    normalized = [str((job or {}).get("status") or "").strip().lower() for job in jobs]
    success_count = sum(1 for status in normalized if status in success_statuses)
    failure_count = sum(1 for status in normalized if status == "failed")
    ended_count = sum(1 for status in normalized if status in ended_statuses)
    return {
        "success_count": success_count,
        "failure_count": failure_count,
        "ended_count": ended_count,
        "success_rate": round(success_count / ended_count * 100, 1) if ended_count else None,
    }


from platform_core.quality_analysis_service import QualityAnalysisDependencies, QualityAnalysisService
from platform_core.quality_analysis_api import create_quality_analysis_router_1, create_quality_analysis_router_2


def _quality_analysis_service() -> QualityAnalysisService:
    return QualityAnalysisService(QualityAnalysisDependencies(
        MODEL_CONFIGS_FILE=lambda: MODEL_CONFIGS_FILE,
        _training_success_rate_stats=lambda *args, **kwargs: _training_success_rate_stats(*args, **kwargs),
        _v35_call_model=lambda *args, **kwargs: _v35_call_model(*args, **kwargs),
        _v35_is_vision_provider=lambda *args, **kwargs: _v35_is_vision_provider(*args, **kwargs),
        _v35_items=lambda *args, **kwargs: _v35_items(*args, **kwargs),
        _v44_labels_in_ann=lambda *args, **kwargs: _v44_labels_in_ann(*args, **kwargs),
        _write_job_json=lambda *args, **kwargs: _write_job_json(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        list_algorithms_internal=lambda *args, **kwargs: list_algorithms_internal(*args, **kwargs),
        list_jobs=lambda *args, **kwargs: list_jobs(*args, **kwargs),
        load_images=lambda *args, **kwargs: load_images(*args, **kwargs),
        material_store=lambda *args, **kwargs: material_store(*args, **kwargs),
        normalize_box_for_project=lambda *args, **kwargs: normalize_box_for_project(*args, **kwargs),
        normalize_label=lambda *args, **kwargs: normalize_label(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        read_annotation=lambda *args, **kwargs: read_annotation(*args, **kwargs),
        read_annotations_many=lambda *args, **kwargs: read_annotations_many(*args, **kwargs),
        read_json=lambda *args, **kwargs: read_json(*args, **kwargs),
        resolve_material_path=lambda *args, **kwargs: resolve_material_path(*args, **kwargs),
        sync_jobs_index=lambda *args, **kwargs: sync_jobs_index(*args, **kwargs),
        v35_test_model_config=lambda *args, **kwargs: v35_test_model_config(*args, **kwargs),
        v35_test_saved_model_annotation=lambda *args, **kwargs: v35_test_saved_model_annotation(*args, **kwargs),
    ))


app.include_router(create_quality_analysis_router_1(_quality_analysis_service))


def v44_quality_center(project_id: str):
    return _quality_analysis_service().v44_quality_center(project_id)

def v44_data_quality(project_id: str, payload: V44QualityReq):
    return _quality_analysis_service().v44_data_quality(project_id, payload)

def v44_test_saved_model_config(config_id: str):
    return _quality_analysis_service().v44_test_saved_model_config(config_id)

# Training report (v44) read/projection now lives in
# platform_core/training_report_api.py (router + legacy version-report
# composition). The thin bindings below stay in app.py only as legacy
# compatibility for callers/tests that patch these names.
from platform_core.training_report_api import (
    TrainingReportReader,
    create_training_report_router,
    training_history as _training_history_impl,
)


def _v45_training_history(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _training_history_impl(job)


_TRAINING_REPORT_READER = TrainingReportReader(
    get_project=lambda project_id: get_project(project_id),
    project_dir=lambda project_id: project_dir(project_id),
    algorithms_file=lambda project_id: algorithms_file(project_id),
   algorithm_repository=lambda project_id: algorithm_repository(project_id),
    data_dir=lambda: DATA_DIR,
    read_json=lambda path, default: read_json(path, default),
    enrich_job_runtime=lambda project_id, job, **kwargs: enrich_job_runtime(project_id, job, **kwargs),
    list_algorithms_internal=lambda project_id, algorithm_id=None: list_algorithms_internal(
        project_id, algorithm_id=algorithm_id
    ),
    durable_training_task=lambda project_id, task_id: _durable_training_task(project_id, task_id),
    task_repository=lambda: shared_task_repository(),
    task_artifacts=lambda: shared_task_artifacts(),
    # Late-bound: app.py keeps owning the results.csv history seam and every
    # accessor above that callers/tests already replace at runtime.
    training_history=lambda job: _v45_training_history(job),
    now_iso=lambda: now_iso(),
)
app.include_router(create_training_report_router(_TRAINING_REPORT_READER))


def v44_training_report(project_id: str, job_id: str, algorithm_id: str = '', version_id: str = '', reader_view: bool=False, history_offset: Optional[int]=None, history_limit: int=200):
    return _TRAINING_REPORT_READER.report(
        project_id, job_id, algorithm_id=algorithm_id, version_id=version_id,
        reader_view=reader_view, history_offset=history_offset, history_limit=history_limit,
    )


from platform_core.quality_analysis_contracts import V45ErrorCauseReq

app.include_router(create_quality_analysis_router_2(_quality_analysis_service))


def v45_error_cause_analysis(project_id: str, job_id: str, payload: V45ErrorCauseReq):
    return _quality_analysis_service().v45_error_cause_analysis(project_id, job_id, payload)

def v44_supplement_training_data(project_id: str, job_id: str):
    return _quality_analysis_service().v44_supplement_training_data(project_id, job_id)

# ============================================================
# v42.7: ordinary-user data curation + staged AI annotation
# ============================================================
from collections import defaultdict

from platform_core.material_governance_contracts import V47ImageEditReq

app.include_router(create_material_governance_router_6(_material_governance_service))


def v47_edit_image(project_id: str, image_id: str, payload: V47ImageEditReq):
    return _material_governance_service().v47_edit_image(project_id, image_id, payload)


def _v47_file_for(project_id: str, folder: str, task_id: str) -> Path:
    d = project_dir(project_id) / folder
    d.mkdir(parents=True, exist_ok=True)
    return d / f'{task_id}.json'


from platform_core.cleaning import (
    MemoryHashIndex as _V47MemoryHashIndex,
    clean_options as _v47_clean_options,
    dhash as _v47_dhash,
    hamming as _v47_hamming,
    image_metrics as _v47_image_metrics,
    metric_issues as _v47_metric_issues,
)


from platform_core.cleaning_management_contracts import V47CleanReq


from platform_core.cleaning_management_contracts import V47CleanConfirmReq


from platform_core.cleaning_management_contracts import V47CleanRuntimeReq


def _v47_run_clean_task(project_id: str, task_id: str, payload: Dict[str, Any]):
    try:
        _v33_update_task(
            project_id,
            'clean_tasks',
            task_id,
            status='running',
            status_text='清洗检查中',
            stage='scanning',
            progress=0,
            started_at=now_iso(),
        )
        wanted = set(str(x) for x in (payload.get('image_ids') or []))
        images = load_images(project_id)
        if wanted:
            images = [x for x in images if str(x.get('id')) in wanted]
        if not images:
            raise RuntimeError('没有可清洗的图片')
        total = len(images)
        rows: List[Dict[str, Any]] = []
        hash_index = _V47MemoryHashIndex()
        started = time.time()
        last_saved_count = 0
        last_saved_at = time.monotonic()
        pdir = project_dir(project_id)
        for idx, img in enumerate(images, 1):
            cur = _v33_get_task(project_id, 'clean_tasks', task_id) or {}
            if cur.get('stop_requested'):
                _v33_update_task(
                    project_id,
                    'clean_tasks',
                    task_id,
                    status='stopped',
                    status_text='已停止',
                    stage='stopped',
                    finished_at=now_iso(),
                )
                return
            issues: List[Dict[str, Any]] = []
            metrics: Dict[str, Any] = {}
            try:
                path = resolve_material_path(project_id, img)
                metrics = _v47_image_metrics(path)
                issues, near_indexed = _v47_metric_issues(metrics, payload, str(img.get('id')), hash_index)
                hash_index.remember(str(img.get('id')), metrics, near_indexed)
            except Exception as e:
                if payload.get('corrupt_check'):
                    issues.append({'code': 'corrupt', 'name': '图片损坏', 'detail': str(e)[:180]})
            if issues:
                rows.append({'image_id': img.get('id'), 'filename': img.get('filename'), 'url': img.get('url'), 'issues': issues, 'metrics': metrics, 'suggest_delete': True})
            now_mono = time.monotonic()
            if idx == total or idx - last_saved_count >= 50 or now_mono - last_saved_at >= 0.5:
                elapsed = max(0.001, time.time() - started)
                eta = int(max(0, elapsed / idx * (total - idx)))
                _v33_update_task(
                    project_id,
                    'clean_tasks',
                    task_id,
                    stage='scanning',
                    processed_images=idx,
                    total_images=total,
                    flagged_images=len(rows),
                    progress=int(idx / total * 100),
                    elapsed_seconds=int(elapsed),
                    eta_seconds=eta,
                    heartbeat_at=now_iso(),
                )
                last_saved_count = idx
                last_saved_at = now_mono
        result_path = _v47_file_for(project_id, 'clean_results', task_id)
        write_json(result_path, {'task_id': task_id, 'items': rows, 'generated_at': now_iso(), 'rules': payload})
        _v33_update_task(
            project_id,
            'clean_tasks',
            task_id,
            status='awaiting_confirmation',
            status_text='待确认',
            stage='review',
            progress=100,
            processed_images=total,
            total_images=total,
            flagged_images=len(rows),
            result_file=str(result_path),
            finished_scan_at=now_iso(),
        )
    except Exception as e:
        _v33_update_task(
            project_id,
            'clean_tasks',
            task_id,
            status='failed',
            status_text='失败',
            stage='failed',
            error=str(e),
            finished_at=now_iso(),
        )


from platform_core.cleaning_management_service import CleaningManagementDependencies, CleaningManagementService
from platform_core.cleaning_management_api import create_cleaning_management_router_1, create_cleaning_management_router_2


def _cleaning_management_service() -> CleaningManagementService:
    return CleaningManagementService(CleaningManagementDependencies(
        _require_material_delete_preview=lambda *args, **kwargs: _require_material_delete_preview(*args, **kwargs),
        _v33_get_task=lambda *args, **kwargs: _v33_get_task(*args, **kwargs),
        _v33_load_tasks=lambda *args, **kwargs: _v33_load_tasks(*args, **kwargs),
        _v47_clean_agent_preflight=lambda *args, **kwargs: _v47_clean_agent_preflight(*args, **kwargs),
        _v47_clean_compat_task=lambda *args, **kwargs: _v47_clean_compat_task(*args, **kwargs),
        _v47_material_batch_request=lambda *args, **kwargs: _v47_material_batch_request(*args, **kwargs),
        _v62_prepare_clean_compat=lambda *args, **kwargs: _v62_prepare_clean_compat(*args, **kwargs),
        _v62_publish_clean_compat=lambda *args, **kwargs: _v62_publish_clean_compat(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        material_store=lambda *args, **kwargs: material_store(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        public_material=lambda *args, **kwargs: public_material(*args, **kwargs),
        shared_task_artifacts=lambda *args, **kwargs: shared_task_artifacts(*args, **kwargs),
        shared_task_repository=lambda *args, **kwargs: shared_task_repository(*args, **kwargs),
    ))


app.include_router(create_cleaning_management_router_1(_cleaning_management_service))


def v47_list_clean_tasks(project_id: str):
    return _cleaning_management_service().v47_list_clean_tasks(project_id)



def _v47_clean_execution_mode(value: Any) -> str:
    mode = str(value or 'local').strip().lower()
    if mode not in {'local', 'agent'}:
        raise ValueError('清洗执行方式仅支持 local 或 agent')
    return mode


def _v47_clean_required_capabilities(request: Dict[str, Any]) -> Tuple[str, ...]:
    if (
        str(request.get('operation') or '').upper() == MaterialBatchOperation.CLEAN.value
        and str(request.get('execution_mode') or 'local').lower() == 'agent'
    ):
        return ('agent.remote',)
    return ('materials.batch',)


_V47_CLEAN_SCOPE_STATES = {
    'all': None,
    'annotated': 'annotated',
    'unannotated': 'unannotated',
    'confirmed_empty': 'confirmed_empty',
}


def _v47_clean_selection_spec(
    clean_scope: str = 'all',
    image_ids: Optional[List[str]] = None,
    selection_spec: Optional[Dict[str, Any]] = None,
    selection_mode: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    selected = list(dict.fromkeys(
        str(value).strip() for value in (image_ids or []) if str(value).strip()
    ))
    scope = str(clean_scope or 'all').strip().lower()
    if selection_spec is not None:
        raw = dict(selection_spec)
        raw_filters = dict(raw.get('filters') or {})
        requested_state = _V47_CLEAN_SCOPE_STATES.get(scope)
        supplied_state = str(raw_filters.get('annotation_state') or '').strip().lower() or None
        if scope not in _V47_CLEAN_SCOPE_STATES:
            raise ValueError('规范化素材范围不能再使用旧版 selected 清洗范围')
        if requested_state and supplied_state and requested_state != supplied_state:
            raise ValueError('清洗标注状态与素材选择条件不一致')
        if requested_state:
            raw_filters['annotation_state'] = requested_state
        raw['filters'] = raw_filters
        try:
            normalized = MaterialSelectionSpec.from_mapping(raw, allow_filtered_exclusions=True)
        except (TypeError, ValueError) as error:
            raise ValueError(str(error)) from error
        if normalized.scope is SelectionScope.FILTERED:
            inferred_scope = 'labels' if normalized.filters.labels else (
                normalized.filters.annotation_state or 'all'
            )
        else:
            inferred_scope = 'selected'
        primary = str(selection_mode or '').strip().lower()
        if primary and primary not in {'all', 'selected', 'labels'}:
            raise ValueError('未知清洗主要范围')
        if primary == 'labels' and not normalized.filters.labels:
            raise ValueError('选定标签范围至少需要一个有效标签')
        if primary == 'labels' and normalized.scope is not SelectionScope.FILTERED:
            raise ValueError('选定标签范围必须使用服务端筛选条件')
        if primary == 'all' and (
            normalized.scope is not SelectionScope.FILTERED or normalized.filters.labels
        ):
            raise ValueError('全部图片范围不能伪装为指定图片或标签范围')
        normalized_scope = primary or inferred_scope
        return normalized.as_dict(), normalized_scope
    if selected:
        if scope not in {'all', 'selected'}:
            raise ValueError('当前选中图片不能同时叠加标注状态清洗范围')
        return {'scope': 'SELECTED', 'image_ids': selected}, 'selected'
    if scope == 'selected':
        raise ValueError('当前没有选中的图片')
    if scope not in _V47_CLEAN_SCOPE_STATES:
        raise ValueError('未知清洗范围')
    annotation_state = _V47_CLEAN_SCOPE_STATES[scope]
    filters = {'annotation_state': annotation_state} if annotation_state else {}
    return {'scope': 'FILTERED', 'filters': filters}, scope


def _v47_validate_clean_selection_labels(project_id: str, selection: Dict[str, Any]) -> None:
    labels = list(dict.fromkeys(
        str(value).strip()
        for value in ((selection.get('filters') or {}).get('labels') or [])
        if str(value).strip()
    ))
    if not labels:
        return
    active_codes = {
        str(item.get('code') or '').strip()
        for item in active_label_options(project_label_items(get_project(project_id)))
        if str(item.get('code') or '').strip()
    }
    unknown = [label for label in labels if label not in active_codes]
    if unknown:
        raise ValueError('清洗范围只能使用当前有效正式标签：' + '、'.join(unknown[:20]))


def _v47_clean_agent_preflight(
    project_id: str,
    image_ids: Optional[List[str]] = None,
    clean_scope: str = 'all',
    selection_spec: Optional[Dict[str, Any]] = None,
    selection_mode: Optional[str] = None,
) -> Dict[str, Any]:
    get_project(project_id)
    try:
        selection, normalized_scope = _v47_clean_selection_spec(clean_scope, image_ids, selection_spec, selection_mode)
        _v47_validate_clean_selection_labels(project_id, selection)
    except ValueError as error:
        return {
            'agent_available': False,
            'reason': str(error),
            'selected_count': 0,
            'eligible_nodes': [],
        }
    selected = list(selection.get('image_ids') or [])
    materials = material_store(project_id)
    spec = (
        MaterialSelectionSpec.from_mapping(selection, allow_filtered_exclusions=True)
        if selection.get('scope') == 'FILTERED' else None
    )
    clauses, params = spec.filtered_predicate(materials) if spec else materials._filters(selection.get('filters') or {})
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    with closing(materials._connect()) as database:
        database.execute('BEGIN')
        revision = materials._revision(database)
        if spec and spec.excluded_image_ids and spec.repository_revision is not None and spec.repository_revision != revision:
            return {
                'agent_available': False,
                'reason': '素材范围已变化，请重新核对清洗范围',
                'selected_count': 0,
                'eligible_nodes': [],
            }
        join = ''
        existing_selected = len(selected)
        if selected:
            database.execute(
                "CREATE TEMP TABLE clean_preflight_selection ("
                "image_id TEXT PRIMARY KEY) WITHOUT ROWID"
            )
            database.executemany(
                "INSERT INTO clean_preflight_selection(image_id) VALUES (?)",
                ((image_id,) for image_id in selected),
            )
            join = " JOIN clean_preflight_selection s ON s.image_id=m.id"
            existing_selected = int(database.execute(
                "SELECT COUNT(*) FROM materials m" + join
            ).fetchone()[0])
        row = database.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(CASE WHEN trim(object_key)='' OR length(trim(content_sha256))<>64 "
            "OR size_bytes<=0 THEN 1 ELSE 0 END),0) AS incomplete "
            "FROM materials m" + join + where,
            params,
        ).fetchone()
        total = int(row['total'] or 0)
        incomplete = int(row['incomplete'] or 0)
        sources = database.execute(
            "SELECT storage_source_id,storage_type,COUNT(*) AS total "
            "FROM materials m" + join + where + " GROUP BY storage_source_id,storage_type "
            "ORDER BY storage_source_id",
            params,
        ).fetchall()

    if selected and existing_selected != len(selected):
        return {
            'agent_available': False,
            'reason': '所选素材已发生变化，请刷新后重新选择',
            'selected_count': total,
            'repository_revision': revision,
            'eligible_nodes': [],
        }
    if total <= 0:
        return {
            'agent_available': False,
            'reason': '当前清洗范围没有可处理素材',
            'selected_count': 0,
            'clean_scope': normalized_scope,
            'eligible_nodes': [],
        }
    if incomplete:
        return {
            'agent_available': False,
            'reason': f'有 {incomplete} 张素材缺少对象存储大小或 SHA256 证据',
            'selected_count': total,
            'repository_revision': revision,
            'clean_scope': normalized_scope,
            'eligible_nodes': [],
        }

    source_repo = storage_source_repository()
    source_truth = []
    for row in sources:
        source_id = str(row['storage_source_id'] or '')
        configured = source_repo.get(source_id)
        try:
            storage_type = StorageType.parse(configured.type if configured is not None else row['storage_type'])
        except ValueError:
            storage_type = None
        portable = bool(
            configured is not None
            and configured.enabled
            and storage_type in {StorageType.OSS, StorageType.S3}
        )
        source_truth.append({
            'storage_source_id': source_id,
            'storage_type': storage_type.value if storage_type is not None else str(row['storage_type'] or ''),
            'count': int(row['total'] or 0),
            'portable': portable,
        })
    blocked = [row for row in source_truth if not row['portable']]
    if blocked:
        names = '、'.join(row['storage_source_id'] or 'default_local' for row in blocked[:3])
        return {
            'agent_available': False,
            'reason': f'本次范围包含不可远程读取的素材存储：{names}',
            'selected_count': total,
            'repository_revision': revision,
            'sources': source_truth,
            'eligible_nodes': [],
        }

    repository = shared_task_repository()
    artifacts = shared_task_artifacts()
    allocator = CentralTaskAllocator(repository, artifacts)
    nodes = [
        node for node in ServiceNodeRepository(repository).list_public()
        if str(node.get('connection_mode') or '') == 'agent'
        and bool(node.get('online'))
        and 'cleaning' in set(node.get('effective_capabilities') or [])
    ]
    active_assignments = allocator.list(active_only=True)
    assignments_by_node: Dict[str, List[Dict[str, Any]]] = {}
    for assignment in active_assignments:
        assignments_by_node.setdefault(str(assignment.get('node_id') or ''), []).append(assignment)
    executions_by_node: Dict[str, List[str]] = {}
    with repository._connect() as database:
        rows = database.execute(
            """
            SELECT task_id,worker_id FROM tasks
             WHERE status IN ('RUNNING','CANCEL_REQUESTED')
               AND worker_id LIKE 'agent:%'
             ORDER BY updated_at,task_id
            """
        ).fetchall()
    for row in rows:
        worker_id = str(row['worker_id'] or '')
        node_id = worker_id.removeprefix('agent:')
        if node_id and worker_id.startswith('agent:'):
            executions_by_node.setdefault(node_id, []).append(str(row['task_id']))
    if not nodes:
        return {
            'agent_available': False,
            'reason': '当前没有在线且已授权 cleaning 能力的 Agent 节点',
            'selected_count': total,
            'repository_revision': revision,
            'sources': source_truth,
            'eligible_nodes': [],
        }

    try:
        _remote_execution_transport_service().build_cleaning_remote_contract(
            project_id,
            'cleaning-preflight',
        )
    except RemoteExecutionTransportError as error:
        return {
            'agent_available': False,
            'reason': str(error),
            'selected_count': total,
            'repository_revision': revision,
            'sources': source_truth,
            'eligible_nodes': [],
        }

    def scheduling_task_row(task: TaskRecord) -> Dict[str, Any]:
        request = artifacts.read_json(task.task_id, task.payload_ref, default={}) or {}
        operation = str(request.get('operation') or '').strip().upper() if isinstance(request, dict) else ''
        return {
            'task_id': task.task_id,
            'kind': task.kind.value,
            'operation': operation,
            'status': task.status.value,
            'stage': task.stage,
            'progress': float(task.progress or 0),
            'preemptible': task.status is not TaskStatus.RUNNING or task_preemptible(task, artifacts),
        }

    eligible_nodes = []
    for node in nodes:
        node_id = str(node.get('node_id') or '')
        tasks_by_id: Dict[str, Dict[str, Any]] = {}
        for task_id in executions_by_node.get(node_id, []):
            task = repository.get(task_id)
            if task is not None:
                tasks_by_id[task.task_id] = scheduling_task_row(task)
        for assignment in assignments_by_node.get(node_id, []):
            task = repository.get(str(assignment.get('task_id') or ''))
            if task is not None:
                tasks_by_id.setdefault(task.task_id, scheduling_task_row(task))
        task_rows = list(tasks_by_id.values())
        can_preempt = all(
            row.get('status') != TaskStatus.RUNNING.value or bool(row.get('preemptible'))
            for row in task_rows
        )
        resources = dict(node.get('resources') or {})
        eligible_nodes.append({
            'node_id': node_id,
            'display_name': str(node.get('display_name') or node_id),
            'build_id': str(node.get('build_id') or ''),
            'status': str(node.get('status') or ''),
            'idle': not task_rows,
            'active_count': len(task_rows),
            'active_tasks': task_rows[:6],
            'preemptible': bool(task_rows) and can_preempt,
            'resources': {
                'cpu': dict(resources.get('cpu') or {}),
                'memory': dict(resources.get('memory') or {}),
                'disk': dict(resources.get('disk') or {}),
            },
        })
    eligible_nodes.sort(key=lambda row: (not bool(row['idle']), int(row['active_count']), row['display_name'].lower()))
    return {
        'agent_available': True,
        'reason': '',
        'selected_count': total,
            'repository_revision': revision,
        'sources': source_truth,
        'eligible_nodes': eligible_nodes,
        'idle_nodes': sum(1 for row in eligible_nodes if row['idle']),
        'busy_nodes': sum(1 for row in eligible_nodes if not row['idle']),
        'label_counts': materials.label_usage(),
    }


def v47_clean_runtime_preflight(project_id: str, payload: V47CleanRuntimeReq):
    return _cleaning_management_service().v47_clean_runtime_preflight(project_id, payload)


def _v47_clean_scheduling(
    execution_mode: str,
    scheduling_mode: str,
    target_node_id: str,
    queue_policy: str,
) -> Dict[str, str]:
    mode = str(scheduling_mode or 'auto').strip().lower()
    node_id = str(target_node_id or '').strip()
    policy = str(queue_policy or 'normal').strip().lower()
    if execution_mode != 'agent':
        if mode != 'auto' or node_id or policy != 'normal':
            raise ValueError('指定节点、插队或抢占仅适用于远程 Agent 清洗')
        return {'mode': 'auto', 'node_id': '', 'queue_policy': 'normal'}
    if mode == 'auto':
        if node_id or policy != 'normal':
            raise ValueError('自动调度不能同时指定节点或插队策略')
        return {'mode': 'auto', 'node_id': '', 'queue_policy': 'normal'}
    if mode != 'node' or not node_id:
        raise ValueError('指定节点清洗必须选择一个 cleaning Agent')
    if policy not in {'normal', 'front', 'preempt'}:
        raise ValueError('未知清洗队列策略')
    return {'mode': 'node', 'node_id': node_id, 'queue_policy': policy}


def _v47_material_batch_payload(project_id: str, payload: V47CleanReq) -> Dict[str, Any]:
    data = payload.model_dump() if hasattr(payload, 'model_dump') else payload.dict()
    image_ids = list(dict.fromkeys(str(x) for x in (data.pop('image_ids', None) or []) if str(x)))
    requested_selection = data.pop('selection_spec', None)
    selection_mode = str(data.pop('selection_mode', '') or '') or None
    clean_scope = str(data.pop('clean_scope', 'all') or 'all')
    execution_mode = _v47_clean_execution_mode(data.pop('execution_mode', 'local'))
    scheduling = _v47_clean_scheduling(
        execution_mode,
        data.pop('scheduling_mode', 'auto'),
        data.pop('target_node_id', ''),
        data.pop('queue_policy', 'normal'),
    )
    # Use the same CLEAN option owner as material_batches.parse_request().
    # Prepared durable requests persist canonical defaults, so retries must
    # compare against that canonical shape rather than raw V47 payload fields.
    data = _v47_clean_options(data)
    selection, _normalized_scope = _v47_clean_selection_spec(
        clean_scope, image_ids, requested_selection, selection_mode,
    )
    _v47_validate_clean_selection_labels(project_id, selection)
    draft = {'operation': MaterialBatchOperation.CLEAN.value, 'selection_spec': selection, 'options': data, 'scheduling': scheduling}
    estimate = estimate_material_batch(project_id, material_store(project_id), draft)
    if selection.get('excluded_image_ids') and (
        selection.get('repository_revision') != estimate['repository_revision'] or not estimate['count']
    ):
        raise ValueError('素材范围已变化或为空，请重新核对清洗范围')
    draft['selection_spec'] = estimate['selection_spec']
    if execution_mode == 'agent':
        draft['execution_mode'] = 'agent'
    return draft


def _v47_material_batch_request(task_id: str) -> Dict[str, Any]:
    return shared_task_artifacts().read_json(task_id, 'request.json', default={}) or {}


def _v47_clean_compat_task(task: TaskRecord) -> Dict[str, Any]:
    repository = shared_task_repository()
    artifacts = shared_task_artifacts()
    body = public_material_batch(task, artifacts, repository if repository.get(task.task_id) is not None else None)
    request = _v47_material_batch_request(task.task_id)
    options = dict(request.get('options') or {})
    selection = dict(request.get('selection_spec') or {})
    selection_scope = str(selection.get('scope') or '').upper()
    selection_filters = dict(selection.get('filters') or {})
    clean_scope = (
        'selected'
        if selection_scope != 'FILTERED'
        else ('labels' if selection_filters.get('labels') else str(selection_filters.get('annotation_state') or 'all').lower())
    )
    scheduling = dict(request.get('scheduling') or {'mode': 'auto', 'node_id': '', 'queue_policy': 'normal'})
    request_payload = {
        **options,
        'image_ids': list(selection.get('image_ids') or []),
        'clean_scope': clean_scope,
        'selection_spec': selection,
        'scheduling': scheduling,
    }
    scheduling_event = artifacts.read_json(task.task_id, 'scheduling.json', default={}) or {}
    confirmed = artifacts.read_json(task.task_id, 'clean_confirmation.json', default=None)
    public_status = str(body.get('status') or task.status.value)
    execution_mode = str(request.get('execution_mode') or 'local').lower()
    if public_status in {'QUEUED', 'WAITING_RESOURCE'}:
        status = 'queued'
        if public_status == 'WAITING_RESOURCE' and execution_mode == 'agent':
            status_text = '等待远程清洗节点'
        else:
            status_text = '等待资源' if public_status == 'WAITING_RESOURCE' else '排队中'
    elif public_status == 'RUNNING':
        status, status_text = 'running', '清洗中'
    elif public_status == 'CANCEL_REQUESTED':
        status, status_text = 'running', '正在停止'
    elif public_status == 'CANCELLED':
        status, status_text = 'cancelled', '已停止'
    elif public_status == 'SUCCEEDED':
        status, status_text = ('done', '已确认') if confirmed else ('awaiting_confirmation', '待确认')
    elif public_status == 'PARTIAL_SUCCESS':
        status, status_text = 'failed', '部分失败，请重试'
    elif public_status in {'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE'}:
        status, status_text = 'failed', '运行环境不可用'
    else:
        status, status_text = 'failed', '失败'
    return {
        'id': task.task_id,
        'name': options.get('task_name') or '自动清洗任务',
        'status': status,
        'status_text': status_text,
        'stage': 'review' if status == 'awaiting_confirmation' else body.get('phase'),
        'progress': body.get('progress_percent') or 0,
        'processed_images': body.get('processed') or 0,
        'total_images': body.get('total') or 0,
        'flagged_images': body.get('flagged') or 0,
        'created_at': body.get('created_at'),
        'finished_at': body.get('finished_at'),
        'request_payload': request_payload,
        'resource_queue_position': body.get('resource_queue_position'),
        'resource_queue_position_exact': bool(body.get('resource_queue_position_exact')),
        'resource_wait_reason': body.get('resource_wait_reason'),
        'worker_id': body.get('worker_id'),
        'lease_expires_at': body.get('lease_expires_at'),
        'current_item': body.get('current_item'),
        'durable_task_kind': TaskKind.MATERIAL_BATCH.value,
        'execution_mode': execution_mode,
        'clean_scope': clean_scope,
        'scheduling': scheduling,
        'scheduling_event': scheduling_event,
    }


def _v47_list_durable_clean_tasks(project_id: str) -> List[Dict[str, Any]]:
    repository = shared_task_repository()
    page = repository.list(project_id=project_id, kinds={TaskKind.MATERIAL_BATCH}, limit=100)
    rows = []
    for task in page.items:
        request = _v47_material_batch_request(task.task_id)
        if request.get('operation') == MaterialBatchOperation.CLEAN.value:
            rows.append(_v47_clean_compat_task(task))
    return rows


def _v62_prepare_clean_compat(project_id: str, payload: V47CleanReq, task_id: Optional[str] = None) -> Tuple[Dict[str, Any], bool]:
    get_project(project_id)
    requested_id = str(task_id or uuid.uuid4().hex[:12])
    repository = shared_task_repository()
    existing = repository.get(requested_id)
    if existing is not None:
        if existing.project_id != project_id or existing.kind is not TaskKind.MATERIAL_BATCH:
            raise ValueError('清洗任务 ID 已被其他任务占用')
        request = _v47_material_batch_request(requested_id)
        if request.get('operation') != MaterialBatchOperation.CLEAN.value:
            raise ValueError('清洗任务 ID 已被其他批处理占用')
        return _v47_clean_compat_task(existing), False

    batch_payload = _v47_material_batch_payload(project_id, payload)
    if str(batch_payload.get('execution_mode') or 'local') == 'agent':
        preflight = _v47_clean_agent_preflight(
            project_id, payload.image_ids, payload.clean_scope, payload.selection_spec, payload.selection_mode,
        )
        if not preflight.get('agent_available'):
            raise ValueError(str(preflight.get('reason') or '远程清洗当前不可用'))
        scheduling = dict(batch_payload.get('scheduling') or {})
        if str(scheduling.get('mode') or 'auto') == 'node':
            eligible = {
                str(node.get('node_id') or '')
                for node in preflight.get('eligible_nodes') or []
            }
            if str(scheduling.get('node_id') or '') not in eligible:
                raise ValueError('指定节点当前不在线、未启用 cleaning 服务或不满足远程清洗条件')
        batch_payload['remote_execution'] = (
            _remote_execution_transport_service().build_cleaning_remote_contract(
                project_id,
                requested_id,
            )
        )
    prepared_request = _v47_material_batch_request(requested_id)
    if prepared_request:
        def semantic_request(value: Dict[str, Any]) -> Dict[str, Any]:
            value = dict(value or {})
            selection = dict(value.get('selection_spec') or {})
            selection.pop('repository_revision', None)
            return {
                'operation': value.get('operation'),
                'selection_spec': selection,
                'options': dict(value.get('options') or {}),
                'execution_mode': str(value.get('execution_mode') or 'local'),
                'scheduling': dict(value.get('scheduling') or {}),
            }

        if semantic_request(prepared_request) != semantic_request(batch_payload):
            raise ValueError('清洗任务 ID 已关联不同请求')
        prepared = TaskRecord.new(
            requested_id, project_id, TaskKind.MATERIAL_BATCH, 'request.json',
            f'materials:{project_id}',
            required_capabilities=_v47_clean_required_capabilities(prepared_request),
        )
        return _v47_clean_compat_task(prepared), False

    prepared = prepare_material_batch(
        project_id,
        material_store(project_id),
        shared_task_artifacts(),
        batch_payload,
        task_id=requested_id,
    )
    return _v47_clean_compat_task(prepared), True

def _v62_publish_clean_compat(project_id: str, task_id: str) -> Dict[str, Any]:
    with _storage_source_fence():
        repository = shared_task_repository()
        existing = repository.get(task_id)
        if existing is not None:
            compat = _v47_clean_compat_task(existing)
            if compat.get('status') == 'failed':
                existing = repository.retry(task_id)
            return _v47_clean_compat_task(existing)
        request = _v47_material_batch_request(task_id)
        if request.get('operation') != MaterialBatchOperation.CLEAN.value:
            raise ValueError('清洗任务尚未准备完成')
        prepared = TaskRecord.new(
            task_id, project_id, TaskKind.MATERIAL_BATCH, 'request.json',
            f'materials:{project_id}',
            required_capabilities=_v47_clean_required_capabilities(request),
        )
        published = publish_prepared_material_batch(
            prepared, repository, shared_task_artifacts(),
        )
        return _v47_clean_compat_task(published)


def _v47_durable_clean_results(task_id: str, project_id: Optional[str]=None) -> Dict[str, Any]:
    return _cleaning_management_service()._v47_durable_clean_results(task_id, project_id)


def _v47_durable_annotation_audit(task_id: str, project_id: Optional[str]=None, *, cursor: str='', limit: int=100, page: Optional[int]=None, page_size: int=20) -> Dict[str, Any]:
    return _cleaning_management_service()._v47_durable_annotation_audit(task_id, project_id, cursor=cursor, limit=limit, page=page, page_size=page_size)

def _v47_frozen_clean_selection_ids(task_id: str) -> List[str]:
    return _cleaning_management_service()._v47_frozen_clean_selection_ids(task_id)

def _v47_validate_clean_confirmation(project_id: str, task_id: str, *, skip_image_ids=()) -> set[str]:
    return _cleaning_management_service()._v47_validate_clean_confirmation(project_id, task_id, skip_image_ids=skip_image_ids)


_V47_ACTIVE_CLEAN_WORKERS: set[Tuple[str, str]] = set()


def _v47_prepare_clean_task_record(
    project_id: str,
    payload: V47CleanReq,
    task_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], bool]:
    get_project(project_id)
    task_id = task_id or uuid.uuid4().hex[:12]
    data = payload.model_dump() if hasattr(payload, 'model_dump') else payload.dict()
    images = load_images(project_id)
    wanted = set(data.get('image_ids') or [])
    total = len([x for x in images if not wanted or x.get('id') in wanted])
    task = {'id': task_id, 'name': data.get('task_name') or '自动清洗任务', 'status': 'prepared', 'status_text': '已准备', 'progress': 0, 'processed_images': 0, 'total_images': total, 'flagged_images': 0, 'created_at': now_iso(), 'request_payload': data, 'stop_requested': False}
    with _v33_task_lock:
        tasks = read_json(_v33_tasks_file(project_id, 'clean_tasks'), [])
        existing = next(
            (item for item in tasks if str(item.get('id')) == task_id),
            None,
        )
        if existing is not None:
            if (existing.get('request_payload') or {}) != data:
                raise ValueError('清洗任务 ID 已关联不同请求')
            return dict(existing), False
        tasks.insert(0, task)
        atomic_write_json(_v33_tasks_file(project_id, 'clean_tasks'), tasks[:100])
    return dict(task), True


def _v47_remove_prepared_clean_task_record(project_id: str, task_id: str) -> bool:
    key = (str(project_id), str(task_id))
    with _v33_task_lock:
        if key in _V47_ACTIVE_CLEAN_WORKERS:
            return False
        tasks = read_json(_v33_tasks_file(project_id, 'clean_tasks'), [])
        target = next(
            (item for item in tasks if str(item.get('id')) == str(task_id)),
            None,
        )
        if target is None or target.get('status') not in {'prepared', 'queued'}:
            return False
        atomic_write_json(
            _v33_tasks_file(project_id, 'clean_tasks'),
            [item for item in tasks if str(item.get('id')) != str(task_id)],
        )
        return True


def _v47_reset_failed_clean_task_record(project_id: str, task_id: str) -> bool:
    """Put a failed upload-batch cleaning task back into a retryable state."""
    with _v33_task_lock:
        tasks = read_json(_v33_tasks_file(project_id, 'clean_tasks'), [])
        target = next(
            (item for item in tasks if str(item.get('id')) == str(task_id)),
            None,
        )
        if target is None or target.get('status') != 'failed':
            return False
        target.update({
            'status': 'prepared',
            'status_text': '已准备（重试）',
            'progress': 0,
            'processed_images': 0,
            'flagged_images': 0,
            'updated_at': now_iso(),
            'stop_requested': False,
        })
        for field in (
            'error', 'result_file', 'started_at', 'finished_at',
            'finished_scan_at', 'elapsed_seconds', 'eta_seconds',
        ):
            target.pop(field, None)
        atomic_write_json(_v33_tasks_file(project_id, 'clean_tasks'), tasks)
        return True


def _v47_restore_clean_task_record(
    project_id: str,
    task_id: str,
    snapshot: Optional[Dict[str, Any]],
) -> bool:
    """Restore a task snapshot when publishing a retry cannot be completed."""
    if not snapshot:
        return False
    key = (str(project_id), str(task_id))
    with _v33_task_lock:
        if key in _V47_ACTIVE_CLEAN_WORKERS:
            return False
        tasks = read_json(_v33_tasks_file(project_id, 'clean_tasks'), [])
        for index, item in enumerate(tasks):
            if str(item.get('id')) == str(task_id):
                tasks[index] = dict(snapshot)
                atomic_write_json(_v33_tasks_file(project_id, 'clean_tasks'), tasks)
                return True
    return False


def _v47_start_clean_task_record(project_id: str, task_id: str) -> Dict[str, Any]:
    key = (str(project_id), str(task_id))
    with _v33_task_lock:
        tasks = read_json(_v33_tasks_file(project_id, 'clean_tasks'), [])
        task = next(
            (item for item in tasks if str(item.get('id')) == str(task_id)),
            None,
        )
        if task is None:
            raise ValueError('清洗任务不存在')
        if key in _V47_ACTIVE_CLEAN_WORKERS:
            return dict(task)
        if task.get('status') not in {'prepared', 'queued', 'running'}:
            return dict(task)
        task['status'] = 'queued'
        task['status_text'] = '排队中'
        task['updated_at'] = now_iso()
        atomic_write_json(_v33_tasks_file(project_id, 'clean_tasks'), tasks)
        _V47_ACTIVE_CLEAN_WORKERS.add(key)
        queued = dict(task)
        data = dict(task.get('request_payload') or {})

    def run_and_release():
        try:
            _v47_run_clean_task(project_id, task_id, data)
        finally:
            with _v33_task_lock:
                _V47_ACTIVE_CLEAN_WORKERS.discard(key)

    worker = threading.Thread(target=run_and_release, daemon=True)
    try:
        worker.start()
    except Exception:
        with _v33_task_lock:
            _V47_ACTIVE_CLEAN_WORKERS.discard(key)
        raise
    return queued


def _v47_recover_clean_tasks(project_id: str) -> list[str]:
    get_project(project_id)
    return []


def _v47_create_clean_task_record(
    project_id: str,
    payload: V47CleanReq,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    task, _ = _v47_prepare_clean_task_record(project_id, payload, task_id)
    return _v47_start_clean_task_record(project_id, str(task.get('id')))


def _v47_apply_clean_scheduling(task_id: str) -> Dict[str, Any]:
    return _cleaning_management_service()._v47_apply_clean_scheduling(task_id)


def v47_create_clean_task(project_id: str, payload: V47CleanReq):
    return _cleaning_management_service().v47_create_clean_task(project_id, payload)


from platform_core.material_ingestion_contracts import V55UploadDecisionsReq


def _v55_read_upload_batch(
    store: UploadBatchStore,
    batch_id: str,
    *,
    locked: bool = False,
) -> Dict[str, Any]:
    try:
        return store._read_unlocked(batch_id) if locked else store.read(batch_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail='上传批次不存在')


def _v55_enrich_upload_batch(project_id: str, batch: Dict[str, Any]) -> Dict[str, Any]:
    return _material_ingestion_service()._v55_enrich_upload_batch(project_id, batch)


def _v55_upload_clean_task_id(project_id: str, batch_id: str, image_ids: List[str]) -> str:
    return _material_ingestion_service()._v55_upload_clean_task_id(project_id, batch_id, image_ids)


app.include_router(create_material_ingestion_router_4(_material_ingestion_service))


def v55_get_upload_batch(project_id: str, batch_id: str):
    return _material_ingestion_service().v55_get_upload_batch(project_id, batch_id)


def v55_apply_upload_batch_decisions(project_id: str, batch_id: str, payload: V55UploadDecisionsReq):
    return _material_ingestion_service().v55_apply_upload_batch_decisions(project_id, batch_id, payload)


app.include_router(create_cleaning_management_router_2(_cleaning_management_service))


def v47_stop_clean_task(project_id: str, task_id: str):
    return _cleaning_management_service().v47_stop_clean_task(project_id, task_id)


def v47_clean_result(project_id: str, task_id: str):
    return _cleaning_management_service().v47_clean_result(project_id, task_id)


def v47_clean_annotation_audit(project_id: str, task_id: str, cursor: str='', limit: int=100, page: Optional[int]=Query(default=None, ge=1), page_size: int=Query(default=20, ge=1, le=100)):
    return _cleaning_management_service().v47_clean_annotation_audit(project_id, task_id, cursor, limit, page, page_size)


def v47_confirm_clean(project_id: str, task_id: str, payload: V47CleanConfirmReq):
    return _cleaning_management_service().v47_confirm_clean(project_id, task_id, payload)


class V47AutoLabelReq(BaseModel):
    image_ids: List[str]
    labels_text: Optional[str] = ''
    reference_image_ids: Optional[List[str]] = None
    threshold: float = 0.45
    overwrite: bool = False
    task_name: str = 'AI自动标注任务'
    provider_id: Optional[str] = None
    model_config_id: Optional[str] = None
    prompt_template_id: Optional[str] = None
    business_instruction: str = ''
    preview_count: int = 0

class V47AutoLabelConfirmReq(BaseModel):
    image_ids: Optional[List[str]] = None


from platform_core.ai_annotation_contracts import AnnotationTaskCreateReq


from platform_core.ai_annotation_contracts import AnnotationDecisionReq


def _v47_parse_label_text(
    text: str,
    catalog: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    import re
    values = list(dict.fromkeys(
        str(x or '').strip()
        for x in re.split(r'[、,，;；\n\t]+', text or '')
        if str(x or '').strip()
    ))
    if catalog is None:
        return [normalize_label(value) for value in values if normalize_label(value)]
    active_codes = {
        str(item.get('code') or '').strip()
        for item in catalog
        if str(item.get('code') or '').strip()
    }
    unknown = [value for value in values if value not in active_codes]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                "AI 标注标签必须显式使用当前标签库中的英文编码；"
                "系统不会根据中文名、别名或历史映射自动选择标签："
                + "、".join(unknown[:20])
            ),
        )
    return values


def _v47_default_annotation_model() -> Dict[str, Any]:
    items = _v35_model_items()
    if not items:
        raise HTTPException(status_code=400, detail='尚未配置可用AI模型，请先在高级功能里的模型配置完成一次配置')
    return next((x for x in items if x.get('default_for_annotation')), items[0])


def _annotation_label_catalog(project: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _ai_annotation_service()._annotation_label_catalog(project)


def _v47_build_annotation_prompt(
    cfg: Dict[str, Any],
    labels: List[Dict[str, Any]],
    *,
    width: int,
    height: int,
    business_instruction: str,
    template: str = '',
) -> str:
    template = (template or cfg.get('annotation_prompt_template') or '').strip()
    if not template:
        template = (
            '你是视觉目标检测标注助手。只标注标签库中的目标：{{labels_json}}。'
            '图片尺寸为 {{image_width}}x{{image_height}}。{{business_instruction}}'
            '必须只返回符合此结构的 JSON，不要输出解释或 Markdown：{{output_schema}}'
        )
    if '{{' in template:
        return render_prompt(
            template,
            labels=labels,
            width=width,
            height=height,
            business_instruction=business_instruction,
        )
    return template.replace('{labels}', '、'.join(str(item.get('code')) for item in labels))


def _retired_v47_annotation_api() -> None:
    raise HTTPException(
        status_code=410,
        detail=(
            "旧版 v47 AI 标注接口已退役；请使用 /api/v60/projects/{project_id}/annotation-tasks。"
            "AI 候选结果必须通过 durable review/decisions 流程确认后才能写入正式标注。"
        ),
    )


@app.post('/api/v47/projects/{project_id}/ai-label-tasks', deprecated=True)
def v47_create_ai_label_task(project_id: str, payload: V47AutoLabelReq):
    _retired_v47_annotation_api()


@app.get('/api/v47/projects/{project_id}/ai-label-tasks/{task_id}/result', deprecated=True)
def v47_ai_label_result(project_id: str, task_id: str):
    _retired_v47_annotation_api()


@app.post('/api/v47/projects/{project_id}/ai-label-tasks/{task_id}/confirm', deprecated=True)
def v47_confirm_ai_label(project_id: str, task_id: str, payload: V47AutoLabelConfirmReq):
    _retired_v47_annotation_api()

def public_annotation_task(task: TaskRecord, *, summary: Optional[dict]=None, worker_runtime=None, queued_candidates=None, statistics_synced_at: Optional[str]=None, include_review_policy: bool=False) -> Dict[str, Any]:
    return _ai_annotation_service().public_annotation_task(task, summary=summary, worker_runtime=worker_runtime, queued_candidates=queued_candidates, statistics_synced_at=statistics_synced_at, include_review_policy=include_review_policy)


def _annotation_summary(task: TaskRecord) -> dict:
    return _ai_annotation_service()._annotation_summary(task)


def _annotation_create_payload(project_id: str, payload: AnnotationTaskCreateReq) -> tuple[dict, str]:
    return _ai_annotation_service()._annotation_create_payload(project_id, payload)



# P1 hard samples extend the existing AI_ANNOTATION task, CandidateStore and
# formal annotation review; no independent task/annotation owner is introduced.
from platform_core.training_evaluation_contracts import HardSampleMiningCreateReq


def _enqueue_hard_sample_mining(project_id: str, algorithm_id: str, version_id: str, image_ids: Sequence[str], *, source: str, request_key: str=''):
    return _training_evaluation_service()._enqueue_hard_sample_mining(project_id, algorithm_id, version_id, image_ids, source=source, request_key=request_key)



app.include_router(create_training_evaluation_router_3(_training_evaluation_service))


def eligible_hard_sample_materials(project_id: str, algorithm_id: str, version_id: str, limit: int=100):
    return _training_evaluation_service().eligible_hard_sample_materials(project_id, algorithm_id, version_id, limit)

def create_hard_sample_mining(project_id: str, algorithm_id: str, version_id: str, payload: HardSampleMiningCreateReq):
    return _training_evaluation_service().create_hard_sample_mining(project_id, algorithm_id, version_id, payload)


def _persist_annotation_task_create(project_id: str, payload: AnnotationTaskCreateReq, task_id: str, *, identity: str=''):
    return _ai_annotation_service()._persist_annotation_task_create(project_id, payload, task_id, identity=identity)


from platform_core.ai_annotation_service import AiAnnotationDependencies, AiAnnotationService
from platform_core.ai_annotation_api import create_ai_annotation_router_1, create_ai_annotation_router_2, create_ai_annotation_router_3


def _ai_annotation_service() -> AiAnnotationService:
    return AiAnnotationService(AiAnnotationDependencies(
        DATA_DIR=lambda: DATA_DIR,
        _annotation_search_worker_errors=lambda: _annotation_search_worker_errors,
        _annotation_search_worker_lock=lambda: _annotation_search_worker_lock,
        _material_governance_actor=lambda *args, **kwargs: _material_governance_actor(*args, **kwargs),
        _negative_pool_training_usage=lambda *args, **kwargs: _negative_pool_training_usage(*args, **kwargs),
        _review_training_negative=lambda *args, **kwargs: _review_training_negative(*args, **kwargs),
        _start_annotation_search_backfill=lambda *args, **kwargs: _start_annotation_search_backfill(*args, **kwargs),
        _start_annotation_statistics_backfill=lambda *args, **kwargs: _start_annotation_statistics_backfill(*args, **kwargs),
        _storage_source_fence=lambda *args, **kwargs: _storage_source_fence(*args, **kwargs),
        _v35_model_items=lambda *args, **kwargs: _v35_model_items(*args, **kwargs),
        _v35_prompt_items=lambda *args, **kwargs: _v35_prompt_items(*args, **kwargs),
        _v50_annotation_repository=lambda *args, **kwargs: _v50_annotation_repository(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        material_store=lambda *args, **kwargs: material_store(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        project_label_items=lambda *args, **kwargs: project_label_items(*args, **kwargs),
        public_material=lambda *args, **kwargs: public_material(*args, **kwargs),
        read_annotation=lambda *args, **kwargs: read_annotation(*args, **kwargs),
        read_annotations_many=lambda *args, **kwargs: read_annotations_many(*args, **kwargs),
        shared_task_artifacts=lambda *args, **kwargs: shared_task_artifacts(*args, **kwargs),
        shared_task_repository=lambda *args, **kwargs: shared_task_repository(*args, **kwargs),
        v19_read_import_report=lambda *args, **kwargs: v19_read_import_report(*args, **kwargs),
        v19_read_job=lambda *args, **kwargs: v19_read_job(*args, **kwargs),
    ))


app.include_router(create_ai_annotation_router_1(_ai_annotation_service))


def create_annotation_task(project_id: str, payload: AnnotationTaskCreateReq):
    return _ai_annotation_service().create_annotation_task(project_id, payload)


def _annotation_create_id(project_id: str, request_id: str) -> str:
    return _ai_annotation_service()._annotation_create_id(project_id, request_id)


def _annotation_create_identity(payload: AnnotationTaskCreateReq) -> str:
    return _ai_annotation_service()._annotation_create_identity(payload)


def get_annotation_task_by_create_request(project_id: str, request_id: str):
    return _ai_annotation_service().get_annotation_task_by_create_request(project_id, request_id)


class AnnotationSelectionReq(BaseModel):
    labels: List[str] = Field(default_factory=list, max_length=100)
    query: str = Field(default="", max_length=1000)
    annotation_state: Optional[Literal["unannotated", "annotated", "confirmed_empty", "partial"]] = None
    previous_ref: Optional[str] = None
    image_ids: List[str] = Field(default_factory=list, max_length=50000)
    excluded_image_ids: List[str] = Field(default_factory=list, max_length=10000)


app.include_router(create_ai_annotation_router_2(_ai_annotation_service, AnnotationSelectionReq))


def freeze_annotation_selection(project_id: str, payload: AnnotationSelectionReq):
    return _ai_annotation_service().freeze_annotation_selection(project_id, payload)


def annotation_selection_summary(project_id: str, payload: AnnotationSelectionReq):
    return _ai_annotation_service().annotation_selection_summary(project_id, payload)


from platform_core.ai_annotation_contracts import AnnotationSelectionMembershipReq


def annotation_selection_membership(project_id: str, payload: AnnotationSelectionMembershipReq):
    return _ai_annotation_service().annotation_selection_membership(project_id, payload)


from platform_core.ai_annotation_contracts import AnnotationComparisonReq


def compare_annotation_preview(project_id: str, payload: AnnotationComparisonReq):
    return _ai_annotation_service().compare_annotation_preview(project_id, payload)


def preview_annotation_image(project_id: str, payload: AnnotationTaskCreateReq):
    return _ai_annotation_service().preview_annotation_image(project_id, payload)


_annotation_search_worker_lock = threading.Lock()
_annotation_search_workers: Dict[str, threading.Thread] = {}
_annotation_search_worker_errors: Dict[str, str] = {}


def _backfill_annotation_search(project_id: str) -> None:
    """One bounded legacy-index pass per batch, off the interactive request path."""
    repository = shared_task_repository()
    lock_path = str(repository.path.resolve()) + ".annotation-search." + hashlib.sha256(
        project_id.encode("utf-8")
    ).hexdigest()[:20] + ".lock"
    try:
        # A second web process may serve the same project. Only one writer
        # enumerates its frozen request artifacts at a time.
        with FileLock(lock_path, timeout=0):
            while repository.backfill_annotation_search_batch(
                project_id, shared_task_artifacts(), limit=100
            ):
                time.sleep(0.01)
    except Timeout:
        pass  # Another web process owns the backfill; its DB progress is shared.
    except Exception:
        logging.exception("AI annotation legacy search index failed for project %s", project_id)
        with _annotation_search_worker_lock:
            _annotation_search_worker_errors[project_id] = "历史任务索引失败，请检查服务日志后重试"
    finally:
        with _annotation_search_worker_lock:
            _annotation_search_workers.pop(project_id, None)


def _start_annotation_search_backfill(project_id: str) -> None:
    with _annotation_search_worker_lock:
        active = _annotation_search_workers.get(project_id)
        if active and active.is_alive():
            return
        worker = threading.Thread(
            target=_backfill_annotation_search, args=(project_id,),
            name="annotation-search-index", daemon=True,
        )
        _annotation_search_workers[project_id] = worker
        worker.start()


# History reconciliation only ever touches the visible page, off the HTTP
# request. A running/reviewing task's normal owner wins any snapshot race.
_annotation_statistics_lock = threading.Lock()
_annotation_statistics_pending: Dict[str, set[str]] = {}
_annotation_statistics_workers: Dict[str, threading.Thread] = {}


def _backfill_annotation_statistics_page(project_id: str, repository, artifacts) -> None:
    while True:
        with _annotation_statistics_lock:
            pending = _annotation_statistics_pending.get(project_id, set())
            if not pending:
                _annotation_statistics_workers.pop(project_id, None)
                _annotation_statistics_pending.pop(project_id, None)
                return
            task_ids = [pending.pop() for _ in range(min(25, len(pending)))]
        existing = repository.annotation_statistics_many(project_id, task_ids)
        for task_id in task_ids:
            if task_id in existing:
                continue
            task = repository.get(task_id)
            if not task or task.project_id != project_id or task.kind is not TaskKind.AI_ANNOTATION or not task.result_ref:
                continue
            try:
                counts = CandidateStore(artifacts, task_id=task_id).statistics()
                repository.set_annotation_statistics(task_id, counts, only_if_absent=True)
            except (FileNotFoundError, ValueError, OSError, sqlite3.Error):
                # Missing/corrupt historical evidence must remain unknown,
                # never a fabricated zero. A later detail request can retry.
                continue


def _start_annotation_statistics_backfill(project_id: str, task_ids: list[str], repository, artifacts) -> None:
    if not task_ids:
        return
    with _annotation_statistics_lock:
        pending = _annotation_statistics_pending.setdefault(project_id, set())
        pending.update(task_ids[:max(0, 200 - len(pending))])
        active = _annotation_statistics_workers.get(project_id)
        if active and active.is_alive():
            return
        worker = threading.Thread(
            target=_backfill_annotation_statistics_page,
            args=(project_id, repository, artifacts), name="annotation-stats-reconcile", daemon=True,
        )
        _annotation_statistics_workers[project_id] = worker
        worker.start()


def list_annotation_tasks(project_id: str, limit: int=50, cursor: Optional[str]=None, status: str='', q: str='', retry_index: bool=False, reader_view: bool=False):
    return _ai_annotation_service().list_annotation_tasks(project_id, limit, cursor, status, q, retry_index, reader_view)


def _require_annotation_review_task(project_id: str, task_id: str):
    return _ai_annotation_service()._require_annotation_review_task(project_id, task_id)


def get_annotation_task(project_id: str, task_id: str, reader_view: bool=False):
    return _ai_annotation_service().get_annotation_task(project_id, task_id, reader_view)


def audit_annotation_task_gt(project_id: str, task_id: str, limit: int=50, cursor: Optional[str]=None):
    return _ai_annotation_service().audit_annotation_task_gt(project_id, task_id, limit, cursor)


def annotation_material_states(project_id: str, image_ids: str=''):
    return _ai_annotation_service().annotation_material_states(project_id, image_ids)


def get_annotation_candidates(project_id: str, task_id: str, limit: int=50, cursor: Optional[str]=None, filter: str='all', reader_view: bool=False, selection_id: Optional[str]=None, request: Request=None):
    return _ai_annotation_service().get_annotation_candidates(project_id, task_id, limit, cursor, filter, reader_view, selection_id, request)


def get_annotation_candidate(project_id: str, task_id: str, image_id: str):
    return _ai_annotation_service().get_annotation_candidate(project_id, task_id, image_id)


from platform_core.ai_annotation_contracts import AnnotationDraftReq


def save_annotation_review_draft(project_id: str, task_id: str, image_id: str, payload: AnnotationDraftReq, request: Request):
    return _ai_annotation_service().save_annotation_review_draft(project_id, task_id, image_id, payload, request)



from platform_core.ai_annotation_contracts import AnnotationDraftBatchEntry


from platform_core.ai_annotation_contracts import AnnotationDraftBatchReq


def save_annotation_review_drafts_batch(project_id: str, task_id: str, payload: AnnotationDraftBatchReq, request: Request):
    return _ai_annotation_service().save_annotation_review_drafts_batch(project_id, task_id, payload, request)


from platform_core.ai_annotation_contracts import ConfirmedDraftSelection


class AnnotationSelectionReq(BaseModel):
    filter: str = 'all'
    purpose: Literal['gt', 'transfer', 'ambiguity'] = 'gt'
    review_revision: Optional[int] = None
    confirmed_drafts: List[ConfirmedDraftSelection] = Field(default_factory=list, max_length=50000)


app.include_router(create_ai_annotation_router_3(_ai_annotation_service, AnnotationSelectionReq))


def create_annotation_review_selection(project_id: str, task_id: str, payload: AnnotationSelectionReq, request: Request):
    return _ai_annotation_service().create_annotation_review_selection(project_id, task_id, payload, request)


def _load_annotation_review_selection(store, project_id, task_id, selection_id, actor, revision):
    return _ai_annotation_service()._load_annotation_review_selection(store, project_id, task_id, selection_id, actor, revision)



from platform_core.ai_annotation_contracts import BulkFormalIntentReq


def accept_bulk_formal_intent(project_id: str, task_id: str, payload: BulkFormalIntentReq, request: Request):
    return _ai_annotation_service().accept_bulk_formal_intent(project_id, task_id, payload, request)


def read_bulk_formal_intent(project_id: str, task_id: str, request_id: str, request: Request):
    return _ai_annotation_service().read_bulk_formal_intent(project_id, task_id, request_id, request)


def _bulk_formal_execution_view(project_id, task_id, request_id, actor):
    return _ai_annotation_service()._bulk_formal_execution_view(project_id, task_id, request_id, actor)


def execute_bulk_formal_intent(project_id: str, task_id: str, request_id: str, request: Request):
    return _ai_annotation_service().execute_bulk_formal_intent(project_id, task_id, request_id, request)


def read_bulk_formal_execution(project_id: str, task_id: str, request_id: str, request: Request):
    return _ai_annotation_service().read_bulk_formal_execution(project_id, task_id, request_id, request)


def cancel_bulk_formal_execution(project_id: str, task_id: str, request_id: str, request: Request):
    return _ai_annotation_service().cancel_bulk_formal_execution(project_id, task_id, request_id, request)


def recover_bulk_formal_execution(project_id: str, task_id: str, request_id: str, request: Request):
    return _ai_annotation_service().recover_bulk_formal_execution(project_id, task_id, request_id, request)


def get_annotation_review_selection_candidates(project_id: str, task_id: str, selection_id: str, request: Request, cursor: int=0, limit: int=100):
    return _ai_annotation_service().get_annotation_review_selection_candidates(project_id, task_id, selection_id, request, cursor, limit)


from platform_core.ai_annotation_contracts import AnnotationTransferReq


def _annotation_transfer_ids(store, project_id, task_id, payload, actor, revision):
    return _ai_annotation_service()._annotation_transfer_ids(store, project_id, task_id, payload, actor, revision)


def _annotation_transfer_ineligibility(item, material, formal, *, operation_id=None):
    return _ai_annotation_service()._annotation_transfer_ineligibility(item, material, formal, operation_id=operation_id)


def _annotation_transfer_eligible_selection(project_id, store, ids):
    return _ai_annotation_service()._annotation_transfer_eligible_selection(project_id, store, ids)


def _annotation_transfer_identity(payload):
    return _ai_annotation_service()._annotation_transfer_identity(payload)


def _annotation_transfer_preview_path(request_id):
    return _ai_annotation_service()._annotation_transfer_preview_path(request_id)


def _load_annotation_transfer(artifacts, task_id, path, store):
    return _ai_annotation_service()._load_annotation_transfer(artifacts, task_id, path, store)


def transfer_annotation_candidates(project_id: str, task_id: str, payload: AnnotationTransferReq, request: Request):
    return _ai_annotation_service().transfer_annotation_candidates(project_id, task_id, payload, request)


def get_annotation_transfer(project_id: str, task_id: str, request_id: str, offset: int=Query(default=0, ge=0, le=50000), limit: int=Query(default=100, ge=1, le=200)):
    return _ai_annotation_service().get_annotation_transfer(project_id, task_id, request_id, offset, limit)


def undo_annotation_transfer(project_id: str, task_id: str, request_id: str, request: Request):
    return _ai_annotation_service().undo_annotation_transfer(project_id, task_id, request_id, request)


def preview_annotation_transfer(project_id: str, task_id: str, payload: AnnotationTransferReq, request: Request):
    return _ai_annotation_service().preview_annotation_transfer(project_id, task_id, payload, request)


def get_annotation_candidate_diagnostics(project_id: str, task_id: str, image_id: str):
    return _ai_annotation_service().get_annotation_candidate_diagnostics(project_id, task_id, image_id)


def decide_annotation_candidates(project_id: str, task_id: str, payload: AnnotationDecisionReq, request: Request):
    return _ai_annotation_service().decide_annotation_candidates(project_id, task_id, payload, request)


def _annotation_review_operation_path(request_id: str) -> str:
    return _ai_annotation_service()._annotation_review_operation_path(request_id)


def _annotation_review_operation_identity(payload: AnnotationDecisionReq) -> str:
    return _ai_annotation_service()._annotation_review_operation_identity(payload)


def _annotation_review_resolve_receipt(task: TaskRecord, receipt: Dict[str, Any]):
    return _ai_annotation_service()._annotation_review_resolve_receipt(task, receipt)


def _annotation_review_recover_task_transition(task, artifacts, request_id):
    return _ai_annotation_service()._annotation_review_recover_task_transition(task, artifacts, request_id)


def get_annotation_review_operation(project_id: str, task_id: str, request_id: str, request: Request):
    return _ai_annotation_service().get_annotation_review_operation(project_id, task_id, request_id, request)


def _annotation_selected_commit_response(task, store, committed):
    return _ai_annotation_service()._annotation_selected_commit_response(task, store, committed)


def _decide_single_annotation_candidate(project_id, task_id, decision, pending):
    return _ai_annotation_service()._decide_single_annotation_candidate(project_id, task_id, decision, pending)


def _check_single_supplement_decision(project_id, decision, frozen):
    return _ai_annotation_service()._check_single_supplement_decision(project_id, decision, frozen)


def _decide_annotation_candidates(project_id: str, task_id: str, payload: AnnotationDecisionReq):
    return _ai_annotation_service()._decide_annotation_candidates(project_id, task_id, payload)


def cancel_annotation_task(project_id: str, task_id: str):
    return _ai_annotation_service().cancel_annotation_task(project_id, task_id)


def retry_annotation_task(project_id: str, task_id: str, retry_payload: Optional[Dict[str, Any]]=Body(default=None)):
    return _ai_annotation_service().retry_annotation_task(project_id, task_id, retry_payload)


def review_completed_annotation_task(project_id: str, task_id: str):
    return _ai_annotation_service().review_completed_annotation_task(project_id, task_id)


def _resolve_v61_test_model(project_id: str, *, model_name: str, model_source: str, local_path: str, algorithm_id: str, version_id: str) -> ModelResolution:
    return _deployment_validation_service()._resolve_v61_test_model(project_id, model_name=model_name, model_source=model_source, local_path=local_path, algorithm_id=algorithm_id, version_id=version_id)


def public_deployment_test(task: TaskRecord) -> Dict[str, Any]:
    return _deployment_validation_service().public_deployment_test(task)


from platform_core.deployment_validation_service import DeploymentValidationDependencies, DeploymentValidationService
from platform_core.deployment_validation_api import create_deployment_validation_router_1


def _deployment_validation_service() -> DeploymentValidationService:
    return DeploymentValidationService(DeploymentValidationDependencies(
        BASE_DIR=lambda: BASE_DIR,
        IMAGE_EXTS=lambda: IMAGE_EXTS,
        _algorithm_version_for_action=lambda *args, **kwargs: _algorithm_version_for_action(*args, **kwargs),
        _algorithm_version_reference_fence=lambda *args, **kwargs: _algorithm_version_reference_fence(*args, **kwargs),
        _business_file_url=lambda *args, **kwargs: _business_file_url(*args, **kwargs),
        _durable_process_identity=lambda *args, **kwargs: _durable_process_identity(*args, **kwargs),
        _online_feedback_version_model_sha256=lambda *args, **kwargs: _online_feedback_version_model_sha256(*args, **kwargs),
        _online_prediction_evidence=lambda *args, **kwargs: _online_prediction_evidence(*args, **kwargs),
        _register_prediction_files=lambda *args, **kwargs: _register_prediction_files(*args, **kwargs),
        _remote_execution_transport_service=lambda *args, **kwargs: _remote_execution_transport_service(*args, **kwargs),
        _require_shared_task=lambda *args, **kwargs: _require_shared_task(*args, **kwargs),
        _testable_version_pt_path=lambda *args, **kwargs: _testable_version_pt_path(*args, **kwargs),
        deploy_root=lambda *args, **kwargs: deploy_root(*args, **kwargs),
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        image_info=lambda *args, **kwargs: image_info(*args, **kwargs),
        inference_env_items=lambda *args, **kwargs: inference_env_items(*args, **kwargs),
        list_algorithms_internal=lambda *args, **kwargs: list_algorithms_internal(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        project_dir=lambda *args, **kwargs: project_dir(*args, **kwargs),
        resolve_any_model_path=lambda *args, **kwargs: resolve_any_model_path(*args, **kwargs),
        resolve_inference_python=lambda *args, **kwargs: resolve_inference_python(*args, **kwargs),
        resolve_ultralytics_model=lambda *args, **kwargs: resolve_ultralytics_model(*args, **kwargs),
        safe_filename=lambda *args, **kwargs: safe_filename(*args, **kwargs),
        shared_task_artifacts=lambda *args, **kwargs: shared_task_artifacts(*args, **kwargs),
        shared_task_repository=lambda *args, **kwargs: shared_task_repository(*args, **kwargs),
    ))


app.include_router(create_deployment_validation_router_1(_deployment_validation_service))


async def create_deployment_test(project_id: str, model_name: str=Form(''), model_source: str=Form('project'), local_path: str=Form(''), algorithm_id: str=Form(''), version_id: str=Form(''), conf: float=Form(0.25), inference_framework: str=Form('ultralytics'), inference_env_id: str=Form(''), detection_batch_id: str=Form(''), detection_item_index: int=Form(-1), detection_item_total: int=Form(0), detection_side: str=Form(''), model_label: str=Form(''), original_filename: str=Form(''), model_scope: str=Form(''), creation_id: str=Form(''), detection_sides: str=Form(''), file: UploadFile=File(...)):
    return await _deployment_validation_service().create_deployment_test(project_id, model_name, model_source, local_path, algorithm_id, version_id, conf, inference_framework, inference_env_id, detection_batch_id, detection_item_index, detection_item_total, detection_side, model_label, original_filename, model_scope, creation_id, detection_sides, file)


async def _create_deployment_test_under_version_fence(project_id: str, model_name: str, model_source: str, local_path: str, algorithm_id: str, version_id: str, conf: float, inference_framework: str, inference_env_id: str, detection_batch_id: str, detection_item_index: int, detection_item_total: int, detection_side: str, model_label: str, original_filename: str, file: UploadFile, model_scope: str=''):
    return await _deployment_validation_service()._create_deployment_test_under_version_fence(project_id, model_name, model_source, local_path, algorithm_id, version_id, conf, inference_framework, inference_env_id, detection_batch_id, detection_item_index, detection_item_total, detection_side, model_label, original_filename, file, model_scope)


def get_deployment_creation(project_id: str, creation_id: str):
    return _deployment_validation_service().get_deployment_creation(project_id, creation_id)


async def recover_deployment_creation(project_id: str, creation_id: str):
    return await _deployment_validation_service().recover_deployment_creation(project_id, creation_id)


def get_deployment_test(project_id: str, task_id: str):
    return _deployment_validation_service().get_deployment_test(project_id, task_id)


def retry_deployment_test(project_id: str, task_id: str):
    return _deployment_validation_service().retry_deployment_test(project_id, task_id)


def cancel_deployment_test(project_id: str, task_id: str):
    return _deployment_validation_service().cancel_deployment_test(project_id, task_id)


def promote_deployment_test_to_feedback_evidence(project_id: str, task_id: str):
    return _deployment_validation_service().promote_deployment_test_to_feedback_evidence(project_id, task_id)


from platform_core.detection_batches_contracts import DetectionBatchReviewReq


def _iter_detection_batch_rows(project_id: str, batch_id: str='', *, scan_limit: int=2000):
    return _detection_batches_service()._iter_detection_batch_rows(project_id, batch_id, scan_limit=scan_limit)


def _public_detection_batch(project_id: str, batch_id: str, rows):
    return _detection_batches_service()._public_detection_batch(project_id, batch_id, rows)


from platform_core.detection_batches_service import DetectionBatchesDependencies, DetectionBatchesService
from platform_core.detection_batches_api import create_detection_batches_router_1


def _detection_batches_service() -> DetectionBatchesService:
    return DetectionBatchesService(DetectionBatchesDependencies(
        get_project=lambda *args, **kwargs: get_project(*args, **kwargs),
        now_iso=lambda *args, **kwargs: now_iso(*args, **kwargs),
        public_deployment_test=lambda *args, **kwargs: public_deployment_test(*args, **kwargs),
        shared_task_artifacts=lambda *args, **kwargs: shared_task_artifacts(*args, **kwargs),
        shared_task_repository=lambda *args, **kwargs: shared_task_repository(*args, **kwargs),
    ))


app.include_router(create_detection_batches_router_1(_detection_batches_service))


def list_detection_batches(project_id: str, limit: int=Query(default=12, ge=1, le=50)):
    return _detection_batches_service().list_detection_batches(project_id, limit)


def get_detection_batch(project_id: str, batch_id: str):
    return _detection_batches_service().get_detection_batch(project_id, batch_id)


def review_detection_batch_item(project_id: str, batch_id: str, item_index: int, payload: DetectionBatchReviewReq):
    return _detection_batches_service().review_detection_batch_item(project_id, batch_id, item_index, payload)


# ============================================================
# v42.12 — import review, batch label remap, explicit ready state
# ============================================================

from platform_core.annotation_governance_contracts import V52LabelRemapReq

from platform_core.material_governance_contracts import V52ReadyReq

app.include_router(create_annotation_governance_router_4(_annotation_governance_service))


def v52_remap_import_labels(project_id: str, payload: V52LabelRemapReq):
    return _annotation_governance_service().v52_remap_import_labels(project_id, payload)

app.include_router(create_material_governance_router_4(_material_governance_service))


def v52_mark_ready(project_id: str, payload: V52ReadyReq):
    return _material_governance_service().v52_mark_ready(project_id, payload)

app.include_router(create_material_ingestion_router_5(_material_ingestion_service))


def v52_import_review(project_id: str, job_id: str):
    return _material_ingestion_service().v52_import_review(project_id, job_id)

# ============================================================
# v42.9 — processed/unprocessed data pool + algorithm report
# ============================================================

def _v49_metric_from_report(report: Dict[str, Any], *keys: str):
    return _training_evaluation_service()._v49_metric_from_report(report, *keys)

def _v49_job_label_counts(project_id: str, job: Dict[str, Any]) -> Dict[str, int]:
    return _training_evaluation_service()._v49_job_label_counts(project_id, job)

app.include_router(create_training_evaluation_router_4(_training_evaluation_service))


def v49_algorithm_report(project_id: str, algorithm_id: str, lightweight: bool=False):
    return _training_evaluation_service().v49_algorithm_report(project_id, algorithm_id, lightweight)

app.include_router(create_material_governance_router_5(_material_governance_service))


def v49_mark_processed(project_id: str, payload: V46BatchDeleteImagesReq):
    return _material_governance_service().v49_mark_processed(project_id, payload)


# ============================================================
# v42.13 — startup bootstrap / warm cache
# ============================================================
_V53_BOOTSTRAP_LOCK = threading.Lock()
_V53_BOOTSTRAP_THREAD: Optional[threading.Thread] = None
_V53_BOOTSTRAP_STATUS: Dict[str, Any] = {"status":"idle","progress":0,"stage":"尚未开始","message":"","started_at":"","finished_at":"","active_project_id":"","error":"","readiness_scope":"core","maintenance_status":"not_started"}
_V53_BOOTSTRAP_SNAPSHOT: Dict[str, Any] = {}

def _v53_set_bootstrap(progress:int, stage:str, message:str="", **extra):
    _V53_BOOTSTRAP_STATUS.update({"status":"running" if progress<100 else "ready","progress":max(0,min(100,int(progress))),"stage":stage,"message":message,"updated_at":now_iso(),**extra})

def _v53_project_counts(project:Dict[str,Any])->Dict[str,int]:
    pid=str(project.get("id") or "")
    if not pid:return {"images":0,"algorithms":0,"versions":0,"jobs":0}
    image_count=material_store(pid).count(); algs=list_algorithm_assets(algorithms_file(pid)); jobs=read_json(project_dir(pid)/"jobs"/"index.json",[])
    if not isinstance(algs,list):algs=[]
    if not isinstance(jobs,list):jobs=[]
    return {"images":image_count,"algorithms":len(algs),"versions":sum(len(a.get("versions") or []) for a in algs if isinstance(a,dict)),"jobs":len(jobs)}

def _v53_choose_project(projects:List[Dict[str,Any]], preferred_project_id:str=""):
    if not ALLOW_MULTIPLE_PROJECTS_FOR_TESTS:
        runtime_projects = list_projects()
        return runtime_projects[0] if runtime_projects else None
    counts={str(project.get("id") or ""):_v53_project_counts(project) for project in projects}
    return choose_project(projects,preferred_project_id,counts)

def _v53_index_annotations_sync(project_id:str, images:List[Dict[str,Any]], base_progress:int, span:int):
    pending=[x for x in images if not x.get("annotation_summary_at")]
    if not pending:return images
    from concurrent.futures import ThreadPoolExecutor, as_completed
    patches={}; total=len(pending); workers=min(8,max(2,os.cpu_count() or 2))
    def one(img):
        iid=str(img.get("id") or ""); ann=read_annotation(project_id,iid); boxes=ann.get("boxes",[]) if isinstance(ann,dict) else []
        return iid,ann,boxes,img
    done=0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fut in as_completed([ex.submit(one,img) for img in pending]):
            iid,ann,boxes,img=fut.result(); patch={**_annotation_summary_for_material_index(boxes,ann.get('annotation_state'),img),"annotation_summary_at":ann.get("updated_at") or now_iso(),"annotation_version":int(ann.get("version") or 0),"annotation_hash":str(ann.get("content_digest") or ""),"annotation_scope":list(ann.get("annotation_scope") or [])}
            if boxes:patch["processing_status"]="processed"
            if patch["annotation_version"]>0 and patch["annotation_hash"]:patches[iid]=patch
            done+=1
            if done==total or done%100==0:_v53_set_bootstrap(base_progress+int(span*done/max(1,total)),"整理历史标注索引",f"{done}/{total} 张")
    material_store(project_id).patch_annotation_projections(patches); return load_images(project_id)

def _v53_job_summary(source: Mapping[str, Any]) -> Dict[str, Any]:
    """First-paint task metadata; full evidence stays in the existing report API.

    Always copy before trimming: the worker JSON, durable index and incremental
    history projection remain complete and can serve independent report reads.
    """
    deferred = {
        "history", "training_history", "epoch_history", "training_metrics",
        "runtime_metrics", "resource_samples", "error_samples", "evaluation",
        "frozen_evidence", "frozen_audit", "frozen_data_quality", "snapshot_manifest",
        "dataset_manifest", "dataset_selected_ids", "selected_ids",
    }
    row = {key: value for key, value in source.items() if key not in deferred}
    report = source.get("training_report")
    if isinstance(report, Mapping):
        summary_keys = {
            "generated_at", "framework", "status", "metrics", "train_metrics",
            "val_metrics", "summary", "note", "training_outcome", "completion_reason",
        }
        row["training_report"] = {key: value for key, value in report.items() if key in summary_keys}
    data_summary = source.get("data_summary")
    if isinstance(data_summary, Mapping):
        row["data_summary"] = {key: value for key, value in data_summary.items() if key != "selected_ids"}
    return row


def _v53_fast_jobs_summary(project_id: str) -> List[Dict[str, Any]]:
    """Bounded job-card projection with live Durable status, no history scan.

    Historical evidence remains in the existing index and full job/report APIs.
    When a worker has updated a task since the last index write, the canonical
    Durable status wins; no GET writes either store or dispatches a job.
    """
    snapshot = read_json(project_dir(project_id) / "jobs" / "index.json", [])
    indexed = {
        str(row.get("task_id") or row.get("id")): _v53_job_summary(row)
        for row in snapshot if isinstance(row, Mapping) and (row.get("task_id") or row.get("id"))
    } if isinstance(snapshot, list) else {}
    try:
        repository = shared_task_repository()
        retired=repository.deleted_task_ids(indexed,project_id=project_id)
    except Exception as error:
        raise HTTPException(status_code=503, detail="TRAINING_TASK_DELETE_STATE_UNAVAILABLE: 任务删除身份暂时无法核验，请重试") from error
    indexed={identity:row for identity,row in indexed.items() if identity not in retired}
    try:
        recent = repository.list(project_id=project_id, kinds=(TaskKind.TRAINING,), limit=50)
        durable = {task.task_id: task for task in recent.items}
        cursor = None
        while True:
            page = repository.list(
                project_id=project_id, kinds=(TaskKind.TRAINING,),
                statuses=_TRAINING_STREAM_ACTIVE_STATUSES, limit=100, cursor=cursor,
            )
            durable.update((task.task_id, task) for task in page.items)
            cursor = page.next_cursor
            if not cursor:
                break
        for task_id, row in indexed.items():
            if task_id in durable or not _training_job_is_active(row):
                continue
            persisted = repository.get(task_id)
            if persisted is not None and persisted.project_id == project_id and persisted.kind is TaskKind.TRAINING:
                durable[task_id] = persisted
        status_map = {
            TaskStatus.QUEUED: "queued", TaskStatus.RUNNING: "running",
            TaskStatus.CANCEL_REQUESTED: "stopping",
            TaskStatus.SUCCEEDED: "done", TaskStatus.PARTIAL_SUCCESS: "done",
            TaskStatus.CANCELLED: "stopped", TaskStatus.FAILED: "failed",
            TaskStatus.BLOCKED_BY_ENVIRONMENT: "failed",
            TaskStatus.BLOCKED_BY_HARDWARE: "failed",
        }
        for task_id, task in durable.items():
            row = indexed.get(task_id)
            if row is None:
                job_file = project_dir(project_id) / "jobs" / task_id / "job.json"
                row = _v53_job_summary(read_json(job_file, {}))
                if not row:
                    payload = shared_task_artifacts().read_json(task_id, task.payload_ref, default={})
                    row = _v53_job_summary(payload) if isinstance(payload, Mapping) else {}
                row = {**row, "id": task_id, "task_id": task_id}
            public = task_to_public(task, repository)
            legacy_status = status_map.get(task.status, str(row.get("status") or "queued"))
            if public["status"] == "WAITING_RESOURCE":
                legacy_status = "waiting"
            elif public["status"] == "PAUSED":
                legacy_status = "paused"
            apply_training_task_truth(row, public, legacy_status=legacy_status)
            row["updated_at"] = task.updated_at
            row.setdefault("created_at", task.created_at)
            indexed[task_id] = row
    except Exception:
        # Only deletion-verified index rows may survive enrichment failure.
        # A tombstone lookup failure above must never reach this fallback.
        pass
    return [_v53_job_summary(row) for row in _training_job_index_rows(list(indexed.values()))]


def _v53_live_jobs(project_id: str, *, history_context=None) -> List[Dict[str, Any]]:
    """Overlay volatile training truth without rebuilding the whole bootstrap snapshot."""
    try:
        current = sync_jobs_index(project_id, history_context=history_context, read_only=True)
    except Exception:
        # A bootstrap response may still use the last durable index if one job
        # cannot be enriched temporarily; never fall back to an older in-memory
        # snapshot merely because the live overlay failed.
        current = None
    if not isinstance(current, list):
        current = read_json(project_dir(project_id) / "jobs" / "index.json", [])
    jobs = current if isinstance(current, list) else []
    try:
        retired = shared_task_repository().deleted_task_ids(
            (row.get('task_id') or row.get('id') for row in jobs), project_id=project_id)
    except Exception as error:
        raise HTTPException(status_code=503, detail="TRAINING_TASK_DELETE_STATE_UNAVAILABLE: 任务删除身份暂时无法核验，请重试") from error
    return [_v53_job_summary(row) for row in jobs if str(row.get('task_id') or row.get('id')) not in retired]


def _v53_algorithms_with_revision(project_id: str) -> tuple[List[Dict[str, Any]], int]:
    """Read algorithms against one stable SQL revision.

    A concurrent writer between the two revision probes makes us retry. This
    avoids caching rows from revision N under revision N+1.
    """
    path = algorithms_file(project_id)
    algorithms: List[Dict[str, Any]] = []
    before = 0
    for _ in range(5):
        before = algorithm_store_revision(path)
        algorithms = list_algorithms_internal(project_id)
        after = algorithm_store_revision(path)
        if before == after:
            return algorithms, after

    # Under sustained concurrent writes, never label potentially older rows with
    # a newer revision. Returning the last pre-read revision guarantees the next
    # request will retry instead of publishing a falsely-fresh cache entry.
    return algorithms, before


def _v53_snapshot_with_live_jobs(snapshot: Mapping[str, Any], project_id: str) -> Dict[str, Any]:
    global _V53_BOOTSTRAP_SNAPSHOT
    payload = dict(snapshot or {})
    if payload.get("core_only"):
        return _v53_build_snapshot(project_id)  # explicit non-core compatibility read
    cached_revision = int(payload.get("algorithm_revision") or 0)
    current_revision = algorithm_store_revision(algorithms_file(project_id))
    if cached_revision != current_revision:
        algorithms, stable_revision = _v53_algorithms_with_revision(project_id)
        payload["algorithms"] = algorithms
        payload["algorithm_revision"] = stable_revision
        payload["algorithms_generated_at"] = now_iso()

        # Publish an atomic replacement only when it cannot move the cached
        # algorithm revision backwards under concurrent snapshot requests.
        current_cached = _V53_BOOTSTRAP_SNAPSHOT
        published_revision = int(current_cached.get("algorithm_revision") or 0)
        publish_revision = algorithm_store_revision(algorithms_file(project_id))
        cached_project_id = str((current_cached.get("project") or {}).get("id") or "")
        if (
            cached_project_id == project_id
            and stable_revision == publish_revision
            and stable_revision >= published_revision
        ):
            refreshed = dict(current_cached)
            refreshed["algorithms"] = algorithms
            refreshed["algorithm_revision"] = stable_revision
            refreshed["algorithms_generated_at"] = payload["algorithms_generated_at"]
            refreshed["generated_at"] = now_iso()
            _V53_BOOTSTRAP_SNAPSHOT = refreshed

    history_context = _training_history_context(project_id)
    counts = _successful_training_counts(project_id, history_context=history_context)
    payload["algorithms"] = [{**algorithm, "successful_training_count": counts.get(str(algorithm.get("id") or ""), 0)} for algorithm in payload.get("algorithms", [])]
    payload["jobs"] = _v53_live_jobs(project_id, history_context=history_context)
    payload["jobs_generated_at"] = now_iso()
    return payload


@performance_stage("bootstrap.revision")
def _v53_core_revisions(project_id):
    project=get_project(project_id)
    return {"algorithm": algorithm_store_revision(algorithms_file(project_id)),
            "material": material_store(project_id).current_revision(),
            "annotation": AnnotationRepository(project_dir(project_id)).current_revision(),
            "project": hashlib.sha256(json.dumps(project, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            "datasets": hashlib.sha256(json.dumps(read_json(datasets_file(project_id), []), sort_keys=True, ensure_ascii=False).encode()).hexdigest()}


def _v53_build_core_snapshot(project_id):
    from platform_core.algorithm_sql_store import AlgorithmSqlStore
    timings = {}
    def measure(name, operation):
        began=time.perf_counter()
        try:return operation()
        finally:timings[name]=round((time.perf_counter()-began)*1000,3)
    datasets=measure("datasets",lambda:ensure_default_datasets(project_id))
    revisions=measure("revision",lambda:_v53_core_revisions(project_id))
    project=measure("project",lambda:get_project(project_id))
    algorithms,total,revision=measure("algorithms",lambda:algorithm_presentation_store(project_id).bootstrap_summary())
    materials=measure("materials",lambda:material_store(project_id).summary())
    annotations=measure("annotations",lambda:AnnotationRepository(project_dir(project_id)).summary())
    if revisions != _v53_core_revisions(project_id) or revision != revisions["algorithm"]:
        raise ValueError("BOOTSTRAP_REVISION_CHANGED")
    now=now_iso()
    return {"core_only":True,"core_revisions":revisions,"project":project,"datasets":datasets,
        "labels":project_label_items(project),"algorithms":algorithms,"algorithm_revision":revision,
        "algorithms_total":total,"algorithms_deferred":True,"material_summary":materials,"annotation_summary":annotations,
        "jobs":[],"jobs_deferred":True,"training_counts_deferred":True,"model_configs_deferred":True,
        "platform_version":APP_VERSION,"build_id":BUILD_ID,"generated_at":now,"algorithms_generated_at":now,
        "bootstrap_timings_ms":timings}


def _v53_build_snapshot(project_id:str, prepared_targets:Optional[List[Dict[str,Any]]]=None, *, core_only:bool=False):
    if core_only:return _v53_build_core_snapshot(project_id)
    # First paint reads repository counters and small metadata indexes only.
    # Materials use v61 pagination; legacy annotation JSON is resolved per image.
    project=get_project(project_id); datasets=ensure_default_datasets(project_id); labels=project_label_items(project)
    algorithms, algorithm_revision = _v53_algorithms_with_revision(project_id)
    materials=material_store(project_id).summary()
    annotations=AnnotationRepository(project_dir(project_id)).summary()
    history_context=_training_history_context(project_id)
    jobs=_v53_live_jobs(project_id, history_context=history_context)
    counts=_successful_training_counts(project_id, history_context=history_context)
    algorithms=[{**algorithm,"successful_training_count":counts.get(str(algorithm.get("id") or ""),0)} for algorithm in algorithms]
    model_configs=[_v35_sanitize_secret(item) for item in _v35_model_items()]
    generated_at=now_iso()
    return {"project":project,"datasets":datasets,"material_summary":materials,"annotation_summary":annotations,"labels":labels,"algorithms":algorithms,"algorithm_revision":algorithm_revision,"algorithms_generated_at":generated_at,"jobs":jobs,"model_configs":model_configs,"platform_version":APP_VERSION,"build_id":BUILD_ID,"generated_at":generated_at,"jobs_generated_at":generated_at}

def _v53_bootstrap_worker(preferred_project_id:str=""):
    global _V53_BOOTSTRAP_SNAPSHOT
    try:
        _V53_BOOTSTRAP_STATUS.update({"status":"running","progress":1,"stage":"读取平台数据","message":"正在读取项目索引","started_at":now_iso(),"finished_at":"","error":""})
        projects=list_projects()
        if not projects:projects=[create_project(ProjectCreate(name="默认空间",description="系统自动创建",labels=[]))]
        _v53_set_bootstrap(8,"读取平台数据",f"发现 {len(projects)} 个项目")
        active=next((p for p in projects if str(p.get("id"))==preferred_project_id),None) if preferred_project_id and ALLOW_MULTIPLE_PROJECTS_FOR_TESTS else _v53_choose_project(projects,preferred_project_id)
        if not active:raise RuntimeError("没有可用项目")
        active_id=str(active.get("id"))
        _V53_BOOTSTRAP_STATUS["active_project_id"]=active_id
        _v53_set_bootstrap(20,"读取核心页面","训练历史与维护任务将在首屏之后按需读取")
        # One existing worker per process; persistent lock prevents simultaneous
        # builds in different Web workers. No second cache or background task system.
        with FileLock(str(Path(DATA_DIR)/".v53-bootstrap-build.lock"), timeout=10):
            snap=_v53_build_snapshot(active_id,core_only=True)
        snap["projects"]=projects
        _V53_BOOTSTRAP_SNAPSHOT=snap
        _V53_BOOTSTRAP_STATUS.update({"status":"ready","progress":100,"stage":"核心页面已就绪","message":"后台数据按页面读取","finished_at":now_iso(),"updated_at":now_iso(),"active_project_id":active_id,"error":""})
    except Exception as error:
        code="BOOTSTRAP_DATABASE_BUSY" if isinstance(error,sqlite3.OperationalError) and any(v in str(error).lower() for v in ("locked","busy")) else "BOOTSTRAP_BUILD_FAILED"
        if type(error).__name__=="Timeout":code="BOOTSTRAP_BUILD_BUSY"
        logging.exception("Core bootstrap failed: %s",code)
        _V53_BOOTSTRAP_STATUS.update({"status":"failed","stage":"核心页面准备失败","message":"核心数据准备失败，请重试；后台训练不受影响。","error":code,"finished_at":now_iso(),"updated_at":now_iso()})

def _v53_post_bootstrap_recovery():
    # Existing recovery operations are startup-only, never run by snapshot retry.
    # Let the core worker finish without making its thread represent maintenance.
    worker=_V53_BOOTSTRAP_THREAD
    if worker:worker.join()
    _V53_BOOTSTRAP_STATUS.update(maintenance_status="running",maintenance_started_at=now_iso())
    failed=False
    try:
        for project in list_projects():
            project_id=str(project.get("id") or "")
            if not project_id:continue
            try:
                ensure_project_dirs(project_id)
                _v50_recover_dataset_deletions(project_id)
                _v47_recover_clean_tasks(project_id)
            except Exception:
                failed=True
                logging.exception("Post-bootstrap recovery failed for project %s",project_id)
    except Exception:
        failed=True
        logging.exception("Post-bootstrap recovery project lookup failed")
    finally:
        _V53_BOOTSTRAP_STATUS.update(maintenance_status="failed" if failed else "ready",maintenance_finished_at=now_iso())



def _v53_start_bootstrap(preferred_project_id:str="", force:bool=False):
    global _V53_BOOTSTRAP_THREAD
    with _V53_BOOTSTRAP_LOCK:
        if _V53_BOOTSTRAP_THREAD and _V53_BOOTSTRAP_THREAD.is_alive():return
        if _V53_BOOTSTRAP_STATUS.get("status")=="ready" and not force:return
        _V53_BOOTSTRAP_STATUS.update(status="running",progress=0,stage="准备核心页面",error="")
        _V53_BOOTSTRAP_THREAD=threading.Thread(target=_v53_bootstrap_worker,args=(preferred_project_id,),daemon=True,name="v53-bootstrap"); _V53_BOOTSTRAP_THREAD.start()

@app.on_event("startup")
def _v53_startup_bootstrap():
    # Resource discovery is requested by the resource/deployment page.
    _v53_start_bootstrap()
    threading.Thread(target=_v53_post_bootstrap_recovery,daemon=True,name="v53-existing-recovery").start()

class V53BootstrapReq(BaseModel):
    preferred_project_id: Optional[str]=""; force: bool=False

@app.post("/api/v53/bootstrap/start")
def v53_bootstrap_start(payload:V53BootstrapReq):_v53_start_bootstrap(payload.preferred_project_id or "",bool(payload.force)); return {"ok":True,**_V53_BOOTSTRAP_STATUS}

@app.get("/api/v53/bootstrap/status")
def v53_bootstrap_status(response:Response):
    response.headers["Cache-Control"]="no-store"
    return {"ok":True,**_V53_BOOTSTRAP_STATUS}

@app.get("/api/v53/bootstrap/snapshot")
def v53_bootstrap_snapshot(preferred_project_id:Optional[str]="", refresh:bool=False, core:bool=True):
    global _V53_BOOTSTRAP_SNAPSHOT
    started_at = time.perf_counter()
    def respond(payload):
        serialize_started=time.perf_counter()
        with performance_measure("bootstrap.serialize"):
            response = fast_json_response(payload)
        serialize_ms=(time.perf_counter()-serialize_started)*1000
        response.headers["Server-Timing"] = f"bootstrap;dur={(time.perf_counter() - started_at) * 1000:.2f}, serialize;dur={serialize_ms:.2f}"
        response.headers["X-Response-Bytes"]=str(len(response.body))
        response.headers["Cache-Control"]="no-store"
        return response
    if core:
        snapshot=dict(_V53_BOOTSTRAP_SNAPSHOT)
        project_id=str((snapshot.get("project") or {}).get("id") or "")
        requested=str(preferred_project_id or "") if ALLOW_MULTIPLE_PROJECTS_FOR_TESTS else ""
        if not refresh and snapshot.get("core_only") and project_id and (not requested or requested==project_id):
            revision_started=time.perf_counter()
            try:fresh=snapshot.get("core_revisions")==_v53_core_revisions(project_id)
            except HTTPException as error:
                if error.status_code!=404:raise
                fresh=False
            except (OSError,sqlite3.Error) as error:
                logging.exception("Core bootstrap revision probe failed")
                code="BOOTSTRAP_DATABASE_BUSY" if isinstance(error,sqlite3.OperationalError) and any(v in str(error).lower() for v in ("busy","locked")) else "BOOTSTRAP_DATABASE_UNAVAILABLE"
                return JSONResponse(status_code=503,headers={"Cache-Control":"no-store"},content={"code":code,"message":"核心数据版本暂不可读取，请重试；后台任务不受影响。"})
            revision_ms=(time.perf_counter()-revision_started)*1000
            if fresh:
                snapshot["cache_state"]="fresh"
                response=respond({"ok":True,"bootstrap":dict(_V53_BOOTSTRAP_STATUS),**snapshot})
                response.headers["Server-Timing"]+=f", revision;dur={revision_ms:.2f}"
                response.headers["X-Bootstrap-Cache"]="fresh"
                return response
        _v53_start_bootstrap(requested,force=True)
        return JSONResponse(status_code=503,headers={"Retry-After":"1","Cache-Control":"no-store"},content={"code":"BOOTSTRAP_PENDING","message":"核心页面正在准备，请稍候。","bootstrap":dict(_V53_BOOTSTRAP_STATUS)})
    projects=list_projects(); requested=str(preferred_project_id or "") if ALLOW_MULTIPLE_PROJECTS_FOR_TESTS else ""; cached_id=str(_V53_BOOTSTRAP_SNAPSHOT.get("project",{}).get("id") or ""); project_ids={str(project.get("id") or "") for project in projects}
    if not refresh and _V53_BOOTSTRAP_STATUS.get("status")=="ready" and cached_id in project_ids and (not requested or requested==cached_id):
        live_snapshot=_v53_snapshot_with_live_jobs(_V53_BOOTSTRAP_SNAPSHOT,cached_id)
        return respond({"ok":True,"bootstrap":dict(_V53_BOOTSTRAP_STATUS),**live_snapshot})
    counts={str(project.get("id") or ""):_v53_project_counts(project) for project in projects}; chosen=choose_requested_project(projects,requested,counts) if requested else choose_project(projects,"",counts); chosen_id=str(chosen.get("id")) if chosen else ""
    projects_with_counts=[{**project,"bootstrap_counts":counts.get(str(project.get("id") or ""),{"images":0,"algorithms":0,"versions":0,"jobs":0})} for project in projects]
    if _V53_BOOTSTRAP_STATUS.get("status")!="ready":
        if chosen_id and (not requested or chosen_id==requested):
            snap=_v53_build_snapshot(chosen_id); snap["projects"]=projects_with_counts; _V53_BOOTSTRAP_SNAPSHOT=snap; return respond({"ok":True,"bootstrap":dict(_V53_BOOTSTRAP_STATUS),**snap})
        raise HTTPException(status_code=503,detail={"message":"平台数据仍在启动预加载",**_V53_BOOTSTRAP_STATUS})
    if chosen_id and (refresh or chosen_id!=str(_V53_BOOTSTRAP_SNAPSHOT.get("project",{}).get("id") or "")):
        snap=_v53_build_snapshot(chosen_id); snap["projects"]=projects_with_counts; _V53_BOOTSTRAP_SNAPSHOT=snap; return respond({"ok":True,"bootstrap":dict(_V53_BOOTSTRAP_STATUS),**snap})
    final_id=str(_V53_BOOTSTRAP_SNAPSHOT.get("project",{}).get("id") or "")
    live_snapshot=_v53_snapshot_with_live_jobs(_V53_BOOTSTRAP_SNAPSHOT,final_id) if final_id else dict(_V53_BOOTSTRAP_SNAPSHOT)
    return respond({"ok":True,"bootstrap":dict(_V53_BOOTSTRAP_STATUS),**live_snapshot})


# ============================================================
# v42.14 — label schema management / annotation stability
# ============================================================
from platform_core.annotation_governance_contracts import V54LabelUnifyReq


from platform_core.annotation_governance_contracts import V54LabelsUnifyReq


from platform_core.annotation_governance_contracts import V54LabelsUnifyPreviewReq


def _v54_resolve_unify_sources(project_id: str, source_class_ids):
    return _annotation_governance_service()._v54_resolve_unify_sources(project_id, source_class_ids)


def _v54_start_unify(project_id: str, source_class_ids, target_label: str):
    return _annotation_governance_service()._v54_start_unify(project_id, source_class_ids, target_label)


app.include_router(create_annotation_governance_router_5(_annotation_governance_service))


def v54_label_schema(project_id: str):
    return _annotation_governance_service().v54_label_schema(project_id)


def v54_preview_unify_labels(project_id: str, payload: V54LabelsUnifyPreviewReq):
    return _annotation_governance_service().v54_preview_unify_labels(project_id, payload)


def v54_unify_labels(project_id: str, payload: V54LabelsUnifyReq):
    return _annotation_governance_service().v54_unify_labels(project_id, payload)


def v54_unify_label(project_id: str, class_id: int, payload: V54LabelUnifyReq):
    return _annotation_governance_service().v54_unify_label(project_id, class_id, payload)


@app.get('/api/v54/projects/{project_id}/algorithms/{algorithm_id}/iteration-base')
def v54_iteration_base_info(project_id: str, algorithm_id: str, framework: str = 'ultralytics'):
    get_project(project_id)
    return {'ok': True, 'base': _v54_iteration_base(project_id, algorithm_id, framework, strict_latest=True)}


from platform_core.external_algorithm_platform import (
    ExternalAlgorithmPlatformService,
    assert_algorithm_mutable,
    external_algorithm_platform_router,
)
from platform_core.external_algorithm_publish import (
    ExternalAlgorithmPublishService,
    ExternalPublicationRepository,
    external_algorithm_publish_router,
    request_external_auto_publish_for_conversion_if_enabled,
    request_external_auto_publish_if_enabled,
)
from platform_core.material_batches import material_batch_router
from platform_core.training_material_picker_api import training_material_picker_router
from platform_core.training_recovery_api import training_recovery_router
from platform_core.legacy_material_compatibility_api import legacy_material_compatibility_router
from platform_core.legacy_material_compatibility import LegacyMaterialCompatibilityService

app.include_router(legacy_material_compatibility_router(
    lambda project_id: LegacyMaterialCompatibilityService(DATA_DIR, project_id,
        enabled=os.environ.get('LEGACY_MATERIAL_COMPATIBILITY_ENABLED', '1').strip().lower() not in {'0', 'false', 'off'}),
    _material_governance_actor,
))
from platform_core.remote_execution_transport import (
    RemoteExecutionTransportError,
    RemoteExecutionTransportService,
    SUPPORTED_PORTABLE_RKNN_CHIPS,
)


def _remote_execution_transport_service():
    return RemoteExecutionTransportService(
        data_dir=DATA_DIR,
        project_dir=project_dir,
        algorithms_file=algorithms_file,
        storage_sources_factory=storage_source_repository,
        storage_credentials_factory=storage_credentials,
        task_artifacts=shared_task_artifacts(),
        task_repository=shared_task_repository(),
    )


def _resolve_agent_execution_payload(task, payload, assignment):
    if task.kind is TaskKind.MODEL_INSTALL:
        remote = payload.get("remote_execution") if isinstance(payload, dict) else None
        selected = _verified_mother_model_asset(DATA_DIR, str(payload.get("asset_id") or ""))
        if (not isinstance(remote, dict) or remote.get("version") != 1
                or remote.get("task_kind") != "MODEL_INSTALL"
                or remote.get("transport") != "agent-artifact-v1"
                or str(payload.get("node_id") or "") != str(assignment.get("node_id") or "")
                or selected is None
                or selected.get("sha256") != payload.get("sha256")
                or selected.get("size_bytes") != payload.get("size_bytes")):
            raise ValueError("MODEL_INSTALL_ASSET_OR_NODE_CHANGED")
        return {"schema_version": 1, "task_kind": "MODEL_INSTALL",
                "transport": "agent-artifact-v1", "asset_id": payload["asset_id"],
                "sha256": payload["sha256"], "size_bytes": payload["size_bytes"]}
    return _remote_execution_transport_service().resolve_execution_payload(
        task,
        payload,
        assignment,
    )


def _prepare_agent_result_upload(task, payload, evidence):
    return _remote_execution_transport_service().prepare_result_upload(
        task,
        payload,
        evidence,
    )


def _confirm_agent_result_upload(task, payload, evidence):
    return _remote_execution_transport_service().confirm_result_upload(
        task,
        payload,
        evidence,
    )


def _commit_agent_result_publication(task, payload, evidence, confirmed):
    return _remote_execution_transport_service().commit_result_publication(
        task,
        payload,
        evidence,
        confirmed,
    )


def _prepare_agent_training_model_uploads(task, payload, *, execution_generation, models):
    return _remote_execution_transport_service().prepare_training_model_uploads(
        task,
        payload,
        execution_generation=execution_generation,
        models=models,
    )


def _confirm_agent_training_model_uploads(task, payload, *, execution_generation, models):
    return _remote_execution_transport_service().confirm_training_model_uploads(
        task,
        payload,
        execution_generation=execution_generation,
        models=models,
    )


def _agent_training_inputs(task, payload, *, image_id=None):
    return _remote_execution_transport_service().training_inputs(task, payload, image_id=image_id)


def _agent_material_scan_page(task, payload, *, cursor=None, limit=100):
    return _remote_execution_transport_service().material_scan_page(
        task,
        payload,
        cursor=cursor,
        limit=limit,
    )


def _agent_material_scan_read(task, payload, *, object_key):
    return _remote_execution_transport_service().material_scan_read_contract(
        task,
        payload,
        object_key=object_key,
    )


def _agent_clean_selection_page(task, payload, *, cursor=None, limit=100):
    return _remote_execution_transport_service().clean_selection_page(
        task,
        payload,
        cursor=cursor,
        limit=limit,
    )


def _agent_clean_selection_read(task, payload, *, image_id):
    return _remote_execution_transport_service().clean_selection_read_contract(
        task,
        payload,
        image_id=image_id,
    )


app.include_router(external_algorithm_platform_router(
    data_dir=DATA_DIR,
    get_project=_authorize_business_file_project,
    algorithms_file=algorithms_file,
    secret_store_factory=_v35_secret_store,
))
app.include_router(external_algorithm_publish_router(
    data_dir=DATA_DIR,
    get_project=_authorize_business_file_project,
    project_dir=project_dir,
    algorithms_file=algorithms_file,
    external_secret_store_factory=_v35_secret_store,
    storage_sources_factory=storage_source_repository,
    storage_credentials_factory=storage_credentials,
))
app.include_router(material_batch_router(
    _authorize_business_file_project,
    material_store,
    shared_task_repository,
    shared_task_artifacts,
    _storage_source_fence,
    training_selection_provider=_training_compatibility_request,
    actor_provider=_material_governance_actor,
    legacy_batch_resolver=_material_legacy_zip_batch_ids,
))
from platform_core.smart_material_audit.api import smart_material_audit_router
app.include_router(smart_material_audit_router(
    _authorize_business_file_project,lambda:DATA_DIR,shared_task_repository,shared_task_artifacts,
    actor_provider=_material_governance_actor,
))
def _review_training_negative(project_id, item, effective_codes, actor):
    """Reuse the formal annotation save and its CAS/content/lifecycle fences."""
    image_id = str(item.get('image_id') or '')
    expected = item.get('expected_version')
    source_hash = str(item.get('source_content_sha256') or '').strip().lower()
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0 or len(source_hash) != 64:
        raise HTTPException(422, detail='审核缺少真实标注版本或图片摘要，请刷新图片')
    actor_id = str((actor or {}).get('actor_id') or '')
    if not actor_id:
        raise HTTPException(401, detail='请先登录后审核素材')
    current = read_annotation(project_id, image_id)
    boxes = list(current.get('boxes') or [])
    if any(str(box.get('label') or box.get('code') or '') in set(effective_codes) for box in boxes):
        raise HTTPException(409, detail='图片已有本次训练目标，请进入标注工作台审核，不能确认纯负样本')
    if int(current.get('version') or 0) != expected:
        evidence = _v50_annotation_repository(project_id).negative_review_evidence(image_id,expected,actor_id,effective_codes,source_hash)
        material = material_store(project_id).get(image_id)
        if (evidence and material and not material.get(_V50_DATASET_DELETE_CLAIM_FIELD)
                and material.get('source_available') is not False
                and not any(material.get(flag) for flag in ('annotation_needs_review','external_annotation_needs_review','needs_review'))
                and str(material.get('content_sha256') or '') == source_hash
                and int(current.get('version') or 0) == evidence['annotation_version']
                and current.get('content_digest') == evidence['annotation_digest']):
            return {'ok':True,'annotation':current,'review_evidence':evidence}
        raise HTTPException(409, detail='正式GT版本已经变化，请重新查看图片后审核')
    payload = AnnotationSave(boxes=boxes,annotation_state='annotated' if boxes else 'confirmed_empty',
        expected_version=expected,source_content_sha256=source_hash,
        reviewed_label_codes=sorted(set(effective_codes) | {str(code) for code in current.get('annotation_scope') or [] if code != '*'}))
    payload._review_actor = actor_id
    payload._review_codes = list(effective_codes)
    return save_annotation(project_id,image_id,payload)


from platform_core.negative_pool_api import create_negative_pool_router

def _negative_pool_training_usage(project_id, rows):
    from platform_core.training_material_usage import TrainingMaterialUsage
    database = DATA_DIR / 'task_runtime' / 'tasks.sqlite3'
    if not database.is_file():
        return {}
    return TrainingMaterialUsage(database).query_filter(project_id, '', rows, exclude_used=False)['by_image_id']

app.include_router(create_negative_pool_router(material_store, _authorize_business_file_project,
    public_material, usage_for_page=_negative_pool_training_usage))

app.include_router(training_material_picker_router(
    _authorize_business_file_project,
    lambda: DATA_DIR,
    project_path_provider=project_dir,
    algorithm_provider=lambda project_id, algorithm_id: next(
        (
            row for row in list_algorithms_internal(project_id)
            if str(row.get("id") or "") == str(algorithm_id or "")
        ),
        None,
    ),
    compatibility_payload_provider=_training_compatibility_request,
    review_negative_provider=_review_training_negative,
    actor_provider=_material_governance_actor,
))
app.include_router(training_recovery_router(
    get_project,
    shared_task_repository,
    shared_task_artifacts,
    project_path_provider=project_dir,
    workspace_actor_provider=_material_governance_actor,
    agent_execution_payload_resolver=_resolve_agent_execution_payload,
    agent_result_upload_preparer=_prepare_agent_result_upload,
    agent_result_upload_confirmer=_confirm_agent_result_upload,
    agent_result_commit_handler=_commit_agent_result_publication,
    agent_training_model_upload_preparer=_prepare_agent_training_model_uploads,
    agent_training_model_upload_confirmer=_confirm_agent_training_model_uploads,
    agent_material_scan_page_provider=_agent_material_scan_page,
    agent_material_scan_read_provider=_agent_material_scan_read,
    agent_clean_selection_page_provider=_agent_clean_selection_page,
    agent_clean_selection_read_provider=_agent_clean_selection_read,
    agent_training_inputs_provider=_agent_training_inputs,
    agent_model_install_asset_provider=lambda asset_id: _verified_mother_model_asset(DATA_DIR, asset_id),
))
