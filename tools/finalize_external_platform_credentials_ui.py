from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "platform_core" / "external_algorithm_platform.py"
FRONTEND = ROOT / "static" / "modules" / "external-algorithm-platform.js"
BACKEND_TEST = ROOT / "tests" / "unit" / "test_external_algorithm_platform.py"
FRONTEND_TEST = ROOT / "tests" / "frontend" / "external-algorithm-platform.test.mjs"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


backend = BACKEND.read_text(encoding="utf-8")
old_client = '''    def _client(self) -> ChangLianClient:\n        config = self.repository.config()\n        if str(config.get("provider") or "") != "changlian":\n            raise PlatformError(\n                "EXTERNAL_PLATFORM_PROVIDER_UNSUPPORTED",\n                "暂不支持该外部平台",\n                str(config.get("provider") or ""),\n                "当前版本已实现新畅联 Provider；其他平台后续通过 Provider 扩展。",\n                422,\n            )\n        ref = str(config.get("credential_ref") or DEFAULT_CONFIG["credential_ref"])\n        credentials = self._credential_store().get(ref) or {}\n        return self.client_factory(\n            base_url=str(config.get("base_url") or ""),\n            access_key=str(credentials.get("access_key_id") or ""),\n            access_secret=str(credentials.get("access_secret") or ""),\n            endpoints=ChangLianEndpoints.from_mapping(config.get("endpoints")),\n        )\n\n    def test_connection(self) -> Dict[str, Any]:\n        return self._client().probe()\n\n    def diagnose(self) -> Dict[str, Any]:\n        client = self._client()\n'''
new_client = '''    def _client_for_payload(self, payload: Optional[ExternalPlatformConfigPayload] = None) -> ChangLianClient:\n        config = self.repository.config()\n        provider = str(payload.provider if payload is not None else config.get("provider") or "changlian")\n        if provider != "changlian":\n            raise PlatformError(\n                "EXTERNAL_PLATFORM_PROVIDER_UNSUPPORTED",\n                "暂不支持该外部平台",\n                provider,\n                "当前版本已实现新畅联 Provider；其他平台后续通过 Provider 扩展。",\n                422,\n            )\n        ref = str(config.get("credential_ref") or DEFAULT_CONFIG["credential_ref"])\n        stored = self._credential_store().get(ref) or {}\n        if payload is None:\n            base_url = str(config.get("base_url") or "")\n            access_key = str(stored.get("access_key_id") or "")\n            access_secret = str(stored.get("access_secret") or "")\n            endpoints = ChangLianEndpoints.from_mapping(config.get("endpoints"))\n        else:\n            # Draft credentials are used only for this request. Blank fields reuse the\n            # already-saved credential so the browser never needs to read secrets back.\n            base_url = str(payload.base_url or "")\n            access_key = str(payload.access_key or "").strip() or str(stored.get("access_key_id") or "")\n            access_secret = str(payload.access_secret or "") or str(stored.get("access_secret") or "")\n            endpoints = ChangLianEndpoints.from_mapping(payload.endpoints.model_dump())\n        return self.client_factory(\n            base_url=base_url,\n            access_key=access_key,\n            access_secret=access_secret,\n            endpoints=endpoints,\n        )\n\n    def _client(self) -> ChangLianClient:\n        return self._client_for_payload()\n\n    def test_connection(self, payload: Optional[ExternalPlatformConfigPayload] = None) -> Dict[str, Any]:\n        client = self._client_for_payload(payload)\n        steps: list[Dict[str, Any]] = []\n\n        def record(key: str, name: str, action: Callable[[], Any], *, count_items: bool = False) -> Any:\n            try:\n                value = action()\n                row: Dict[str, Any] = {"key": key, "name": name, "status": "success"}\n                if count_items:\n                    row["count"] = len(extract_items(value))\n                steps.append(row)\n                return value\n            except Exception as error:\n                steps.append({\n                    "key": key,\n                    "name": name,\n                    "status": "failed",\n                    "detail": str(getattr(error, "detail", error))[:500],\n                })\n                return None\n\n        auth = record("auth", "应用鉴权", client.probe)\n        if auth is not None:\n            record("categories", "算法品目", client.category_tree, count_items=True)\n            record("products", "算法产品", client.products, count_items=True)\n            record("compute_platforms", "算力环境", client.compute_platforms, count_items=True)\n        return {\n            "ok": bool(steps) and all(row.get("status") == "success" for row in steps),\n            "provider": "changlian",\n            "provider_name": "新畅联",\n            "base_url": client.base_url,\n            "auth_mode": "test_sign_bridge",\n            "tested_at": utc_now(),\n            "steps": steps,\n        }\n\n    def diagnose(self, payload: Optional[ExternalPlatformConfigPayload] = None) -> Dict[str, Any]:\n        client = self._client_for_payload(payload)\n'''
backend = replace_once(backend, old_client, new_client, "draft client + non-persistent connection test")
backend = replace_once(
    backend,
    '''    @router.post("/test")\n    def test_connection():\n        try:\n            result = service.test_connection()\n''',
    '''    @router.post("/test")\n    def test_connection(payload: Optional[ExternalPlatformConfigPayload] = None):\n        try:\n            result = service.test_connection(payload)\n''',
    "test route accepts draft payload",
)
backend = replace_once(
    backend,
    '''    @router.post("/diagnostics")\n    def diagnostics():\n        return service.diagnose()\n''',
    '''    @router.post("/diagnostics")\n    def diagnostics(payload: Optional[ExternalPlatformConfigPayload] = None):\n        return service.diagnose(payload)\n''',
    "diagnostics route accepts draft payload",
)
BACKEND.write_text(backend, encoding="utf-8")

