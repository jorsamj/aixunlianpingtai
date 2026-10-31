import {withRequestDeadline} from './api.js?v=20261021s';

const API_ROOT = '/api/v64/external-publish';
const PLATFORM_PAGE = '平台对接';
const TARGETS = [['original','通用原始模型'],['onnx','通用 ONNX'],['paddle_inference','Paddle Inference']];

function rawFetch() {
  const scoped = window.fetch;
  return scoped?.__pageRequestScopeOriginal || scoped;
}

async function requestJson(url, options = {}) {
  return withRequestDeadline(async signal => {
  const response = await rawFetch()(url, {
    headers: {'Accept': 'application/json', ...(options.headers || {})},
    ...options, signal,
  });
  const text = await response.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch (_) { body = {detail: text}; }
  if (!response.ok) {
    throw Object.assign(new Error(String(body.message || body.detail || `请求失败（HTTP ${response.status}）`)), {httpStatus: response.status});
  }
  return body;
  }, {label: '发布接口'});
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
  return `<details open data-weight-publication-details style="grid-column:1/-1;min-width:0"><summary>权重发布状态 · Version ${escapeHtml(status.publication?.status||'未登记')} / Weight ${escapeHtml(status.weight_delivery_status||status.publication?.status||'待核验')}</summary><div style="overflow:auto"><table class="table"><thead><tr><th>权重 / 算力 / 芯片</th><th>登记与元数据</th><th>模型事实</th></tr></thead><tbody>${rows.map(row=>{
    const meta=row.metadata||row.weight_metadata||{};
    const tagsText=value=>Array.isArray(value)?`${value.length} 类 · ${value.join(', ')||'[]'}`:'未记录';
    const pending=row.remote_registered&&Array.isArray(row.prepared_tags)&&JSON.stringify(row.prepared_tags)!==JSON.stringify(row.confirmed_tags);
    const tagsFacts=`冻结类别：${escapeHtml(tagsText(row.frozen_tags))}<br>本地类别：${escapeHtml(tagsText(row.local_tags??meta.tags))}<br>准备提交：${escapeHtml(tagsText(row.prepared_tags))}<br>HTTP 请求记录：${escapeHtml(tagsText(row.request_tags))}（${escapeHtml(row.request_status||'无记录')}）<br>已确认提交：${escapeHtml(tagsText(row.confirmed_tags))}<br>${row.remote_tags_status==='READ_BACK'?`远端读回：${escapeHtml(tagsText(row.remote_tags))} ${escapeHtml(row.remote_tags_checked_at||'')}`:row.remote_tags_status==='NOT_RETURNED'?'远端未返回 tags（不能视为读回验证）':'远端 tags 未读回验证'}${pending?'<br>标签补齐待处理':''}`;
    const plan=row.recovery_plan||{};
    const review=row.review_required?`<br>自动发布异常，请管理员核对：${escapeHtml(plan.reason||row.last_error||'远端身份未确认')}<br>建议 ${escapeHtml(plan.suggested_operation||'READ_ONLY_RECOVERY')}<br>目标分类 ${escapeHtml(plan.target_compute_platform_id||'未确认')}<br>原Weight ${escapeHtml(plan.old_weight_id||'未确认')}`:'';
    const role=({HISTORICAL:'历史成果',AUTOMATIC_CURRENT:'自动当前交付',CONFIRMED_OWNER:'当前交付',SINGLE_CANDIDATE:'自动交付候选'})[row.delivery_role]||row.delivery_role||'待核验';
    const readback=row.remote_identity_status==='READ_BACK'?'远端读回已确认':row.remote_identity_status==='HISTORICAL_RECEIPT'?'历史登记回执（已被当前成果取代）':'远端身份未读回验证';
    const facts=`Artifact ${escapeHtml(row.artifact_id||'未登记')}<br>Weight ${escapeHtml(row.external_weight_id||'未确认')}<br>OSS ${escapeHtml(row.storage_status||'未登记')}<br>登记状态 ${escapeHtml(row.sync_status||'PENDING')}<br>交付角色 ${escapeHtml(role)}<br>${readback}${review}`;
    const delivery=row.delivery_role==='HISTORICAL'?'历史成果':row.sync_status==='SYNCED'?'同步成功':row.remote_registered?'已登记 · 待确认':'尚未登记';
    return `<tr><td>${escapeHtml(row.file_name||row.target)}<br>${escapeHtml(row.compute_platform_id||'未配置')} / ${escapeHtml(row.remote_chip_code||row.mapped_chip_code||row.chip_code||'通用')}</td><td>${delivery}<br>${facts}<br>${escapeHtml(names[row.metadata_sync_status]||'待同步')}<br>${escapeHtml(row.metadata_note||'')}${meta.execution_evidence_note?`<br>${escapeHtml(meta.execution_evidence_note)}`:''}<br>${escapeHtml(row.last_error||'')}<br><details><summary>类别与同步证据</summary>${tagsFacts}</details></td><td>宽 ${escapeHtml(meta.image_width??'未记录')} / 高 ${escapeHtml(meta.image_height??'未记录')} · ${escapeHtml(meta.yolo_version||'YOLO型号未记录')}<br>${escapeHtml(row.size_bytes??'未知')} bytes<br><code style="overflow-wrap:anywhere">${escapeHtml(row.sha256||'SHA256未记录')}</code><br>类别：${escapeHtml(Array.isArray(meta.tags)?meta.tags.join(', '):'未记录')}</td></tr>`;
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
    targetMappings: Object.fromEntries([...new Set([...TARGETS.map(([key])=>key),...Object.keys(mappings)])].map(key=>[key,{
      ...mappings[key],compute_platform_id:mappings[key]?.compute_platform_id||'',chip_code:mappings[key]?.chip_code||'',chip_mappings:{...(mappings[key]?.chip_mappings||{})},enabled:mappings[key]?.enabled!==false,
    }])),
    mappingRevision: Number(config.mapping_revision||0),
    mappingHistory: Array.isArray(config.mapping_history)?config.mapping_history:[],
    localCatalog: body.local_catalog||{revision:0,vendors:[],chips:[]},
    mappingDiagnostics: body.mapping_diagnostics||{vendors:{},legacy_proposals:[]},
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
  let loadPromise=null,draft=null,draftRevision=0,dirty=false,replaceMappings=false,saving=false;
  let mutationQueued = false;

  function currentProjectId() {
    return String(projectId?.() || '');
  }

  async function loadConfig({silent=false}={}) {
    if(loadPromise)return loadPromise;
    loadPromise=requestJson(`${API_ROOT}/config`).then(body=>{
      const incoming=normalizePublishConfig(body);
      if(config&&incoming.mappingRevision<config.mappingRevision)return config;
      config=incoming;
      if(!dirty){draft=structuredClone(config.targetMappings);draftRevision=config.mappingRevision}
      return config;
    }).catch(error=>{if(!silent&&String(state().page||'')===PLATFORM_PAGE)notify?.(error.message||error);throw error}).finally(()=>{loadPromise=null});
    return loadPromise;
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

  function childOptions(parentId,selected='') {
    const rows=childPlatformChoices(config?.computePlatforms||[],parentId).filter(row=>!computePlatformTreeRows(config?.computePlatforms||[]).some(item=>item.parentId===row.id));
    const stale=selected&&!rows.some(row=>row.id===selected)?`<option value="${escapeHtml(selected)}" selected data-invalid="1">旧绑定 ${escapeHtml(selected)} 不属于当前有效父级，请重新选择</option>`:'';
    return `<option value="">尚未绑定</option>${stale}${rows.map(row=>`<option value="${escapeHtml(row.id)}" ${row.id===selected?'selected':''}>${escapeHtml(row.path)} · ID ${escapeHtml(row.id)}</option>`).join('')}`;
  }
  function mappingRows() {
    return TARGETS.map(([key,label])=>{
      const row=draft?.[key]||{},selected=String(row.compute_platform_id||'');
      return `<article class="external-vendor-card" data-publish-target="${key}"><div class="row between"><b>${label}</b>${key==='original'?'<span class="pill ok">必配</span>':`<label><input data-publish-enabled type="checkbox" ${row.enabled!==false?'checked':''}> 启用发布</label>`}</div>${key==='original'?'<p>通用是特殊映射：训练刚完成、尚未转换的原始模型保留独立映射。</p>':''}<label class="field"><span>畅联云算力环境</span><select class="select" data-publish-platform>${computeOptions(selected)}</select></label><input type="hidden" data-publish-chip value="${escapeHtml(row.chip_code||'')}"></article>`;
    }).join('');
  }
  function hardwareRows() {
    const catalog=config?.localCatalog||{vendors:[],chips:[]};
    return catalog.vendors.map(vendor=>{
      const key='vendor:'+vendor.id,row=draft?.[key]||{},parent=String(row.compute_platform_id||''),enabled=vendor.enabled!==false;
      const chips=catalog.chips.filter(chip=>chip.vendor_id===vendor.id),known=new Set(chips.map(chip=>chip.id));
      const diagnostic=config?.mappingDiagnostics?.vendors?.[vendor.id]||{};
      const proposals=(config?.mappingDiagnostics?.legacy_proposals||[]).filter(item=>item.local_vendor_id===vendor.id);
      return `<details class="external-vendor-card external-stable-vendor" data-publish-target="${escapeHtml(key)}" data-local-vendor="${escapeHtml(vendor.id)}"><summary><div><b>${escapeHtml(vendor.name)}</b><small>本地 ID ${escapeHtml(vendor.id)} · SDK ${escapeHtml(vendor.template_id||'待适配')}</small></div><span class="pill ${diagnostic.status==='BOUND'?'ok':'warn'}">${!enabled?'本地已停用':escapeHtml(diagnostic.reason||'待绑定')}</span></summary><div class="external-stable-body"><div class="form two"><label class="field"><span>新畅联厂商 / 父级分类</span><select class="select" data-publish-platform ${enabled?'':'disabled'}>${computeOptions(parent,{rootsOnly:true})}</select></label><label class="field"><span>外部发布</span><span><input type="checkbox" data-publish-enabled ${row.enabled!==false?'checked':''} ${enabled?'':'disabled'}> 启用该厂商发布</span></label></div><small>本地与远端稳定 ID 绑定；修改映射不会自动迁移已有 Weight。</small><div class="table-wrap"><table class="table"><thead><tr><th>本地芯片 / ID</th><th>SDK 目标编码</th><th>新畅联具体芯片 / ID</th><th>本地状态</th></tr></thead><tbody>${chips.map(chip=>`<tr data-publish-chip-row data-local-chip="${escapeHtml(chip.id)}"><td><b>${escapeHtml(chip.name)}</b><small>${escapeHtml(chip.id)}</small></td><td><code>${escapeHtml(chip.sdk_code||'待适配')}</code></td><td><select class="select" data-publish-chip-child ${enabled&&chip.enabled!==false?'':'disabled'}>${childOptions(parent,row.chip_mappings?.[chip.id]||'')}</select></td><td>${chip.enabled===false?'已停用 · 历史绑定保留':'已启用'}</td></tr>`).join('')||'<tr><td colspan="4">本地字典尚无芯片，请在部署资源中管理。</td></tr>'}${Object.entries(row.chip_mappings||{}).filter(([id])=>!known.has(id)).map(([id,remote])=>`<tr><td>历史芯片 ID ${escapeHtml(id)}</td><td>本地记录缺失</td><td>${escapeHtml(remote)}</td><td>需核对，保留原绑定</td></tr>`).join('')}</tbody></table></div>${proposals.map(proposal=>`<div class="external-mapping-migration"><span>旧 ${escapeHtml(proposal.legacy_target)} 映射：${escapeHtml(proposal.reason)}</span>${proposal.status==='READY'?`<button class="btn mini" data-mapping-adopt="${escapeHtml(vendor.id)}">采用已核验旧绑定为草稿</button>`:'<span class="pill warn">归属待人工确认</span>'}</div>`).join('')}</div></details>`;
    }).join('')||'<div class="empty">本地尚无厂商，请先在“部署资源 → 厂商与芯片管理”登记。通用模型仍可独立发布。</div>';
  }
  function panelHtml() {
    return `<section class="panel external-vendor-panel" data-platform-tab-panel="vendor" data-external-publish-panel="1"><header class="panel-head external-vendor-panel-head"><div><div class="panel-title">厂商对应表</div><div class="subline">本地稳定厂商 / 芯片 → 新畅联真实分类。算力环境来自最近一次新畅联主数据同步。</div></div><button class="btn small" id="externalPublishRefreshPlatforms">拉取畅联云厂商</button></header><div class="panel-body"><h3>通用交付映射</h3><div class="external-vendor-grid">${mappingRows()}</div><h3>硬件厂商映射</h3><p class="subline">芯片绑定身份读取本地字典；可转换能力和实际芯片以SDK检测及真实产物为准。</p><div class="external-stable-vendors">${hardwareRows()}</div>${Object.keys(draft||{}).filter(key=>key.startsWith('vendor:')&&!config?.localCatalog?.vendors?.some(row=>'vendor:'+row.id===key)).map(key=>`<div class="external-mapping-migration">历史厂商 ${escapeHtml(key)} 本地记录缺失，原绑定只读保留。</div>`).join('')}<details class="external-vendor-advanced"><summary>高级操作</summary><div class="subline">创建、查询和删除均使用新畅联官方 OpenAPI 固定路径，不允许前端修改。官方同步接口：${escapeHtml(config?.versionListByProduct)} / ${escapeHtml(config?.weightListByVersion)}</div><h4>旧配置及回退证据</h4><pre>${escapeHtml(JSON.stringify(config?.targetMappings||{},null,2))}</pre>${config?.mappingHistory?.length?'<button class="btn" data-mapping-restore>恢复上一版映射为草稿</button>':''}<p>回退仅恢复本地配置草稿，仍需核验并保存；不会执行远端Weight迁移。</p><div data-external-publish-automation="1"><button class="btn" id="externalPublishAutoRun">立即检查待同步结果</button></div></details><div class="external-vendor-savebar"><span data-mapping-dirty>${dirty?(draftRevision!==config?.mappingRevision?'配置已被其他操作更新，请重新核对草稿':'存在未保存草稿'):'按稳定 ID 保存；已有 Weight 改挂会进入复核。'}</span><button class="btn" data-mapping-discard>重新读取并放弃草稿</button><button class="btn primary" id="externalPublishSave">保存厂商对应表</button></div></div></section>`;
  }
  function collectConfig() {
    const mappings=structuredClone(draft||{});
    for(const row of document.querySelectorAll('[data-external-publish-panel="1"] [data-publish-target]')){
      const key=row.dataset.publishTarget,previous=mappings[key]||{},chipMappings={...(previous.chip_mappings||{})};
      for(const item of row.querySelectorAll('[data-publish-chip-row]')){
        const select=item.querySelector('[data-publish-chip-child]');if(select?.disabled)continue;
        if(select?.value)chipMappings[item.dataset.localChip]=select.value;else delete chipMappings[item.dataset.localChip];
      }
      if(row.dataset.localVendor&&!Object.hasOwn(mappings,key)&&!row.querySelector('[data-publish-platform]')?.value&&!Object.keys(chipMappings).length)continue;
      mappings[key]={...previous,enabled: key === 'original' ? true : Boolean(row.querySelector('[data-publish-enabled]')?.checked),compute_platform_id:row.querySelector('[data-publish-platform]')?.value||'',chip_code:row.querySelector('[data-publish-chip]')?.value||previous.chip_code||'',chip_mappings: chipMappings,...(row.dataset.localVendor?{local_vendor_id:row.dataset.localVendor}:{})};
    }
    return {storage_source_id: '',public_base_url: '',publish_original_model:true,target_mappings:mappings,expected_revision:draftRevision,expected_catalog_revision:config?.localCatalog?.revision,replace_target_mappings:replaceMappings,version_list_by_product: '/internal/algorithm/algorithm-version/listByProduct/{productId}',weight_list_by_version: '/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}'}; // ModelArtifactRuntime is the single owner of model asset storage.
  }
  function updateDraft() {
    draft=collectConfig().target_mappings;dirty=true;
    const note=document.querySelector('[data-mapping-dirty]');if(note)note.textContent=draftRevision!==config?.mappingRevision?'配置已被其他操作更新，请重新核对草稿':'存在未保存草稿';
    refreshOccupiedOptions();
  }
  function refreshOccupiedOptions(){
    const owners=new Map();
    for(const [key,row] of Object.entries(draft||{}))if(key.startsWith('vendor:')&&row.enabled!==false){for(const value of [row.compute_platform_id,...Object.values(row.chip_mappings||{})])if(value)owners.set(value,[...(owners.get(value)||[]),key])}
    for(const row of document.querySelectorAll('[data-local-vendor]'))for(const option of row.querySelectorAll('option[value]')){
      const used=owners.get(option.value)||[],conflict=used.some(key=>key!==row.dataset.publishTarget);
      option.disabled=Boolean(option.dataset.invalid||conflict&&option.value!==option.parentElement.value);option.title=conflict?'已被其他有效绑定占用':'';
    }
  }
  function repaintPanel(panel){
    if(String(state().page||'')!==PLATFORM_PAGE||!panel?.isConnected)return;
    panel.outerHTML=panelHtml();bindPanel();
  }
  async function saveConfig(){
    if(saving)return;
    const panel=document.querySelector('[data-external-publish-panel="1"]'),payload=collectConfig(),controls=[...(panel?.querySelectorAll('input,select,button')||[])].map(node=>[node,node.disabled]);
    saving=true;for(const [node] of controls)node.disabled=true;
    try{
      const body=await requestJson(`${API_ROOT}/config`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      config={...config,...normalizePublishConfig({config:body.config,storage_sources:config?.storageSources,compute_platforms:config?.computePlatforms,chip_dictionary: config?.chipDictionary,local_catalog:config?.localCatalog,mapping_diagnostics:config?.mappingDiagnostics})};
      dirty=false;replaceMappings=false;draft=structuredClone(config.targetMappings);draftRevision=config.mappingRevision;
      let message='厂商与芯片映射已保存';
      try{await loadConfig({silent:true})}catch(error){message=`映射已保存，状态刷新失败：${error.message}`}
      if(String(state().page||'')===PLATFORM_PAGE)notify?.(message);
    }catch(error){if(String(state().page||'')===PLATFORM_PAGE)notify?.(error.message||error)}finally{saving=false;for(const [node,disabled] of controls)if(node.isConnected)node.disabled=disabled;const active=document.querySelector('[data-external-publish-panel="1"]');repaintPanel(active)}
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

  function bindPanel(){
    const panel=document.querySelector('[data-external-publish-panel="1"]');if(!panel)return;
    panel.onchange=event=>{
      const row=event.target.closest('[data-publish-target]');if(!row)return;
      if(event.target.matches('[data-publish-platform]'))for(const child of row.querySelectorAll('[data-publish-chip-child]'))child.innerHTML=childOptions(event.target.value,child.value);
      updateDraft();
    };
    panel.onclick=event=>{
      const button=event.target.closest('button');if(!button||button.disabled)return;
      const fail=error=>{if(panel.isConnected&&String(state().page||'')===PLATFORM_PAGE)notify?.(error.message||error)};
      if(button.id==='externalPublishSave'){void saveConfig().catch(fail);return}
      if(button.id==='externalPublishAutoRun'){void runAutoOnce().catch(fail);return}
      if(button.hasAttribute('data-mapping-adopt')){
        const proposal=config.mappingDiagnostics.legacy_proposals.find(row=>row.local_vendor_id===button.dataset.mappingAdopt&&row.status==='READY');
        if(proposal){draft['vendor:'+proposal.local_vendor_id]=structuredClone(proposal.mapping);dirty=true;repaintPanel(panel)}return;
      }
      if(button.hasAttribute('data-mapping-restore')){draft=structuredClone(config.mappingHistory.at(-1).target_mappings);draftRevision=config.mappingRevision;dirty=true;replaceMappings=true;repaintPanel(panel);return}
      if(button.hasAttribute('data-mapping-discard')||button.id==='externalPublishRefreshPlatforms'){
        button.disabled=true;
        void(async()=>{
          if(button.hasAttribute('data-mapping-discard'))dirty=false;
          else await window.ExternalAlgorithmPlatformRuntime?.syncNow?.();
          await loadConfig({silent:true});repaintPanel(panel);
        })().catch(fail).finally(()=>{if(button.isConnected)button.disabled=false});
      }
    };
    refreshOccupiedOptions();
    if(saving)for(const node of panel.querySelectorAll('input,select,button'))node.disabled=true;
  }

  async function decoratePlatformPage() {
    if (String(state().page || '') !== PLATFORM_PAGE) return;
    const shell = document.querySelector('[data-external-platform-page="1"]');
    if (!shell || shell.querySelector('[data-external-publish-panel="1"]')) return;
    if(!saving&&(!config||!loading)){
      loading=true;
      try{await loadConfig({silent:true})}catch(error){if(shell.isConnected)notify?.(error.message||error);return}finally{loading=false}
    }else if(loadPromise){await loadPromise.catch(()=>{})}
    if(!config||String(state().page||'')!==PLATFORM_PAGE||!shell.isConnected||shell!==document.querySelector('[data-external-platform-page="1"]')||shell.querySelector('[data-external-publish-panel="1"]'))return;
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

  const publicationRequests = new Map();
  async function publishVersion(algorithmId, versionId, button) {
    const pid = currentProjectId();
    if (!pid) return notify?.('当前项目不可用，请刷新页面后重试');
    const key = `${pid}:${algorithmId}:${versionId}`;
    if(publicationRequests.get(key)==='pending')return;
    const queryOnly=publicationRequests.get(key)==='uncertain';
    publicationRequests.set(key,'pending');
    let postStarted=false, postConfirmed=false, outcomeUncertain=queryOnly;
    if (button) { button.disabled = true; button.setAttribute('aria-busy','true'); button.textContent = queryOnly?'正在查询发布结果…':'正在检查…'; }
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
      if(status.publication?.status==='PUBLISHED'&&status.requires_sync===false){outcomeUncertain=false;return;}
      if(queryOnly){notify?.('上次发布结果仍待确认，请核对发布状态；本次仅查询，没有再次提交。');return;}
      const preflight = publicationPreflight(status);
      if (!preflight.ready) {
        notify?.(preflight.message);
        return;
      }
      notify?.(preflight.message);
      if (button) button.textContent = '正在同步…';
      postStarted=true;
      const result=await requestJson(`${API_ROOT}/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(algorithmId)}/versions/${encodeURIComponent(versionId)}/publish`, {method: 'POST'});
      if(!current())return;
      postConfirmed=true;
      notify?.(publicationResultMessage(result));
      await algorithmListRuntime?.refresh?.({render: true});
      if(!current())return;
      showStatus(await requestJson(`${API_ROOT}/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(algorithmId)}/versions/${encodeURIComponent(versionId)}`));
    } catch (error) {
      outcomeUncertain=outcomeUncertain||(postStarted&&!postConfirmed&&!(Number(error.httpStatus)>=400&&Number(error.httpStatus)<500));
      if(!current())return;
      notify?.(outcomeUncertain?'发布结果待确认，请点击查询发布结果；不会自动再次发布。 '+(error?.message||error):(error?.message || error));
      await algorithmListRuntime?.refresh?.({render: true});
      if(current()){
        try{showStatus(await requestJson(`${API_ROOT}/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(algorithmId)}/versions/${encodeURIComponent(versionId)}`));}catch(_){/* original error remains visible */}
      }
    } finally {
      if(outcomeUncertain)publicationRequests.set(key,'uncertain');else publicationRequests.delete(key);
      if (button?.isConnected) {
        button.removeAttribute('aria-busy');
        const {version} = versionFromIds(algorithmId, versionId);
        button.disabled = false;
        button.textContent = outcomeUncertain?'查询发布结果':publicationActionLabel(version || {});
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
