from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one marker, found {count}")
    return text.replace(old, new, 1)


def patch_backend() -> None:
    path = ROOT / "platform_core" / "external_algorithm_platform.py"
    text = path.read_text(encoding="utf-8")
    if "DEFAULT_AUTO_SYNC_INTERVAL_SECONDS" in text:
        return

    text = replace_once(
        text,
        "from filelock import FileLock\n",
        "from filelock import FileLock, Timeout\n",
        "filelock import",
    )
    text = replace_once(
        text,
        "MAX_SYNC_HISTORY = 100\n",
        "MAX_SYNC_HISTORY = 100\nDEFAULT_AUTO_SYNC_INTERVAL_SECONDS = 600\n",
        "auto sync constant",
    )
    text = replace_once(
        text,
        '    "auto_sync_enabled": False,\n    "auto_publish_enabled": False,\n',
        '    "auto_sync_enabled": False,\n    "auto_sync_interval_seconds": DEFAULT_AUTO_SYNC_INTERVAL_SECONDS,\n    "auto_publish_enabled": False,\n',
        "default config interval",
    )
    text = replace_once(
        text,
        "    auto_sync_enabled: bool = False\n    auto_publish_enabled: bool = False\n",
        "    auto_sync_enabled: bool = False\n    auto_sync_interval_seconds: int = Field(default=DEFAULT_AUTO_SYNC_INTERVAL_SECONDS, ge=60, le=86400)\n    auto_publish_enabled: bool = False\n",
        "payload interval",
    )
    text = replace_once(
        text,
        '            "auto_sync_enabled": bool(value.get("auto_sync_enabled", False)),\n            "auto_publish_enabled": bool(value.get("auto_publish_enabled", False)),\n',
        '            "auto_sync_enabled": bool(value.get("auto_sync_enabled", False)),\n            "auto_sync_interval_seconds": max(60, min(86400, int(value.get("auto_sync_interval_seconds") or DEFAULT_AUTO_SYNC_INTERVAL_SECONDS))),\n            "auto_publish_enabled": bool(value.get("auto_publish_enabled", False)),\n',
        "save config interval",
    )
    text = replace_once(
        text,
        '            "auto_sync_enabled": bool(config.get("auto_sync_enabled")),\n            "auto_publish_enabled": bool(config.get("auto_publish_enabled")),\n',
        '            "auto_sync_enabled": bool(config.get("auto_sync_enabled")),\n            "auto_sync_interval_seconds": int(config.get("auto_sync_interval_seconds") or DEFAULT_AUTO_SYNC_INTERVAL_SECONDS),\n            "auto_publish_enabled": bool(config.get("auto_publish_enabled")),\n            "auth_mode": "test_sign_bridge",\n',
        "public config interval",
    )
    text = replace_once(
        text,
        "    def sync(self, *, project_id: str, algorithms_path: Path) -> Dict[str, Any]:\n",
        "    def sync(\n        self,\n        *,\n        project_id: str,\n        algorithms_path: Path,\n        sync_type: Literal[\"manual\", \"auto\"] = \"manual\",\n    ) -> Dict[str, Any]:\n",
        "sync signature",
    )
    text = replace_once(
        text,
        '            "sync_type": "manual",\n',
        '            "sync_type": sync_type,\n',
        "sync type history",
    )

    marker = "\n\ndef external_algorithm_platform_router(\n"
    insertion = '''\n\n    def auto_sync_due(self, *, now: Optional[datetime] = None) -> bool:\n        config = self.repository.config()\n        if str(config.get("mode") or "local") != "external":\n            return False\n        if not bool(config.get("auto_sync_enabled")):\n            return False\n        if not str(config.get("base_url") or "").strip():\n            return False\n        interval = max(60, min(86400, int(config.get("auto_sync_interval_seconds") or DEFAULT_AUTO_SYNC_INTERVAL_SECONDS)))\n        history = self.repository.history()\n        latest = history[0] if history else None\n        if not latest:\n            return True\n        stamp = latest.get("finished_at") or latest.get("started_at")\n        if not stamp:\n            return True\n        try:\n            last = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))\n        except ValueError:\n            return True\n        current = now or datetime.now(timezone.utc)\n        if current.tzinfo is None:\n            current = current.replace(tzinfo=timezone.utc)\n        return (current - last).total_seconds() >= interval\n\n\ndef external_algorithm_platform_router(\n'''
    text = replace_once(text, marker, insertion, "auto sync due insertion")

    router_marker = '''    service = ExternalAlgorithmPlatformService(\n        data_dir=Path(data_dir),\n        secret_store_factory=secret_store_factory,\n    )\n\n    @router.get("/config")\n'''
    router_replacement = '''    service = ExternalAlgorithmPlatformService(\n        data_dir=Path(data_dir),\n        secret_store_factory=secret_store_factory,\n    )\n    auto_sync_lock = FileLock(str(service.repository.root / ".auto-sync-worker.lock"), timeout=0)\n\n    def _auto_sync_projects() -> list[str]:\n        projects_path = Path(data_dir) / "projects.json"\n        if not projects_path.exists():\n            return []\n        try:\n            rows = json.loads(projects_path.read_text(encoding="utf-8"))\n        except (OSError, json.JSONDecodeError):\n            return []\n        if not isinstance(rows, list):\n            return []\n        result: list[str] = []\n        for row in rows:\n            if not isinstance(row, dict):\n                continue\n            project_id = str(row.get("id") or "").strip()\n            if project_id:\n                result.append(project_id)\n        return result\n\n    def _auto_sync_once() -> None:\n        if not service.auto_sync_due():\n            return\n        try:\n            with auto_sync_lock.acquire(timeout=0):\n                if not service.auto_sync_due():\n                    return\n                for project_id in _auto_sync_projects():\n                    try:\n                        get_project(project_id)\n                        service.sync(\n                            project_id=project_id,\n                            algorithms_path=algorithms_file(project_id),\n                            sync_type="auto",\n                        )\n                    except Exception:\n                        # sync() records provider failures; one project must not stop the worker.\n                        continue\n        except Timeout:\n            return\n\n    def _auto_sync_loop() -> None:\n        while True:\n            try:\n                _auto_sync_once()\n            except Exception:\n                pass\n            time.sleep(30)\n\n    threading.Thread(\n        target=_auto_sync_loop,\n        name="external-algorithm-platform-auto-sync",\n        daemon=True,\n    ).start()\n\n    @router.get("/config")\n'''
    text = replace_once(text, router_marker, router_replacement, "auto sync worker")
    text = replace_once(
        text,
        "        return service.sync(project_id=project_id, algorithms_path=algorithms_file(project_id))\n",
        "        return service.sync(project_id=project_id, algorithms_path=algorithms_file(project_id), sync_type=\"manual\")\n",
        "manual sync explicit",
    )
    path.write_text(text, encoding="utf-8")