frontend = FRONTEND.read_text(encoding="utf-8")
frontend = replace_once(
    frontend,
    '''    const message = body.message || body.detail || `请求失败（HTTP ${response.status}）`;\n    const solution = body.solution ? `\\n建议：${body.solution}` : '';\n    throw new Error(`${message}${solution}`);\n''',
    '''    const message = body.message || body.detail || `请求失败（HTTP ${response.status}）`;\n    const solution = body.solution ? `\\n建议：${body.solution}` : '';\n    const error = new Error(`${message}${solution}`);\n    error.code = body.code || '';\n    error.detail = body.detail || '';\n    error.solution = body.solution || '';\n    error.httpStatus = response.status;\n    throw error;\n''',
    "structured request error",
)
frontend = replace_once(
    frontend,
    '''  let diagnostics = null;\n  let selectedCategoryId = '';\n''',
    '''  let diagnostics = null;\n  let connectionTest = null;\n  let selectedCategoryId = '';\n''',
    "connection test state",
)
frontend = replace_once(
    frontend,
    '''            <div class="field"><label>服务地址</label><input id="externalBaseUrl" class="input" value="${escapeHtml(c.baseUrl)}" placeholder="https://api.example.com"></div>\n            <div class="field"><label>AccessKey</label><input id="externalAccessKey" class="input" autocomplete="off" placeholder="${escapeHtml(c.credentials?.masked || '未配置')}"></div>\n            <div class="field"><label>AccessSecret</label><input id="externalAccessSecret" type="password" class="input" autocomplete="new-password" placeholder="${c.credentials?.configured ? '已配置，留空表示不修改' : '请输入 AccessSecret'}"></div>\n''',
    '''            <div class="field"><label>API 服务地址</label><input id="externalBaseUrl" class="input" value="${escapeHtml(c.baseUrl)}" placeholder="https://api.example.com"></div>\n            <div class="field"><label>AccessKey</label><input id="externalAccessKey" class="input" autocomplete="off" spellcheck="false" placeholder="${escapeHtml(c.credentials?.masked || '请输入 AccessKey')}"></div>\n            <div class="field"><label>AccessSecret</label><div class="row"><input id="externalAccessSecret" type="password" class="input" autocomplete="new-password" spellcheck="false" placeholder="${c.credentials?.configured ? '已配置，留空表示继续使用原 Secret' : '请输入 AccessSecret'}"><button type="button" class="btn" id="externalSecretToggle">显示</button></div></div>\n            <div class="field full"><div class="subline">凭据状态：${c.credentials?.configured ? `已配置（${escapeHtml(c.credentials?.masked || 'AccessKey 已保存')}）` : '未配置'}。AccessSecret 仅提交给后端保存，页面不会读取已保存的明文 Secret。</div></div>\n''',
    "credential fields",
)
frontend = replace_once(
    frontend,
    '''      </section>\n\n      <section class="panel">\n        <div class="panel-head"><div><div class="panel-title">同步状态</div><div class="subline">“立即同步”只执行 新畅联 → 本平台 的算法品目、算法产品、分析方式和算力环境同步。</div></div></div>\n''',
    '''      </section>\n\n      <section class="panel">\n        <div class="panel-head"><div><div class="panel-title">连接测试</div><div class="subline">使用当前页面填写的 API 地址和凭据临时测试，不会自动保存或覆盖已保存凭据。</div></div></div>\n        <div class="panel-body" id="externalConnectionResult">${connectionTestHtml()}</div>\n      </section>\n\n      <section class="panel">\n        <div class="panel-head"><div><div class="panel-title">同步状态</div><div class="subline">“立即同步”只执行 新畅联 → 本平台 的算法品目、算法产品、分析方式和算力环境同步。</div></div></div>\n''',
    "connection test panel",
)
frontend = replace_once(
    frontend,
    '''  function diagnosticsHtml() {\n''',
    '''  function connectionTestHtml() {\n    if (!connectionTest) return '<div class="subline">尚未测试连接</div>';\n    if (!connectionTest.ok) {\n      return `<div class="alert err"><b>连接失败</b><div>${escapeHtml(connectionTest.message || '新畅联连接测试失败')}</div>${connectionTest.detail ? `<div>${escapeHtml(connectionTest.detail)}</div>` : ''}${connectionTest.solution ? `<div>建议：${escapeHtml(connectionTest.solution)}</div>` : ''}</div>`;\n    }\n    const rows = Array.isArray(connectionTest.steps) ? connectionTest.steps : [];\n    const body = rows.map(row => `<tr><td>${escapeHtml(row.name || row.key || '-')}</td><td><span class="pill ${row.status === 'success' ? 'ok' : 'err'}">${row.status === 'success' ? '成功' : '失败'}</span></td><td>${escapeHtml(row.count ?? row.detail ?? '-')}</td></tr>`).join('');\n    return `<div class="alert ok"><b>连接成功</b> · ${escapeHtml(connectionTest.base_url || '')}</div><table class="table"><thead><tr><th>检查项</th><th>结果</th><th>详情/数量</th></tr></thead><tbody>${body || '<tr><td colspan="3">鉴权连接正常</td></tr>'}</tbody></table>`;\n  }\n\n  function paintConnectionTest() {\n    const root = document.getElementById('externalConnectionResult');\n    if (root) root.innerHTML = connectionTestHtml();\n  }\n\n  function diagnosticsHtml() {\n''',
    "connection result renderer",
)
old_test = '''  async function testConnection() {\n    await save({quiet: true});\n    const button = document.getElementById('externalPlatformTest');\n    if (button) { button.disabled = true; button.textContent = '正在测试…'; }\n    try {\n      await requestJson(`${API_ROOT}/test`, {method: 'POST'});\n      notify?.('新畅联鉴权连接正常');\n    } finally {\n      if (button) { button.disabled = false; button.textContent = '测试连接'; }\n    }\n  }\n\n  async function runDiagnostics() {\n    if (String(state().page || '') === PAGE) await save({quiet: true});\n    const button = document.getElementById('externalPlatformDiagnostics');\n'''
new_test = '''  async function testConnection() {\n    const payload = collectForm();\n    const button = document.getElementById('externalPlatformTest');\n    if (button) { button.disabled = true; button.textContent = '正在测试…'; }\n    connectionTest = null;\n    paintConnectionTest();\n    try {\n      connectionTest = await requestJson(`${API_ROOT}/test`, {\n        method: 'POST',\n        headers: {'Content-Type': 'application/json'},\n        body: JSON.stringify(payload),\n      });\n      paintConnectionTest();\n      notify?.(connectionTest.ok ? '新畅联连接测试通过' : '新畅联连接测试存在失败项');\n      return connectionTest;\n    } catch (error) {\n      connectionTest = {\n        ok: false,\n        message: error?.message || '新畅联连接测试失败',\n        detail: error?.detail || '',\n        solution: error?.solution || '',\n      };\n      paintConnectionTest();\n      notify?.(connectionTest.message);\n      return connectionTest;\n    } finally {\n      if (button) { button.disabled = false; button.textContent = '测试连接'; }\n    }\n  }\n\n  async function runDiagnostics() {\n    const payload = String(state().page || '') === PAGE ? collectForm() : null;\n    const button = document.getElementById('externalPlatformDiagnostics');\n'''
frontend = replace_once(frontend, old_test, new_test, "non-persistent frontend test")
frontend = replace_once(
    frontend,
    '''      diagnostics = await requestJson(`${API_ROOT}/diagnostics`, {method: 'POST'});\n''',
    '''      diagnostics = await requestJson(`${API_ROOT}/diagnostics`, {\n        method: 'POST',\n        headers: {'Content-Type': 'application/json'},\n        body: payload ? JSON.stringify(payload) : undefined,\n      });\n''',
    "non-persistent diagnostics payload",
)
frontend = replace_once(
    frontend,
    '''    const syncButton = document.getElementById('externalPlatformSync');\n''',
    '''    const syncButton = document.getElementById('externalPlatformSync');\n    const secretToggle = document.getElementById('externalSecretToggle');\n    const secretInput = document.getElementById('externalAccessSecret');\n''',
    "secret toggle refs",
)
frontend = replace_once(
    frontend,
    '''    if (syncButton) syncButton.onclick = () => void syncNow().catch(error => notify?.(error?.message || error));\n\n    for (const radio of document.querySelectorAll('input[name="externalMode"]')) {\n''',
    '''    if (syncButton) syncButton.onclick = () => void syncNow().catch(error => notify?.(error?.message || error));\n    if (secretToggle && secretInput) secretToggle.onclick = () => {\n      const show = secretInput.type === 'password';\n      secretInput.type = show ? 'text' : 'password';\n      secretToggle.textContent = show ? '隐藏' : '显示';\n    };\n\n    for (const radio of document.querySelectorAll('input[name="externalMode"]')) {\n''',
    "secret show/hide binding",
)
frontend = frontend.replace("build: 'external-algorithm-platform-63002'", "build: 'external-algorithm-platform-63003'", 1)
FRONTEND.write_text(frontend, encoding="utf-8")

