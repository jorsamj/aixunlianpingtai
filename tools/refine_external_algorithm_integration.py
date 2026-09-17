from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"missing expected block in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: str, marker: str, content: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + content.strip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Backend: preserve every analysis method, require explicit selection when a
# product exposes more than one, reject training after the external product is
# inactivated, and add a read-only diagnostic endpoint.
# ---------------------------------------------------------------------------
platform_py = "platform_core/external_algorithm_platform.py"
replace_once(
    platform_py,
    '''def _analysis_name(row: Mapping[str, Any]) -> str:\n    return str(_value_from(row, "analysisName", "analysisTypeName", "name", "analysisType") or "").strip()\n\n\ndef _choose_analysis(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:''',
    '''def _analysis_name(row: Mapping[str, Any]) -> str:\n    return str(_value_from(row, "analysisName", "analysisTypeName", "name", "analysisType") or "").strip()\n\n\ndef _analysis_summary(row: Mapping[str, Any]) -> Dict[str, Any]:\n    return {\n        "analysis_id": _analysis_id(row),\n        "analysis_name": _analysis_name(row),\n        "analysis_type": str(_value_from(row, "analysisType", "analysisTypeName", "type") or "").strip(),\n        "compute_platform_ids": list(row.get("computePlatformIds") or row.get("compute_platform_ids") or []),\n    }\n\n\ndef _choose_analysis(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:''',
)
replace_once(
    platform_py,
    '''            "external_analysis_id": _analysis_id(selected_analysis),\n            "external_analysis_ids": [_analysis_id(row) for row in analyses if _analysis_id(row)],\n            "external_category_id": cid,''',
    '''            "external_analysis_id": _analysis_id(selected_analysis),\n            "external_analysis_ids": [_analysis_id(row) for row in analyses if _analysis_id(row)],\n            "external_analyses": [_analysis_summary(row) for row in analyses if _analysis_id(row)],\n            "external_category_id": cid,''',
)
replace_once(
    platform_py,
    '''def assert_local_algorithm_create_allowed(data_dir: Path) -> None:\n    config = ExternalPlatformRepository(Path(data_dir)).config()''',
    '''def resolve_external_training_analysis(algorithm: Mapping[str, Any] | None, requested_analysis_id: Any = "") -> str:\n    if not algorithm:\n        return ""\n    if str(algorithm.get("source_type") or "").upper() != SOURCE_EXTERNAL:\n        return ""\n    if str(algorithm.get("provider_type") or "").upper() != PROVIDER_CHANGLIAN:\n        return ""\n    if algorithm.get("external_active") is False:\n        raise PlatformError(\n            "EXTERNAL_ALGORITHM_INACTIVE",\n            "该外部算法已下架，不能新建训练任务",\n            str(algorithm.get("name") or algorithm.get("id") or ""),\n            "历史训练和版本仍可查看；如需继续训练，请先在新畅联恢复该算法产品并重新同步。",\n            409,\n        )\n    analysis_ids = [str(value) for value in (algorithm.get("external_analysis_ids") or []) if str(value or "").strip()]\n    if not analysis_ids:\n        analysis_ids = [\n            str(row.get("analysis_id") or "")\n            for row in (algorithm.get("external_analyses") or [])\n            if isinstance(row, dict) and str(row.get("analysis_id") or "").strip()\n        ]\n    default_id = str(algorithm.get("external_analysis_id") or "").strip()\n    requested = str(requested_analysis_id or "").strip()\n    if requested and analysis_ids and requested not in analysis_ids:\n        raise PlatformError(\n            "EXTERNAL_ANALYSIS_INVALID",\n            "所选分析方式不属于当前算法产品",\n            requested,\n            "请刷新新畅联主数据后重新选择分析方式。",\n            409,\n        )\n    if len(analysis_ids) > 1 and not requested:\n        raise PlatformError(\n            "EXTERNAL_ANALYSIS_REQUIRED",\n            "当前算法存在多个分析方式，请选择本次训练绑定的分析方式",\n            str(algorithm.get("name") or algorithm.get("id") or ""),\n            "请在创建训练任务时选择具体分析方式。",\n            409,\n        )\n    return requested or default_id or (analysis_ids[0] if analysis_ids else "")\n\n\ndef assert_local_algorithm_create_allowed(data_dir: Path) -> None:\n    config = ExternalPlatformRepository(Path(data_dir)).config()''',
)
replace_once(
    platform_py,
    '''    def test_connection(self) -> Dict[str, Any]:\n        return self._client().probe()\n\n    def sync(''',
    '''    def test_connection(self) -> Dict[str, Any]:\n        return self._client().probe()\n\n    def diagnose(self) -> Dict[str, Any]:\n        client = self._client()\n        steps: list[Dict[str, Any]] = []\n\n        def record(key: str, name: str, action: Callable[[], Any], *, count_items: bool = False) -> Any:\n            try:\n                value = action()\n                row: Dict[str, Any] = {"key": key, "name": name, "status": "success"}\n                if count_items:\n                    row["count"] = len(extract_items(value))\n                steps.append(row)\n                return value\n            except Exception as error:\n                steps.append({\n                    "key": key,\n                    "name": name,\n                    "status": "failed",\n                    "detail": str(getattr(error, "detail", error))[:500],\n                })\n                return None\n\n        auth = record("auth", "应用鉴权", client.probe)\n        if auth is None:\n            return {"ok": False, "provider": "changlian", "auth_mode": "test_sign_bridge", "steps": steps}\n        categories = record("categories", "算法品目", client.category_tree, count_items=True)\n        products = record("products", "算法产品", client.products, count_items=True)\n        record("compute_platforms", "算力环境", client.compute_platforms, count_items=True)\n        product_rows = extract_items(products) if products is not None else []\n        if product_rows:\n            product_id = _product_id(product_rows[0])\n            if product_id:\n                record("analysis", "产品分析方式", lambda: client.analyses(product_id), count_items=True)\n        else:\n            steps.append({"key": "analysis", "name": "产品分析方式", "status": "skipped", "detail": "当前没有可用于抽查的算法产品"})\n        return {\n            "ok": all(row.get("status") in {"success", "skipped"} for row in steps),\n            "provider": "changlian",\n            "auth_mode": "test_sign_bridge",\n            "steps": steps,\n            "category_sample_available": bool(extract_items(categories)) if categories is not None else False,\n        }\n\n    def sync(''',
)
replace_once(
    platform_py,
    '''    @router.post("/sync")\n    def sync(project_id: str = Query(..., min_length=1)):\n        get_project(project_id)\n        return service.sync(project_id=project_id, algorithms_path=algorithms_file(project_id), sync_type="manual")\n''',
    '''    @router.post("/diagnostics")\n    def diagnostics():\n        return service.diagnose()\n\n    @router.post("/sync")\n    def sync(project_id: str = Query(..., min_length=1)):\n        get_project(project_id)\n        return service.sync(project_id=project_id, algorithms_path=algorithms_file(project_id), sync_type="manual")\n''',
)

