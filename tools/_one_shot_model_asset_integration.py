from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, got {count}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def insert_after(path: str, marker: str, addition: str) -> None:
    replace_once(path, marker, marker + addition)


# ---- Changlian client: central HTTP audit ----
path = "platform_core/external_algorithm_platform.py"
insert_after(path, "from .errors import PlatformError\n", "from .integration_audit import IntegrationAuditRepository\n")

replace_once(
    path,
    "        session: Optional[requests.Session] = None,\n        timeout: float = 15.0,\n    ):\n",
    "        session: Optional[requests.Session] = None,\n        timeout: float = 15.0,\n        audit_callback: Optional[Callable[[Mapping[str, Any]], Any]] = None,\n    ):\n",
)
insert_after(
    path,
    "        self._token_lock = threading.Lock()\n",
    "        self.audit_callback = audit_callback\n        self.audit_context: Dict[str, Any] = {}\n",
)

old_request = '''    def _request(self, method: str, path: str, *, auth: bool = False, **kwargs: Any) -> Any:\n        headers = dict(kwargs.pop("headers", {}) or {})\n        headers.setdefault("Accept", "application/json")\n        if auth:\n            token_type, token = self.token()\n            headers["Authorization"] = f"{token_type} {token}".strip()\n        try:\n            response = self.session.request(\n                method.upper(),\n                self._url(path),\n                headers=headers,\n                timeout=self.timeout,\n                **kwargs,\n            )\n        except requests.RequestException as error:\n            raise RuntimeError(f"无法连接外部平台：{type(error).__name__}") from error\n        if not 200 <= response.status_code < 300:\n            message = ""\n            try:\n                body = response.json()\n                if isinstance(body, dict):\n                    message = str(body.get("message") or body.get("msg") or body.get("detail") or "")\n            except ValueError:\n                pass\n            suffix = f"：{message}" if message else ""\n            raise RuntimeError(f"外部平台请求失败 HTTP {response.status_code}{suffix}")\n        return _ResponseAdapter.json(response)\n'''
new_request = '''    def set_audit_context(self, **context: Any) -> None:\n        self.audit_context.update({key: value for key, value in context.items() if value not in (None, "")})\n\n    def _operation_for_path(self, path: str) -> str:\n        current = str(path or "").split("?", 1)[0]\n        exact = {\n            self.endpoints.test_sign: "auth_signature",\n            self.endpoints.token: "auth_token",\n            self.endpoints.category_tree: "category_list",\n            self.endpoints.product_list: "product_list",\n            self.endpoints.compute_platform_list: "compute_platform_list",\n            self.endpoints.version_create: "version_create",\n            self.endpoints.weight_create: "weight_create",\n        }\n        if current in exact:\n            return exact[current]\n        if "algorithm-product-analysis" in current:\n            return "analysis_list"\n        if "algorithm-version" in current:\n            return "version_list"\n        if "algorithm-weight" in current:\n            return "weight_list"\n        return "http_request"\n\n    def _emit_audit(self, event: Mapping[str, Any]) -> None:\n        if not self.audit_callback:\n            return\n        try:\n            self.audit_callback({"provider": "changlian", **self.audit_context, **dict(event)})\n        except Exception:\n            # Audit persistence must never change remote-call semantics.\n            pass\n\n    def _request(self, method: str, path: str, *, auth: bool = False, **kwargs: Any) -> Any:\n        headers = dict(kwargs.pop("headers", {}) or {})\n        headers.setdefault("Accept", "application/json")\n        if auth:\n            token_type, token = self.token()\n            headers["Authorization"] = f"{token_type} {token}".strip()\n        started = time.perf_counter()\n        correlation_id = hashlib.sha256(f"{time.time_ns()}:{method}:{path}".encode()).hexdigest()[:24]\n        request_snapshot = {\n            "headers": headers,\n            "params": kwargs.get("params") or {},\n            "json": kwargs.get("json") or {},\n        }\n        try:\n            response = self.session.request(\n                method.upper(),\n                self._url(path),\n                headers=headers,\n                timeout=self.timeout,\n                **kwargs,\n            )\n        except requests.RequestException as error:\n            self._emit_audit({\n                "operation": self._operation_for_path(path), "status": "UNKNOWN", "method": method,\n                "endpoint": str(path), "duration_ms": int((time.perf_counter() - started) * 1000),\n                "correlation_id": correlation_id, "request": request_snapshot,\n                "error_code": type(error).__name__, "error_message": str(error),\n            })\n            raise RuntimeError(f"无法连接外部平台：{type(error).__name__}") from error\n        try:\n            body = response.json()\n        except ValueError:\n            body = {"raw": str(getattr(response, "text", ""))[:2000]}\n        response_headers = getattr(response, "headers", {}) or {}\n        request_id = str(\n            response_headers.get("X-Request-Id") or response_headers.get("X-Request-ID")\n            or response_headers.get("X-Correlation-Id") or response_headers.get("Trace-Id") or ""\n        )\n        business_code = str(body.get("code") or "") if isinstance(body, dict) else ""\n        business_failed = bool(\n            isinstance(body, dict)\n            and (body.get("success") is False or (body.get("code") is not None and business_code not in {"0", "200", "SUCCESS", "success"}))\n        )\n        http_ok = 200 <= response.status_code < 300\n        message = ""\n        if isinstance(body, dict):\n            message = str(body.get("message") or body.get("msg") or body.get("detail") or "")\n        self._emit_audit({\n            "operation": self._operation_for_path(path),\n            "status": "SUCCESS" if http_ok and not business_failed else "FAILED",\n            "method": method, "endpoint": str(path), "http_status": response.status_code,\n            "business_code": business_code, "duration_ms": int((time.perf_counter() - started) * 1000),\n            "request_id": request_id, "correlation_id": correlation_id,\n            "request": request_snapshot, "response": body,\n            "error_code": business_code if (business_failed or not http_ok) else "",\n            "error_message": message if (business_failed or not http_ok) else "",\n        })\n        if not http_ok:\n            suffix = f"：{message}" if message else ""\n            raise RuntimeError(f"外部平台请求失败 HTTP {response.status_code}{suffix}")\n        return body\n'''
replace_once(path, old_request, new_request)

