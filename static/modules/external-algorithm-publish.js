const API_ROOT = '/api/v64/external-publish';
const PLATFORM_PAGE = '平台对接';
const TARGETS = [
  ['original', '通用'],
  ['rockchip', '瑞芯微'],
  ['tensorrt', 'NVIDIA'],
  ['ascend', '华为 Ascend'],
  ['sophon', '算能 Sophon'],
  ['onnx', 'ONNX 通用运行时'],
  ['paddle_inference', 'Paddle Inference'],
];

const VENDOR_META = {
  original: {mark: '通', scene: '原始训练模型', note: '训练完成但尚未转换的模型统一走“通用”对应关系。', required: true},
  rockchip: {mark: 'RK', scene: 'RKNN 转换', note: 'RK3568 / RK3576 等具体芯片型号仍以真实转换产物为准。'},
  tensorrt: {mark: 'NV', scene: 'TensorRT 转换', note: '用于 NVIDIA GPU / TensorRT 交付产物。'},
  ascend: {mark: '昇', scene: 'Ascend / OM', note: '用于华为 Ascend 转换产物。'},
  sophon: {mark: '算', scene: 'Sophon / BModel', note: '用于算能转换产物。'},
  onnx: {mark: 'ON', scene: 'ONNX', note: '通用 ONNX 交付目标，可按畅联云实际算力环境关联。'},
  paddle_inference: {mark: 'PD', scene: 'Paddle Inference', note: 'Paddle 推理产物的扩展映射。'},
};

function rawFetch() {
  const scoped = window.fetch;
  return scoped?.__pageRequestScopeOriginal || scoped;
}

async function requestJson(url, options = {}) {
  const response = await rawFetch()(url, {
    headers: {'Accept': 'application/json', ...(options.headers || {})},
    ...options,
  });
  const text = await response.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch (_) { body = {detail: text}; }
  if (!response.ok) {
    throw new Error(String(body.message || body.detail || `请求失败（HTTP ${response.status}）`));
  }
  return body;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, match => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[match]));
}

export function normalizePublishConfig(body = {}) {
  const config = body.config || {};
  const mappings = config.target_mappings || {};
  return {
    storageSourceId: config.storage_source_id || '',
    publicBaseUrl: config.public_base_url || '',
    publishOriginalModel: config.publish_original_model !== false,
    versionListByProduct: config.version_list_by_product || '/internal/algorithm/algorithm-version/listByProduct/{productId}',
    weightListByVersion: config.weight_list_by_version || '/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}',
    targetMappings: Object.fromEntries(TARGETS.map(([key]) => [key, {
      compute_platform_id: mappings[key]?.compute_platform_id || '',
      chip_code: mappings[key]?.chip_code || '',
      enabled: mappings[key]?.enabled !== false,
    }])),
    storageSources: Array.isArray(body.storage_sources) ? body.storage_sources : [],
    computePlatforms: Array.isArray(body.compute_platforms) ? body.compute_platforms : [],
  };
}

export function publicationActionLabel(version = {}) {
  const status = String(version.external_publish_status || '').toLowerCase();
  if (status === 'published') return '已同步';
  if (status === 'partial' || status === 'failed' || status === 'unknown') return '重新同步';
  if (status === 'preparing' || status === 'version_ready') return '同步中';
  if (version.external_publish_requested_at) return '待同步';
  return '同步到新畅联';
}