# ---------------------------------------------------------------------------
# Training: persist the chosen analysis id in durable + legacy jobs, enforce
# inactive product and multi-analysis rules server-side, and carry the binding
# into the generated algorithm version so publish uses the exact analysis.
# ---------------------------------------------------------------------------
app_py = "app.py"
replace_once(
    app_py,
    '''    queue_priority: StrictInt = 50\n    auto_convert_targets: Optional[List[str]] = None\n''',
    '''    queue_priority: StrictInt = 50\n    auto_convert_targets: Optional[List[str]] = None\n    external_analysis_id: Optional[str] = None\n''',
)
replace_once(
    app_py,
    '''def _enqueue_explicit_training(project_id: str, payload: TrainReq) -> JSONResponse:\n    try:\n        split = _explicit_training_split(payload)\n    except (TypeError, ValueError) as error:\n        raise HTTPException(status_code=400, detail=str(error)) from error\n    framework = str(payload.framework or "ultralytics").strip().lower()''',
    '''def _enqueue_explicit_training(project_id: str, payload: TrainReq) -> JSONResponse:\n    try:\n        split = _explicit_training_split(payload)\n    except (TypeError, ValueError) as error:\n        raise HTTPException(status_code=400, detail=str(error)) from error\n    asset_algorithm = next((x for x in list_algorithms_internal(project_id) if x.get("id") == (payload.algorithm_asset_id or "")), None)\n    external_analysis_id = resolve_external_training_analysis(asset_algorithm, payload.external_analysis_id)\n    framework = str(payload.framework or "ultralytics").strip().lower()''',
)
replace_once(
    app_py,
    '''            "schema_version": 3,\n            "requested_device": payload.device,\n''',
    '''            "schema_version": 3,\n            "requested_device": payload.device,\n            "external_analysis_id": external_analysis_id,\n''',
)
replace_once(
    app_py,
    '''            "asset_algorithm_id": payload.algorithm_asset_id,\n            "algorithm_asset_id": payload.algorithm_asset_id,\n            "algorithm": payload.algorithm,''',
    '''            "asset_algorithm_id": payload.algorithm_asset_id,\n            "algorithm_asset_id": payload.algorithm_asset_id,\n            "asset_algorithm_source_type": (asset_algorithm or {}).get("source_type", "LOCAL"),\n            "external_provider": (asset_algorithm or {}).get("provider_type", ""),\n            "external_product_id": (asset_algorithm or {}).get("external_product_id", ""),\n            "external_analysis_id": external_analysis_id,\n            "external_category_id": (asset_algorithm or {}).get("external_category_id", ""),\n            "algorithm": payload.algorithm,''',
)
replace_once(
    app_py,
    '''    p = project_dir(project_id)\n    framework = (payload.framework or "ultralytics").strip().lower()''',
    '''    p = project_dir(project_id)\n    asset_algorithm = next((x for x in list_algorithms_internal(project_id) if x.get("id") == (payload.algorithm_asset_id or "")), None)\n    external_analysis_id = resolve_external_training_analysis(asset_algorithm, payload.external_analysis_id)\n    framework = (payload.framework or "ultralytics").strip().lower()''',
)
replace_once(
    app_py,
    '''    asset_algorithm = next((x for x in list_algorithms_internal(project_id) if x.get("id") == (payload.algorithm_asset_id or "")), None)\n    job = {''',
    '''    job = {''',
)
replace_once(
    app_py,
    '''        "external_analysis_id": (asset_algorithm or {}).get("external_analysis_id", ""),''',
    '''        "external_analysis_id": external_analysis_id,''',
)
replace_once(
    app_py,
    '''        "framework": str(job.get("framework") or "ultralytics").strip().lower(),\n        "trainable": bool(stored_path),''',
    '''        "framework": str(job.get("framework") or "ultralytics").strip().lower(),\n        "external_analysis_id": str(job.get("external_analysis_id") or ""),\n        "trainable": bool(stored_path),''',
)
replace_once(
    app_py,
    '''    assert_local_algorithm_create_allowed,\n    external_algorithm_platform_router,''',
    '''    assert_local_algorithm_create_allowed,\n    resolve_external_training_analysis,\n    external_algorithm_platform_router,''',
)