insert_after(
    path,
    "        self.client_factory = client_factory\n",
    "        self.audit = IntegrationAuditRepository(Path(data_dir))\n",
)
replace_once(
    path,
    "            access_secret=access_secret,\n            endpoints=endpoints,\n        )\n",
    "            access_secret=access_secret,\n            endpoints=endpoints,\n            audit_callback=self.audit.record,\n        )\n",
)

router_marker = '''    @router.get("/sync-history")\n    def sync_history(limit: int = Query(default=20, ge=1, le=100)):\n        return {"ok": True, "items": service.repository.history()[:limit]}\n\n'''
router_addition = '''    @router.get("/interaction-logs/summary")\n    def interaction_log_summary(hours: int = Query(default=24, ge=1, le=720)):\n        return {"ok": True, "summary": service.audit.summary(provider="changlian", hours=hours)}\n\n    @router.get("/interaction-logs")\n    def interaction_logs(\n        status: str = Query(default=""), operation: str = Query(default=""),\n        project_id: str = Query(default=""), limit: int = Query(default=50, ge=1, le=200),\n        offset: int = Query(default=0, ge=0),\n    ):\n        return {\n            "ok": True,\n            "items": service.audit.list(\n                provider="changlian", status=status, operation=operation, project_id=project_id,\n                limit=limit, offset=offset,\n            ),\n        }\n\n    @router.get("/interaction-logs/{log_id}")\n    def interaction_log_detail(log_id: str):\n        item = service.audit.get(log_id)\n        if item is None:\n            raise PlatformError("INTERACTION_LOG_NOT_FOUND", "交互日志不存在", log_id, "请刷新日志列表。", 404)\n        return {"ok": True, "item": item}\n\n'''
replace_once(path, router_marker, router_marker + router_addition)


