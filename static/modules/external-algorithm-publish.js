const API_ROOT = '/api/v64/external-publish';
const PLATFORM_PAGE = '平台对接';
const TARGETS = [
  ['onnx', 'ONNX / 通用'],
  ['tensorrt', 'TensorRT / NVIDIA'],
  ['ascend', '华为 Atlas / Ascend'],
  ['rockchip', '瑞芯微 / RKNN'],
  ['sophon', '算能 / Sophon'],
  ['paddle_inference', 'Paddle Inference'],
  ['original', '原始训练模型'],
];

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
    publishOriginalModel: Boolean(config.publish_original_model),
    versionListByProduct: config.version_list_by_product || '/algorithm-version/listByProduct/{productId}',
    weightListByVersion: config.weight_list_by_version || '/algorithm-weight/listByVersion/{algoVersionId}',
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
  if (status.conversion_active) {
    return {ready: false, message: '模型转换仍在进行，请等待转换完成后再同步到新畅联。'};
  }
  if (status.transport_ready === false) {
    const issues = Array.isArray(status.transport_issues) ? status.transport_issues : [];
    const detail = issues.map(row => row?.message).filter(Boolean).join('；');
    return {
      ready: false,
      message: detail || '模型发布传输配置尚未就绪，请先配置外部访问地址和模型资产存储。',
    };
  }
  const discovered = Array.isArray(status.discovered) ? status.discovered : [];
  if (!discovered.length) {
    return {ready: false, message: '当前版本还没有可发布的转换产物，请先完成模型转换。'};
  }
  const blocked = Number(status.blocked_artifact_count || 0);
  if (blocked > 0) {
    const targets = [...new Set(discovered
      .filter(row => row.publish_mapping_status === 'blocked')
      .map(row => String(row.target || '').toUpperCase())
      .filter(Boolean))];
    return {
      ready: false,
      message: `还有 ${blocked} 个已启用转换产物缺少畅联云算力环境映射${targets.length ? `（${targets.join('、')}）` : ''}，请先到“平台对接 → 畅联云版本发布”补齐；不需要发布的目标请明确关闭。`,
    };
  }
  const mapped = Number(status.mapped_artifact_count || 0);
  if (mapped <= 0 || status.publish_ready === false) {
    return {ready: false, message: '当前没有已完成映射的可发布转换产物。'};
  }
  const ignored = Number(status.ignored_artifact_count || 0);
  return {
    ready: true,
    message: `发布预检通过：将同步 ${mapped} 个权重${ignored ? `，另有 ${ignored} 个转换目标已明确关闭发布` : ''}。`,
  };
}