# Publish the version under the analysis selected for that training run.
publish_py = "platform_core/external_algorithm_publish.py"
replace_once(
    publish_py,
    '''        analysis_id = str(algorithm.get("external_analysis_id") or "")''',
    '''        analysis_id = str(version.get("external_analysis_id") or algorithm.get("external_analysis_id") or "")''',
)

# ---------------------------------------------------------------------------
# Frontend: use canonical AlgorithmListRuntime decorators instead of wrapping
# renderAlg412, add category filtering + inactive badges, analysis selection,
# diagnostics, and remove stale “next phase” wording.
# ---------------------------------------------------------------------------
platform_js = "static/modules/external-algorithm-platform.js"
replace_once(
    platform_js,
    '''export function algorithmSourceLabel(algorithm) {\n  if (!isExternalAlgorithm(algorithm)) return '本平台';\n  return String(algorithm?.source_name || (\n    String(algorithm?.provider_type || '').toUpperCase() === 'CHANG_LIAN' ? '新畅联' : '外部平台'\n  ));\n}\n''',
    '''export function algorithmSourceLabel(algorithm) {\n  if (!isExternalAlgorithm(algorithm)) return '本平台';\n  return String(algorithm?.source_name || (\n    String(algorithm?.provider_type || '').toUpperCase() === 'CHANG_LIAN' ? '新畅联' : '外部平台'\n  ));\n}\n\nexport function externalAnalysisOptions(algorithm = {}) {\n  const rows = Array.isArray(algorithm.external_analyses) ? algorithm.external_analyses : [];\n  const normalized = rows.map(row => ({\n    id: String(row?.analysis_id || row?.analysisId || ''),\n    name: String(row?.analysis_name || row?.analysisName || row?.analysis_type || row?.analysisType || ''),\n    type: String(row?.analysis_type || row?.analysisType || ''),\n  })).filter(row => row.id);\n  if (normalized.length) return normalized;\n  return (algorithm.external_analysis_ids || []).map(id => ({id: String(id), name: String(id), type: ''}));\n}\n''',
)
replace_once(
    platform_js,
    '''  let loading = false;\n  let destroyed = false;\n  let renderQueued = false;\n  let originalRenderAlg412 = null;''',
    '''  let loading = false;\n  let destroyed = false;\n  let renderQueued = false;\n  let diagnostics = null;\n  let selectedCategoryId = '';\n  let unregisterAlgorithmDecorator = null;\n  let trainingAnalysisObserver = null;''',
)
old_decorator = '''  function decorateAlgorithmCards() {\n    const s = state();\n    if (String(s.page || '') !== '算法列表') return;\n    const rows = s.algorithms || [];\n    const root = document.getElementById('alg412List');\n    if (!root) return;\n\n    for (const card of root.querySelectorAll('.alg428-card')) {\n      const actionButton = [...card.querySelectorAll('button')].find(button =>\n        String(button.getAttribute('onclick') || '').includes("editAlgorithm423(")\n      );\n      const match = String(actionButton?.getAttribute('onclick') || '').match(/editAlgorithm423\\('([^']+)'\\)/);\n      const algorithm = rows.find(row => String(row.id) === String(match?.[1] || ''));\n      if (!algorithm) continue;\n      const title = card.querySelector('.alg428-title');\n      if (title && !title.querySelector('[data-algorithm-source]')) {\n        const source = document.createElement('em');\n        source.dataset.algorithmSource = '1';\n        source.textContent = algorithmSourceLabel(algorithm);\n        if (isExternalAlgorithm(algorithm)) source.title = '算法名称、品目和基础属性由外部平台维护';\n        title.appendChild(source);\n      }\n      if (!isExternalAlgorithm(algorithm)) continue;\n      for (const button of card.querySelectorAll('button')) {\n        const onclick = String(button.getAttribute('onclick') || '');\n        if (onclick.includes("editAlgorithm423(") || onclick.includes("delAlgorithm(")) {\n          button.disabled = true;\n          button.title = '外部平台算法主数据为只读，请在新畅联修改后重新同步';\n        }\n      }\n    }\n\n    const create = document.querySelector('.alg428-toolbar [data-action="algorithm.create"]');\n    if (create && externalMode()) {\n      create.removeAttribute('data-action');\n      create.textContent = '↻ 同步新畅联';\n      create.onclick = event => {\n        event.preventDefault();\n        void syncNow();\n      };\n      create.title = '当前算法主数据由新畅联管理';\n    }\n  }\n\n  function installAlgorithmDecorator() {\n    if (typeof window.renderAlg412 !== 'function' || originalRenderAlg412) return;\n    originalRenderAlg412 = window.renderAlg412;\n    const wrapped = function (...args) {\n      const result = originalRenderAlg412.apply(this, args);\n      decorateAlgorithmCards();\n      return result;\n    };\n    wrapped.__externalPlatformWrapper = true;\n    window.renderAlg412 = wrapped;\n    decorateAlgorithmCards();\n  }\n'''
new_decorator = '''  function categoryMatches(categoryId) {\n    if (!selectedCategoryId) return true;\n    let current = String(categoryId || '');\n    const parentById = new Map((cacheData.categories || []).map(row => [\n      String(row.categoryId || row.id || ''),\n      String(row.parentId || ''),\n    ]));\n    while (current) {\n      if (current === selectedCategoryId) return true;\n      current = parentById.get(current) || '';\n    }\n    return false;\n  }\n\n  function decorateAlgorithmCards() {\n    const s = state();\n    if (String(s.page || '') !== '算法列表') return;\n    const rows = s.algorithms || [];\n    const root = document.getElementById('alg412List');\n    if (!root) return;\n\n    for (const card of root.querySelectorAll('.alg428-card')) {\n      const actionButton = [...card.querySelectorAll('button')].find(button =>\n        String(button.getAttribute('onclick') || '').includes("editAlgorithm423(")\n      );\n      const match = String(actionButton?.getAttribute('onclick') || '').match(/editAlgorithm423\\('([^']+)'\\)/);\n      const algorithm = rows.find(row => String(row.id) === String(match?.[1] || ''));\n      if (!algorithm) continue;\n      card.dataset.externalCategoryId = String(algorithm.external_category_id || '');\n      card.hidden = !categoryMatches(algorithm.external_category_id);\n      const title = card.querySelector('.alg428-title');\n      if (title && !title.querySelector('[data-algorithm-source]')) {\n        const source = document.createElement('em');\n        source.dataset.algorithmSource = '1';\n        source.textContent = algorithmSourceLabel(algorithm);\n        if (isExternalAlgorithm(algorithm)) source.title = '算法名称、品目和基础属性由外部平台维护';\n        title.appendChild(source);\n      }\n      if (!isExternalAlgorithm(algorithm)) continue;\n      if (algorithm.external_active === false && title && !title.querySelector('[data-external-inactive]')) {\n        const inactive = document.createElement('em');\n        inactive.dataset.externalInactive = '1';\n        inactive.textContent = '已下架';\n        inactive.title = '新畅联已不再返回该算法；历史版本保留，但不能新建训练';\n        title.appendChild(inactive);\n      }\n      for (const button of card.querySelectorAll('button')) {\n        const onclick = String(button.getAttribute('onclick') || '');\n        if (onclick.includes("editAlgorithm423(") || onclick.includes("delAlgorithm(")) {\n          button.disabled = true;\n          button.title = '外部平台算法主数据为只读，请在新畅联修改后重新同步';\n        }\n        if (algorithm.external_active === false && /训练/.test(String(button.textContent || ''))) {\n          button.disabled = true;\n          button.title = '该算法已在新畅联下架，不能新建训练任务';\n        }\n      }\n    }\n\n    const toolbar = document.querySelector('.alg428-toolbar');\n    if (toolbar && externalMode() && Array.isArray(cacheData.categories) && cacheData.categories.length) {\n      let select = toolbar.querySelector('[data-external-category-filter]');\n      if (!select) {\n        select = document.createElement('select');\n        select.className = 'select';\n        select.dataset.externalCategoryFilter = '1';\n        select.title = '按新畅联算法品目筛选';\n        select.addEventListener('change', () => {\n          selectedCategoryId = select.value;\n          decorateAlgorithmCards();\n        });\n        toolbar.prepend(select);\n      }\n      const options = ['<option value="">全部品目</option>', ...(cacheData.categories || []).map(row => {\n        const id = String(row.categoryId || row.id || '');\n        const name = String(row.categoryName || row.name || id);\n        return `<option value="${escapeHtml(id)}" ${id === selectedCategoryId ? 'selected' : ''}>${escapeHtml(name)}</option>`;\n      })];\n      select.innerHTML = options.join('');\n      select.value = selectedCategoryId;\n    }\n\n    const create = document.querySelector('.alg428-toolbar [data-action="algorithm.create"]');\n    if (create && externalMode()) {\n      create.removeAttribute('data-action');\n      create.textContent = '↻ 同步新畅联';\n      create.onclick = event => {\n        event.preventDefault();\n        void syncNow();\n      };\n      create.title = '当前算法主数据由新畅联管理';\n    }\n  }\n\n  function installAlgorithmDecorator() {\n    if (unregisterAlgorithmDecorator || !algorithmListRuntime?.registerDecorator) return;\n    unregisterAlgorithmDecorator = algorithmListRuntime.registerDecorator('external-algorithm-platform', decorateAlgorithmCards);\n  }\n\n  function selectedAnalysisId(algorithmId) {\n    const algorithm = (state().algorithms || []).find(row => String(row.id) === String(algorithmId));\n    if (!isExternalAlgorithm(algorithm)) return '';\n    const options = externalAnalysisOptions(algorithm);\n    state().externalAnalysisSelection = state().externalAnalysisSelection || {};\n    return String(state().externalAnalysisSelection[algorithmId] || algorithm.external_analysis_id || options[0]?.id || '');\n  }\n\n  function decorateTrainingAnalysisSelector() {\n    const form = document.querySelector('.train429-create');\n    if (!form || form.querySelector('[data-external-analysis-selector]')) return;\n    const algorithmId = String(state().trainingDraft?.algorithmId || '');\n    const algorithm = (state().algorithms || []).find(row => String(row.id) === algorithmId);\n    if (!isExternalAlgorithm(algorithm) || algorithm.external_active === false) return;\n    const options = externalAnalysisOptions(algorithm);\n    state().externalAnalysisSelection = state().externalAnalysisSelection || {};\n    if (options.length <= 1) {\n      if (options[0]?.id) state().externalAnalysisSelection[algorithmId] = options[0].id;\n      return;\n    }\n    const panel = document.createElement('div');\n    panel.className = 'panel';\n    panel.dataset.externalAnalysisSelector = '1';\n    panel.innerHTML = `<div class="panel-body"><div class="field"><label>本次训练分析方式</label><select id="externalTrainingAnalysis" class="select">${options.map(row => `<option value="${escapeHtml(row.id)}">${escapeHtml(row.name || row.id)}</option>`).join('')}</select></div></div>`;\n    form.prepend(panel);\n    const select = panel.querySelector('#externalTrainingAnalysis');\n    const current = selectedAnalysisId(algorithmId);\n    if (current && options.some(row => row.id === current)) select.value = current;\n    state().externalAnalysisSelection[algorithmId] = select.value;\n    select.addEventListener('change', () => { state().externalAnalysisSelection[algorithmId] = select.value; });\n  }\n'''
replace_once(platform_js, old_decorator, new_decorator)
replace_once(
    platform_js,
    '''          <button class="btn" id="externalPlatformTest">测试连接</button>\n          <button class="btn primary" id="externalPlatformSync" ${external ? '' : 'disabled'}>↻ 立即同步</button>''',
    '''          <button class="btn" id="externalPlatformTest">测试连接</button>\n          <button class="btn" id="externalPlatformDiagnostics">联调诊断</button>\n          <button class="btn primary" id="externalPlatformSync" ${external ? '' : 'disabled'}>↻ 立即同步</button>''',
)
replace_once(platform_js, '训练成果自动发布（下一阶段启用）', '训练成果自动发布')
replace_once(platform_js, '新增算法版本（下一阶段）', '新增算法版本')
replace_once(platform_js, '新增权重文件（下一阶段）', '新增权重文件')
replace_once(
    platform_js,
    '''      ${masterDataPreviewHtml()}\n\n      <section class="panel">''',
    '''      ${diagnosticsHtml()}\n\n      ${masterDataPreviewHtml()}\n\n      <section class="panel">''',
)
replace_once(
    platform_js,
    '''  function masterDataPreviewHtml() {''',
    '''  function diagnosticsHtml() {\n    if (!diagnostics) return '';\n    const rows = Array.isArray(diagnostics.steps) ? diagnostics.steps : [];\n    const body = rows.map(row => `<tr><td>${escapeHtml(row.name || row.key || '-')}</td><td><span class="pill ${row.status === 'success' ? 'ok' : row.status === 'skipped' ? 'warn' : 'err'}">${row.status === 'success' ? '成功' : row.status === 'skipped' ? '跳过' : '失败'}</span></td><td>${escapeHtml(row.count ?? row.detail ?? '-')}</td></tr>`).join('');\n    return `<section class="panel"><div class="panel-head"><div><div class="panel-title">联调诊断</div><div class="subline">只读检查鉴权、品目、算法产品、分析方式和算力环境，不创建或修改新畅联数据。</div></div></div><div class="panel-body"><table class="table"><thead><tr><th>检查项</th><th>结果</th><th>详情/数量</th></tr></thead><tbody>${body || '<tr><td colspan="3">暂无诊断结果</td></tr>'}</tbody></table></div></section>`;\n  }\n\n  function masterDataPreviewHtml() {''',
)
replace_once(
    platform_js,
    '''  async function syncNow() {''',
    '''  async function runDiagnostics() {\n    if (String(state().page || '') === PAGE) await save({quiet: true});\n    const button = document.getElementById('externalPlatformDiagnostics');\n    if (button) { button.disabled = true; button.textContent = '正在诊断…'; }\n    try {\n      diagnostics = await requestJson(`${API_ROOT}/diagnostics`, {method: 'POST'});\n      notify?.(diagnostics.ok ? '新畅联联调诊断通过' : '联调诊断存在失败项，请查看详情');\n      if (String(state().page || '') === PAGE) await render({reload: false});\n      return diagnostics;\n    } finally {\n      if (button) { button.disabled = false; button.textContent = '联调诊断'; }\n    }\n  }\n\n  async function syncNow() {''',
)
replace_once(
    platform_js,
    '''    const testButton = document.getElementById('externalPlatformTest');\n    const syncButton = document.getElementById('externalPlatformSync');\n    if (saveButton) saveButton.onclick = () => void save().then(() => render({reload: false})).catch(error => notify?.(error?.message || error));\n    if (testButton) testButton.onclick = () => void testConnection().catch(error => notify?.(error?.message || error));\n    if (syncButton) syncButton.onclick = () => void syncNow().catch(error => notify?.(error?.message || error));''',
    '''    const testButton = document.getElementById('externalPlatformTest');\n    const diagnosticsButton = document.getElementById('externalPlatformDiagnostics');\n    const syncButton = document.getElementById('externalPlatformSync');\n    if (saveButton) saveButton.onclick = () => void save().then(() => render({reload: false})).catch(error => notify?.(error?.message || error));\n    if (testButton) testButton.onclick = () => void testConnection().catch(error => notify?.(error?.message || error));\n    if (diagnosticsButton) diagnosticsButton.onclick = () => void runDiagnostics().catch(error => notify?.(error?.message || error));\n    if (syncButton) syncButton.onclick = () => void syncNow().catch(error => notify?.(error?.message || error));''',
)
replace_once(
    platform_js,
    '''  decorateNavigation();\n  void loadConfig({silent: true}).then(() => decorateAlgorithmCards()).catch(() => {});\n\n  const runtime = {\n    build: 'external-algorithm-platform-63001',''',
    '''  decorateNavigation();\n  installAlgorithmDecorator();\n  trainingAnalysisObserver = new MutationObserver(() => decorateTrainingAnalysisSelector());\n  trainingAnalysisObserver.observe(document.body, {childList: true, subtree: true});\n  void Promise.all([loadConfig({silent: true}), loadCache({silent: true})]).then(() => {\n    algorithmListRuntime?.runDecorators?.();\n    decorateTrainingAnalysisSelector();\n  }).catch(() => {});\n\n  const runtime = {\n    build: 'external-algorithm-platform-63002',''',
)
replace_once(
    platform_js,
    '''    testConnection,\n    syncNow,\n    decorateNavigation,\n    decorateAlgorithmCards,\n    config: () => config,\n    destroy() {\n      destroyed = true;\n      observer?.disconnect();\n      if (originalRenderAlg412 && window.renderAlg412?.__externalPlatformWrapper) {\n        window.renderAlg412 = originalRenderAlg412;\n      }''',
    '''    testConnection,\n    runDiagnostics,\n    syncNow,\n    selectedAnalysisId,\n    decorateTrainingAnalysisSelector,\n    decorateNavigation,\n    decorateAlgorithmCards,\n    config: () => config,\n    destroy() {\n      destroyed = true;\n      observer?.disconnect();\n      trainingAnalysisObserver?.disconnect();\n      unregisterAlgorithmDecorator?.();\n      unregisterAlgorithmDecorator = null;''',
)

