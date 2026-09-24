const PAGE = '畅联云数据';
const BASE = '/api/v63/external-algorithm-platform/provider';

function valueOf(row, ...keys) {
  for (const key of keys) {
    const value = row?.[key];
    if (value !== undefined && value !== null && String(value).trim() !== '') return value;
  }
  return '';
}

export function providerItems(value) {
  const root = value?.response ?? value;
  const visit = current => {
    if (Array.isArray(current)) return current.filter(item => item && typeof item === 'object');
    if (!current || typeof current !== 'object') return [];
    for (const key of ['items', 'records', 'rows', 'list']) {
      if (Array.isArray(current[key])) return current[key].filter(item => item && typeof item === 'object');
    }
    if (current.data !== undefined && current.data !== current) return visit(current.data);
    return [];
  };
  return visit(root);
}

export function productIdentity(row) {
  return String(valueOf(row, 'productId', 'product_id', 'id')).trim();
}
export function versionIdentity(row) {
  return String(valueOf(row, 'algoVersionId', 'algorithmVersionId', 'versionId', 'id')).trim();
}
export function weightIdentity(row) {
  return String(valueOf(row, 'weightId', 'algorithmWeightId', 'id')).trim();
}

export function weightRemoteLink(row) {
  const value = String(valueOf(row, 'downloadUrl', 'fileUrl', 'publicUrl', 'url', 'filePath')).trim();
  return /^https?:\/\//i.test(value) ? value : '';
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function text(value, fallback = '-') {
  const result = String(value ?? '').trim();
  return result || fallback;
}

async function mapLimit(rows, limit, worker) {
  const result = new Array(rows.length);
  let cursor = 0;
  const runners = Array.from({length: Math.min(Math.max(1, limit), Math.max(1, rows.length))}, async () => {
    while (cursor < rows.length) {
      const index = cursor++;
      result[index] = await worker(rows[index], index);
    }
  });
  await Promise.all(runners);
  return result;
}

function mergeProducts(...groups) {
  const seen = new Set();
  const rows = [];
  for (const row of groups.flat()) {
    const id = productIdentity(row);
    const key = id || JSON.stringify(row);
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push(row);
  }
  return rows;
}

export function installChangLianDataBrowserRuntime({
  getState = () => ({}),
  request,
  notify = () => {},
  document: doc = globalThis.document,
} = {}) {
  if (typeof request !== 'function') throw new Error('畅联云数据浏览器缺少 request 依赖');

  let destroyed = false;
  let refreshPromise = null;
  let refreshEpoch = 0;
  let snapshot = {
    loaded: false,
    loading: false,
    loadedAt: '',
    products: [],
    error: '',
  };

  function counts() {
    const products = snapshot.products.length;
    const versions = snapshot.products.reduce((sum, row) => sum + (row.versions?.length || 0), 0);
    const weights = snapshot.products.reduce((sum, row) => sum + (row.versions || []).reduce((n, version) => n + (version.weights?.length || 0), 0), 0);
    return {products, versions, weights};
  }

  function weightHtml(row) {
    const fileName = text(valueOf(row, 'fileName', 'file_name', 'name'));
    const filePath = text(valueOf(row, 'filePath', 'file_path', 'downloadUrl', 'fileUrl', 'publicUrl', 'url'));
    const link = weightRemoteLink(row);
    const platform = text(valueOf(row, 'computePlatformName', 'compute_platform_name', 'computePlatformId', 'compute_platform_id'));
    const chip = text(valueOf(row, 'chipCode', 'chip_code'));
    const id = text(weightIdentity(row));
    return `<div class="cldb-weight">
      <div><b>${esc(fileName)}</b><span>ID ${esc(id)}</span></div>
      <div><span>算力环境</span><b>${esc(platform)}</b></div>
      <div><span>芯片</span><b>${esc(chip)}</b></div>
      <div class="cldb-weight-path"><span>文件地址</span><code title="${esc(filePath)}">${esc(filePath)}</code></div>
      <div class="cldb-weight-link">${link ? `<a class="btn mini" href="${esc(link)}" target="_blank" rel="noopener noreferrer">下载 / 打开</a>` : '<span class="cldb-muted">未返回可直接访问链接</span>'}</div>
    </div>`;
  }

  function versionHtml(row) {
    const versionId = versionIdentity(row);
    const versionName = text(valueOf(row, 'versionName', 'version_name', 'name'), '未命名版本');
    const versionNo = text(valueOf(row, 'versionNo', 'version_no'));
    const analysisId = text(valueOf(row, 'analysisId', 'analysis_id'));
    const status = text(valueOf(row, 'status', 'versionStatus', 'version_status'));
    const weights = row.weights || [];
    return `<section class="cldb-version">
      <header>
        <div><b>${esc(versionName)}</b><span>版本号 ${esc(versionNo)} · ID ${esc(versionId)}</span></div>
        <div class="cldb-version-meta"><span>分析方式 ${esc(analysisId)}</span><em>${esc(status)}</em><strong>${weights.length} 个权重/转换结果</strong></div>
      </header>
      <div class="cldb-weights">${weights.map(weightHtml).join('') || '<div class="cldb-empty compact">该版本未返回权重/转换结果</div>'}</div>
    </section>`;
  }

  function productHtml(row) {
    const productId = productIdentity(row);
    const name = text(valueOf(row, 'productName', 'product_name', 'name'), '未命名算法产品');
    const code = text(valueOf(row, 'productCode', 'product_code', 'code'));
    const category = text(valueOf(row, 'categoryName', 'category_name', 'categoryId', 'category_id'));
    const status = String(valueOf(row, 'status')).trim();
    const versions = row.versions || [];
    const weightCount = versions.reduce((sum, version) => sum + (version.weights?.length || 0), 0);
    return `<details class="cldb-product">
      <summary>
        <div class="cldb-product-name"><span class="cldb-product-mark">CL</span><div><b>${esc(name)}</b><small>${esc(code)} · ID ${esc(productId)}</small></div></div>
        <div class="cldb-product-facts"><span>品目 <b>${esc(category)}</b></span><span>状态 <b>${esc(status || '-')}</b></span><span>版本 <b>${versions.length}</b></span><span>权重/转换 <b>${weightCount}</b></span></div>
        <i>⌄</i>
      </summary>
      <div class="cldb-product-body">
        <div class="cldb-product-raw"><span>远端产品 ID</span><code>${esc(productId)}</code><span>产品类型</span><code>${esc(text(valueOf(row, 'productType', 'product_type')))}</code></div>
        <div class="cldb-versions">${versions.map(versionHtml).join('') || '<div class="cldb-empty compact">该算法产品未返回版本</div>'}</div>
      </div>
    </details>`;
  }

  function render() {
    if (destroyed || !doc) return false;
    const state = getState?.() || {};
    if (String(state.page || '') !== PAGE) return false;
    const view = doc.getElementById?.('view');
    if (!view) return false;
    const summary = counts();
    const status = snapshot.loading
      ? '正在从畅联云读取'
      : snapshot.loaded
        ? `上次手动刷新：${new Date(snapshot.loadedAt).toLocaleString()}`
        : '尚未读取远端数据';
    view.innerHTML = `<section class="cldb-shell" data-changlian-data-browser="1">
      <header class="cldb-hero">
        <div><span class="cldb-eyebrow">CHANG LIAN REMOTE DATA</span><h2>畅联云数据</h2><p>只读查看畅联云算法产品、算法版本以及版本下权重/转换结果。进入页面不会自动请求，只有手动刷新才访问畅联云。</p></div>
        <button class="btn primary" data-cldb-refresh ${snapshot.loading ? 'disabled' : ''}>${snapshot.loading ? '正在读取…' : '手动刷新畅联云'}</button>
      </header>
      <div class="cldb-summary">
        <div><span>算法产品</span><b>${summary.products}</b></div>
        <div><span>算法版本</span><b>${summary.versions}</b></div>
        <div><span>权重 / 转换结果</span><b>${summary.weights}</b></div>
        <div><span>读取状态</span><b class="small">${esc(status)}</b></div>
      </div>
      ${snapshot.error ? `<div class="cldb-error"><b>读取失败</b><span>${esc(snapshot.error)}</span></div>` : ''}
      <div class="cldb-note"><b>只读模式</b><span>本页面不会新增、修改、删除畅联云数据，也不会触发现有主数据同步；下载地址直接采用畅联云接口返回的文件地址。</span></div>
      <div class="cldb-list">
        ${snapshot.loaded
          ? snapshot.products.map(productHtml).join('') || '<div class="cldb-empty"><b>畅联云未返回算法产品</b><span>请确认远端数据库中存在 productType=3 的算法产品。</span></div>'
          : '<div class="cldb-empty"><b>点击“手动刷新畅联云”读取数据</b><span>页面不会自动读取远端数据库。</span></div>'}
      </div>
    </section>`;
    const button = view.querySelector?.('[data-cldb-refresh]');
    button?.addEventListener?.('click', () => {
      void refresh().catch(error => notify?.(error?.message || error));
    });
    return true;
  }

  async function refresh() {
    if (destroyed) throw new Error('畅联云数据浏览器已销毁');
    if (refreshPromise) return refreshPromise;
    const epoch = ++refreshEpoch;
    snapshot = {...snapshot, loading: true, error: ''};
    render();
    refreshPromise = (async () => {
      const [enabledRaw, disabledRaw] = await Promise.all([
        request(`${BASE}/products?status=1`),
        request(`${BASE}/products?status=0`),
      ]);
      const products = mergeProducts(providerItems(enabledRaw), providerItems(disabledRaw));
      const hydrated = await mapLimit(products, 4, async product => {
        const productId = productIdentity(product);
        if (!productId) return {...product, versions: []};
        const versionsRaw = await request(`${BASE}/versions/by-product/${encodeURIComponent(productId)}`);
        const versions = providerItems(versionsRaw);
        const hydratedVersions = await mapLimit(versions, 4, async version => {
          const versionId = versionIdentity(version);
          if (!versionId) return {...version, weights: []};
          const weightsRaw = await request(`${BASE}/weights/by-version/${encodeURIComponent(versionId)}`);
          return {...version, weights: providerItems(weightsRaw)};
        });
        return {...product, versions: hydratedVersions};
      });
      if (destroyed || epoch !== refreshEpoch) return snapshot;
      snapshot = {loaded: true, loading: false, loadedAt: new Date().toISOString(), products: hydrated, error: ''};
      render();
      notify?.(`已读取畅联云：${hydrated.length} 个算法产品`);
      return snapshot;
    })().catch(error => {
      if (!destroyed && epoch === refreshEpoch) {
        snapshot = {...snapshot, loading: false, error: String(error?.message || error || '读取失败')};
        render();
      }
      throw error;
    }).finally(() => {
      refreshPromise = null;
    });
    return refreshPromise;
  }

  const runtime = {
    build: 'changlian-data-browser-63001',
    page: PAGE,
    render,
    refresh,
    snapshot: () => snapshot,
    destroy() {
      destroyed = true;
      refreshEpoch += 1;
    },
  };
  const host = globalThis.window || globalThis;
  host.ChangLianDataBrowserRuntime = runtime;
  return runtime;
}
