const PAGE = '平台对接';
const API_ROOT = '/api/v63/external-algorithm-platform';

function rawFetch() {
  const scoped = window.fetch;
  return scoped?.__pageRequestScopeOriginal || scoped;
}

async function requestJson(url, options = {}, fetchImpl = rawFetch()) {
  const response = await fetchImpl(url, {
    headers: {'Accept': 'application/json', ...(options.headers || {})},
    ...options,
  });
  const text = await response.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch (_) { body = {detail: text}; }
  if (!response.ok) {
    const message = body.message || body.detail || `请求失败（HTTP ${response.status}）`;
    const solution = body.solution ? `\n建议：${body.solution}` : '';
    const error = new Error(`${message}${solution}`);
    error.code = body.code || '';
    error.detail = body.detail || '';
    error.solution = body.solution || '';
    error.httpStatus = response.status;
    throw error;
  }
  return body;
}

export function isExternalAlgorithm(algorithm) {
  return String(algorithm?.source_type || '').toUpperCase() === 'EXTERNAL';
}

export function algorithmSourceLabel(algorithm) {
  if (!isExternalAlgorithm(algorithm)) return '本平台';
  return String(algorithm?.source_name || (
    String(algorithm?.provider_type || '').toUpperCase() === 'CHANG_LIAN' ? '新畅联' : '外部平台'
  ));
}

export function externalAnalysisOptions(algorithm = {}) {
  const rows = Array.isArray(algorithm.external_analyses) ? algorithm.external_analyses : [];
  const normalized = rows.map(row => ({
    id: String(row?.analysis_id || row?.analysisId || ''),
    name: String(row?.analysis_name || row?.analysisName || row?.analysis_type || row?.analysisType || ''),
    type: String(row?.analysis_type || row?.analysisType || ''),
  })).filter(row => row.id);
  if (normalized.length) return normalized;
  return (algorithm.external_analysis_ids || []).map(id => ({id: String(id), name: String(id), type: ''}));
}

export function externalAlgorithmMapping(algorithm = {}) {
  const analyses = externalAnalysisOptions(algorithm);
  return {
    source: algorithmSourceLabel(algorithm),
    productId: String(algorithm.external_product_id || ''),
    categoryId: String(algorithm.external_category_id || ''),
    analysisIds: analyses.map(row => row.id),
    analysisNames: analyses.map(row => row.name || row.id),
    active: algorithm.external_active !== false,
    syncedAt: String(algorithm.external_last_synced_at || ''),
  };
}

export function normalizeExternalPlatformConfig(body = {}) {
  const config = body?.config || body || {};
  const endpoints = config.endpoints || {};
  return {
    mode: config.mode === 'external' ? 'external' : 'local',
    provider: config.provider || 'changlian',
    providerName: config.provider_name || '新畅联',
    baseUrl: config.base_url || '',
    autoSyncEnabled: Boolean(config.auto_sync_enabled),
    autoSyncIntervalSeconds: Number(config.auto_sync_interval_seconds || 600),
    autoPublishEnabled: Boolean(config.auto_publish_enabled),
    authMode: config.auth_mode || 'test_sign_bridge',
    credentials: config.credentials || {configured: false, masked: ''},
    endpoints: {
      test_sign: endpoints.test_sign || '/internal/auth/test-sign',
      token: endpoints.token || '/internal/auth/token',
      category_tree: endpoints.category_tree || '/algorithm-category/tree',
      product_list: endpoints.product_list || '/algorithm-product/listAll',
      analysis_by_product: endpoints.analysis_by_product || '/algorithm-product-analysis/listByProduct/{productId}',
      compute_platform_list: endpoints.compute_platform_list || '/compute-platform/listAll',
      version_create: endpoints.version_create || '/algorithm-version/add',
      weight_create: endpoints.weight_create || '/algorithm-weight/add',
    },
    updatedAt: config.updated_at || '',
    lastSync: config.last_sync || null,
    cache: config.cache || {},
  };
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, match => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[match]));
}

function timeText(value) {
  if (!value) return '-';
  return String(value).replace('T', ' ').replace('Z', '').slice(0, 19);
}

function syncStatusText(value) {
  return ({success: '成功', failed: '失败', running: '同步中'}[String(value || '')] || '未同步');
}

function syncCountsText(item) {
  const counts = item?.counts || {};
  if (!item || item.status !== 'success') return '';
  return `品目 ${counts.categories || 0} · 算法 ${counts.products || 0} · 分析方式 ${counts.analyses || 0} · 算力环境 ${counts.compute_platforms || 0}`;
}