publish_js = "static/modules/external-algorithm-publish.js"
replace_once(publish_js, '''  let originalRender = null;\n  let mutationQueued = false;''', '''  let unregisterAlgorithmDecorator = null;\n  let mutationQueued = false;''')
replace_once(
    publish_js,
    '''  function installRendererHook() {\n    if (originalRender || typeof window.renderAlg412 !== 'function') return;\n    originalRender = window.renderAlg412;\n    const wrapped = function (...args) {\n      const result = originalRender.apply(this, args);\n      decorateVersionRows();\n      return result;\n    };\n    wrapped.__externalPublishWrapper = true;\n    window.renderAlg412 = wrapped;\n    decorateVersionRows();\n  }''',
    '''  function installRendererHook() {\n    if (unregisterAlgorithmDecorator || !algorithmListRuntime?.registerDecorator) return;\n    unregisterAlgorithmDecorator = algorithmListRuntime.registerDecorator('external-algorithm-publish', decorateVersionRows);\n  }''',
)
replace_once(
    publish_js,
    '''    build: 'external-algorithm-publish-64001',''',
    '''    build: 'external-algorithm-publish-64002',''',
)
replace_once(
    publish_js,
    '''    destroy() {\n      observer.disconnect();\n      if (originalRender && window.renderAlg412?.__externalPublishWrapper) window.renderAlg412 = originalRender;\n      window.__externalAlgorithmPublishRuntimeInstalled = false;''',
    '''    destroy() {\n      observer.disconnect();\n      unregisterAlgorithmDecorator?.();\n      unregisterAlgorithmDecorator = null;\n      window.__externalAlgorithmPublishRuntimeInstalled = false;''',
)

