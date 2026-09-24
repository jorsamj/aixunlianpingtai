const MODEL_API = '/api/v64/model-artifacts';
const PLATFORM_API = '/api/v63/external-algorithm-platform';
const PLATFORM_PAGE = '平台对接';
const STORAGE_PAGE = '存储配置';

function rawFetch() {
  const scoped = window.fetch;
  return scoped?.__pageRequestScopeOriginal || scoped;
}

export function formatModelArtifactApiError(body = {}, status = 0) {
  const message = String(body?.message || '').trim();
  const detail = String(body?.detail || '').trim();
  const solution = String(body?.solution || '').trim();
  const parts = [message];
  if (detail && detail !== message) parts.push(`详情：${detail}`);
  if (solution) parts.push(`建议：${solution}`);
  return parts.filter(Boolean).join('；') || `请求失败（HTTP ${status || '-'}）`;
}

async function requestJson(url, options = {}) {
  const response = await rawFetch()(url, {
    headers: {'Accept': 'application/json', ...(options.headers || {})},
    ...options,
  });
  const text = await response.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch (_) { body = {detail: text}; }
  if (!response.ok) throw new Error(formatModelArtifactApiError(body, response.status));
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
  const storageSources = Array.isArray(body.storage_sources) ? body.storage_sources : [];
  const storageSourceId = String(config.storage_source_id || '');
  const source = storageSources.find(row => String(row.id || '') === storageSourceId);
  const artifactStorage = body.artifact_storage || {};
  return {
    storageSourceId,
    rootPrefix: String(config.root_prefix || config.object_prefix || 'changlian-ai/artifacts'),
    endpoint: String(artifactStorage.endpoint || source?.config?.endpoint || ''),
    bucket: String(artifactStorage.bucket || source?.config?.bucket || ''),
    publicBaseUrl: String(artifactStorage.public_base_url || source?.config?.public_base_url || ''),
    credentialConfigured: artifactStorage.credential_configured === true || source?.secret_configured === true,
    credentialMasked: String(artifactStorage.credential_masked || source?.secret_masked || ''),
    dedicatedStorage: artifactStorage.dedicated === true,
    autoUploadEnabled: config.auto_upload_enabled !== false,
    updatedAt: config.updated_at || null,
    storageSources,
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
    version_remove: '删除算法版本', version_list: '查询算法版本',
    weight_create: '创建权重记录', weight_remove: '删除权重记录', weight_list: '查询权重记录',
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
    @media(max-width:640px){.ma-grid{grid-template-columns:1fr}.ma-actions{justify-content:stretch}.ma-actions .btn{flex:1 1 100%}}
  `;
  document.head.appendChild(style);
}

export function installModelArtifactRuntime({getState, notify, pollRegistry} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__modelArtifactRuntimeInstalled) return window.ModelArtifactRuntime;
  const state = () => getState?.() || {};
  const registry = pollRegistry || window.PollRegistryRuntime;
  const AUDIT_POLL_KEY = 'model-artifact-audit';
  let config = null;
  let configLoadedAt = 0;
  let configInflight = null;
  const MODEL_CONFIG_CACHE_TTL_MS = 2 * 60 * 1000;
  let summary = {total: 0, uploaded: 0, failed: 0, pending: 0};
  let auditSummary = {total: 0, success: 0, failed: 0, unknown: 0, avg_duration_ms: 0};
  let logs = [];
  let logsLoadedAt = 0;
  let logsInflight = null;
  let logsInflightKey = '';
  let logsCacheKey = '';
  const AUDIT_LOG_CACHE_TTL_MS = 10 * 1000;
  let loading = false;
  let mutationQueued = false;

  ensureStyles();

  function storagePanel() {
    const c = config || normalizeModelArtifactConfig({});
    const credentialHint = c.credentialConfigured
      ? `已配置（${escapeHtml(c.credentialMasked || '安全凭据库')}），留空表示保持现有凭据`
      : '首次配置请填写 AccessKey ID 与 AccessKey Secret';
    const migrationHint = c.storageSourceId && !c.dedicatedStorage
      ? '<div class="alert soft"><b>检测到旧配置</b><span>当前算法产物仍复用了其他存储源。保存本区域后会自动迁移为独立的算法产物 OSS，不再依赖“素材存储”。</span></div>'
      : '';
    return `<section class="panel" data-model-artifact-panel="1">
      <div class="panel-head"><div><div class="panel-title">算法与转换结果存储</div><div class="subline">这里独立配置训练模型、ONNX、RKNN 等算法产物的 OSS；不需要先在“素材存储”创建或选择存储源。</div></div><span class="ma-pill ok">独立配置 · 自动归档</span></div>
      <div class="panel-body">
        <div class="ma-grid">
          <div class="ma-stat"><span>算法产物</span><strong>${Number(summary.total || 0)}</strong></div>
          <div class="ma-stat"><span>已上传</span><strong>${Number(summary.uploaded || 0)}</strong></div>
          <div class="ma-stat"><span>待处理</span><strong>${Number(summary.pending || 0)}</strong></div>
          <div class="ma-stat"><span>上传失败</span><strong>${Number(summary.failed || 0)}</strong></div>
        </div>
        ${migrationHint}
        <div class="form two">
          <div class="field"><label>OSS Endpoint</label><input id="modelArtifactEndpoint" class="input" value="${escapeHtml(c.endpoint)}" placeholder="https://oss-cn-hangzhou.aliyuncs.com"></div>
          <div class="field"><label>Bucket</label><input id="modelArtifactBucket" class="input" value="${escapeHtml(c.bucket)}" placeholder="new24hlink"></div>
          <div class="field"><label>AccessKey ID</label><input id="modelArtifactAccessKeyId" class="input" autocomplete="off" placeholder="${escapeHtml(credentialHint)}"></div>
          <div class="field"><label>AccessKey Secret</label><input id="modelArtifactAccessKeySecret" class="input" type="password" autocomplete="new-password" placeholder="${escapeHtml(credentialHint)}"></div>
          <div class="field full"><label>OSS 长期访问地址</label><input id="modelArtifactPublicBaseUrl" class="input" value="${escapeHtml(c.publicBaseUrl)}" placeholder="https://new24hlink.oss-cn-hangzhou.aliyuncs.com"><div class="subline">新畅联最终 filePath 使用这里的长期地址；配置后测试必须返回 HTTP 200/206。</div></div>
          <div class="field"><label>算法产物根目录</label><input id="modelArtifactPrefix" class="input" value="${escapeHtml(c.rootPrefix)}" placeholder="changlian-ai/artifacts"><div class="subline">测试对象会真实写入 &lt;根目录&gt;/.changlian-health-check/，正式模型也归档在该目录下。</div></div>
          <div class="field"><label>权限要求</label><div class="alert soft"><b>对象级权限必须完整</b><span>PUT / STAT / GET / DELETE 必须成功；Bucket 元信息 403 仅作为 warning。DELETE 失败仍会判定不可用。</span></div></div>
        </div>
        <div class="ma-actions"><button class="btn" id="modelArtifactTestStorage">保存并测试</button><button class="btn" id="modelArtifactRunNow">立即扫描上传</button><button class="btn primary" id="modelArtifactSave">保存算法产物 OSS</button></div>
      </div>
    </section>`;
  }
  function mountStoragePanel({replace = false} = {}) {
    const mount = document.getElementById('modelArtifactStorageMount');
    if (!mount) return false;
    if (!replace && mount.querySelector('[data-model-artifact-panel="1"]')) return false;
    mount.innerHTML = storagePanel();
    bindPanels();
    return true;
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
          <select class="select" id="changlianAuditOperation"><option value="">全部操作</option><option value="auth_token">鉴权</option><option value="category_list">算法品目</option><option value="product_list">算法产品</option><option value="analysis_list">分析方式</option><option value="compute_platform_list">算力环境</option><option value="version_create">创建算法版本</option><option value="version_remove">删除算法版本</option><option value="weight_create">创建权重记录</option><option value="weight_remove">删除权重记录</option></select>
          <button class="btn" id="changlianAuditRefresh">刷新</button>
        </div>
        <div class="ma-table-wrap"><table class="ma-table"><thead><tr><th>时间</th><th>结果</th><th>操作</th><th>接口</th><th>耗时</th><th>Request ID</th><th></th></tr></thead><tbody id="changlianAuditRows">${auditRowsHtml()}</tbody></table></div>
      </div>
    </section>`;
  }

  function auditRowHtml(row) {
    const p = auditStatusPresentation(row.status);
    return `<tr data-audit-id="${escapeHtml(row.log_id)}"><td>${escapeHtml(formatTime(row.created_at))}</td><td><span class="ma-pill ${p.cls}">${p.label}</span></td><td>${escapeHtml(operationLabel(row.operation))}</td><td><div class="ma-endpoint" title="${escapeHtml(row.endpoint)}">${escapeHtml(row.method || '')} ${escapeHtml(row.endpoint || '')}</div></td><td>${Number(row.duration_ms || 0)} ms</td><td class="ma-muted">${escapeHtml(row.request_id || '-')}</td><td><button class="btn mini" data-audit-detail="${escapeHtml(row.log_id)}">详情</button></td></tr>`;
  }

  function auditRowsHtml() {
    if (!logs.length) return `<tr class="ma-audit-empty"><td colspan="7"><div class="ma-empty">暂无交互记录</div></td></tr>`;
    return logs.map(auditRowHtml).join('');
  }

  function patchAuditRows(body) {
    if (!body) return false;
    if (!logs.length) {
      for (const row of [...(body.querySelectorAll?.('tr[data-audit-id]') || [])]) row.remove?.();
      if (!body.querySelector?.('.ma-audit-empty')) {
        const holder = document.createElement('tbody');
        holder.innerHTML = auditRowsHtml();
        const emptyRow = holder.firstElementChild;
        if (emptyRow) body.appendChild(emptyRow);
      }
      return true;
    }

    body.querySelector?.('.ma-audit-empty')?.remove?.();
    const existing = new Map(
      [...body.querySelectorAll('tr[data-audit-id]')]
        .map(row => [String(row.dataset?.auditId || ''), row]),
    );
    const wanted = new Set();

    logs.forEach((item, index) => {
      const id = String(item?.log_id || '');
      if (!id) return;
      wanted.add(id);
      const html = auditRowHtml(item);
      let row = existing.get(id) || null;
      if (!row) {
        const holder = document.createElement('tbody');
        holder.innerHTML = html;
        row = holder.firstElementChild;
      } else {
        const holder = document.createElement('tbody');
        holder.innerHTML = html;
        const next = holder.firstElementChild;
        if (next && row.innerHTML !== next.innerHTML) row.innerHTML = next.innerHTML;
      }
      if (!row) return;
      const reference = body.children[index] || null;
      if (reference !== row) body.insertBefore(row, reference);
    });

    for (const [id, row] of existing) {
      if (!wanted.has(id)) row.remove?.();
    }
    return true;
  }

  async function loadModelConfig({force = false} = {}) {
    const age = Date.now() - Number(configLoadedAt || 0);
    if (!force && config && configLoadedAt > 0 && age >= 0 && age < MODEL_CONFIG_CACHE_TTL_MS) return config;
    if (configInflight) return configInflight;
    const request = requestJson(`${MODEL_API}/config`).then(body => {
      config = normalizeModelArtifactConfig(body);
      summary = config.summary;
      configLoadedAt = Date.now();
      return config;
    });
    configInflight = request;
    try {
      return await request;
    } finally {
      if (configInflight === request) configInflight = null;
    }
  }

  async function loadLogs({force = false} = {}) {
    const status = document.getElementById('changlianAuditStatus')?.value || '';
    const operation = document.getElementById('changlianAuditOperation')?.value || '';
    const cacheKey = `${status}\u0000${operation}`;
    const age = Date.now() - Number(logsLoadedAt || 0);
    if (!force && logsLoadedAt > 0 && logsCacheKey === cacheKey && age >= 0 && age < AUDIT_LOG_CACHE_TTL_MS) return logs;
    if (logsInflight && logsInflightKey === cacheKey) return logsInflight;
    if (logsInflight) {
      try { await logsInflight; } catch (_) {}
    }
    const params = new URLSearchParams({limit: '50'});
    if (status) params.set('status', status);
    if (operation) params.set('operation', operation);
    const request = Promise.all([
      requestJson(`${PLATFORM_API}/interaction-logs?${params}`),
      requestJson(`${PLATFORM_API}/interaction-logs/summary?hours=24`),
    ]).then(([listBody, summaryBody]) => {
      logs = Array.isArray(listBody.items) ? listBody.items : [];
      auditSummary = summaryBody.summary || auditSummary;
      logsLoadedAt = Date.now();
      logsCacheKey = cacheKey;
      return logs;
    });
    logsInflight = request;
    logsInflightKey = cacheKey;
    try {
      return await request;
    } finally {
      if (logsInflight === request) {
        logsInflight = null;
        logsInflightKey = '';
      }
    }
  }

  function artifactOssPayload() {
    return {
      endpoint: document.getElementById('modelArtifactEndpoint')?.value.trim() || '',
      bucket: document.getElementById('modelArtifactBucket')?.value.trim() || '',
      access_key_id: document.getElementById('modelArtifactAccessKeyId')?.value.trim() || '',
      access_key_secret: document.getElementById('modelArtifactAccessKeySecret')?.value || '',
      public_base_url: document.getElementById('modelArtifactPublicBaseUrl')?.value.trim() || '',
      root_prefix: document.getElementById('modelArtifactPrefix')?.value.trim() || 'changlian-ai/artifacts',
    };
  }

  async function saveModelConfig({rerender = true, announce = true} = {}) {
    const body = await requestJson(`${MODEL_API}/oss-config`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(artifactOssPayload()),
    });
    config = normalizeModelArtifactConfig(body);
    summary = config.summary;
    configLoadedAt = Date.now();
    if (announce) notify?.('算法与转换结果 OSS 已独立保存');
    if (rerender) await refresh({rerender: true, force: true});
    return config;
  }

  async function testStorage() {
    const button = document.getElementById('modelArtifactTestStorage');
    if (button) { button.disabled = true; button.textContent = '保存并测试中…'; }
    try {
      const saved = await saveModelConfig({rerender: false, announce: false});
      const body = await requestJson(`${MODEL_API}/storage-test`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({storage_source_id: saved.storageSourceId}),
      });
      const warning = String(body.warning || '');
      notify?.(warning || body.message || '算法产物 OSS 对象级读写与长期地址测试通过');
      await refresh({rerender: true, force: true});
    } finally {
      if (button) { button.disabled = false; button.textContent = '保存并测试'; }
    }
  }

  async function runNow() {
    const button = document.getElementById('modelArtifactRunNow');
    if (button) { button.disabled = true; button.textContent = '正在扫描…'; }
    try {
      const body = await requestJson(`${MODEL_API}/run-auto`, {method: 'POST'});
      notify?.(`资产扫描完成：发现 ${body.discovered || 0}，已上传 ${body.uploaded || 0}，失败 ${body.failed || 0}`);
      await refresh({rerender: true, force: true});
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
    document.getElementById('changlianAuditRefresh')?.addEventListener('click', () => void refreshLogsOnly({force: true}).catch(error => notify?.(error?.message || error)));
    document.getElementById('changlianAuditStatus')?.addEventListener('change', () => void refreshLogsOnly({force: true}));
    document.getElementById('changlianAuditOperation')?.addEventListener('change', () => void refreshLogsOnly({force: true}));
    document.querySelector('[data-changlian-audit-panel]')?.addEventListener('click', event => {
      const button = event.target.closest('[data-audit-detail]');
      if (button) void openAuditDetail(button.dataset.auditDetail).catch(error => notify?.(error?.message || error));
    });
  }

  function scheduleAuditPoll() {
    if (!registry?.startTimeout || String(state().page || '') !== PLATFORM_PAGE) {
      registry?.clear?.(AUDIT_POLL_KEY);
      return null;
    }
    const active = registry.snapshot?.().some(row => row.key === AUDIT_POLL_KEY);
    if (active) return true;
    return registry.startTimeout(AUDIT_POLL_KEY, PLATFORM_PAGE, async () => {
      try {
        if (String(state().page || '') === PLATFORM_PAGE) await refreshLogsOnly({force: true});
      } catch (_) {
        scheduleAuditPoll();
      }
    }, 10000);
  }

  async function refreshLogsOnly({force = false} = {}) {
    await loadLogs({force});
    const body = document.getElementById('changlianAuditRows');
    if (body) patchAuditRows(body);
    const panel = document.querySelector('[data-changlian-audit-panel]');
    if (panel) {
      const stats = panel.querySelectorAll('.ma-stat strong');
      if (stats[0]) stats[0].textContent = String(auditSummary.total || 0);
      if (stats[1]) stats[1].textContent = String(auditSummary.success || 0);
      if (stats[2]) stats[2].textContent = String(Number(auditSummary.failed || 0) + Number(auditSummary.unknown || 0));
      if (stats[3]) stats[3].innerHTML = `${Number(auditSummary.avg_duration_ms || 0)}<small style="font-size:12px;margin-left:3px">ms</small>`;
    }
    scheduleAuditPoll();
  }

  async function renderPanels() {
    const page = String(state().page || '');
    if (page === STORAGE_PAGE) {
      if (!config && !loading) {
        loading = true;
        try { await loadModelConfig(); } finally { loading = false; }
      }
      if (!config || String(state().page || '') !== STORAGE_PAGE) return;
      mountStoragePanel();
      return;
    }
    if (page !== PLATFORM_PAGE) return;
    const shell = document.querySelector('[data-external-platform-page="1"]');
    if (!shell) return;
    if (!loading) {
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
    scheduleAuditPoll();
  }
  async function refresh({rerender = false, force = false} = {}) {
    const page = String(state().page || '');
    if (page === STORAGE_PAGE) {
      await loadModelConfig({force});
      if (rerender && mountStoragePanel({replace: true})) return;
      await renderPanels();
      return;
    }
    if (page === PLATFORM_PAGE) {
      await loadLogs({force});
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
  schedule();

  const runtime = {
    build: 'model-artifacts-65008',
    refresh,
    renderPanels,
    openAuditDetail,
    config: () => config,
    destroy() {
      observer.disconnect();
      registry?.clear?.(AUDIT_POLL_KEY);
      window.__modelArtifactRuntimeInstalled = false;
      if (window.ModelArtifactRuntime === runtime) window.ModelArtifactRuntime = null;
    },
  };
  window.ModelArtifactRuntime = runtime;
  window.__modelArtifactRuntimeInstalled = true;
  return runtime;
}