def patch_frontend() -> None:
    path = ROOT / "static" / "modules" / "external-algorithm-platform.js"
    text = path.read_text(encoding="utf-8")
    if "masterDataPreviewHtml" in text:
        return

    text = replace_once(
        text,
        "    autoSyncEnabled: Boolean(config.auto_sync_enabled),\n    autoPublishEnabled: Boolean(config.auto_publish_enabled),\n",
        "    autoSyncEnabled: Boolean(config.auto_sync_enabled),\n    autoSyncIntervalSeconds: Number(config.auto_sync_interval_seconds || 600),\n    autoPublishEnabled: Boolean(config.auto_publish_enabled),\n    authMode: config.auth_mode || 'test_sign_bridge',\n",
        "frontend normalize auto sync",
    )
    text = replace_once(
        text,
        "  let config = null;\n  let history = [];\n",
        "  let config = null;\n  let history = [];\n  let cacheData = {categories: [], products: [], analyses_by_product: {}, compute_platforms: []};\n",
        "cache state",
    )
    load_history = '''  async function loadHistory({silent = false} = {}) {\n    try {\n      const body = await requestJson(`${API_ROOT}/sync-history?limit=20`);\n      history = Array.isArray(body?.items) ? body.items : [];\n      return history;\n    } catch (error) {\n      if (!silent) notify?.(error?.message || error);\n      throw error;\n    }\n  }\n\n'''
    load_cache = load_history + '''  async function loadCache({silent = false} = {}) {\n    try {\n      const body = await requestJson(`${API_ROOT}/cache`);\n      cacheData = body?.cache || {categories: [], products: [], analyses_by_product: {}, compute_platforms: []};\n      return cacheData;\n    } catch (error) {\n      if (!silent) notify?.(error?.message || error);\n      throw error;\n    }\n  }\n\n'''
    text = replace_once(text, load_history, load_cache, "load cache")
    text = replace_once(
        text,
        "            <label class=\"field check\"><input id=\"externalAutoSync\" type=\"checkbox\" ${c.autoSyncEnabled ? 'checked' : ''}> 自动同步（配置预留）</label>\n",
        "            <label class=\"field check\"><input id=\"externalAutoSync\" type=\"checkbox\" ${c.autoSyncEnabled ? 'checked' : ''}> 自动同步（后台每 ${Math.round(c.autoSyncIntervalSeconds / 60)} 分钟检查）</label>\n",
        "auto sync label",
    )
    text = replace_once(
        text,
        "          ${last?.status === 'failed' ? `<div class=\"alert warn\">${escapeHtml(last.error || '同步失败')}：${escapeHtml(last.detail || '')}</div>` : ''}\n        </div>\n      </section>\n\n      <section class=\"panel\">\n        <div class=\"panel-head\"><div><div class=\"panel-title\">接口路径</div><div class=\"subline\">鉴权路径按当前新畅联文档预置；业务路径可按实际部署前缀调整。</div></div></div>\n",
        "          ${last?.status === 'failed' ? `<div class=\"alert warn\">${escapeHtml(last.error || '同步失败')}：${escapeHtml(last.detail || '')}</div>` : ''}\n          ${c.authMode === 'test_sign_bridge' ? '<div class=\"alert warn\">当前鉴权使用新畅联 /internal/auth/test-sign 联调辅助接口生成签名参数。待新畅联提供正式签名算法规范后，应切换为本地签名实现。</div>' : ''}\n        </div>\n      </section>\n\n      ${masterDataPreviewHtml()}\n\n      <section class=\"panel\">\n        <div class=\"panel-head\"><div><div class=\"panel-title\">接口路径</div><div class=\"subline\">鉴权路径按当前新畅联文档预置；业务路径可按实际部署前缀调整。</div></div></div>\n",
        "master data preview section",
    )
    endpoint_marker = '''  function endpointField(key, label, value) {\n    return `<div class="field"><label>${escapeHtml(label)}</label><input class="input" data-external-endpoint="${escapeHtml(key)}" value="${escapeHtml(value || '')}"></div>`;\n  }\n\n'''
    preview_fn = '''  function masterDataPreviewHtml() {\n    const categories = Array.isArray(cacheData?.categories) ? cacheData.categories.slice(0, 12) : [];\n    const products = Array.isArray(cacheData?.products) ? cacheData.products.slice(0, 20) : [];\n    const categoryRows = categories.length ? categories.map(row => `<tr>\n      <td>${escapeHtml(row.categoryName || row.name || '-')}</td>\n      <td>${escapeHtml(row.categoryId || row.id || '-')}</td>\n      <td>${escapeHtml(row.parentId || '-')}</td>\n    </tr>`).join('') : '<tr><td colspan="3">尚未同步算法品目</td></tr>';\n    const productRows = products.length ? products.map(row => `<tr>\n      <td>${escapeHtml(row.productName || row.name || '-')}</td>\n      <td>${escapeHtml(row.productCode || row.code || '-')}</td>\n      <td>${escapeHtml(row.productId || row.id || '-')}</td>\n      <td>${escapeHtml(row.categoryName || row.category?.categoryName || row.categoryId || '-')}</td>\n    </tr>`).join('') : '<tr><td colspan="4">尚未同步算法产品</td></tr>';\n    return `<section class="panel">\n      <div class="panel-head"><div><div class="panel-title">已同步主数据</div><div class="subline">这里只读展示新畅联缓存；名称、品目和产品基础信息仍以新畅联为准。</div></div></div>\n      <div class="panel-body">\n        <div class="panel-title" style="margin-bottom:10px">算法品目</div>\n        <table class="table"><thead><tr><th>品目名称</th><th>品目 ID</th><th>父级 ID</th></tr></thead><tbody>${categoryRows}</tbody></table>\n        <div class="panel-title" style="margin:18px 0 10px">算法产品</div>\n        <table class="table"><thead><tr><th>算法名称</th><th>产品编码</th><th>Product ID</th><th>品目</th></tr></thead><tbody>${productRows}</tbody></table>\n      </div>\n    </section>`;\n  }\n\n''' + endpoint_marker
    text = replace_once(text, endpoint_marker, preview_fn, "preview function")
    text = replace_once(
        text,
        "      auto_sync_enabled: Boolean(document.getElementById('externalAutoSync')?.checked),\n      auto_publish_enabled: Boolean(document.getElementById('externalAutoPublish')?.checked),\n",
        "      auto_sync_enabled: Boolean(document.getElementById('externalAutoSync')?.checked),\n      auto_sync_interval_seconds: config?.autoSyncIntervalSeconds || 600,\n      auto_publish_enabled: Boolean(document.getElementById('externalAutoPublish')?.checked),\n",
        "collect interval",
    )
    text = replace_once(
        text,
        "      await Promise.all([loadConfig({silent: true}), loadHistory({silent: true})]);\n",
        "      await Promise.all([loadConfig({silent: true}), loadHistory({silent: true}), loadCache({silent: true})]);\n",
        "sync reload cache",
    )
    text = replace_once(
        text,
        "        const [nextConfig, nextHistory] = await Promise.all([\n          loadConfig({silent: true}),\n          loadHistory({silent: true}),\n        ]);\n        config = nextConfig;\n        history = nextHistory;\n",
        "        const [nextConfig, nextHistory, nextCache] = await Promise.all([\n          loadConfig({silent: true}),\n          loadHistory({silent: true}),\n          loadCache({silent: true}),\n        ]);\n        config = nextConfig;\n        history = nextHistory;\n        cacheData = nextCache;\n",
        "render load cache",
    )
    text = replace_once(
        text,
        "    loadHistory,\n    render,\n",
        "    loadHistory,\n    loadCache,\n    render,\n",
        "runtime load cache export",
    )
    path.write_text(text, encoding="utf-8")


