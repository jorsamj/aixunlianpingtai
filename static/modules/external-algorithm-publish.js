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
    const review=row.review_required&&row.included_in_delivery!==false?`<br>自动发布异常，请管理员核对：${escapeHtml(plan.reason||row.last_error||'远端身份未确认')}<br>建议 ${escapeHtml(plan.suggested_operation||'READ_ONLY_RECOVERY')}<br>目标分类 ${escapeHtml(plan.target_compute_platform_id||'未确认')}<br>原Weight ${escapeHtml(plan.old_weight_id||'未确认')}`:'';
    const role=({HISTORICAL:'历史成果',AUTOMATIC_CURRENT:'自动当前交付',CONFIRMED_OWNER:'当前交付',SINGLE_CANDIDATE:'自动交付候选'})[row.delivery_role]||row.delivery_role||'待核验';
    const readback=row.remote_identity_status==='READ_BACK'?'远端读回已确认':row.remote_identity_status==='HISTORICAL_RECEIPT'?'历史登记回执（已被当前成果取代）':'远端身份未读回验证';
    const facts=`Artifact ${escapeHtml(row.artifact_id||'未登记')}<br>Weight ${escapeHtml(row.external_weight_id||'未确认')}<br>OSS ${escapeHtml(row.storage_status||'未登记')}<br>登记状态 ${escapeHtml(row.sync_status||'PENDING')}<br>交付角色 ${escapeHtml(role)}<br>${readback}${review}`;
    const delivery=row.delivery_role==='HISTORICAL'?'历史成果':row.sync_status==='SYNCED'?'同步成功':row.remote_registered?'已登记 · 待确认':'尚未登记';
    return `<tr><td>${escapeHtml(row.file_name||row.target)}<br>${escapeHtml(row.compute_platform_id||'未配置')} / ${escapeHtml(row.remote_chip_code||row.mapped_chip_code||row.chip_code||'通用')}</td><td>${delivery}<br>${facts}<br>${escapeHtml(names[row.metadata_sync_status]||'待同步')}<br>${escapeHtml(row.metadata_note||'')}${meta.execution_evidence_note?`<br>${escapeHtml(meta.execution_evidence_note)}`:''}<br>${escapeHtml(row.last_error||'')}<br><details><summary>类别与同步证据</summary>${tagsFacts}</details></td><td>宽 ${escapeHtml(meta.image_width??'未记录')} / 高 ${escapeHtml(meta.image_height??'未记录')} · ${escapeHtml(meta.yolo_version||'YOLO型号未记录')}<br>${escapeHtml(row.size_bytes??'未知')} bytes<br><code style="overflow-wrap:anywhere">${escapeHtml(row.sha256||'SHA256未记录')}</code><br>类别：${escapeHtml(Array.isArray(meta.tags)?meta.tags.join(', '):'未记录')}</td></tr>`;
  }).join('')}</tbody></table></div><small>转换产物登记与目标硬件验证分别记录，登记成功不表示实机验证通过。</small></details>`;
}

export function publicationDeliveryRows(status={}) {
  const all=Array.isArray(status.artifacts)?status.artifacts:Array.isArray(status.discovered)?status.discovered:[];
  const current=all.filter(row=>row.included_in_delivery!==false && row.delivery_role!=='HISTORICAL');
  const historical=all.filter(row=>row.included_in_delivery===false || row.delivery_role==='HISTORICAL');
  return {current,historical,delivered:current.filter(row=>row.sync_status==='SYNCED').length,
    reviewing:current.filter(row=>row.review_required).length};
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
  let activeDeliveryDialog = null;

  function installDeliveryDialogStyles() {
    if (document.getElementById('external-delivery-dialog-styles')) return;
    const style = document.createElement('style');
    style.id = 'external-delivery-dialog-styles';
    style.textContent = `
      .external-delivery-dialog{display:grid;gap:16px;max-width:100%;min-width:0;color:#17233d}
      .external-delivery-intro{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
      .external-delivery-intro h3{font-size:20px;line-height:1.4;margin:0 0 5px;font-weight:750}
      .external-delivery-intro p{margin:0;color:#64748b;font-size:13px;line-height:1.6;overflow-wrap:anywhere}
      .external-delivery-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
      .external-delivery-kpi{padding:14px 16px;border:1px solid #e5eaf2;border-radius:13px;background:#f8fafc;min-width:0}
      .external-delivery-kpi span{display:block;color:#64748b;font-size:12px;margin-bottom:7px}
      .external-delivery-kpi b{display:block;font-size:18px;line-height:1.4;overflow-wrap:anywhere}
      .external-delivery-banner{padding:12px 14px;border:1px solid #dbe7fc;border-radius:12px;background:#f4f8ff;font-size:13px;line-height:1.65}
      .external-delivery-banner b{display:block;margin-bottom:3px}
      .external-delivery-banner.warn{border-color:#f6d7a4;background:#fffbf1}
      .external-delivery-banner.ok{border-color:#bce6d0;background:#f2fbf7}
      .external-delivery-banner.error{border-color:#fecaca;background:#fff5f5}
      .external-delivery-list{border:1px solid #e5eaf2;border-radius:13px;overflow:hidden}
      .external-delivery-list-head{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 14px;background:#f8fafc}
      .external-delivery-list-head strong{font-size:14px}
      .external-delivery-list-head span{color:#64748b;font-size:12px}
      .external-delivery-item{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:11px 14px;border-top:1px solid #eef2f7}
      .external-delivery-item-main{min-width:0;flex:1}
      .external-delivery-item-main b{display:block;max-width:100%;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .external-delivery-item-main small{display:block;margin-top:4px;color:#64748b;font-size:11px}
      .external-delivery-pill{font-size:12px;padding:4px 10px;border-radius:100px;white-space:nowrap;background:#eef2f7;color:#475569}
      .external-delivery-pill.ok{background:#dcfce7;color:#166534}
      .external-delivery-pill.warn{background:#fff0ce;color:#92400e}
      .external-delivery-pill.error{background:#fee2e2;color:#991b1b}
      .external-delivery-technical{border:1px solid #e5eaf2;border-radius:11px;padding:11px 13px}
      .external-delivery-technical>summary{cursor:pointer;font-size:13px;font-weight:600;color:#475569}
      .external-delivery-technical>[data-weight-publication-details]{margin-top:12px;max-width:100%;overflow:auto}
      .external-delivery-technical .table{min-width:700px}
      .external-delivery-footer{display:flex;align-items:center;justify-content:space-between;gap:10px;padding-top:13px;border-top:1px solid #e5eaf2}
      .external-delivery-footer .row{flex-wrap:wrap;justify-content:flex-end}
      .external-delivery-footnote{font-size:12px;color:#64748b;line-height:1.5;max-width:55%}
      @media(max-width:760px){.external-delivery-kpis{grid-template-columns:1fr}.external-delivery-intro{flex-direction:column}.external-delivery-footer{flex-direction:column;align-items:stretch}.external-delivery-footnote{max-width:none}}
    `;
    document.head.appendChild(style);
  }

  function deliveryEndpoint(context) {
    return `${API_ROOT}/projects/${encodeURIComponent(context.projectId)}/algorithms/${encodeURIComponent(context.algorithmId)}/versions/${encodeURIComponent(context.versionId)}`;
  }

  function deliveryIsCurrent(context) {
    return Boolean(context?.root?.isConnected) && currentProjectId() === context.projectId
      && String(state().page || '') === '算法列表';
  }

  function deliveryRowStatus(row) {
    if (row.included_in_delivery===false || row.delivery_role==='HISTORICAL') return {label:'历史成果', tone:''};
    if (row.review_required) return {label:'需人工核对', tone:'error'};
    if (row.sync_status === 'SYNCED') return {label:'已同步', tone:'ok'};
    if (row.remote_registered) return {label:'已登记 · 待核实', tone:'warn'};
    if (row.publish_mapping_status === 'blocked') return {label:'待配置映射', tone:'warn'};
    return {label:'待同步', tone:''};
  }

  function deliveryDialogBody(context) {
    const status = context.status;
    const {current:rows,historical:historicalRows,delivered,reviewing}=publicationDeliveryRows(status || {});
    const versionPublished = String(status?.publication?.status || '').toUpperCase() === 'PUBLISHED';
    const partial = String(status?.weight_delivery_status || '').toUpperCase() === 'PARTIAL';
    const done = Boolean(status) && versionPublished && status.requires_sync === false && !partial;
    const preflight = status ? publicationPreflight(status) : {ready:false,message:''};
    const canSync = Boolean(status && !context.busy && !context.uncertain && !context.awaitingReadback
      && status.requires_sync !== false && preflight.ready);
    const busy = Boolean(context.busy);
    const banner = context.awaitingReadback
      ? '<section class="external-delivery-banner warn"><b>同步请求已完成，等待状态确认</b>请刷新状态确认最终权重结果；在获得最新读回前不能重复提交。</section>'
      : context.error
      ? `<section class="external-delivery-banner error" role="alert"><b>操作未完成</b>${escapeHtml(context.error)}</section>`
      : context.uncertain
        ? '<section class="external-delivery-banner warn"><b>上次提交结果尚未确认</b>请先查询远端状态，不会自动再次提交，避免重复创建版本或权重。</section>'
        : !status
          ? '<section class="external-delivery-banner">正在检查当前版本的外部交付状态…</section>'
          : done
            ? '<section class="external-delivery-banner ok"><b>交付已完成</b>当前已登记版本及已配置权重均无需再次同步。</section>'
            : `<section class="external-delivery-banner ${reviewing || !preflight.ready || partial ? 'warn' : ''}"><b>${versionPublished ? '版本已登记，权重交付待处理' : '尚未完成外部交付'}</b>${escapeHtml(reviewing ? `其中 ${reviewing} 份权重需要管理员核对；` : '')}${escapeHtml(preflight.message || '请核对交付范围后确认同步。')}</section>`;
    const list = !status
      ? '<div class="external-delivery-item"><span class="muted-line">正在读取权重清单…</span></div>'
      : rows.length
        ? rows.map(row => {
          const display = deliveryRowStatus(row);
          const name = String(row.file_name || row.target || '模型权重');
          const target = row.target === 'original' || row.target === 'training' ? '原始模型' : String(row.target || '转换产物');
          const platform = String(row.compute_platform_id || row.mapped_chip_code || row.chip_code || '通用');
          return `<div class="external-delivery-item"><div class="external-delivery-item-main"><b title="${escapeHtml(name)}">${escapeHtml(name)}</b><small>${escapeHtml(target)} · ${escapeHtml(platform)}</small></div><span class="external-delivery-pill ${display.tone}">${display.label}</span></div>`;
        }).join('')
        : '<div class="external-delivery-item"><span class="muted-line">当前版本未发现可交付的权重</span></div>';
    const history=historicalRows.length
      ? `<details class="external-delivery-technical"><summary>历史转换成果 ${historicalRows.length} 份（不参与本次同步）</summary>${historicalRows.map(row=>`<div class="external-delivery-item"><div class="external-delivery-item-main"><b title="${escapeHtml(row.file_name||row.target||'历史模型')}">${escapeHtml(row.file_name||row.target||'历史模型')}</b><small>Artifact ${escapeHtml(row.artifact_id||'未登记')}</small></div><span class="external-delivery-pill">历史成果</span></div>`).join('')}</details>`:'';
    return `<div class="external-delivery-dialog">
      <header class="external-delivery-intro"><div><h3>${escapeHtml(context.algorithmName)}</h3><p>版本 ${escapeHtml(context.versionName)} · 目标平台：新畅联</p></div><span class="external-delivery-pill ${versionPublished ? 'ok' : 'warn'}">${versionPublished ? '版本已登记' : status ? '待登记' : '检查中'}</span></header>
      <div class="external-delivery-kpis"><div class="external-delivery-kpi"><span>版本交付</span><b>${versionPublished ? '已登记' : status ? '未完成' : '检查中'}</b></div><div class="external-delivery-kpi"><span>权重已同步</span><b>${status ? `${delivered} / ${rows.length}` : '—'}</b></div><div class="external-delivery-kpi"><span>待人工核对</span><b>${status ? reviewing : '—'}</b></div></div>
      ${banner}
      <section class="external-delivery-list"><div class="external-delivery-list-head"><strong>本次版本的模型权重</strong><span>仅显示本次需要同步的成果</span></div>${list}${history}</section>
      ${status ? `<details class="external-delivery-technical"><summary>技术回执与分类证据（高级详情）</summary>${publicationWeightDetails(status)}</details>` : ''}
      <footer class="external-delivery-footer"><span class="external-delivery-footnote">打开此窗口或刷新状态不会提交同步。只有点击“确认同步”才会向新畅联写入数据；登记成功不代表实机验证通过。</span><div class="row"><button class="btn" type="button" data-delivery-action="refresh" ${busy ? 'disabled' : ''}>${context.busy === 'checking' ? '查询中…' : context.uncertain ? '查询发布结果' : '刷新状态'}</button><button class="btn" type="button" data-delivery-action="close">关闭</button>${!done ? `<button class="btn primary" type="button" data-delivery-action="sync" ${canSync ? '' : 'disabled'}>${context.busy === 'publishing' ? '正在同步…' : '确认同步到新畅联'}</button>` : ''}</div></footer>
    </div>`;
  }

  function paintDeliveryDialog(context) {
    if (deliveryIsCurrent(context)) context.root.innerHTML = deliveryDialogBody(context);
  }

  async function readDeliveryStatus(context) {
    if (!deliveryIsCurrent(context) || context.busy) return;
    context.busy = 'checking';
    context.error = '';
    paintDeliveryDialog(context);
    try {
      const status = await requestJson(deliveryEndpoint(context));
      if (!deliveryIsCurrent(context)) return;
      context.status = status;
      context.awaitingReadback = false;
      if (context.uncertain && status.publication?.status === 'PUBLISHED' && status.requires_sync === false) {
        context.uncertain = false;
        publicationRequests.delete(context.key);
      }
    } catch (error) {
      if (deliveryIsCurrent(context)) context.error = String(error?.message || error);
    } finally {
      context.busy = '';
      paintDeliveryDialog(context);
    }
  }

  async function executeDeliverySync(context) {
    if (!deliveryIsCurrent(context) || context.busy || context.uncertain || publicationRequests.get(context.key) === 'pending') return;
    if (!context.status || context.status.requires_sync === false || !publicationPreflight(context.status).ready) return;
    publicationRequests.set(context.key, 'pending');
    context.busy = 'publishing';
    context.error = '';
    paintDeliveryDialog(context);
    let requestConfirmed = false;
    try {
      const result = await requestJson(deliveryEndpoint(context) + '/publish', {method:'POST'});
      requestConfirmed = true;
      context.uncertain = false;
      context.awaitingReadback = true;
      context.message = publicationResultMessage(result);
      notify?.(context.message);
      await algorithmListRuntime?.refresh?.({render: String(state().page || '') === '算法列表'});
      context.busy = '';
      await readDeliveryStatus(context);
    } catch (error) {
      context.uncertain = !requestConfirmed && !(Number(error?.httpStatus) >= 400 && Number(error?.httpStatus) < 500);
      if (deliveryIsCurrent(context)) {
        context.error = context.uncertain
          ? `发布结果待确认，请先查询状态；系统不会自动再次提交。 ${String(error?.message || error)}`
          : String(error?.message || error);
      }
      if (context.uncertain) publicationRequests.set(context.key, 'uncertain');
    } finally {
      if (!context.uncertain) publicationRequests.delete(context.key);
      context.busy = '';
      paintDeliveryDialog(context);
    }
  }

  async function publishVersion(algorithmId, versionId) {
    const pid = currentProjectId();
    if (!pid) return notify?.('当前项目不可用，请刷新页面后重试');
    const key = `${pid}:${algorithmId}:${versionId}`;
    if (activeDeliveryDialog?.key === key && deliveryIsCurrent(activeDeliveryDialog)) {
      activeDeliveryDialog.layer?.querySelector('button')?.focus?.();
      return;
    }
    const {algorithm, version} = versionFromIds(algorithmId, versionId);
    installDeliveryDialogStyles();
    const context = {
      key, projectId:pid, algorithmId, versionId,
      algorithmName:String(algorithm?.name || '算法模型'),
      versionName:String(version?.version_name || versionId),
      status:null, busy:'', error:'', awaitingReadback:false,
      uncertain:publicationRequests.get(key) === 'uncertain',
    };
    if (typeof window.modal !== 'function') return notify?.('当前弹窗组件不可用，请刷新后重试');
    context.layer = window.modal('新畅联模型交付', '<div data-external-delivery-dialog="1"></div>', true);
    context.root = context.layer?.querySelector('[data-external-delivery-dialog]')
      || document.querySelector('[data-external-delivery-dialog]');
    if (!context.root) return notify?.('交付窗口创建失败，请重试');
    activeDeliveryDialog = context;
    context.root.addEventListener('click', event => {
      const action = event.target.closest('[data-delivery-action]')?.dataset.deliveryAction;
      if (!action) return;
      if (action === 'close') {
        window.closeModalLayer424?.(context.layer);
        return;
      }
      if (action === 'refresh') void readDeliveryStatus(context);
      if (action === 'sync') void executeDeliverySync(context);
    });
    paintDeliveryDialog(context);
    void readDeliveryStatus(context);
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