training_submit_js = "static/modules/training-submit.js"
replace_once(
    training_submit_js,
    '''      const payload = buildTrainingStartPayload({draft, target, algorithm, trainingDraftToRequest});\n      const pid = projectId?.();''',
    '''      const payload = buildTrainingStartPayload({draft, target, algorithm, trainingDraftToRequest});\n      const externalAnalysisId = window.ExternalAlgorithmPlatformRuntime?.selectedAnalysisId?.(asset.id) || '';\n      if (externalAnalysisId) payload.external_analysis_id = externalAnalysisId;\n      const pid = projectId?.();''',
)
replace_once(training_submit_js, "build: 'training-submit-422505'", "build: 'training-submit-422506'")

main_mjs = "static/main.mjs"
replace_once(main_mjs, "./modules/algorithm-list-runtime.js?v=422503", "./modules/algorithm-list-runtime.js?v=422504")
replace_once(main_mjs, "./modules/external-algorithm-platform.js?v=63001", "./modules/external-algorithm-platform.js?v=63002")
replace_once(main_mjs, "./modules/external-algorithm-publish.js?v=64001", "./modules/external-algorithm-publish.js?v=64002")
replace_once(main_mjs, "./modules/training-submit.js?v=422505", "./modules/training-submit.js?v=422506")
replace_once("static/index.html", "/static/main.mjs?v=42.25.101", "/static/main.mjs?v=42.25.102")