def patch_backend_tests() -> None:
    path = ROOT / "tests" / "unit" / "test_external_algorithm_platform.py"
    text = path.read_text(encoding="utf-8")
    if "test_auto_sync_due_respects_switch_and_interval" in text:
        return
    text += '''\n\ndef test_auto_sync_due_respects_switch_and_interval(tmp_path: Path):\n    memory = MemorySecretStore()\n    service = ExternalAlgorithmPlatformService(\n        data_dir=tmp_path,\n        secret_store_factory=lambda: memory,\n        client_factory=FakeChangLianClient,\n    )\n    service.save(ExternalPlatformConfigPayload(\n        mode="external",\n        provider="changlian",\n        base_url="https://changlian.example",\n        auto_sync_enabled=True,\n        auto_sync_interval_seconds=600,\n        access_key="ak",\n        access_secret="secret",\n        endpoints=EndpointPayload(),\n    ))\n    assert service.auto_sync_due() is True\n    service.repository.append_history({\n        "id": "recent",\n        "sync_type": "manual",\n        "status": "success",\n        "finished_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z"),\n    })\n    assert service.auto_sync_due() is False\n\n\ndef test_public_config_marks_test_sign_as_integration_bridge(tmp_path: Path):\n    memory = MemorySecretStore()\n    service = ExternalAlgorithmPlatformService(\n        data_dir=tmp_path,\n        secret_store_factory=lambda: memory,\n        client_factory=FakeChangLianClient,\n    )\n    public = service.public_config()\n    assert public["auth_mode"] == "test_sign_bridge"\n    assert public["auto_sync_interval_seconds"] == 600\n'''
    path.write_text(text, encoding="utf-8")


def patch_frontend_tests() -> None:
    path = ROOT / "tests" / "frontend" / "external-algorithm-platform.test.mjs"
    text = path.read_text(encoding="utf-8")
    if "autoSyncIntervalSeconds" in text:
        return
    text = replace_once(
        text,
        "  assert.equal(local.endpoints.token, '/internal/auth/token');\n",
        "  assert.equal(local.endpoints.token, '/internal/auth/token');\n  assert.equal(local.autoSyncIntervalSeconds, 600);\n  assert.equal(local.authMode, 'test_sign_bridge');\n",
        "frontend defaults assertions",
    )
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_backend()
    patch_frontend()
    patch_backend_tests()
    patch_frontend_tests()
    print("external algorithm platform phase1 completion migration applied")