# ---- Model asset storage + external publish reuse ----
path = "platform_core/external_algorithm_publish.py"
insert_after(path, "from .errors import PlatformError\n", "from .integration_audit import IntegrationAuditRepository\nfrom .model_artifacts import ModelArtifactConfigPayload, ModelArtifactService, StorageTestPayload\n")

insert_after(
    path,
    "        self.external_repository = ExternalPlatformRepository(self.data_dir)\n",
    '''        self.audit = IntegrationAuditRepository(self.data_dir)\n        self.model_assets = ModelArtifactService(\n            data_dir=self.data_dir, project_dir=self.project_dir, algorithms_file=self.algorithms_file,\n            storage_sources_factory=self.storage_sources_factory,\n            storage_credentials_factory=self.storage_credentials_factory,\n        )\n        legacy_publish = self.repository.config()\n        asset_config = self.model_assets.repository.config()\n        if not str(asset_config.get("storage_source_id") or "") and str(legacy_publish.get("storage_source_id") or ""):\n            self.model_assets.save_config(ModelArtifactConfigPayload(\n                storage_source_id=str(legacy_publish.get("storage_source_id") or ""),\n                object_prefix="model-assets", auto_upload_enabled=True,\n            ))\n''',
)

old_save_config = '''    def save_config(self, payload: ExternalPublishConfigPayload) -> Dict[str, Any]:\n        source_id = str(payload.storage_source_id or "").strip()\n        if source_id and self.storage_sources_factory().get(source_id) is None:\n            raise PlatformError(\n                "ARTIFACT_STORAGE_SOURCE_NOT_FOUND", "模型发布存储源不存在", source_id,\n                "请在存储源配置中创建或恢复该存储源。", 404,\n            )\n        if payload.public_base_url and not str(payload.public_base_url).startswith(("http://", "https://")):\n            raise PlatformError(\n                "ARTIFACT_PUBLIC_URL_INVALID", "模型下载服务地址格式不正确", str(payload.public_base_url),\n                "请填写以 http:// 或 https:// 开头的本平台外部访问地址。", 422,\n            )\n        return self.repository.save_config(payload)\n'''
new_save_config = '''    def save_config(self, payload: ExternalPublishConfigPayload) -> Dict[str, Any]:\n        source_id = str(payload.storage_source_id or "").strip()\n        if source_id and self.storage_sources_factory().get(source_id) is None:\n            raise PlatformError(\n                "ARTIFACT_STORAGE_SOURCE_NOT_FOUND", "模型发布存储源不存在", source_id,\n                "请在存储源配置中创建或恢复该存储源。", 404,\n            )\n        if payload.public_base_url and not str(payload.public_base_url).startswith(("http://", "https://")):\n            raise PlatformError(\n                "ARTIFACT_PUBLIC_URL_INVALID", "模型下载服务地址格式不正确", str(payload.public_base_url),\n                "请填写以 http:// 或 https:// 开头的本平台外部访问地址。", 422,\n            )\n        saved = self.repository.save_config(payload)\n        # Backward compatible: an existing publication storage choice becomes the platform model-asset storage.\n        if source_id:\n            current = self.model_assets.repository.config()\n            self.model_assets.save_config(ModelArtifactConfigPayload(\n                storage_source_id=source_id,\n                object_prefix=str(current.get("object_prefix") or "model-assets"),\n                auto_upload_enabled=bool(current.get("auto_upload_enabled", True)),\n            ))\n        return saved\n'''
replace_once(path, old_save_config, new_save_config)