# ---------------------------------------------------------------------------
# Tests and permanent guards.
# ---------------------------------------------------------------------------
unit_test = "tests/unit/test_external_algorithm_platform.py"
replace_once(
    unit_test,
    '''    algorithm_is_external_readonly,\n    mirror_products_to_algorithms,\n)''',
    '''    algorithm_is_external_readonly,\n    mirror_products_to_algorithms,\n    resolve_external_training_analysis,\n)''',
)
replace_once(
    unit_test,
    '''    assert external["external_analysis_id"] == "a1"\n    assert external["external_category_id"] == "c1"''',
    '''    assert external["external_analysis_id"] == "a1"\n    assert external["external_analyses"] == [{\n        "analysis_id": "a1",\n        "analysis_name": "视觉智能分析",\n        "analysis_type": "",\n        "compute_platform_ids": ["gpu"],\n    }]\n    assert external["external_category_id"] == "c1"''',
)
append_once(
    unit_test,
    "test_external_training_analysis_requires_choice_for_multiple_methods",
    '''\ndef test_external_training_analysis_requires_choice_for_multiple_methods():\n    import pytest\n\n    algorithm = {\n        "id": "external-1",\n        "name": "抽烟检测",\n        "source_type": SOURCE_EXTERNAL,\n        "provider_type": PROVIDER_CHANGLIAN,\n        "external_active": True,\n        "external_analysis_id": "a1",\n        "external_analysis_ids": ["a1", "a2"],\n    }\n    with pytest.raises(Exception) as missing:\n        resolve_external_training_analysis(algorithm, "")\n    assert getattr(missing.value, "code", "") == "EXTERNAL_ANALYSIS_REQUIRED"\n    assert resolve_external_training_analysis(algorithm, "a2") == "a2"\n\n\ndef test_external_training_rejects_inactive_product():\n    import pytest\n\n    algorithm = {\n        "id": "external-1",\n        "name": "抽烟检测",\n        "source_type": SOURCE_EXTERNAL,\n        "provider_type": PROVIDER_CHANGLIAN,\n        "external_active": False,\n        "external_analysis_ids": ["a1"],\n    }\n    with pytest.raises(Exception) as inactive:\n        resolve_external_training_analysis(algorithm, "a1")\n    assert getattr(inactive.value, "code", "") == "EXTERNAL_ALGORITHM_INACTIVE"\n\n\ndef test_diagnostics_reports_read_only_master_data_checks(tmp_path: Path):\n    memory = MemorySecretStore()\n    service = ExternalAlgorithmPlatformService(\n        data_dir=tmp_path,\n        secret_store_factory=lambda: memory,\n        client_factory=FakeChangLianClient,\n    )\n    service.save(ExternalPlatformConfigPayload(\n        mode="external", provider="changlian", base_url="https://changlian.example",\n        access_key="ak", access_secret="secret", endpoints=EndpointPayload(),\n    ))\n    result = service.diagnose()\n    assert result["ok"] is True\n    assert [row["key"] for row in result["steps"]] == ["auth", "categories", "products", "compute_platforms", "analysis"]\n''',
)

