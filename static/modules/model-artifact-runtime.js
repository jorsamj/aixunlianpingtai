const MODEL_API = '/api/v64/model-artifacts';
const PLATFORM_API = '/api/v63/external-algorithm-platform';
const PLATFORM_PAGE = '平台对接';
const STORAGE_PAGE = '存储配置';

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
  if (!response.ok) throw new Error(String(body.message || body.detail || `请求失败（HTTP ${response.status}）`));
  return body;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, match => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[match]));
}

function formatTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', {hour12: false});
}

export function normalizeModelArtifactConfig(body = {}) {
  const config = body.config || {};
  return {
    storageSourceId: String(config.storage_source_id || ''),
    objectPrefix: String(config.object_prefix || 'model-assets'),
    publicBaseUrl: String(config.public_base_url || ''),
    autoUploadEnabled: config.auto_upload_enabled !== false,
    updatedAt: config.updated_at || null,
    storageSources: Array.isArray(body.storage_sources) ? body.storage_sources : [],
    summary: body.summary || {total: 0, uploaded: 0, failed: 0, pending: 0},
  };
}

export function auditStatusPresentation(status) {
  const key = String(status || '').toUpperCase();
  if (key === 'SUCCESS') return {label: '成功', cls: 'ok'};
  if (key === 'UNKNOWN') return {label: '状态未知', cls: 'warn'};
  return {label: '失败', cls: 'bad'};
}

export function operationLabel(value) {
  const map = {
    auth_signature: '签名', auth_token: '鉴权', category_list: '算法品目', product_list: '算法产品',
    analysis_list: '分析方式', compute_platform_list: '算力环境', version_create: '创建算法版本',
    version_list: '查询算法版本', weight_create: '创建权重记录', weight_list: '查询权重记录',
  };
  return map[String(value || '')] || String(value || '接口调用');
}

export function diagnosticText(row = {}) {
  const request = row.request || {};
  const response = row.response || {};
  return [
    `时间：${row.created_at || ''}`,
    `状态：${row.status || ''}`,
    `操作：${operationLabel(row.operation)}`,
    `接口：${row.method || ''} ${row.endpoint || ''}`.trim(),
    `HTTP状态：${row.http_status ?? ''}`,
    `业务返回码：${row.business_code || ''}`,
    `Request ID：${row.request_id || ''}`,
    `Correlation ID：${row.correlation_id || ''}`,
    `本地 project_id：${row.project_id || ''}`,
    `本地 algorithm_id：${row.algorithm_id || ''}`,
    `本地 version_id：${row.version_id || ''}`,
    `artifact_id：${row.artifact_id || ''}`,
    `畅联云 productId：${row.external_product_id || ''}`,
    `畅联云 analysisId：${row.external_analysis_id || ''}`,
    `畅联云 algoVersionId：${row.external_algo_version_id || ''}`,
    `畅联云 weightId：${row.external_weight_id || ''}`,
    `耗时：${row.duration_ms || 0}ms`,
    `重试次数：${row.retry_count || 0}`,
    `错误码：${row.error_code || ''}`,
    `失败原因：${row.error_message || ''}`,
    `请求（已脱敏）：${JSON.stringify(request)}`,
    `响应（已脱敏）：${JSON.stringify(response)}`,
  ].join('\n');
}