replace_once(
    path,
    "            access_secret=str(credentials.get(\"access_secret\") or \"\"),\n            endpoints=ChangLianEndpoints.from_mapping(config.get(\"endpoints\")),\n        )\n",
    "            access_secret=str(credentials.get(\"access_secret\") or \"\"),\n            endpoints=ChangLianEndpoints.from_mapping(config.get(\"endpoints\")),\n            audit_callback=self.audit.record,\n        )\n",
)

start = (ROOT / path).read_text(encoding="utf-8")
method_start = start.index("    def _upload_artifact(")
method_end = start.index("    def _recover_weight(", method_start)
old_upload = start[method_start:method_end]
new_upload = '''    def _upload_artifact(self, artifact: Mapping[str, Any], algorithm: Mapping[str, Any], version: Mapping[str, Any]) -> Dict[str, Any]:\n        base_url = str(self.repository.config().get("public_base_url") or "").rstrip("/")\n        if not base_url:\n            raise PlatformError(\n                "EXTERNAL_PUBLISH_CONFIG_INCOMPLETE", "模型发布配置不完整", "缺少本平台外部访问地址。",\n                "请在“平台对接 → 畅联云版本发布”填写外部访问地址。", 422,\n            )\n        discovered = {\n            "artifact_id": str(artifact["artifact_id"]),\n            "project_id": str(artifact["project_id"]),\n            "algorithm_id": str(artifact["algorithm_id"]),\n            "version_id": str(artifact["version_id"]),\n            "artifact_kind": "original" if str(artifact.get("target") or "") == "original" else "conversion",\n            "target": str(artifact.get("target") or "unknown"),\n            "conversion_job_id": "",\n            "file_name": str(artifact["file_name"]),\n            "source_path": str(artifact["source_path"]),\n            "sha256": str(artifact.get("source_sha256") or artifact.get("sha256") or ""),\n            "size_bytes": int(artifact["size_bytes"]),\n            "metadata": {"chip_code": str(artifact.get("chip_code") or "")},\n        }\n        stored = self.model_assets.ensure_uploaded(discovered)\n        if str(stored.get("storage_status") or "").upper() != "UPLOADED":\n            raise RuntimeError(str(stored.get("storage_error") or "模型资产上传失败"))\n        public_url = f"{base_url}/api/v64/model-artifacts/{artifact['artifact_id']}/download"\n        return self.repository.patch_artifact(\n            str(artifact["artifact_id"]),\n            storage_source_id=str(stored.get("storage_source_id") or ""),\n            object_key=str(stored.get("object_key") or ""),\n            public_url=public_url, upload_status="UPLOADED", last_error="",\n        )\n\n'''
(ROOT / path).write_text(start[:method_start] + new_upload + start[method_end:], encoding="utf-8")

replace_once(
    path,
    "        client = self._external_client()\n        external_version_id = self._ensure_external_version(publication, algorithm, version, client)\n",
    '''        client = self._external_client()\n        if hasattr(client, "set_audit_context"):\n            client.set_audit_context(\n                project_id=project_id, algorithm_id=algorithm_id, version_id=version_id,\n                external_product_id=str(algorithm.get("external_product_id") or ""),\n                external_analysis_id=str(version.get("external_analysis_id") or algorithm.get("external_analysis_id") or ""),\n            )\n        external_version_id = self._ensure_external_version(publication, algorithm, version, client)\n''',
)
replace_once(
    path,
    "            try:\n                uploaded = self._upload_artifact(row, algorithm, version)\n                self._sync_weight(uploaded, external_version_id, client)\n",
    '''            try:\n                uploaded = self._upload_artifact(row, algorithm, version)\n                if hasattr(client, "set_audit_context"):\n                    client.set_audit_context(artifact_id=str(row.get("artifact_id") or ""), external_algo_version_id=external_version_id)\n                self._sync_weight(uploaded, external_version_id, client)\n''',
)