export function publicationPreflight(status = {}) {
  if (status.identity_ready === false) {
    const issues = Array.isArray(status.identity_issues) ? status.identity_issues : [];
    const issue = issues[0] || {};
    const code = String(issue.code || '');
    if (code === 'EXTERNAL_VERSION_ANALYSIS_STALE') {
      return {
        ready: false,
        message: '该训练版本绑定的畅联云分析方式已失效。请先到“平台对接”执行“立即同步”并核对分析方式；平台不会自动改挂到其他分析方式。',
      };
    }
    if (code === 'EXTERNAL_ALGORITHM_INACTIVE') {
      return {
        ready: false,
        message: '该算法已在新畅联下架，不能发布新版本。请先在新畅联恢复后执行“立即同步”。',
      };
    }
    return {
      ready: false,
      message: '当前算法的畅联云主数据不是最新状态，请先到“平台对接”执行“立即同步”后再发布。',
    };
  }
  if (status.transport_ready === false) {
    const issues = Array.isArray(status.transport_issues) ? status.transport_issues : [];
    const actions = issues.map(row => {
      const code = String(row?.code || '');
      if (code === 'MODEL_ARTIFACT_STORAGE_NOT_CONFIGURED' || code === 'ARTIFACT_STORAGE_SOURCE_NOT_FOUND') {
        return '请到“存储配置 → 算法与转换结果存储”选择可用存储源并执行“测试存储”';
      }
      if (code === 'EXTERNAL_PUBLISH_CONFIG_INCOMPLETE') {
        return '请到“存储配置 → 算法与转换结果存储”填写 OSS / CDN 长期访问域名';
      }
      return String(row?.message || '').trim();
    }).filter(Boolean);
    return {
      ready: false,
      message: actions.join('；') || '算法产物交付配置尚未就绪，请先配置 OSS 存储和长期访问域名。',
    };
  }
  const discovered = Array.isArray(status.discovered) ? status.discovered : [];
  if (!discovered.length) {
    return {ready: false, message: '当前版本还没有可交付的训练模型或转换产物。'};
  }
  const blocked = Number(status.blocked_artifact_count || 0);
  const mapped = Number(status.mapped_artifact_count || 0);
  if (mapped <= 0 || status.publish_ready === false) {
    const targets = [...new Set(discovered
      .filter(row => row.publish_mapping_status === 'blocked')
      .map(row => String(row.target || '').toUpperCase())
      .filter(Boolean))];
    if (blocked > 0) {
      return {
        ready: false,
        message: `原始训练模型尚未具备发布条件${targets.length ? `（当前缺少：${targets.join('、')}）` : ''}，请先补齐 original 的畅联云算力环境映射。`,
      };
    }
    return {ready: false, message: '当前没有已完成映射的原始训练模型。'};
  }
  const ignored = Number(status.ignored_artifact_count || 0);
  const deferred = Number(status.deferred_conversion_count || 0);
  return {
    ready: true,
    message: `发布预检通过：将先同步原始模型及当前已映射权重${deferred ? `；另有 ${deferred} 个转换权重待映射后自动追加` : ''}${ignored ? `；${ignored} 个转换目标已明确关闭发布` : ''}。`,
  };
}