frontend_platform_test = "tests/frontend/external-algorithm-platform.test.mjs"
replace_once(
    frontend_platform_test,
    '''  algorithmSourceLabel,\n  isExternalAlgorithm,\n  normalizeExternalPlatformConfig,''',
    '''  algorithmSourceLabel,\n  externalAnalysisOptions,\n  isExternalAlgorithm,\n  normalizeExternalPlatformConfig,''',
)
append_once(
    frontend_platform_test,
    "external analysis options preserve all synced analysis methods",
    '''\ntest('external analysis options preserve all synced analysis methods', () => {\n  const options = externalAnalysisOptions({\n    external_analyses: [\n      {analysis_id: 'a1', analysis_name: '视觉分析 A'},\n      {analysis_id: 'a2', analysis_name: '视觉分析 B'},\n    ],\n  });\n  assert.deepEqual(options.map(row => row.id), ['a1', 'a2']);\n  assert.deepEqual(options.map(row => row.name), ['视觉分析 A', '视觉分析 B']);\n});\n''',
)

algorithm_runtime_test = "tests/frontend/algorithm-list-runtime.test.mjs"
append_once(
    algorithm_runtime_test,
    "registered decorators run after canonical card render without replacing renderAlg412",
    '''\ntest('registered decorators run after canonical card render without replacing renderAlg412', () => {\n  const state = {page: '算法列表', project: {id: 'p1'}, algorithms: [], jobs: [], alg428Expanded: {}};\n  let renders = 0;\n  let decorated = 0;\n  const renderAlg412 = () => { renders += 1; };\n  globalThis.document = {\n    body: {},\n    getElementById: id => id === 'alg412List' ? {} : null,\n    addEventListener() {},\n    removeEventListener() {},\n  };\n  globalThis.MutationObserver = class { observe() {} disconnect() {} };\n  globalThis.window = {renderAlg412, fetch: async () => response({items: []})};\n  const runtime = installAlgorithmListRuntime({getState: () => state, projectId: () => 'p1'});\n  runtime.registerDecorator('test', () => { decorated += 1; });\n  runtime.renderCards();\n  assert.equal(window.renderAlg412, renderAlg412);\n  assert.equal(renders, 1);\n  runtime.runDecorators();\n  assert.ok(decorated >= 1);\n  runtime.destroy();\n  delete globalThis.MutationObserver;\n  cleanup();\n});\n''',
)