replace_once(
    path,
    "            and publish.get(\"storage_source_id\")\n            and publish.get(\"public_base_url\")\n",
    "            and self.model_assets.repository.config().get(\"storage_source_id\")\n            and publish.get(\"public_base_url\")\n",
)

# Replace download to prefer platform-level model_artifacts while retaining old external rows.
text = (ROOT / path).read_text(encoding="utf-8")
download_start = text.index("    def download(self, artifact_id: str):")
download_end = text.index("\n\ndef request_external_auto_publish_if_enabled", download_start)
old_download = text[download_start:download_end]
new_download = '''    def download(self, artifact_id: str):\n        artifact = self.model_assets.repository.get(artifact_id)\n        if artifact is not None and str(artifact.get("storage_status") or "").upper() == "UPLOADED":\n            _row, provider = self.model_assets.download(artifact_id)\n            object_key = str(artifact["object_key"])\n            filename = str(artifact.get("file_name") or "model.bin").replace('"', "")\n        else:\n            artifact = self.repository.artifact(artifact_id)\n            if artifact is None or str(artifact.get("upload_status") or "").upper() != "UPLOADED":\n                raise PlatformError("MODEL_ARTIFACT_NOT_FOUND", "模型制品不存在或尚未上传", artifact_id, "请重新执行模型资产上传。", 404)\n            provider = self._provider(str(artifact["project_id"]), str(artifact["storage_source_id"]))\n            object_key = str(artifact["object_key"])\n            filename = str(artifact.get("file_name") or "model.bin").replace('"', "")\n        url = provider.generate_preview_url(object_key, expires_seconds=600)\n        if url:\n            return RedirectResponse(url=url, status_code=302)\n        stream = provider.open_reader(object_key)\n\n        def chunks():\n            try:\n                while True:\n                    block = stream.read(1024 * 1024)\n                    if not block:\n                        break\n                    yield block\n            finally:\n                try:\n                    stream.close()\n                except Exception:\n                    pass\n\n        return StreamingResponse(\n            chunks(),\n            media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",\n            headers={"Content-Disposition": f'attachment; filename="{filename}"'},\n        )\n'''
(ROOT / path).write_text(text[:download_start] + new_download + text[download_end:], encoding="utf-8")

insert_after(
    path,
    "    worker_lock = FileLock(str(service.repository.root / \".auto-publish-worker.lock\"), timeout=0)\n",
    "    asset_worker_lock = FileLock(str(service.model_assets.repository.root / \".auto-upload-worker.lock\"), timeout=0)\n",
)
replace_once(
    path,
    '''        while True:\n            try:\n                if service.auto_publish_ready():\n                    try:\n                        with worker_lock.acquire(timeout=0):\n                            service.run_auto_publish_once()\n                    except Timeout:\n                        pass\n            except Exception:\n                pass\n            time.sleep(30)\n''',
    '''        while True:\n            try:\n                try:\n                    with asset_worker_lock.acquire(timeout=0):\n                        service.model_assets.run_auto_upload_once()\n                except Timeout:\n                    pass\n                if service.auto_publish_ready():\n                    try:\n                        with worker_lock.acquire(timeout=0):\n                            service.run_auto_publish_once()\n                    except Timeout:\n                        pass\n            except Exception:\n                pass\n            time.sleep(30)\n''',
)

