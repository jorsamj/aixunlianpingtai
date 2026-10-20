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
  rockchip: {mark: 'RK', scene: 'RKNN 转换', note: '芯片字典包含 RK3568 / RK3576 / RK3578 等可绑定身份；具体可转换能力和实际芯片以转换运行时及产物为准。'},
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

export function localChipKey(value) {
  return String(value || '').replace(/[^A-Za-z0-9]/g, '').toUpperCase();
}

export function publicationWeightDetails(status={}) {
  const names={SYNCED:'补充信息已同步',PENDING:'可同步已确定的补充信息',UNKNOWN:'结果未知 · 需要人工核对',CONFLICT:'标签来源冲突 · 需要人工核对'};
  const rows=status.artifacts||status.discovered||[];
  return `<details open data-weight-publication-details style="grid-column:1/-1;min-width:0"><summary>权重发布状态</summary><div style="overflow:auto"><table class="table"><thead><tr><th>权重 / 算力 / 芯片</th><th>登记与元数据</th><th>模型事实</th></tr></thead><tbody>${rows.map(row=>{
    const meta=row.metadata||row.weight_metadata||{};
    const tagsText=value=>Array.isArray(value)?`${value.length} 类 · ${value.join(', ')||'[]'}`:'未记录';
    const pending=row.remote_registered&&Array.isArray(row.prepared_tags)&&JSON.stringify(row.prepared_tags)!==JSON.stringify(row.confirmed_tags);
    const tagsFacts=`冻结类别：${escapeHtml(tagsText(row.frozen_tags))}<br>本地类别：${escapeHtml(tagsText(row.local_tags??meta.tags))}<br>准备提交：${escapeHtml(tagsText(row.prepared_tags))}<br>已确认提交：${escapeHtml(tagsText(row.confirmed_tags))}<br>${row.remote_tags_status==='READ_BACK'?`远端读回：${escapeHtml(tagsText(row.remote_tags))} ${escapeHtml(row.remote_tags_checked_at||'')}`:row.remote_tags_status==='NOT_RETURNED'?'远端未返回 tags（不能视为读回验证）':'远端 tags 未读回验证'}${pending?'<br>标签补齐待处理':''}`;
    const delivery=row.sync_status==='SYNCED'?'同步成功':row.remote_registered?'已登记 · 待确认':'尚未登记';
    return `<tr><td>${escapeHtml(row.file_name||row.target)}<br>${escapeHtml(row.compute_platform_id||'未配置')} / ${escapeHtml(row.remote_chip_code||row.mapped_chip_code||row.chip_code||'通用')}</td><td>${delivery}<br>${escapeHtml(names[row.metadata_sync_status]||'待同步')}<br>${escapeHtml(row.metadata_note||'')}<br>${escapeHtml(row.last_error||'')}<br>${tagsFacts}</td><td>宽 ${escapeHtml(meta.image_width??'未记录')} / 高 ${escapeHtml(meta.image_height??'未记录')} · ${escapeHtml(meta.yolo_version||'YOLO型号未记录')}<br>${escapeHtml(row.size_bytes??'未知')} bytes<br><code style="overflow-wrap:anywhere">${escapeHtml(row.sha256||'SHA256未记录')}</code><br>类别：${escapeHtml(Array.isArray(meta.tags)?meta.tags.join(', '):'未记录')}</td></tr>`;
  }).join('')}</tbody></table></div><small>转换产物登记与目标硬件验证分别记录，登记成功不表示实机验证通过。</small></details>`;
}

export function publicationResultMessage(result={}) {
  if(result.publication?.status==='PARTIAL'||result.conversion_failures?.length)
    return '部分权重尚未完整同步，请查看权重发布状态中的具体原因';
  if(result.deferred_conversions?.length)return '原始模型已同步；部分转换权重等待配置，请查看发布状态';
  return '模型版本和转换产物已同步到新畅联';
}