function ensureStyles() {
  if (document.getElementById('modelArtifactRuntimeStyles')) return;
  const style = document.createElement('style');
  style.id = 'modelArtifactRuntimeStyles';
  style.textContent = `
    .ma-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:14px 0 18px}
    .ma-stat{border:1px solid var(--border,#263241);background:linear-gradient(180deg,rgba(255,255,255,.035),rgba(255,255,255,.012));border-radius:12px;padding:14px 16px;min-height:74px}
    .ma-stat span{display:block;font-size:12px;opacity:.7;margin-bottom:7px}.ma-stat strong{font-size:22px;line-height:1;font-weight:700}
    .ma-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}.ma-toolbar .select,.ma-toolbar .input{min-width:150px}
    .ma-pill{display:inline-flex;align-items:center;padding:3px 9px;border-radius:999px;font-size:12px;font-weight:650;border:1px solid transparent}
    .ma-pill.ok{color:#75e6aa;background:rgba(31,181,101,.12);border-color:rgba(31,181,101,.28)}
    .ma-pill.bad{color:#ff9797;background:rgba(239,68,68,.11);border-color:rgba(239,68,68,.28)}
    .ma-pill.warn{color:#ffd27a;background:rgba(245,158,11,.11);border-color:rgba(245,158,11,.28)}
    .ma-table-wrap{overflow:auto;border:1px solid var(--border,#263241);border-radius:12px}.ma-table{width:100%;border-collapse:collapse;min-width:900px}
    .ma-table th,.ma-table td{padding:11px 12px;text-align:left;border-bottom:1px solid rgba(128,145,166,.14);font-size:13px;vertical-align:middle}
    .ma-table th{font-size:12px;opacity:.72;background:rgba(255,255,255,.025);position:sticky;top:0}.ma-table tr:last-child td{border-bottom:0}
    .ma-endpoint{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .ma-muted{opacity:.64}.ma-empty{padding:26px;text-align:center;opacity:.65}
    .ma-drawer-mask{position:fixed;inset:0;background:rgba(0,0,0,.48);z-index:10040;display:flex;justify-content:flex-end}
    .ma-drawer{width:min(680px,92vw);height:100%;background:var(--panel,#111923);border-left:1px solid var(--border,#263241);box-shadow:-20px 0 60px rgba(0,0,0,.28);display:flex;flex-direction:column}
    .ma-drawer-head{display:flex;align-items:center;justify-content:space-between;padding:20px 22px;border-bottom:1px solid var(--border,#263241)}
    .ma-drawer-body{padding:20px 22px;overflow:auto}.ma-kv{display:grid;grid-template-columns:140px 1fr;gap:9px 16px;margin:0 0 18px}.ma-kv dt{opacity:.62}.ma-kv dd{margin:0;word-break:break-all}
    .ma-code{white-space:pre-wrap;word-break:break-word;border:1px solid var(--border,#263241);background:rgba(0,0,0,.16);border-radius:10px;padding:12px;font:12px/1.65 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;max-height:260px;overflow:auto}
    .ma-section-title{font-size:13px;font-weight:700;margin:18px 0 8px}.ma-actions{display:flex;gap:9px;align-items:center;justify-content:flex-end;flex-wrap:wrap}
    @media(max-width:980px){.ma-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
  `;
  document.head.appendChild(style);
}