workflow = ".github/workflows/external-algorithm-platform.yml"
replace_once(
    workflow,
    '''      - static/modules/external-algorithm-platform.js\n      - tests/unit/test_external_algorithm_platform.py''',
    '''      - static/modules/external-algorithm-platform.js\n      - static/modules/algorithm-list-runtime.js\n      - static/modules/training-submit.js\n      - tests/unit/test_external_algorithm_platform.py''',
)
replace_once(
    workflow,
    '''      - static/modules/external-algorithm-platform.js\n      - tests/unit/test_external_algorithm_platform.py''',
    '''      - static/modules/external-algorithm-platform.js\n      - static/modules/algorithm-list-runtime.js\n      - static/modules/training-submit.js\n      - tests/unit/test_external_algorithm_platform.py''',
)
replace_once(
    workflow,
    '''        run: node --test tests/frontend/external-algorithm-platform.test.mjs''',
    '''        run: node --test tests/frontend/external-algorithm-platform.test.mjs tests/frontend/algorithm-list-runtime.test.mjs''',
)
replace_once(
    workflow,
    '''          node --check static/modules/external-algorithm-platform.js\n          grep -q "external_algorithm_platform_router" app.py''',
    '''          node --check static/modules/external-algorithm-platform.js\n          node --check static/modules/algorithm-list-runtime.js\n          node --check static/modules/training-submit.js\n          grep -q "external_algorithm_platform_router" app.py''',
)
replace_once(
    workflow,
    '''          grep -q "test_sign_bridge" platform_core/external_algorithm_platform.py\n''',
    '''          grep -q "test_sign_bridge" platform_core/external_algorithm_platform.py\n          grep -q "resolve_external_training_analysis" app.py\n          grep -q "registerDecorator('external-algorithm-platform'" static/modules/external-algorithm-platform.js\n          if grep -q "window.renderAlg412 =" static/modules/external-algorithm-platform.js; then echo "external platform must not wrap renderAlg412" >&2; exit 1; fi\n          if grep -q "下一阶段" static/modules/external-algorithm-platform.js; then echo "stale phase wording remains" >&2; exit 1; fi\n''',
)

publish_workflow = ".github/workflows/external-algorithm-publish.yml"
replace_once(
    publish_workflow,
    '''          grep -q "model-artifacts" platform_core/external_algorithm_publish.py\n''',
    '''          grep -q "model-artifacts" platform_core/external_algorithm_publish.py\n          grep -q "registerDecorator('external-algorithm-publish'" static/modules/external-algorithm-publish.js\n          if grep -q "window.renderAlg412 =" static/modules/external-algorithm-publish.js; then echo "external publish must not wrap renderAlg412" >&2; exit 1; fi\n''',
)

# Basic source guards executed before the workflow commits anything.
platform_text = (ROOT / platform_js).read_text(encoding="utf-8")
publish_text = (ROOT / publish_js).read_text(encoding="utf-8")
app_text = (ROOT / app_py).read_text(encoding="utf-8")
assert "window.renderAlg412 =" not in platform_text
assert "window.renderAlg412 =" not in publish_text
assert "下一阶段" not in platform_text
assert "resolve_external_training_analysis" in app_text
assert "external_analysis_id" in app_text
print("external algorithm integration refinement applied")
