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
    throw new Error(`${message}${solution}`);
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

export function normalizeExternalPlatformConfig(body = {}) {
  const config = body?.config || body || {};
  const endpoints = config.endpoints || {};
  return {
    mode: config.mode === 'external' ? 'external' : 'local',
    provider: config.provider || 'changlian',
    providerName: config.provider_name || '新畅联',
    baseUrl: config.base_url || '',
    autoSyncEnabled: Boolean(config.auto_sync_enabled),
    autoPublishEnabled: Boolean(config.auto_publish_enabled),
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
  let loading = false;
  let destroyed = false;
  let renderQueued = false;
  let originalRenderAlg412 = null;

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

  function externalMode() {
    return (config || state().externalAlgorithmPlatformConfig)?.mode === 'external';
  }

  function decorateAlgorithmCards() {
    const s = state();
    if (String(s.page || '') !== '算法列表') return;
    const rows = s.algorithms || [];
    const root = document.getElementById('alg412List');
    if (!root) return;

    for (const card of root.querySelectorAll('.alg428-card')) {
      const actionButton = [...card.querySelectorAll('button')].find(button =>
        String(button.getAttribute('onclick') || '').includes("editAlgorithm423(")
      );
      const match = String(actionButton?.getAttribute('onclick') || '').match(/editAlgorithm423\('([^']+)'\)/);
      const algorithm = rows.find(row => String(row.id) === String(match?.[1] || ''));
      if (!algorithm) continue;
      const title = card.querySelector('.alg428-title');
      if (title && !title.querySelector('[data-algorithm-source]')) {
        const source = document.createElement('em');
        source.dataset.algorithmSource = '1';
        source.textContent = algorithmSourceLabel(algorithm);
        if (isExternalAlgorithm(algorithm)) source.title = '算法名称、品目和基础属性由外部平台维护';
        title.appendChild(source);
      }
      if (!isExternalAlgorithm(algorithm)) continue;
      for (const button of card.querySelectorAll('button')) {
        const onclick = String(button.getAttribute('onclick') || '');
        if (onclick.includes("editAlgorithm423(") || onclick.includes("delAlgorithm(")) {
          button.disabled = true;
          button.title = '外部平台算法主数据为只读，请在新畅联修改后重新同步';
        }
      }
    }

    const create = document.querySelector('.alg428-toolbar [data-action="algorithm.create"]');
    if (create && externalMode()) {
      create.removeAttribute('data-action');
      create.textContent = '↻ 同步新畅联';
      create.onclick = event => {
        event.preventDefault();
        void syncNow();
      };
      create.title = '当前算法主数据由新畅联管理';
    }
  }

  function installAlgorithmDecorator() {
    if (typeof window.renderAlg412 !== 'function' || originalRenderAlg412) return;
    originalRenderAlg412 = window.renderAlg412;
    const wrapped = function (...args) {
      const result = originalRenderAlg412.apply(this, args);
      decorateAlgorithmCards();
      return result;
    };
    wrapped.__externalPlatformWrapper = true;
    window.renderAlg412 = wrapped;
    decorateAlgorithmCards();
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
    return `<section class="label414-shell" data-external-platform-page="1">
      <div class="label414-head">
        <div>
          <h2>平台对接</h2>
          <p>算法主数据可使用本平台，也可切换为外部平台。切换不会删除已有算法、训练记录或版本。</p>
        </div>
        <div class="row">
          <button class="btn" id="externalPlatformTest">测试连接</button>
          <button class="btn primary" id="externalPlatformSync" ${external ? '' : 'disabled'}>↻ 立即同步</button>
        </div>
      </div>

      <section class="panel">
        <div class="panel-head"><div><div class="panel-title">算法主数据来源</div><div class="subline">外部平台模式下，新建算法由外部平台负责，本平台继续负责数据、训练、评测和转换。</div></div></div>
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
            <div class="field"><label>服务地址</label><input id="externalBaseUrl" class="input" value="${escapeHtml(c.baseUrl)}" placeholder="https://api.example.com"></div>
            <div class="field"><label>AccessKey</label><input id="externalAccessKey" class="input" autocomplete="off" placeholder="${escapeHtml(c.credentials?.masked || '未配置')}"></div>
            <div class="field"><label>AccessSecret</label><input id="externalAccessSecret" type="password" class="input" autocomplete="new-password" placeholder="${c.credentials?.configured ? '已配置，留空表示不修改' : '请输入 AccessSecret'}"></div>
            <label class="field check"><input id="externalAutoSync" type="checkbox" ${c.autoSyncEnabled ? 'checked' : ''}> 自动同步（配置预留）</label>
            <label class="field check"><input id="externalAutoPublish" type="checkbox" ${c.autoPublishEnabled ? 'checked' : ''}> 训练成果自动发布（下一阶段启用）</label>
          </div>
          <div class="row end"><button class="btn primary" id="externalPlatformSave">保存配置</button></div>
        </div>
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
        </div>
      </section>

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
              ${endpointField('version_create', '新增算法版本（下一阶段）', c.endpoints.version_create)}
              ${endpointField('weight_create', '新增权重文件（下一阶段）', c.endpoints.weight_create)}
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
    await save({quiet: true});
    const button = document.getElementById('externalPlatformTest');
    if (button) { button.disabled = true; button.textContent = '正在测试…'; }
    try {
      await requestJson(`${API_ROOT}/test`, {method: 'POST'});
      notify?.('新畅联鉴权连接正常');
    } finally {
      if (button) { button.disabled = false; button.textContent = '测试连接'; }
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
      await Promise.all([loadConfig({silent: true}), loadHistory({silent: true})]);
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
    const syncButton = document.getElementById('externalPlatformSync');
    if (saveButton) saveButton.onclick = () => void save().then(() => render({reload: false})).catch(error => notify?.(error?.message || error));
    if (testButton) testButton.onclick = () => void testConnection().catch(error => notify?.(error?.message || error));
    if (syncButton) syncButton.onclick = () => void syncNow().catch(error => notify?.(error?.message || error));

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
        const [nextConfig, nextHistory] = await Promise.all([
          loadConfig({silent: true}),
          loadHistory({silent: true}),
        ]);
        config = nextConfig;
        history = nextHistory;
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
  void loadConfig({silent: true}).then(() => decorateAlgorithmCards()).catch(() => {});

  const runtime = {
    build: 'external-algorithm-platform-63001',
    page: PAGE,
    loadConfig,
    loadHistory,
    render,
    save,
    testConnection,
    syncNow,
    decorateNavigation,
    decorateAlgorithmCards,
    config: () => config,
    destroy() {
      destroyed = true;
      observer?.disconnect();
      if (originalRenderAlg412 && window.renderAlg412?.__externalPlatformWrapper) {
        window.renderAlg412 = originalRenderAlg412;
      }
      if (window.ExternalAlgorithmPlatformRuntime === runtime) window.ExternalAlgorithmPlatformRuntime = null;
      window.__externalAlgorithmPlatformRuntimeInstalled = false;
    },
  };
  window.ExternalAlgorithmPlatformRuntime = runtime;
  window.__externalAlgorithmPlatformRuntimeInstalled = true;
  return runtime;
}