export function installExternalAlgorithmPlatformRuntime({
  getState,
  projectId,
  notify,
  algorithmListRuntime,
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__externalAlgorithmPlatformRuntimeInstalled) return window.ExternalAlgorithmPlatformRuntime;

  const state = () => getState?.() || {};
  let config = null;
  let history = [];
  let cacheData = {categories: [], products: [], analyses_by_product: {}, compute_platforms: []};
  let loading = false;
  let destroyed = false;
  let renderQueued = false;
  let diagnostics = null;
  let readiness = null;
  let connectionTest = null;
  let selectedCategoryId = '';
  let unregisterAlgorithmDecorator = null;
  let trainingAnalysisObserver = null;

  function currentProjectId() {
    return String(projectId?.() || '');
  }

  async function loadConfig({silent = false} = {}) {
    try {
      const body = await requestJson(`${API_ROOT}/config`);
      config = normalizeExternalPlatformConfig(body);
      state().externalAlgorithmPlatformConfig = config;
      return config;
    } catch (error) {
      if (!silent) notify?.(error?.message || error);
      throw error;
    }
  }

  async function loadHistory({silent = false} = {}) {
    try {
      const body = await requestJson(`${API_ROOT}/sync-history?limit=20`);
      history = Array.isArray(body?.items) ? body.items : [];
      return history;
    } catch (error) {
      if (!silent) notify?.(error?.message || error);
      throw error;
    }
  }

  async function loadCache({silent = false} = {}) {
    try {
      const body = await requestJson(`${API_ROOT}/cache`);
      cacheData = body?.cache || {categories: [], products: [], analyses_by_product: {}, compute_platforms: []};
      return cacheData;
    } catch (error) {
      if (!silent) notify?.(error?.message || error);
      throw error;
    }
  }

  async function loadReadiness({silent = false} = {}) {
    const pid = currentProjectId();
    if (!pid) {
      readiness = null;
      return null;
    }
    try {
      readiness = await requestJson(`${API_ROOT}/readiness?project_id=${encodeURIComponent(pid)}`);
      return readiness;
    } catch (error) {
      readiness = null;
      if (!silent) notify?.(error?.message || error);
      throw error;
    }
  }

  function externalMode() {
    return (config || state().externalAlgorithmPlatformConfig)?.mode === 'external';
  }

  function categoryMatches(categoryId) {
    if (!selectedCategoryId) return true;
    let current = String(categoryId || '');
    const parentById = new Map((cacheData.categories || []).map(row => [
      String(row.categoryId || row.id || ''),
      String(row.parentId || ''),
    ]));
    while (current) {
      if (current === selectedCategoryId) return true;
      current = parentById.get(current) || '';
    }
    return false;
  }

  function decorateAlgorithmDetail(algorithm) {
    if (!isExternalAlgorithm(algorithm)) return;
    const detail = document.querySelector('#modalBody .alg428-detail');
    if (!detail || detail.querySelector('[data-external-algorithm-detail]')) return;
    const mapping = externalAlgorithmMapping(algorithm);
    const panel = document.createElement('section');
    panel.dataset.externalAlgorithmDetail = '1';
    panel.innerHTML = `<div class="alg428-version-head"><b>外部平台映射</b><span>${escapeHtml(mapping.source)}</span></div>
      <dl class="report429-dl">
        <dt>来源平台</dt><dd>${escapeHtml(mapping.source)}</dd>
        <dt>Product ID</dt><dd>${escapeHtml(mapping.productId || '-')}</dd>
        <dt>Category ID</dt><dd>${escapeHtml(mapping.categoryId || '-')}</dd>
        <dt>Analysis ID</dt><dd>${escapeHtml(mapping.analysisIds.join('、') || '-')}</dd>
        <dt>分析方式</dt><dd>${escapeHtml(mapping.analysisNames.join('、') || '-')}</dd>
        <dt>同步状态</dt><dd>${mapping.active ? '正常' : '已下架'}</dd>
        <dt>最近同步</dt><dd>${escapeHtml(timeText(mapping.syncedAt))}</dd>
      </dl>`;
    detail.insertBefore(panel, detail.children[1] || null);
    if (!mapping.active) {
      for (const button of detail.querySelectorAll('button')) {
        if (/开始训练/.test(String(button.textContent || ''))) {
          button.disabled = true;
          button.title = '该算法已在新畅联下架，不能新建训练任务';
        }
      }
    }
  }

  function decorateAlgorithmCards() {
    const s = state();
    if (String(s.page || '') !== '算法列表') return;
    const rows = s.algorithms || [];
    const root = document.getElementById('alg412List');
    if (!root) return;

    const legacyIndustry = document.getElementById('alg412Industry');
    if (legacyIndustry) {
      if (externalMode()) {
        if (legacyIndustry.value !== 'all') {
          legacyIndustry.value = 'all';
          algorithmListRuntime?.renderCards?.();
          return;
        }
        legacyIndustry.hidden = true;
      } else {
        legacyIndustry.hidden = false;
      }
    }

    for (const card of root.querySelectorAll('.alg428-card')) {
      const actionButton = [...card.querySelectorAll('button')].find(button =>
        String(button.getAttribute('onclick') || '').includes("editAlgorithm423(")
      );
      const match = String(actionButton?.getAttribute('onclick') || '').match(/editAlgorithm423\('([^']+)'\)/);
      const algorithm = rows.find(row => String(row.id) === String(match?.[1] || ''));
      if (!algorithm) continue;
      card.dataset.externalCategoryId = String(algorithm.external_category_id || '');
      card.hidden = !categoryMatches(algorithm.external_category_id);
      const title = card.querySelector('.alg428-title');
      if (title && !title.querySelector('[data-algorithm-source]')) {
        const source = document.createElement('em');
        source.dataset.algorithmSource = '1';
        source.textContent = algorithmSourceLabel(algorithm);
        if (isExternalAlgorithm(algorithm)) source.title = '算法名称、品目和基础属性由外部平台维护';
        title.appendChild(source);
      }
      if (!isExternalAlgorithm(algorithm)) continue;
      const detailButton = [...card.querySelectorAll('button')].find(button =>
        String(button.getAttribute('onclick') || '').includes("viewAlgorithm429(")
      );
      if (detailButton && !detailButton.dataset.externalDetailBound) {
        detailButton.dataset.externalDetailBound = '1';
        detailButton.addEventListener('click', () => setTimeout(() => decorateAlgorithmDetail(algorithm), 0));
      }
      if (algorithm.external_active === false && title && !title.querySelector('[data-external-inactive]')) {
        const inactive = document.createElement('em');
        inactive.dataset.externalInactive = '1';
        inactive.textContent = '已下架';
        inactive.title = '新畅联已不再返回该算法；历史版本保留，但不能新建训练';
        title.appendChild(inactive);
      }
      for (const button of card.querySelectorAll('button')) {
        const onclick = String(button.getAttribute('onclick') || '');
        if (onclick.includes("editAlgorithm423(") || onclick.includes("delAlgorithm(")) {
          button.disabled = true;
          button.title = '外部平台算法主数据为只读，请在新畅联修改后重新同步';
        }
        if (algorithm.external_active === false && /训练/.test(String(button.textContent || ''))) {
          button.disabled = true;
          button.title = '该算法已在新畅联下架，不能新建训练任务';
        }
      }
    }

    const toolbar = document.querySelector('.alg428-toolbar');
    if (toolbar && externalMode() && Array.isArray(cacheData.categories) && cacheData.categories.length) {
      let select = toolbar.querySelector('[data-external-category-filter]');
      if (!select) {
        select = document.createElement('select');
        select.className = 'select';
        select.dataset.externalCategoryFilter = '1';
        select.title = '按新畅联算法品目筛选';
        select.addEventListener('change', () => {
          selectedCategoryId = select.value;
          decorateAlgorithmCards();
        });
        toolbar.prepend(select);
      }
      const optionRows = (cacheData.categories || []).map(row => ({
        id: String(row.categoryId || row.id || ''),
        name: String(row.categoryName || row.name || row.categoryId || row.id || ''),
      }));
      const optionSignature = JSON.stringify(optionRows);
      if (select.dataset.externalCategorySignature !== optionSignature) {
        select.innerHTML = [
          '<option value="">全部品目</option>',
          ...optionRows.map(row => `<option value="${escapeHtml(row.id)}">${escapeHtml(row.name || row.id)}</option>`),
        ].join('');
        select.dataset.externalCategorySignature = optionSignature;
      }
      if (select.value !== selectedCategoryId) select.value = selectedCategoryId;
    }
    if (toolbar && !externalMode()) {
      toolbar.querySelector('[data-external-category-filter]')?.remove();
      selectedCategoryId = '';
    }

    const create = document.querySelector('.alg428-toolbar [data-action="algorithm.create"]');
    if (create && externalMode()) {
      create.removeAttribute('data-action');
      if (create.textContent !== '↻ 同步新畅联') create.textContent = '↻ 同步新畅联';
      create.onclick = event => {
        event.preventDefault();
        void syncNow();
      };
      create.title = '当前算法主数据由新畅联管理';
    }
  }

  function installAlgorithmDecorator() {
    if (unregisterAlgorithmDecorator || !algorithmListRuntime?.registerDecorator) return;
    unregisterAlgorithmDecorator = algorithmListRuntime.registerDecorator('external-algorithm-platform', decorateAlgorithmCards);
  }

  function selectedAnalysisId(algorithmId) {
    const algorithm = (state().algorithms || []).find(row => String(row.id) === String(algorithmId));
    if (!isExternalAlgorithm(algorithm)) return '';
    const options = externalAnalysisOptions(algorithm);
    state().externalAnalysisSelection = state().externalAnalysisSelection || {};
    return String(state().externalAnalysisSelection[algorithmId] || algorithm.external_analysis_id || options[0]?.id || '');
  }

  function decorateTrainingAnalysisSelector() {
    const form = document.querySelector('.train429-create');
    if (!form || form.querySelector('[data-external-analysis-selector]')) return;
    const algorithmId = String(state().trainingDraft?.algorithmId || '');
    const algorithm = (state().algorithms || []).find(row => String(row.id) === algorithmId);
    if (!isExternalAlgorithm(algorithm) || algorithm.external_active === false) return;
    const options = externalAnalysisOptions(algorithm);
    state().externalAnalysisSelection = state().externalAnalysisSelection || {};
    if (options.length <= 1) {
      if (options[0]?.id) state().externalAnalysisSelection[algorithmId] = options[0].id;
      return;
    }
    const panel = document.createElement('div');
    panel.className = 'panel';
    panel.dataset.externalAnalysisSelector = '1';
    panel.innerHTML = `<div class="panel-body"><div class="field"><label>本次训练分析方式</label><select id="externalTrainingAnalysis" class="select">${options.map(row => `<option value="${escapeHtml(row.id)}">${escapeHtml(row.name || row.id)}</option>`).join('')}</select></div></div>`;
    form.prepend(panel);
    const select = panel.querySelector('#externalTrainingAnalysis');
    const current = selectedAnalysisId(algorithmId);
    if (current && options.some(row => row.id === current)) select.value = current;
    state().externalAnalysisSelection[algorithmId] = select.value;
    select.addEventListener('change', () => { state().externalAnalysisSelection[algorithmId] = select.value; });
  }

  function decorateNavigation() {
    if (destroyed) return;
    const groups = [...document.querySelectorAll('#nav .nav-group')];
    const configGroup = groups.find(group =>
      group.querySelector('.nav-group-title')?.textContent.trim() === '配置中心'
    );
    if (configGroup && !configGroup.querySelector('[data-external-platform-nav="1"]')) {
      const button = document.createElement('button');
      button.dataset.externalPlatformNav = '1';
      button.className = `nav-btn ${String(state().page || '') === PAGE ? 'active' : ''}`;
      button.innerHTML = '<span class="nav-left"><i>↗</i><b>平台对接</b></span><span class="nav-arrow">›</span>';
      button.addEventListener('click', () => window.setPage?.(PAGE));
      configGroup.appendChild(button);
    }
    installAlgorithmDecorator();
    if (String(state().page || '') === PAGE) scheduleRender();
  }

  function scheduleRender() {
    if (renderQueued || destroyed) return;
    renderQueued = true;
    queueMicrotask(() => {
      renderQueued = false;
      if (!destroyed && String(state().page || '') === PAGE) void render();
    });
  }

  function configFormHtml(current) {
    const c = current || normalizeExternalPlatformConfig({});
    const external = c.mode === 'external';
    const last = c.lastSync;
    const cache = c.cache || {};
    const credential = c.credentials || {};
    const credentialBackendText = ({
      environment: '环境变量',
      keyring: '系统密钥环',
      encrypted_file: '服务器加密文件',
      memory: '内存',
      unavailable: '不可用',
    })[String(credential.backend || '')] || '待检测';
    const credentialManaged = credential.backend === 'environment';
    const credentialStatusText = credential.configured
      ? `已配置（${escapeHtml(credential.masked || 'AccessKey 已保存')}）`
      : credential.available === false ? '安全存储不可用' : '未配置';
    const credentialHelpText = credential.available === false
      ? '服务器没有可用的安全 Secret 后端。请配置系统 SecretService，或设置 MC_SECRET_MASTER_KEY 启用服务器加密文件。'
      : credentialManaged
        ? `当前凭据由 ${escapeHtml(credential.environment_name || '环境变量')} 管理，只读；页面不会覆盖。`
        : 'AccessSecret 仅提交给后端安全存储，页面不会读取已保存的明文 Secret。';
    return `<section class="label414-shell" data-external-platform-page="1">
      <div class="label414-head">
        <div>
          <h2>平台对接</h2>
          <p>算法主数据可使用本平台，也可切换为外部平台。切换不会删除已有算法、训练记录或版本。</p>
        </div>
        <div class="row">
          <button class="btn" id="externalPlatformTest">测试连接</button>
          <button class="btn" id="externalPlatformDiagnostics">联调诊断</button>
          <button class="btn primary" id="externalPlatformSync" ${external ? '' : 'disabled'}>↻ 立即同步</button>
        </div>
      </div>

      <section class="panel">
        <div class="panel-head"><div><div class="panel-title">算法主数据来源</div><div class="subline">先配置并测试连接，再手动同步算法品目、算法产品、分析方式和算力环境。</div></div></div>
        <div class="panel-body">
          <div class="form two">
            <div class="field full">
              <label>算法数据来源</label>
              <div class="row">
                <label class="field check"><input type="radio" name="externalMode" value="local" ${external ? '' : 'checked'}> 本平台管理</label>
                <label class="field check"><input type="radio" name="externalMode" value="external" ${external ? 'checked' : ''}> 外部平台</label>
              </div>
            </div>
            <div class="field"><label>外部平台</label><select id="externalProvider" class="select"><option value="changlian">新畅联</option></select></div>
            <div class="field"><label>API 服务地址</label><input id="externalBaseUrl" class="input" value="${escapeHtml(c.baseUrl)}" placeholder="https://api.example.com"></div>
            <div class="field"><label>AccessKey</label><input id="externalAccessKey" class="input" autocomplete="off" spellcheck="false" ${credentialManaged ? 'disabled' : ''} placeholder="${escapeHtml(credentialManaged ? '由环境变量管理' : (credential.masked || '请输入 AccessKey'))}"></div>
            <div class="field"><label>AccessSecret</label><div class="row"><input id="externalAccessSecret" type="password" class="input" autocomplete="new-password" spellcheck="false" ${credentialManaged ? 'disabled' : ''} placeholder="${credentialManaged ? '由环境变量管理' : (credential.configured ? '已配置，留空表示继续使用原 Secret' : '请输入 AccessSecret')}"><button type="button" class="btn" id="externalSecretToggle" ${credentialManaged ? 'disabled' : ''}>显示</button></div></div>
            <div class="field full"><div class="subline">凭据状态：${credentialStatusText} · 存储后端：${escapeHtml(credentialBackendText)}。${credentialHelpText}</div>${credential.available === false ? '<div class="alert warn" style="margin-top:10px">当前只能查看公开配置，保存 AccessKey / AccessSecret 会失败关闭（fail-closed），不会降级成明文 JSON。</div>' : ''}</div>
            <div class="field full">
              <details data-external-automation-settings="1">
                <summary>高级设置 · 自动化</summary>
                <div class="form two" style="margin-top:12px">
                  <label class="field check"><input id="externalAutoSync" type="checkbox" ${c.autoSyncEnabled ? 'checked' : ''}> 自动同步（后台每 ${Math.round(c.autoSyncIntervalSeconds / 60)} 分钟检查）</label>
                  <label class="field check"><input id="externalAutoPublish" type="checkbox" ${c.autoPublishEnabled ? 'checked' : ''}> 训练成果自动发布</label>
                </div>
              </details>
            </div>
          </div>
          <div class="row end"><button class="btn primary" id="externalPlatformSave">保存配置</button></div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><div><div class="panel-title">连接测试</div><div class="subline">使用当前页面填写的 API 地址和凭据临时测试，不会自动保存或覆盖已保存凭据。</div></div></div>
        <div class="panel-body" id="externalConnectionResult">${connectionTestHtml()}</div>
      </section>

      <section class="panel">
        <div class="panel-head"><div><div class="panel-title">同步状态</div><div class="subline">“立即同步”只执行 新畅联 → 本平台 的算法品目、算法产品、分析方式和算力环境同步。</div></div></div>
        <div class="panel-body">
          <div class="summary">
            <div class="stat"><div class="k">最近同步</div><div class="v" style="font-size:16px">${escapeHtml(timeText(last?.finished_at || last?.started_at))}</div></div>
            <div class="stat"><div class="k">状态</div><div class="v" style="font-size:16px">${escapeHtml(syncStatusText(last?.status))}</div></div>
            <div class="stat"><div class="k">算法品目</div><div class="v">${Number(cache.category_count || 0)}</div></div>
            <div class="stat"><div class="k">算法产品</div><div class="v">${Number(cache.product_count || 0)}</div></div>
            <div class="stat"><div class="k">分析方式</div><div class="v">${Number(cache.analysis_count || 0)}</div></div>
            <div class="stat"><div class="k">算力环境</div><div class="v">${Number(cache.compute_platform_count || 0)}</div></div>
          </div>
          ${last?.status === 'failed' ? `<div class="alert warn">${escapeHtml(last.error || '同步失败')}：${escapeHtml(last.detail || '')}</div>` : ''}
          ${c.authMode === 'test_sign_bridge' ? '<div class="alert warn">当前鉴权使用新畅联 /internal/auth/test-sign 联调辅助接口生成签名参数。待新畅联提供正式签名算法规范后，应切换为本地签名实现。</div>' : ''}
        </div>
      </section>

      ${readinessHtml()}

      ${diagnosticsHtml()}

      ${masterDataPreviewHtml()}

      <section class="panel">
        <div class="panel-head"><div><div class="panel-title">接口路径</div><div class="subline">鉴权路径按当前新畅联文档预置；业务路径可按实际部署前缀调整。</div></div></div>
        <div class="panel-body">
          <details>
            <summary>高级接口路径</summary>
            <div class="form two" style="margin-top:16px">
              ${endpointField('test_sign', '签名测试', c.endpoints.test_sign)}
              ${endpointField('token', '获取 Token', c.endpoints.token)}
              ${endpointField('category_tree', '算法品目树', c.endpoints.category_tree)}
              ${endpointField('product_list', '算法产品列表', c.endpoints.product_list)}
              ${endpointField('analysis_by_product', '产品分析方式', c.endpoints.analysis_by_product)}
              ${endpointField('compute_platform_list', '算力环境列表', c.endpoints.compute_platform_list)}
              ${endpointField('version_create', '新增算法版本', c.endpoints.version_create)}
              ${endpointField('weight_create', '新增权重文件', c.endpoints.weight_create)}
            </div>
          </details>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><div class="panel-title">同步记录</div></div>
        <div class="panel-body">
          <table class="table">
            <thead><tr><th>时间</th><th>方式</th><th>结果</th><th>同步内容</th></tr></thead>
            <tbody>${historyRows()}</tbody>
          </table>
        </div>
      </section>
    </section>`;
  }

  function connectionTestHtml() {
    if (!connectionTest) return '<div class="subline">尚未测试连接</div>';
    if (!connectionTest.ok) {
      return `<div class="alert err"><b>连接失败</b><div>${escapeHtml(connectionTest.message || '新畅联连接测试失败')}</div>${connectionTest.detail ? `<div>${escapeHtml(connectionTest.detail)}</div>` : ''}${connectionTest.solution ? `<div>建议：${escapeHtml(connectionTest.solution)}</div>` : ''}</div>`;
    }
    const rows = Array.isArray(connectionTest.steps) ? connectionTest.steps : [];
    const body = rows.map(row => {
      const status = String(row.status || '');
      const pill = status === 'success' ? 'ok' : status === 'skipped' ? 'warn' : 'err';
      const label = status === 'success' ? '成功' : status === 'skipped' ? '跳过' : '失败';
      return `<tr><td>${escapeHtml(row.name || row.key || '-')}</td><td><span class="pill ${pill}">${label}</span></td><td>${escapeHtml(row.count ?? row.detail ?? '-')}</td></tr>`;
    }).join('');
    return `<div class="alert ok"><b>连接成功</b> · ${escapeHtml(connectionTest.base_url || '')}</div><table class="table"><thead><tr><th>检查项</th><th>结果</th><th>详情/数量</th></tr></thead><tbody>${body || '<tr><td colspan="3">鉴权连接正常</td></tr>'}</tbody></table>`;
  }

  function paintConnectionTest() {
    const root = document.getElementById('externalConnectionResult');
    if (root) root.innerHTML = connectionTestHtml();
  }

  function readinessHtml() {
    if (!readiness) return '';
    const rows = Array.isArray(readiness.checks) ? readiness.checks : [];
    const body = rows.map(row => {
      const status = String(row.status || '');
      const label = status === 'ready' ? '就绪' : status === 'not_required' ? '无需' : '待处理';
      const pill = status === 'ready' ? 'ok' : status === 'not_required' ? 'warn' : 'err';
      return `<tr><td>${escapeHtml(row.name || row.key || '-')}</td><td><span class="pill ${pill}">${label}</span></td><td>${escapeHtml(row.count ?? row.detail ?? '-')}</td></tr>`;
    }).join('');
    return `<section class="panel" data-changlian-readiness="${readiness.ready ? 'ready' : 'blocked'}">
      <div class="panel-head"><div><div class="panel-title">主数据 / 训练准备状态</div><div class="subline">这里只检查应用鉴权、主数据同步和当前项目畅联云算法是否可进入训练；转换与版本/权重发布由版本页同步前的发布预检单独判断。</div></div></div>
      <div class="panel-body">
        <div class="alert ${readiness.ready ? 'ok' : 'warn'}"><b>${readiness.ready ? '主数据与训练条件已就绪' : '还有主数据/训练前置条件未完成'}</b> · 系统对接使用 AccessKey / AccessSecret 应用鉴权，人员网页登录账号不参与机器接口调用。</div>
        <table class="table"><thead><tr><th>检查项</th><th>状态</th><th>详情/数量</th></tr></thead><tbody>${body || '<tr><td colspan="3">暂无准备状态</td></tr>'}</tbody></table>
      </div>
    </section>`;
  }

  function diagnosticsHtml() {
    if (!diagnostics) return '';
    const rows = Array.isArray(diagnostics.steps) ? diagnostics.steps : [];
    const body = rows.map(row => `<tr><td>${escapeHtml(row.name || row.key || '-')}</td><td><span class="pill ${row.status === 'success' ? 'ok' : row.status === 'skipped' ? 'warn' : 'err'}">${row.status === 'success' ? '成功' : row.status === 'skipped' ? '跳过' : '失败'}</span></td><td>${escapeHtml(row.count ?? row.detail ?? '-')}</td></tr>`).join('');
    return `<section class="panel"><div class="panel-head"><div><div class="panel-title">联调诊断</div><div class="subline">只读检查鉴权、品目、算法产品、分析方式和算力环境，不创建或修改新畅联数据。</div></div></div><div class="panel-body"><table class="table"><thead><tr><th>检查项</th><th>结果</th><th>详情/数量</th></tr></thead><tbody>${body || '<tr><td colspan="3">暂无诊断结果</td></tr>'}</tbody></table></div></section>`;
  }

  function masterDataPreviewHtml() {
    const categories = Array.isArray(cacheData?.categories) ? cacheData.categories.slice(0, 12) : [];
    const products = Array.isArray(cacheData?.products) ? cacheData.products.slice(0, 20) : [];
    const categoryRows = categories.length ? categories.map(row => `<tr>
      <td>${escapeHtml(row.categoryName || row.name || '-')}</td>
      <td>${escapeHtml(row.categoryId || row.id || '-')}</td>
      <td>${escapeHtml(row.parentId || '-')}</td>
    </tr>`).join('') : '<tr><td colspan="3">尚未同步算法品目</td></tr>';
    const productRows = products.length ? products.map(row => `<tr>
      <td>${escapeHtml(row.productName || row.name || '-')}</td>
      <td>${escapeHtml(row.productCode || row.code || '-')}</td>
      <td>${escapeHtml(row.productId || row.id || '-')}</td>
      <td>${escapeHtml(row.categoryName || row.category?.categoryName || row.categoryId || '-')}</td>
    </tr>`).join('') : '<tr><td colspan="4">尚未同步算法产品</td></tr>';
    return `<section class="panel">
      <div class="panel-head"><div><div class="panel-title">已同步主数据</div><div class="subline">这里只读展示新畅联缓存；名称、品目和产品基础信息仍以新畅联为准。</div></div></div>
      <div class="panel-body">
        <div class="panel-title" style="margin-bottom:10px">算法品目</div>
        <table class="table"><thead><tr><th>品目名称</th><th>品目 ID</th><th>父级 ID</th></tr></thead><tbody>${categoryRows}</tbody></table>
        <div class="panel-title" style="margin:18px 0 10px">算法产品</div>
        <table class="table"><thead><tr><th>算法名称</th><th>产品编码</th><th>Product ID</th><th>品目</th></tr></thead><tbody>${productRows}</tbody></table>
      </div>
    </section>`;
  }

  function endpointField(key, label, value) {
    return `<div class="field"><label>${escapeHtml(label)}</label><input class="input" data-external-endpoint="${escapeHtml(key)}" value="${escapeHtml(value || '')}"></div>`;
  }

  function historyRows() {
    if (!history.length) return '<tr><td colspan="4">暂无同步记录</td></tr>';
    return history.map(item => `<tr>
      <td>${escapeHtml(timeText(item.finished_at || item.started_at))}</td>
      <td>${item.sync_type === 'manual' ? '手动' : '自动'}</td>
      <td><span class="pill ${item.status === 'success' ? 'ok' : item.status === 'failed' ? 'err' : 'warn'}">${escapeHtml(syncStatusText(item.status))}</span></td>
      <td>${escapeHtml(syncCountsText(item) || item.error || '-')}</td>
    </tr>`).join('');
  }

  function collectForm() {
    const mode = document.querySelector('input[name="externalMode"]:checked')?.value || 'local';
    const endpointValues = {};
    for (const input of document.querySelectorAll('[data-external-endpoint]')) {
      endpointValues[input.dataset.externalEndpoint] = input.value.trim();
    }
    return {
      mode,
      provider: document.getElementById('externalProvider')?.value || 'changlian',
      base_url: document.getElementById('externalBaseUrl')?.value.trim() || '',
      auto_sync_enabled: Boolean(document.getElementById('externalAutoSync')?.checked),
      auto_sync_interval_seconds: config?.autoSyncIntervalSeconds || 600,
      auto_publish_enabled: Boolean(document.getElementById('externalAutoPublish')?.checked),
      access_key: document.getElementById('externalAccessKey')?.value.trim() || null,
      access_secret: document.getElementById('externalAccessSecret')?.value || null,
      endpoints: endpointValues,
    };
  }

  async function save({quiet = false} = {}) {
    const payload = collectForm();
    const body = await requestJson(`${API_ROOT}/config`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    config = normalizeExternalPlatformConfig(body);
    state().externalAlgorithmPlatformConfig = config;
    if (!quiet) notify?.('平台对接配置已保存');
    return config;
  }

  async function testConnection() {
    const payload = collectForm();
    const button = document.getElementById('externalPlatformTest');
    if (button) { button.disabled = true; button.textContent = '正在测试…'; }
    connectionTest = null;
    paintConnectionTest();
    try {
      connectionTest = await requestJson(`${API_ROOT}/test`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      paintConnectionTest();
      notify?.(connectionTest.ok ? '新畅联连接测试通过' : '新畅联连接测试存在失败项');
      return connectionTest;
    } catch (error) {
      connectionTest = {
        ok: false,
        message: error?.message || '新畅联连接测试失败',
        detail: error?.detail || '',
        solution: error?.solution || '',
      };
      paintConnectionTest();
      notify?.(connectionTest.message);
      return connectionTest;
    } finally {
      if (button) { button.disabled = false; button.textContent = '测试连接'; }
    }
  }

  async function runDiagnostics() {
    const payload = String(state().page || '') === PAGE ? collectForm() : null;
    const button = document.getElementById('externalPlatformDiagnostics');
    if (button) { button.disabled = true; button.textContent = '正在诊断…'; }
    try {
      diagnostics = await requestJson(`${API_ROOT}/diagnostics`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: payload ? JSON.stringify(payload) : undefined,
      });
      notify?.(diagnostics.ok ? '新畅联联调诊断通过' : '联调诊断存在失败项，请查看详情');
      if (String(state().page || '') === PAGE) await render({reload: false});
      return diagnostics;
    } finally {
      if (button) { button.disabled = false; button.textContent = '联调诊断'; }
    }
  }

  async function syncNow() {
    const pid = currentProjectId();
    if (!pid) return notify?.('当前项目不可用，请刷新页面后重试');
    if (String(state().page || '') === PAGE) await save({quiet: true});
    else if (!config) await loadConfig({silent: true});
    if (!externalMode()) return notify?.('请先在“平台对接”切换为外部平台并保存');

    const button = document.getElementById('externalPlatformSync');
    if (button) { button.disabled = true; button.textContent = '正在同步…'; }
    try {
      const body = await requestJson(`${API_ROOT}/sync?project_id=${encodeURIComponent(pid)}`, {method: 'POST'});
      const counts = body?.sync?.counts || {};
      await Promise.all([loadConfig({silent: true}), loadHistory({silent: true}), loadCache({silent: true}), loadReadiness({silent: true})]);
      await algorithmListRuntime?.refresh?.({render: String(state().page || '') === '算法列表'});
      notify?.(`同步完成：算法新增 ${counts.added || 0}，更新 ${counts.updated || 0}`);
      if (String(state().page || '') === PAGE) await render({reload: false});
      return body;
    } finally {
      if (button) { button.disabled = false; button.textContent = '↻ 立即同步'; }
    }
  }

  function bindPage() {
    const saveButton = document.getElementById('externalPlatformSave');
    const testButton = document.getElementById('externalPlatformTest');
    const diagnosticsButton = document.getElementById('externalPlatformDiagnostics');
    const syncButton = document.getElementById('externalPlatformSync');
    const secretToggle = document.getElementById('externalSecretToggle');
    const secretInput = document.getElementById('externalAccessSecret');
    if (saveButton) saveButton.onclick = () => void save().then(() => render({reload: false})).catch(error => notify?.(error?.message || error));
    if (testButton) testButton.onclick = () => void testConnection().catch(error => notify?.(error?.message || error));
    if (diagnosticsButton) diagnosticsButton.onclick = () => void runDiagnostics().catch(error => notify?.(error?.message || error));
    if (syncButton) syncButton.onclick = () => void syncNow().catch(error => notify?.(error?.message || error));
    if (secretToggle && secretInput) secretToggle.onclick = () => {
      const show = secretInput.type === 'password';
      secretInput.type = show ? 'text' : 'password';
      secretToggle.textContent = show ? '隐藏' : '显示';
    };

    for (const radio of document.querySelectorAll('input[name="externalMode"]')) {
      radio.addEventListener('change', () => {
        const enabled = document.querySelector('input[name="externalMode"]:checked')?.value === 'external';
        if (syncButton) syncButton.disabled = !enabled;
      });
    }
  }

  async function render({reload = true} = {}) {
    if (destroyed || loading || String(state().page || '') !== PAGE) return false;
    const view = document.getElementById('view');
    if (!view) return false;
    loading = true;
    if (!config) view.innerHTML = '<div class="empty">正在读取平台对接配置…</div>';
    try {
      if (reload || !config) {
        const [nextConfig, nextHistory, nextCache, nextReadiness] = await Promise.all([
          loadConfig({silent: true}),
          loadHistory({silent: true}),
          loadCache({silent: true}),
          loadReadiness({silent: true}),
        ]);
        config = nextConfig;
        history = nextHistory;
        cacheData = nextCache;
        readiness = nextReadiness;
      }
      if (String(state().page || '') !== PAGE) return false;
      view.innerHTML = configFormHtml(config);
      bindPage();
      return true;
    } catch (error) {
      if (String(state().page || '') === PAGE) {
        view.innerHTML = `<div class="alert err">${escapeHtml(error?.message || error)}</div>`;
      }
      return false;
    } finally {
      loading = false;
    }
  }

  const nav = document.getElementById('nav');
  const observer = nav ? new MutationObserver(decorateNavigation) : null;
  observer?.observe(nav, {childList: true, subtree: true});
  decorateNavigation();
  installAlgorithmDecorator();
  trainingAnalysisObserver = new MutationObserver(() => decorateTrainingAnalysisSelector());
  trainingAnalysisObserver.observe(document.body, {childList: true, subtree: true});
  void Promise.all([loadConfig({silent: true}), loadCache({silent: true})]).then(() => {
    algorithmListRuntime?.runDecorators?.();
    decorateTrainingAnalysisSelector();
  }).catch(() => {});

  const runtime = {
    build: 'external-algorithm-platform-63003',
    page: PAGE,
    loadConfig,
    loadHistory,
    loadCache,
    loadReadiness,
    render,
    save,
    testConnection,
    runDiagnostics,
    syncNow,
    selectedAnalysisId,
    decorateTrainingAnalysisSelector,
    decorateNavigation,
    decorateAlgorithmCards,
    config: () => config,
    destroy() {
      destroyed = true;
      observer?.disconnect();
      trainingAnalysisObserver?.disconnect();
      unregisterAlgorithmDecorator?.();
      unregisterAlgorithmDecorator = null;
      if (window.ExternalAlgorithmPlatformRuntime === runtime) window.ExternalAlgorithmPlatformRuntime = null;
      window.__externalAlgorithmPlatformRuntimeInstalled = false;
    },
  };
  window.ExternalAlgorithmPlatformRuntime = runtime;
  window.__externalAlgorithmPlatformRuntimeInstalled = true;
  return runtime;
}