export function installModelArtifactRuntime({getState, notify} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__modelArtifactRuntimeInstalled) return window.ModelArtifactRuntime;
  const state = () => getState?.() || {};
  let config = null;
  let summary = {total: 0, uploaded: 0, failed: 0, pending: 0};
  let auditSummary = {total: 0, success: 0, failed: 0, unknown: 0, avg_duration_ms: 0};
  let logs = [];
  let loading = false;
  let timer = null;
  let mutationQueued = false;

  ensureStyles();

  function storageOptions(selected = '') {
    return (config?.storageSources || []).filter(row => row.enabled !== false).map(row => {
      const id = String(row.id || '');
      const suffix = row.is_default ? ' · 默认' : '';
      return `<option value="${escapeHtml(id)}" ${id === selected ? 'selected' : ''}>${escapeHtml(row.name || id)} · ${escapeHtml(row.type || '')}${suffix}</option>`;
    }).join('');
  }

  function storagePanel() {
    const c = config || normalizeModelArtifactConfig({});
    return `<section class="panel" data-model-artifact-panel="1">
      <div class="panel-head"><div><div class="panel-title">算法与转换结果存储</div><div class="subline">训练成功模型与 ONNX / RKNN 等转换产物统一自动归档到所选存储；新畅联版本和权重接口使用这里生成的长期访问地址。</div></div><span class="ma-pill ok">自动归档</span></div>
      <div class="panel-body">
        <div class="ma-grid">
          <div class="ma-stat"><span>算法产物</span><strong>${Number(summary.total || 0)}</strong></div>
          <div class="ma-stat"><span>已上传</span><strong>${Number(summary.uploaded || 0)}</strong></div>
          <div class="ma-stat"><span>待处理</span><strong>${Number(summary.pending || 0)}</strong></div>
          <div class="ma-stat"><span>上传失败</span><strong>${Number(summary.failed || 0)}</strong></div>
        </div>
        <div class="form two">
          <div class="field"><label>算法产物存储源</label><select id="modelArtifactStorageSource" class="select"><option value="">请选择存储源</option>${storageOptions(c.storageSourceId)}</select><div class="subline">建议选择上方已配置并测试通过的阿里云 OSS。</div></div>
          <div class="field"><label>对象目录前缀</label><input id="modelArtifactPrefix" class="input" value="${escapeHtml(c.objectPrefix)}" placeholder="model-assets"></div>
          <div class="field full"><label>OSS / CDN 长期访问域名</label><input id="modelArtifactPublicBaseUrl" class="input" value="${escapeHtml(c.publicBaseUrl)}" placeholder="https://your-bucket.oss-cn-hangzhou.aliyuncs.com"><div class="subline">用于写入畅联云权重 filePath。请填写长期可访问域名，不保存会过期的临时签名链接。</div></div>
          <label class="field check"><input id="modelArtifactAutoUpload" type="checkbox" ${c.autoUploadEnabled ? 'checked' : ''}> 训练/转换完成后自动上传</label>
        </div>
        <div class="ma-actions"><button class="btn" id="modelArtifactTestStorage">测试存储</button><button class="btn" id="modelArtifactRunNow">立即扫描上传</button><button class="btn primary" id="modelArtifactSave">保存算法产物存储配置</button></div>
      </div>
    </section>`;
  }
  function auditPanel() {
    return `<section class="panel" data-changlian-audit-panel="1">
      <div class="panel-head"><div><div class="panel-title">畅联云交互日志</div><div class="subline">记录鉴权、主数据同步、版本和权重接口的结果、耗时与失败原因；敏感凭据自动脱敏。</div></div></div>
      <div class="panel-body">
        <div class="ma-grid">
          <div class="ma-stat"><span>近24小时调用</span><strong>${Number(auditSummary.total || 0)}</strong></div>
          <div class="ma-stat"><span>成功</span><strong>${Number(auditSummary.success || 0)}</strong></div>
          <div class="ma-stat"><span>失败 / 未知</span><strong>${Number(auditSummary.failed || 0) + Number(auditSummary.unknown || 0)}</strong></div>
          <div class="ma-stat"><span>平均耗时</span><strong>${Number(auditSummary.avg_duration_ms || 0)}<small style="font-size:12px;margin-left:3px">ms</small></strong></div>
        </div>
        <div class="ma-toolbar">
          <select class="select" id="changlianAuditStatus"><option value="">全部结果</option><option value="SUCCESS">成功</option><option value="FAILED">失败</option><option value="UNKNOWN">状态未知</option></select>
          <select class="select" id="changlianAuditOperation"><option value="">全部操作</option><option value="auth_token">鉴权</option><option value="category_list">算法品目</option><option value="product_list">算法产品</option><option value="analysis_list">分析方式</option><option value="compute_platform_list">算力环境</option><option value="version_create">创建算法版本</option><option value="weight_create">创建权重记录</option></select>
          <button class="btn" id="changlianAuditRefresh">刷新</button>
        </div>
        <div class="ma-table-wrap"><table class="ma-table"><thead><tr><th>时间</th><th>结果</th><th>操作</th><th>接口</th><th>耗时</th><th>Request ID</th><th></th></tr></thead><tbody id="changlianAuditRows">${auditRowsHtml()}</tbody></table></div>
      </div>
    </section>`;
  }

  function auditRowsHtml() {
    if (!logs.length) return `<tr><td colspan="7"><div class="ma-empty">暂无交互记录</div></td></tr>`;
    return logs.map(row => {
      const p = auditStatusPresentation(row.status);
      return `<tr data-audit-id="${escapeHtml(row.log_id)}"><td>${escapeHtml(formatTime(row.created_at))}</td><td><span class="ma-pill ${p.cls}">${p.label}</span></td><td>${escapeHtml(operationLabel(row.operation))}</td><td><div class="ma-endpoint" title="${escapeHtml(row.endpoint)}">${escapeHtml(row.method || '')} ${escapeHtml(row.endpoint || '')}</div></td><td>${Number(row.duration_ms || 0)} ms</td><td class="ma-muted">${escapeHtml(row.request_id || '-')}</td><td><button class="btn mini" data-audit-detail="${escapeHtml(row.log_id)}">详情</button></td></tr>`;
    }).join('');
  }

  async function loadModelConfig() {
    const body = await requestJson(`${MODEL_API}/config`);
    config = normalizeModelArtifactConfig(body);
    summary = config.summary;
    return config;
  }

  async function loadLogs() {
    const status = document.getElementById('changlianAuditStatus')?.value || '';
    const operation = document.getElementById('changlianAuditOperation')?.value || '';
    const params = new URLSearchParams({limit: '50'});
    if (status) params.set('status', status);
    if (operation) params.set('operation', operation);
    const [listBody, summaryBody] = await Promise.all([
      requestJson(`${PLATFORM_API}/interaction-logs?${params}`),
      requestJson(`${PLATFORM_API}/interaction-logs/summary?hours=24`),
    ]);
    logs = Array.isArray(listBody.items) ? listBody.items : [];
    auditSummary = summaryBody.summary || auditSummary;
    return logs;
  }

  async function saveModelConfig() {
    const payload = {
      storage_source_id: document.getElementById('modelArtifactStorageSource')?.value || '',
      object_prefix: document.getElementById('modelArtifactPrefix')?.value.trim() || 'model-assets',
      public_base_url: document.getElementById('modelArtifactPublicBaseUrl')?.value.trim() || '',
      auto_upload_enabled: Boolean(document.getElementById('modelArtifactAutoUpload')?.checked),
    };
    await requestJson(`${MODEL_API}/config`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    notify?.('算法与转换结果存储配置已保存');
    await refresh({rerender: true});
  }

  async function testStorage() {
    const storageSourceId = document.getElementById('modelArtifactStorageSource')?.value || '';
    const button = document.getElementById('modelArtifactTestStorage');
    if (button) { button.disabled = true; button.textContent = '正在测试…'; }
    try {
      const body = await requestJson(`${MODEL_API}/storage-test`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({storage_source_id: storageSourceId})});
      notify?.(body.message || '模型资产存储读写测试通过');
    } finally {
      if (button) { button.disabled = false; button.textContent = '测试存储'; }
    }
  }

  async function runNow() {
    const button = document.getElementById('modelArtifactRunNow');
    if (button) { button.disabled = true; button.textContent = '正在扫描…'; }
    try {
      const body = await requestJson(`${MODEL_API}/run-auto`, {method: 'POST'});
      notify?.(`资产扫描完成：发现 ${body.discovered || 0}，已上传 ${body.uploaded || 0}，失败 ${body.failed || 0}`);
      await refresh({rerender: true});
    } finally {
      if (button) { button.disabled = false; button.textContent = '立即扫描上传'; }
    }
  }

  async function openAuditDetail(logId) {
    const body = await requestJson(`${PLATFORM_API}/interaction-logs/${encodeURIComponent(logId)}`);
    const row = body.item || {};
    const p = auditStatusPresentation(row.status);
    const mask = document.createElement('div');
    mask.className = 'ma-drawer-mask';
    mask.innerHTML = `<aside class="ma-drawer" role="dialog" aria-modal="true">
      <div class="ma-drawer-head"><div><div class="panel-title">${escapeHtml(operationLabel(row.operation))}</div><div class="subline">${escapeHtml(formatTime(row.created_at))} · <span class="ma-pill ${p.cls}">${p.label}</span></div></div><button class="btn mini" data-audit-close>关闭</button></div>
      <div class="ma-drawer-body">
        <dl class="ma-kv"><dt>接口</dt><dd>${escapeHtml(row.method || '')} ${escapeHtml(row.endpoint || '')}</dd><dt>HTTP / 业务码</dt><dd>${escapeHtml(row.http_status ?? '-')} / ${escapeHtml(row.business_code || '-')}</dd><dt>耗时</dt><dd>${Number(row.duration_ms || 0)} ms</dd><dt>Request ID</dt><dd>${escapeHtml(row.request_id || '-')}</dd><dt>Correlation ID</dt><dd>${escapeHtml(row.correlation_id || '-')}</dd><dt>算法 / 版本</dt><dd>${escapeHtml(row.algorithm_id || '-')} / ${escapeHtml(row.version_id || '-')}</dd><dt>Artifact</dt><dd>${escapeHtml(row.artifact_id || '-')}</dd><dt>畅联云版本 / 权重</dt><dd>${escapeHtml(row.external_algo_version_id || '-')} / ${escapeHtml(row.external_weight_id || '-')}</dd><dt>失败原因</dt><dd>${escapeHtml(row.error_message || '-')}</dd></dl>
        <div class="ma-section-title">请求（敏感字段已脱敏）</div><div class="ma-code">${escapeHtml(JSON.stringify(row.request || {}, null, 2))}</div>
        <div class="ma-section-title">响应（敏感字段已脱敏）</div><div class="ma-code">${escapeHtml(JSON.stringify(row.response || {}, null, 2))}</div>
        <div class="ma-actions" style="margin-top:18px"><button class="btn primary" data-audit-copy>复制诊断信息</button></div>
      </div></aside>`;
    document.body.appendChild(mask);
    const close = () => mask.remove();
    mask.addEventListener('click', event => { if (event.target === mask || event.target.closest('[data-audit-close]')) close(); });
    mask.querySelector('[data-audit-copy]')?.addEventListener('click', async () => {
      await navigator.clipboard.writeText(diagnosticText(row));
      notify?.('诊断信息已复制，可直接发给 AI 排查');
    });
  }

  function bindPanels() {
    document.getElementById('modelArtifactSave')?.addEventListener('click', () => void saveModelConfig().catch(error => notify?.(error?.message || error)));
    document.getElementById('modelArtifactTestStorage')?.addEventListener('click', () => void testStorage().catch(error => notify?.(error?.message || error)));
    document.getElementById('modelArtifactRunNow')?.addEventListener('click', () => void runNow().catch(error => notify?.(error?.message || error)));
    document.getElementById('changlianAuditRefresh')?.addEventListener('click', () => void refreshLogsOnly().catch(error => notify?.(error?.message || error)));
    document.getElementById('changlianAuditStatus')?.addEventListener('change', () => void refreshLogsOnly());
    document.getElementById('changlianAuditOperation')?.addEventListener('change', () => void refreshLogsOnly());
    document.querySelector('[data-changlian-audit-panel]')?.addEventListener('click', event => {
      const button = event.target.closest('[data-audit-detail]');
      if (button) void openAuditDetail(button.dataset.auditDetail).catch(error => notify?.(error?.message || error));
    });
  }

  async function refreshLogsOnly() {
    await loadLogs();
    const body = document.getElementById('changlianAuditRows');
    if (body) body.innerHTML = auditRowsHtml();
    const panel = document.querySelector('[data-changlian-audit-panel]');
    if (panel) {
      const stats = panel.querySelectorAll('.ma-stat strong');
      if (stats[0]) stats[0].textContent = String(auditSummary.total || 0);
      if (stats[1]) stats[1].textContent = String(auditSummary.success || 0);
      if (stats[2]) stats[2].textContent = String(Number(auditSummary.failed || 0) + Number(auditSummary.unknown || 0));
      if (stats[3]) stats[3].innerHTML = `${Number(auditSummary.avg_duration_ms || 0)}<small style="font-size:12px;margin-left:3px">ms</small>`;
    }
  }

  async function renderPanels() {
    const page = String(state().page || '');
    if (page === STORAGE_PAGE) {
      if (!config && !loading) {
        loading = true;
        try { await loadModelConfig(); } finally { loading = false; }
      }
      if (!config || String(state().page || '') !== STORAGE_PAGE) return;
      const mount = document.getElementById('modelArtifactStorageMount');
      if (mount && !mount.querySelector('[data-model-artifact-panel="1"]')) {
        mount.innerHTML = storagePanel();
        bindPanels();
      }
      return;
    }
    if (page !== PLATFORM_PAGE) return;
    const shell = document.querySelector('[data-external-platform-page="1"]');
    if (!shell) return;
    if (!logs.length && !loading) {
      loading = true;
      try { await loadLogs(); } finally { loading = false; }
    }
    if (String(state().page || '') !== PLATFORM_PAGE) return;
    const existingAudit = shell.querySelector('[data-changlian-audit-panel="1"]');
    if (!existingAudit) {
      const history = [...shell.querySelectorAll('.panel')].find(panel => panel.textContent.includes('同步记录'));
      history ? history.insertAdjacentHTML('beforebegin', auditPanel()) : shell.insertAdjacentHTML('beforeend', auditPanel());
      bindPanels();
    }
  }
  async function refresh({rerender = false} = {}) {
    const page = String(state().page || '');
    if (page === STORAGE_PAGE) {
      await loadModelConfig();
      if (rerender) document.querySelector('[data-model-artifact-panel="1"]')?.remove();
      await renderPanels();
      return;
    }
    if (page === PLATFORM_PAGE) {
      await loadLogs();
      if (rerender) document.querySelector('[data-changlian-audit-panel="1"]')?.remove();
      await renderPanels();
    }
  }
  function schedule() {
    if (mutationQueued) return;
    mutationQueued = true;
    queueMicrotask(() => {
      mutationQueued = false;
      void renderPanels().catch(() => {});
    });
  }

  const observer = new MutationObserver(schedule);
  observer.observe(document.body, {childList: true, subtree: true});
  timer = window.setInterval(() => {
    if (String(state().page || '') === PLATFORM_PAGE) void refreshLogsOnly().catch(() => {});
  }, 10000);
  schedule();

  const runtime = {
    build: 'model-artifacts-65001',
    refresh,
    renderPanels,
    openAuditDetail,
    config: () => config,
    destroy() {
      observer.disconnect();
      if (timer) clearInterval(timer);
      window.__modelArtifactRuntimeInstalled = false;
      if (window.ModelArtifactRuntime === runtime) window.ModelArtifactRuntime = null;
    },
  };
  window.ModelArtifactRuntime = runtime;
  window.__modelArtifactRuntimeInstalled = true;
  return runtime;
}