export function computePlatformTreeRows(platforms = []) {
  const byId = new Map();
  for (const item of platforms) {
    const id = String(item.computePlatformId ?? item.id ?? '').trim();
    if (!id || byId.has(id)) continue;
    byId.set(id, {
      id,
      name: String(item.computePlatformName || item.name || id),
      code: String(item.computePlatformCode || item.code || ''),
      parentId: String(item.parentId ?? '').trim().replace(/^(0|-1)$/, ''),
      deleted: item.delFlag != null && String(item.delFlag) !== '0',
    });
  }
  return [...byId.values()].map(node => {
    const ancestors = [];
    const names = [node.name];
    const seen = new Set([node.id]);
    let parent = node.parentId;
    let active = !node.deleted;
    while (parent && byId.has(parent) && !seen.has(parent)) {
      const item = byId.get(parent);
      ancestors.unshift(parent);
      names.unshift(item.name);
      active = active && !item.deleted;
      seen.add(parent);
      parent = item.parentId;
    }
    if (parent && (seen.has(parent) || !byId.has(parent))) active = false;
    return {...node, ancestorIds: ancestors, path: names.join(' / '), active};
  }).sort((a, b) => a.path.localeCompare(b.path, 'zh-CN'));
}

export function childPlatformChoices(platforms = [], parentId = '') {
  const parent = String(parentId || '');
  return computePlatformTreeRows(platforms).filter(row => row.active && row.ancestorIds.includes(parent));
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
      chip_mappings: {...(mappings[key]?.chip_mappings || {})},
      enabled: mappings[key]?.enabled !== false,
    }])),
    storageSources: Array.isArray(body.storage_sources) ? body.storage_sources : [],
    computePlatforms: Array.isArray(body.compute_platforms) ? body.compute_platforms : [],
    chipDictionary: body.chip_dictionary && typeof body.chip_dictionary === 'object' ? body.chip_dictionary : {},
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

  function computeOptions(selected = '', {rootsOnly = false} = {}) {
    const rows = computePlatformTreeRows(config?.computePlatforms || []);
    const options = rows.filter(item => item.active && (!rootsOnly || !item.parentId || item.id === selected));
    const stale = selected && !options.some(row => row.id === selected)
      ? `<option value="${escapeHtml(selected)}" selected disabled>原绑定 ID ${escapeHtml(selected)} 已失效，请重新选择</option>` : '';
    return `<option value="">请选择畅联云算力环境</option>${stale}${options.map(row =>
      `<option value="${escapeHtml(row.id)}" data-name="${escapeHtml(row.path)}" data-code="${escapeHtml(row.code)}" ${row.id === selected ? 'selected' : ''}>${escapeHtml(row.path)}${row.code ? ` · ${escapeHtml(row.code)}` : ''} · ID ${escapeHtml(row.id)}</option>`
    ).join('')}`;
  }

  function childOptions(parentId, selected = '') {
    const rows = childPlatformChoices(config?.computePlatforms || [], parentId);
    const stale = selected && !rows.some(row => row.id === selected)
      ? `<option value="${escapeHtml(selected)}" selected disabled>旧绑定 ${escapeHtml(selected)} 不属于当前有效父级，请重新选择</option>` : '';
    return `<option value="">请选择该父级下的子分类</option>${stale}${rows.map(row =>
      `<option value="${escapeHtml(row.id)}" ${row.id === selected ? 'selected' : ''}>${escapeHtml(row.path)} · ID ${escapeHtml(row.id)}</option>`
    ).join('')}`;
  }

  function chipRow(code, remoteId, parentId, removable = false) {
    return `<div class="field" data-publish-chip-row data-local-chip="${escapeHtml(code)}" style="margin-top:8px">
      <label>本地 ${escapeHtml(code)} → 畅联云子分类</label>
      <div style="display:flex;gap:8px;align-items:center">
        <select class="select" data-publish-chip-child style="min-width:0;flex:1">${childOptions(parentId, remoteId)}</select>
        ${removable ? '<button type="button" class="btn small" data-publish-remove-chip>移除</button>' : ''}
      </div>
    </div>`;
  }

  function chipBindingRows(target, row, parentId) {
    const suggestions = config?.chipDictionary?.[target] || [];
    const bound = Object.fromEntries(Object.entries(row.chip_mappings || {})
      .map(([code, id]) => [localChipKey(code), id]));
    const known = new Set(suggestions.map(localChipKey));
    const codes = [...new Set([...suggestions, ...Object.keys(bound)].map(localChipKey).filter(Boolean))];
    return codes.map(code => chipRow(code, bound[code] || '', parentId, !known.has(code))).join('');
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
      const selectedCode = selectedPlatform.computePlatformCode || selectedPlatform.code || '';
      const hasChipOptions = key !== 'original';
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
          <select class="select" data-publish-platform>${computeOptions(selected, {rootsOnly: ['rockchip','sophon'].includes(key)})}</select>
        </div>
        <input type="hidden" data-publish-chip value="${escapeHtml(row.chip_code || '')}">
        ${hasChipOptions ? `<details class="external-vendor-advanced" data-publish-chip-details ${['rockchip','sophon'].includes(key) ? 'open' : ''}>
          <summary>芯片 / 环境子分类绑定${['rockchip','sophon'].includes(key) ? '（必须按实际芯片匹配）' : '（按需配置）'}</summary>
          <div data-publish-chip-rows>${chipBindingRows(key, row, selected)}</div>
          <div style="display:flex;gap:8px;margin-top:10px">
            <input class="input" placeholder="添加本地芯片型号（如 RKxxxx）" data-publish-new-chip style="min-width:0;flex:1">
            <button type="button" class="btn small" data-publish-add-chip>添加绑定</button>
          </div>
        </details>` : ''}
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
          <div class="subline">维护“本地转换目标 → 畅联云父级环境 → 真实芯片对应子分类”的全局映射。发布时按产物真实芯片选取 computePlatformId。</div>
        </div>
        <div class="external-vendor-head-actions">
          <span class="pill ${configured ? 'ok' : 'warn'}">已配置 ${configured} / ${TARGETS.length}</span>
          <button class="btn small" id="externalPublishRefreshPlatforms">↻ 拉取畅联云厂商</button>
        </div>
      </div>
      <div class="panel-body">
        <div class="external-vendor-guide">
          <div><span class="external-vendor-guide-icon">通</span><p><b>通用是特殊映射</b><small>训练刚完成、尚未转换的原始模型没有真实硬件厂商，统一使用“通用”对应的畅联云 ID。</small></p></div>
          <div><span class="external-vendor-guide-icon">厂</span><p><b>转换结果按厂商分流</b><small>RKNN 走瑞芯微，TensorRT 走 NVIDIA，Ascend 走华为；具体芯片型号只读取真实转换产物，不能用父分类或名称代替。</small></p></div>
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
      const chipMappings = {};
      for (const item of row.querySelectorAll('[data-publish-chip-row]')) {
        const code = localChipKey(item.dataset.localChip);
        const chosen = item.querySelector('[data-publish-chip-child]')?.value || '';
        if (code && chosen) chipMappings[code] = chosen;
      }
      mappings[key] = {
        enabled: key === 'original' ? true : Boolean(row.querySelector('[data-publish-enabled]')?.checked),
        compute_platform_id: row.querySelector('[data-publish-platform]')?.value || '',
        chip_code: row.querySelector('[data-publish-chip]')?.value.trim() || '',
        chip_mappings: chipMappings,
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
    config = {...config, ...normalizePublishConfig({config: body.config, storage_sources: config?.storageSources, compute_platforms: config?.computePlatforms, chip_dictionary: config?.chipDictionary})};
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
        const panel = document.querySelector('[data-external-publish-panel="1"]');
        if (panel) {
          panel.outerHTML = panelHtml();
          bindPanel();
        }
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
      const syncMeta = () => {
        const option = select?.selectedOptions?.[0];
        const id = String(select?.value || '');
        const name = String(option?.dataset?.name || '');
        const code = String(option?.dataset?.code || '');
        const idNode = row.querySelector('[data-vendor-id]');
        const codeNode = row.querySelector('[data-vendor-code]');
        const nameNode = row.querySelector('[data-vendor-name]');
        if (idNode) idNode.textContent = id || '未配置';
        if (codeNode) codeNode.textContent = code || '-';
        if (nameNode) nameNode.textContent = name || '尚未关联';
        for (const child of row.querySelectorAll('[data-publish-chip-child]')) {
          const previous = child.value;
          child.innerHTML = childOptions(id, previous);
          if (!child.querySelector('option:checked')) child.value = '';
        }
      };
      if (select) select.onchange = syncMeta;
      if (enabled) enabled.onchange = () => row.classList.toggle('disabled', !enabled.checked);
      const add = row.querySelector('[data-publish-add-chip]');
      if (add) add.onclick = () => {
        const input = row.querySelector('[data-publish-new-chip]');
        const code = localChipKey(input?.value);
        if (!/^[A-Z0-9]{2,64}$/.test(code)) return notify?.('请填写有效的芯片型号或环境编号');
        if ([...row.querySelectorAll('[data-publish-chip-row]')].some(node => localChipKey(node.dataset.localChip) === code)) {
          return notify?.('该型号已在当前转换环境中列出');
        }
        row.querySelector('[data-publish-chip-rows]')?.insertAdjacentHTML('beforeend',
          chipRow(code, '', select?.value || '', true));
        if (input) input.value = '';
      };
      row.onclick = event => {
        if (event.target.closest('[data-publish-remove-chip]')) {
          event.target.closest('[data-publish-chip-row]')?.remove();
        }
      };
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
    const current=()=>currentProjectId()===pid&&String(state().page||'')==='算法列表';
    const showStatus=status=>{
      if(!current())return;
      const owner=[...document.querySelectorAll('[data-external-publish-action]')]
        .find(node=>node.dataset.externalPublishAction===`${algorithmId}:${versionId}`)||button;
      const row=owner?.isConnected?owner.closest('.alg428-version-row'):null;
      if(!row)return;
      row.querySelector('[data-weight-publication-details]')?.remove();
      row.insertAdjacentHTML('beforeend',publicationWeightDetails(status));
    };
    try {
      const status = await requestJson(
        `${API_ROOT}/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(algorithmId)}/versions/${encodeURIComponent(versionId)}`
      );
      if(!current())return;
      showStatus(status);
      if(status.publication?.status==='PUBLISHED'&&status.requires_sync===false)return;
      const preflight = publicationPreflight(status);
      if (!preflight.ready) {
        notify?.(preflight.message);
        return;
      }
      notify?.(preflight.message);
      if (button) button.textContent = '正在同步…';
      const result=await requestJson(`${API_ROOT}/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(algorithmId)}/versions/${encodeURIComponent(versionId)}/publish`, {method: 'POST'});
      if(!current())return;
      notify?.(publicationResultMessage(result));
      await algorithmListRuntime?.refresh?.({render: true});
      if(!current())return;
      showStatus(await requestJson(`${API_ROOT}/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(algorithmId)}/versions/${encodeURIComponent(versionId)}`));
    } catch (error) {
      if(!current())return;
      notify?.(error?.message || error);
      await algorithmListRuntime?.refresh?.({render: true});
      if(current()){
        try{showStatus(await requestJson(`${API_ROOT}/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(algorithmId)}/versions/${encodeURIComponent(versionId)}`));}catch(_){/* original error remains visible */}
      }
    } finally {
      if (button?.isConnected) {
        const {version} = versionFromIds(algorithmId, versionId);
        button.disabled = false;
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