export function installExternalAlgorithmPublishRuntime({getState, projectId, notify, algorithmListRuntime} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__externalAlgorithmPublishRuntimeInstalled) return window.ExternalAlgorithmPublishRuntime;

  const state = () => getState?.() || {};
  let config = null;
  let loading = false;
  let unregisterAlgorithmDecorator = null;
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
    return `<option value="">请选择算力环境</option>${rows.map(row => {
      const id = String(row.computePlatformId || row.id || '');
      const name = row.computePlatformName || row.name || row.computePlatformCode || id;
      const code = row.computePlatformCode || row.code || '';
      return `<option value="${escapeHtml(id)}" ${id === selected ? 'selected' : ''}>${escapeHtml(name)}${code ? ` · ${escapeHtml(code)}` : ''}</option>`;
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
      return `<tr data-publish-target="${escapeHtml(key)}">
        <td><label class="field check"><input data-publish-enabled type="checkbox" ${row.enabled !== false ? 'checked' : ''}> ${escapeHtml(label)}</label></td>
        <td><select class="select" data-publish-platform>${computeOptions(row.compute_platform_id || '')}</select></td>
        <td><input class="input" data-publish-chip value="${escapeHtml(row.chip_code || '')}" placeholder="兜底值，如 RK3568 / RK3576"></td>
      </tr>`;
    }).join('');
  }

  function panelHtml() {
    const c = config || normalizePublishConfig({});
    return `<section class="panel" data-external-publish-panel="1">
      <div class="panel-head"><div><div class="panel-title">畅联云版本发布</div><div class="subline">模型文件统一从“模型资产存储”读取；这里仅配置畅联云版本/权重登记和算力环境映射。</div></div></div>
      <div class="panel-body">
        <div class="form two">
          <div class="field"><label>本平台外部访问地址</label><input id="externalPublishBaseUrl" class="input" value="${escapeHtml(c.publicBaseUrl)}" placeholder="https://algorithm.example.com"></div>
          <label class="field check"><input id="externalPublishOriginal" type="checkbox" ${c.publishOriginalModel ? 'checked' : ''}> 将原始训练权重也登记为畅联云权重（文件本身始终自动归档）</label>
        </div>
        <div class="panel-title" style="margin:18px 0 6px">转换目标 → 新畅联算力环境映射</div>
        <div class="subline" style="margin-bottom:10px">算力环境来自最近一次新畅联主数据同步；失效的 computePlatformId 会在保存和发布时被后端拒绝。</div>
        <table class="table"><thead><tr><th>转换目标</th><th>算力环境</th><th>芯片编码（转换产物优先）</th></tr></thead><tbody>${mappingRows()}</tbody></table>
        <details style="margin-top:16px"><summary>幂等恢复接口</summary><div class="form two" style="margin-top:12px">
          <div class="field"><label>按产品查询版本</label><input id="externalPublishVersionList" class="input" value="${escapeHtml(c.versionListByProduct)}"></div>
          <div class="field"><label>按版本查询权重</label><input id="externalPublishWeightList" class="input" value="${escapeHtml(c.weightListByVersion)}"></div>
        </div></details>
        <details data-external-publish-automation="1" style="margin-top:16px"><summary>高级设置 · 自动发布</summary><div class="row" style="margin-top:12px"><button class="btn" id="externalPublishAutoRun">执行一次待发布任务</button></div></details>
        <div class="row end"><button class="btn primary" id="externalPublishSave">保存发布配置</button></div>
      </div>
    </section>`;
  }

  function collectConfig() {
    const mappings = {};
    for (const row of document.querySelectorAll('[data-publish-target]')) {
      const key = row.dataset.publishTarget;
      mappings[key] = {
        enabled: Boolean(row.querySelector('[data-publish-enabled]')?.checked),
        compute_platform_id: row.querySelector('[data-publish-platform]')?.value || '',
        chip_code: row.querySelector('[data-publish-chip]')?.value.trim() || '',
      };
    }
    return {
      storage_source_id: config?.storageSourceId || '',
      public_base_url: document.getElementById('externalPublishBaseUrl')?.value.trim() || '',
      publish_original_model: Boolean(document.getElementById('externalPublishOriginal')?.checked),
      target_mappings: mappings,
      version_list_by_product: document.getElementById('externalPublishVersionList')?.value.trim() || '/algorithm-version/listByProduct/{productId}',
      weight_list_by_version: document.getElementById('externalPublishWeightList')?.value.trim() || '/algorithm-weight/listByVersion/{algoVersionId}',
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
    const historyPanel = [...shell.querySelectorAll('.panel')].find(panel => panel.textContent.includes('同步记录'));
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

  function decorateVersionRows() {
    if (String(state().page || '') !== '算法列表') return;
    for (const row of document.querySelectorAll('.alg428-version-row')) {
      if (row.querySelector('[data-external-publish-action]')) continue;
      const convert = [...row.querySelectorAll('button')].find(button => String(button.getAttribute('onclick') || '').includes('openVersionConvert428('));
      const match = String(convert?.getAttribute('onclick') || '').match(/openVersionConvert428\('([^']+)'\s*,\s*'([^']+)'\)/);
      if (!match) continue;
      const [_, algorithmId, versionId] = match;
      const {algorithm, version} = versionFromIds(algorithmId, versionId);
      if (!algorithm || String(algorithm.source_type || '').toUpperCase() !== 'EXTERNAL' || String(algorithm.provider_type || '').toUpperCase() !== 'CHANG_LIAN') continue;
      const actions = row.querySelector('.alg428-version-actions');
      if (!actions) continue;
      const button = document.createElement('button');
      button.className = 'btn mini';
      button.dataset.externalPublishAction = '1';
      button.textContent = publicationActionLabel(version || {});
      button.disabled = String(version?.external_publish_status || '').toLowerCase() === 'published';
      button.title = '将该版本已完成的转换产物上传到发布存储源，并同步到新畅联';
      button.onclick = event => {
        event.stopPropagation();
        void publishVersion(algorithmId, versionId, button);
      };
      actions.appendChild(button);
    }
  }

  function installRendererHook() {
    if (unregisterAlgorithmDecorator || !algorithmListRuntime?.registerDecorator) return;
    unregisterAlgorithmDecorator = algorithmListRuntime.registerDecorator('external-algorithm-publish', decorateVersionRows);
  }

  function scheduleDecorate() {
    if (mutationQueued) return;
    mutationQueued = true;
    queueMicrotask(() => {
      mutationQueued = false;
      installRendererHook();
      decorateVersionRows();
      void decoratePlatformPage();
    });
  }

  const observer = new MutationObserver(scheduleDecorate);
  observer.observe(document.body, {childList: true, subtree: true});
  scheduleDecorate();

  const runtime = {
    build: 'external-algorithm-publish-64002',
    loadConfig,
    saveConfig,
    runAutoOnce,
    publishVersion,
    decorateVersionRows,
    decoratePlatformPage,
    config: () => config,
    destroy() {
      observer.disconnect();
      unregisterAlgorithmDecorator?.();
      unregisterAlgorithmDecorator = null;
      window.__externalAlgorithmPublishRuntimeInstalled = false;
      if (window.ExternalAlgorithmPublishRuntime === runtime) window.ExternalAlgorithmPublishRuntime = null;
    },
  };
  window.ExternalAlgorithmPublishRuntime = runtime;
  window.__externalAlgorithmPublishRuntimeInstalled = true;
  return runtime;
}