export function installExternalAlgorithmPublishRuntime({getState, projectId, notify, algorithmListRuntime} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__externalAlgorithmPublishRuntimeInstalled) return window.ExternalAlgorithmPublishRuntime;

  const state = () => getState?.() || {};
  let config = null;
  let loading = false;
  let mutationQueued = false;

  function currentProjectId() {
    return String(projectId?.() || '');
  }

  async function loadConfig({silent = false} = {}) {
    try {
      const body = await requestJson(`${API_ROOT}/config`);
      config = normalizePublishConfig(body);
      return config;
    } catch (error) {
      if (!silent) notify?.(error?.message || error);
      throw error;
    }
  }

  function computeOptions(selected = '') {
    const rows = config?.computePlatforms || [];
    return `<option value="">请选择畅联云厂商 / 算力环境</option>${rows.map(row => {
      const id = String(row.computePlatformId || row.id || '');
      const name = row.computePlatformName || row.name || row.computePlatformCode || id;
      const code = row.computePlatformCode || row.code || '';
      return `<option value="${escapeHtml(id)}" data-name="${escapeHtml(name)}" data-code="${escapeHtml(code)}" ${id === selected ? 'selected' : ''}>${escapeHtml(name)}${code ? ` · ${escapeHtml(code)}` : ''} · ID ${escapeHtml(id)}</option>`;
    }).join('')}`;
  }

  function storageOptions(selected = '') {
    const rows = (config?.storageSources || []).filter(row => row.enabled !== false);
    return `<option value="">请选择存储源</option>${rows.map(row => {
      const id = String(row.id || '');
      return `<option value="${escapeHtml(id)}" ${id === selected ? 'selected' : ''}>${escapeHtml(row.name || id)} · ${escapeHtml(row.type || '')}</option>`;
    }).join('')}`;
  }

  function mappingRows() {
    return TARGETS.map(([key, label]) => {
      const row = config?.targetMappings?.[key] || {};
      const meta = VENDOR_META[key] || {mark: label.slice(0, 2), scene: label, note: ''};
      const original = key === 'original';
      const selected = String(row.compute_platform_id || '');
      const selectedPlatform = (config?.computePlatforms || []).find(item => String(item.computePlatformId || item.id || '') === selected) || {};
      const selectedName = selectedPlatform.computePlatformName || selectedPlatform.name || selectedPlatform.computePlatformCode || '';
      const selectedCode = selectedPlatform.computePlatformCode || selectedPlatform.code || row.chip_code || '';
      const enabled = original || row.enabled !== false;
      return `<article class="external-vendor-card ${enabled ? 'enabled' : 'disabled'}" data-publish-target="${escapeHtml(key)}">
        <div class="external-vendor-card-head">
          <span class="external-vendor-mark">${escapeHtml(meta.mark)}</span>
          <div><b>${escapeHtml(label)}</b><span>${escapeHtml(meta.scene)}</span></div>
          ${original ? '<span class="pill ok">必配</span>' : `<label class="external-vendor-switch"><input data-publish-enabled type="checkbox" ${enabled ? 'checked' : ''}><span></span></label>`}
        </div>
        <p>${escapeHtml(meta.note)}</p>
        <div class="field">
          <label>关联畅联云厂商 / 算力环境</label>
          <select class="select" data-publish-platform>${computeOptions(selected)}</select>
        </div>
        <input type="hidden" data-publish-chip value="${escapeHtml(row.chip_code || selectedCode || '')}">
        <div class="external-vendor-meta">
          <span>畅联云 ID <code data-vendor-id>${escapeHtml(selected || '未配置')}</code></span>
          <span>平台编码 <code data-vendor-code>${escapeHtml(selectedCode || '-')}</code></span>
          <span class="external-vendor-name" data-vendor-name>${escapeHtml(selectedName || '尚未关联')}</span>
        </div>
      </article>`;
    }).join('');
  }

  function panelHtml() {
    const c = config || normalizePublishConfig({});
    const configured = TARGETS.filter(([key]) => {
      const row = c.targetMappings?.[key] || {};
      return (key === 'original' || row.enabled !== false) && Boolean(row.compute_platform_id);
    }).length;
    return `<section class="panel external-vendor-panel" data-platform-tab-panel="vendor" data-external-publish-panel="1">
      <div class="panel-head external-vendor-panel-head">
        <div>
          <div class="panel-title">厂商对应表</div>
          <div class="subline">维护“本平台转换厂商 → 畅联云厂商 / 算力环境 ID”的全局对应关系。模型发布时自动按这里取 computePlatformId，不需要每个算法重复配置。</div>
        </div>
        <div class="external-vendor-head-actions">
          <span class="pill ${configured ? 'ok' : 'warn'}">已配置 ${configured} / ${TARGETS.length}</span>
          <button class="btn small" id="externalPublishRefreshPlatforms">↻ 拉取畅联云厂商</button>
        </div>
      </div>
      <div class="panel-body">
        <div class="external-vendor-guide">
          <div><span class="external-vendor-guide-icon">通</span><p><b>通用是特殊映射</b><small>训练刚完成、尚未转换的原始模型没有真实硬件厂商，统一使用“通用”对应的畅联云 ID。</small></p></div>
          <div><span class="external-vendor-guide-icon">厂</span><p><b>转换结果按厂商分流</b><small>RKNN 走瑞芯微，TensorRT 走 NVIDIA，Ascend 走华为；具体芯片型号优先读取真实转换产物。</small></p></div>
        </div>
        <div class="external-vendor-grid">${mappingRows()}</div>
        <div class="external-vendor-reference">
          <div>
            <b>畅联云参考数据</b>
            <span>算力环境来自最近一次新畅联主数据同步；下拉项直接显示名称、平台编码和 ID。</span>
          </div>
          <span class="pill">${Number(c.computePlatforms?.length || 0)} 个可选项</span>
        </div>
        <details class="external-vendor-advanced">
          <summary>高级操作</summary><div class="panel-title" style="margin-top:12px;font-size:12px">官方同步接口</div>
          <div class="form two" style="margin-top:12px">
            <div class="field"><label>按产品查询版本</label><code>${escapeHtml(c.versionListByProduct)}</code></div>
            <div class="field"><label>按版本查询权重</label><code>${escapeHtml(c.weightListByVersion)}</code></div>
          </div>
          <div class="subline" style="margin-top:8px">创建、查询和删除均使用新畅联官方 OpenAPI 固定路径，不允许前端修改。</div>
          <div data-external-publish-automation="1" style="margin-top:12px"><button class="btn" id="externalPublishAutoRun">立即检查待同步结果</button></div>
        </details>
        <div class="external-vendor-savebar"><span>修改对应关系后，只影响后续发布/补同步，不会重复创建已存在的畅联云算法版本。</span><button class="btn primary" id="externalPublishSave">保存厂商对应表</button></div>
      </div>
    </section>`;
  }

  function collectConfig() {
    const mappings = {};
    for (const row of document.querySelectorAll('[data-publish-target]')) {
      const key = row.dataset.publishTarget;
      mappings[key] = {
        enabled: key === 'original' ? true : Boolean(row.querySelector('[data-publish-enabled]')?.checked),
        compute_platform_id: row.querySelector('[data-publish-platform]')?.value || '',
        chip_code: row.querySelector('[data-publish-chip]')?.value.trim() || '',
      };
    }
    return {
      // ModelArtifactRuntime is the single owner of model asset storage.
      // Keep the legacy publish field empty so saving mappings/public URL cannot
      // overwrite a newer model-asset storage choice.
      storage_source_id: '',
      public_base_url: '',
      publish_original_model: true,
      target_mappings: mappings,
      version_list_by_product: '/internal/algorithm/algorithm-version/listByProduct/{productId}',
      weight_list_by_version: '/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}',
    };
  }

  async function saveConfig() {
    const body = await requestJson(`${API_ROOT}/config`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(collectConfig()),
    });
    config = {...config, ...normalizePublishConfig({config: body.config, storage_sources: config?.storageSources, compute_platforms: config?.computePlatforms})};
    notify?.('训练成果发布配置已保存');
  }

  async function runAutoOnce() {
    const button = document.getElementById('externalPublishAutoRun');
    if (button) { button.disabled = true; button.textContent = '正在执行…'; }
    try {
      const body = await requestJson(`${API_ROOT}/run-auto`, {method: 'POST'});
      notify?.(`自动发布检查完成：发布 ${body.published || 0}，跳过 ${body.skipped || 0}，失败 ${body.failed || 0}`);
      await algorithmListRuntime?.refresh?.({render: String(state().page || '') === '算法列表'});
    } finally {
      if (button) { button.disabled = false; button.textContent = '执行一次待发布任务'; }
    }
  }

  function bindPanel() {
    const save = document.getElementById('externalPublishSave');
    if (save) save.onclick = () => void saveConfig().catch(error => notify?.(error?.message || error));
    const run = document.getElementById('externalPublishAutoRun');
    if (run) run.onclick = () => void runAutoOnce().catch(error => notify?.(error?.message || error));
    const refresh = document.getElementById('externalPublishRefreshPlatforms');
    if (refresh) refresh.onclick = () => void (async () => {
      refresh.disabled = true;
      const original = refresh.textContent;
      refresh.textContent = '正在拉取…';
      try {
        await window.ExternalAlgorithmPlatformRuntime?.syncNow?.();
        await loadConfig({silent: true});
        notify?.('畅联云厂商 / 算力环境已刷新');
      } catch (error) {
        notify?.(error?.message || error);
      } finally {
        if (refresh.isConnected) { refresh.disabled = false; refresh.textContent = original || '↻ 拉取畅联云厂商'; }
      }
    })();

    for (const row of document.querySelectorAll('[data-publish-target]')) {
      const enabled = row.querySelector('[data-publish-enabled]');
      const select = row.querySelector('[data-publish-platform]');
      const chip = row.querySelector('[data-publish-chip]');
      const syncMeta = () => {
        const option = select?.selectedOptions?.[0];
        const id = String(select?.value || '');
        const name = String(option?.dataset?.name || '');
        const code = String(option?.dataset?.code || '');
        const idNode = row.querySelector('[data-vendor-id]');
        const codeNode = row.querySelector('[data-vendor-code]');
        const nameNode = row.querySelector('[data-vendor-name]');
        if (idNode) idNode.textContent = id || '未配置';
        if (codeNode) codeNode.textContent = code || chip?.value || '-';
        if (nameNode) nameNode.textContent = name || '尚未关联';
        if (chip && code) chip.value = code;
      };
      if (select) select.onchange = syncMeta;
      if (enabled) enabled.onchange = () => row.classList.toggle('disabled', !enabled.checked);
    }
  }

  async function decoratePlatformPage() {
    if (String(state().page || '') !== PLATFORM_PAGE) return;
    const shell = document.querySelector('[data-external-platform-page="1"]');
    if (!shell || shell.querySelector('[data-external-publish-panel="1"]')) return;
    if (!config && !loading) {
      loading = true;
      try { await loadConfig({silent: true}); } catch (_) { /* phase 1 page remains usable */ }
      finally { loading = false; }
    }
    if (!config || String(state().page || '') !== PLATFORM_PAGE) return;
    const historyPanel = shell.querySelector('[data-platform-tab-panel="history"]');
    if (historyPanel) historyPanel.insertAdjacentHTML('beforebegin', panelHtml());
    else shell.insertAdjacentHTML('beforeend', panelHtml());
    bindPanel();
  }

  function versionFromIds(algorithmId, versionId) {
    const algorithm = (state().algorithms || []).find(row => String(row.id) === String(algorithmId));
    const version = (algorithm?.versions || []).find(row => String(row.id) === String(versionId));
    return {algorithm, version};
  }

  async function publishVersion(algorithmId, versionId, button) {
    const pid = currentProjectId();
    if (!pid) return notify?.('当前项目不可用，请刷新页面后重试');
    if (button) { button.disabled = true; button.textContent = '正在检查…'; }
    try {
      const status = await requestJson(
        `${API_ROOT}/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(algorithmId)}/versions/${encodeURIComponent(versionId)}`
      );
      const preflight = publicationPreflight(status);
      if (!preflight.ready) {
        notify?.(preflight.message);
        return;
      }
      notify?.(preflight.message);
      if (button) button.textContent = '正在同步…';
      await requestJson(`${API_ROOT}/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(algorithmId)}/versions/${encodeURIComponent(versionId)}/publish`, {method: 'POST'});
      notify?.('模型版本和转换产物已同步到新畅联');
      await algorithmListRuntime?.refresh?.({render: true});
    } catch (error) {
      notify?.(error?.message || error);
      await algorithmListRuntime?.refresh?.({render: true});
    } finally {
      if (button?.isConnected) {
        const {version} = versionFromIds(algorithmId, versionId);
        button.disabled = String(version?.external_publish_status || '').toLowerCase() === 'published';
        button.textContent = publicationActionLabel(version || {});
      }
    }
  }

  function schedulePlatformPage() {
    if (mutationQueued) return;
    mutationQueued = true;
    queueMicrotask(() => {
      mutationQueued = false;
      void decoratePlatformPage();
    });
  }

  const observer = new MutationObserver(schedulePlatformPage);
  observer.observe(document.body, {childList: true, subtree: true});
  schedulePlatformPage();

  const runtime = {
    build: 'external-algorithm-publish-64004',
    loadConfig,
    saveConfig,
    runAutoOnce,
    publishVersion,
    decoratePlatformPage,
    config: () => config,
    destroy() {
      observer.disconnect();
      window.__externalAlgorithmPublishRuntimeInstalled = false;
      if (window.ExternalAlgorithmPublishRuntime === runtime) window.ExternalAlgorithmPublishRuntime = null;
    },
  };
  window.ExternalAlgorithmPublishRuntime = runtime;
  window.__externalAlgorithmPublishRuntimeInstalled = true;
  return runtime;
}