backend_test = BACKEND_TEST.read_text(encoding="utf-8")
backend_test += r'''


def test_draft_connection_test_does_not_persist_credentials_or_url(tmp_path: Path):
    memory = MemorySecretStore()
    captured = []

    class CapturingClient(FakeChangLianClient):
        def __init__(self, **kwargs):
            captured.append(dict(kwargs))

    service = ExternalAlgorithmPlatformService(
        data_dir=tmp_path,
        secret_store_factory=lambda: memory,
        client_factory=CapturingClient,
    )
    service.save(ExternalPlatformConfigPayload(
        mode="external", provider="changlian", base_url="https://saved.example",
        access_key="saved-ak", access_secret="saved-secret", endpoints=EndpointPayload(),
    ))
    draft = ExternalPlatformConfigPayload(
        mode="external", provider="changlian", base_url="https://draft.example",
        access_key="draft-ak", access_secret="draft-secret", endpoints=EndpointPayload(),
    )

    result = service.test_connection(draft)

    assert result["ok"] is True
    assert result["base_url"] == "https://draft.example"
    assert [row["key"] for row in result["steps"]] == ["auth", "categories", "products", "compute_platforms"]
    assert "draft-secret" not in str(result)
    assert service.repository.config()["base_url"] == "https://saved.example"
    ref = service.repository.config()["credential_ref"]
    stored = service._credential_store().get(ref)
    assert stored == {"access_key_id": "saved-ak", "access_secret": "saved-secret"}
    assert captured[-1]["access_key"] == "draft-ak"
    assert captured[-1]["access_secret"] == "draft-secret"


def test_draft_connection_blank_secret_reuses_saved_secret_without_exposing_it(tmp_path: Path):
    memory = MemorySecretStore()
    captured = []

    class CapturingClient(FakeChangLianClient):
        def __init__(self, **kwargs):
            captured.append(dict(kwargs))

    service = ExternalAlgorithmPlatformService(
        data_dir=tmp_path,
        secret_store_factory=lambda: memory,
        client_factory=CapturingClient,
    )
    service.save(ExternalPlatformConfigPayload(
        mode="external", provider="changlian", base_url="https://saved.example",
        access_key="saved-ak", access_secret="saved-secret", endpoints=EndpointPayload(),
    ))
    draft = ExternalPlatformConfigPayload(
        mode="external", provider="changlian", base_url="https://saved.example",
        access_key=None, access_secret=None, endpoints=EndpointPayload(),
    )

    result = service.test_connection(draft)

    assert result["ok"] is True
    assert captured[-1]["access_key"] == "saved-ak"
    assert captured[-1]["access_secret"] == "saved-secret"
    assert "saved-secret" not in str(result)
'''
BACKEND_TEST.write_text(backend_test, encoding="utf-8")

frontend_test = FRONTEND_TEST.read_text(encoding="utf-8")
frontend_test = replace_once(
    frontend_test,
    "import assert from 'node:assert/strict';\n",
    "import assert from 'node:assert/strict';\nimport {readFileSync} from 'node:fs';\n",
    "frontend source contract import",
)
frontend_test += r'''

test('connection test uses draft form without saving credentials first', () => {
  const source = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  const start = source.indexOf('async function testConnection()');
  const end = source.indexOf('async function runDiagnostics()', start);
  assert.ok(start >= 0 && end > start);
  const block = source.slice(start, end);
  assert.doesNotMatch(block, /await save\(/);
  assert.match(block, /const payload = collectForm\(\)/);
  assert.match(block, /JSON\.stringify\(payload\)/);
  assert.match(source, /id="externalSecretToggle"/);
  assert.match(source, /id="externalConnectionResult"/);
});
'''
FRONTEND_TEST.write_text(frontend_test, encoding="utf-8")

print("patched external platform credential form, non-persistent connectivity test, and contracts")
