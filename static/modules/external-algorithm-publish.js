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
  if (blocked > 0) {
    const targets = [...new Set(discovered
      .filter(row => row.publish_mapping_status === 'blocked')
      .map(row => String(row.target || '').toUpperCase())
      .filter(Boolean))];
    return {
      ready: false,
      message: `还有 ${blocked} 个已启用转换产物缺少畅联云算力环境映射${targets.length ? `（${targets.join('、')}）` : ''}，请先到“平台对接 → 畅联云版本与权重同步”补齐；不需要发布的目标请明确关闭。`,
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
      const original = key === 'original';
      return `<tr data-publish-target="${escapeHtml(key)}">
        <td><label class="field check"><input data-publish-enabled type="checkbox" ${original || row.enabled !== false ? 'checked' : ''} ${original ? 'disabled' : ''}> ${escapeHtml(original ? '原始训练模型（必传）' : label)}</label></td>
        <td><select class="select" data-publish-platform>${computeOptions(row.compute_platform_id || '')}</select></td>
        <td><input class="input" data-publish-chip value="${escapeHtml(row.chip_code || '')}" placeholder="兜底值，如 RK3568 / RK3576"></td>
      </tr>`;
    }).join('');
  }

  function panelHtml() {
    const c = config || normalizePublishConfig({});
    return `<section class="panel" data-external-publish-panel="1">
      <div class="panel-head"><div><div class="panel-title">畅联云版本与权重同步</div><div class="subline">训练成功后自动创建算法版本；原始训练模型与后续转换结果上传 OSS 后，通过官方权重接口追加到同一版本。</div></div><span class="pill ok">自动同步</span></div>
      <div class="panel-body">
        <div class="alert soft"><b>文件存储已统一</b><span>OSS 存储源、目录和长期访问域名请到“存储配置 → 算法与转换结果存储”维护；这里不重复保存存储配置。</span></div>
        <div class="panel-title" style="margin:18px 0 6px">模型类型 → 新畅联算力环境映射</div>
        <div class="subline" style="margin-bottom:10px">原始训练模型必须登记；转换目标可按需要启用。算力环境来自最近一次新畅联主数据同步。</div>
        <table class="table"><thead><tr><th>模型类型</th><th>算力环境</th><th>芯片编码（产物优先）</th></tr></thead><tbody>${mappingRows()}</tbody></table>
        <details style="margin-top:16px"><summary>官方同步接口</summary><div class="form two" style="margin-top:12px">
          <div class="field"><label>按产品查询版本</label><code>${escapeHtml(c.versionListByProduct)}</code></div>
          <div class="field"><label>按版本查询权重</label><code>${escapeHtml(c.weightListByVersion)}</code></div>
        </div><div class="subline" style="margin-top:8px">创建、查询和删除均使用新畅联官方 OpenAPI 固定路径，不允许前端修改。</div></details>
        <details data-external-publish-automation="1" style="margin-top:16px"><summary>高级操作</summary><div class="row" style="margin-top:12px"><button class="btn" id="externalPublishAutoRun">立即检查待同步结果</button></div></details>
        <div class="row end"><button class="btn primary" id="externalPublishSave">保存算力环境映射</button></div>
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
    build: 'external-algorithm-publish-64003',
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