route_anchor = '''    @router.get("/api/v64/external-publish/config")\n    def get_publish_config():\n        return {"ok": True, **service.public_config()}\n\n'''
model_routes = '''    @router.get("/api/v64/model-artifacts/config")\n    def get_model_artifact_config():\n        return {"ok": True, **service.model_assets.public_config()}\n\n    @router.put("/api/v64/model-artifacts/config")\n    def save_model_artifact_config(payload: ModelArtifactConfigPayload):\n        return {"ok": True, "config": service.model_assets.save_config(payload)}\n\n    @router.post("/api/v64/model-artifacts/storage-test")\n    def test_model_artifact_storage(payload: StorageTestPayload):\n        return service.model_assets.test_storage(payload.storage_source_id)\n\n    @router.get("/api/v64/model-artifacts")\n    def list_model_artifacts(\n        project_id: str = Query(default=""), algorithm_id: str = Query(default=""),\n        version_id: str = Query(default=""), status: str = Query(default=""),\n        limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),\n    ):\n        return {\n            "ok": True,\n            "items": service.model_assets.repository.list(\n                project_id=project_id, algorithm_id=algorithm_id, version_id=version_id,\n                status=status, limit=limit, offset=offset,\n            ),\n            "summary": service.model_assets.repository.summary(project_id=project_id),\n        }\n\n    @router.post("/api/v64/model-artifacts/{artifact_id}/retry")\n    def retry_model_artifact(artifact_id: str):\n        return {"ok": True, "artifact": service.model_assets.retry(artifact_id)}\n\n    @router.post("/api/v64/model-artifacts/run-auto")\n    def run_model_artifact_auto_upload():\n        return {"ok": True, **service.model_assets.run_auto_upload_once()}\n\n'''
replace_once(path, route_anchor, route_anchor + model_routes)


# ---- Publishing UI: storage lives in the platform-level model asset panel ----
path = "static/modules/external-algorithm-publish.js"
replace_once(
    path,
    '<div class="panel-head"><div><div class="panel-title">训练成果发布</div><div class="subline">转换完成后将模型制品上传到选定对象存储，并把算法版本、算力环境、芯片和下载地址登记到新畅联。</div></div></div>',
    '<div class="panel-head"><div><div class="panel-title">畅联云版本发布</div><div class="subline">模型文件统一从“模型资产存储”读取；这里仅配置畅联云版本/权重登记和算力环境映射。</div></div></div>',
)
replace_once(
    path,
    '''        <div class="form two">\n          <div class="field"><label>模型制品存储源</label><select id="externalPublishStorage" class="select">${storageOptions(c.storageSourceId)}</select></div>\n          <div class="field"><label>本平台外部访问地址</label><input id="externalPublishBaseUrl" class="input" value="${escapeHtml(c.publicBaseUrl)}" placeholder="https://algorithm.example.com"></div>\n          <label class="field check"><input id="externalPublishOriginal" type="checkbox" ${c.publishOriginalModel ? 'checked' : ''}> 同时发布原始训练权重（默认仅发布转换产物）</label>\n        </div>''',
    '''        <div class="form two">\n          <div class="field"><label>本平台外部访问地址</label><input id="externalPublishBaseUrl" class="input" value="${escapeHtml(c.publicBaseUrl)}" placeholder="https://algorithm.example.com"></div>\n          <label class="field check"><input id="externalPublishOriginal" type="checkbox" ${c.publishOriginalModel ? 'checked' : ''}> 将原始训练权重也登记为畅联云权重（文件本身始终自动归档）</label>\n        </div>''',
)
replace_once(
    path,
    "      storage_source_id: document.getElementById('externalPublishStorage')?.value || '',\n",
    "      storage_source_id: config?.storageSourceId || '',\n",
)


# ---- Register the new frontend runtime ----
path = "static/main.mjs"
insert_after(
    path,
    "import {installExternalAlgorithmPublishRuntime} from './modules/external-algorithm-publish.js?v=64002';\n",
    "import {installModelArtifactRuntime} from './modules/model-artifact-runtime.js?v=65001';\n",
)
insert_after(
    path,
    "window.PlatformCore.runtime.externalAlgorithmPublishRuntime = externalAlgorithmPublishRuntime;\n",
    '''\nconst modelArtifactRuntime = installModelArtifactRuntime({\n  getState: () => state,\n  notify,\n});\nwindow.PlatformCore.runtime.modelArtifactRuntime = modelArtifactRuntime;\n''',
)

print("model asset + changlian audit patch applied")
