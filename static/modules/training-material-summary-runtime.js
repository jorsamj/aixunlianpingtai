function uniqueIds(values) {
  return [...new Set((values || []).map(value => String(value || '').trim()).filter(Boolean))];
}

export function trainingMaterialSelectionSignature(ids = []) {
  return uniqueIds(ids).sort().join('\u0000');
}

function htmlEscape(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

export function trainingCompatibilitySignature(draft = {}) {
  return JSON.stringify({
    algorithmId: String(draft?.algorithmId || ''),
    materialIds: uniqueIds(draft?.materialIds).sort(),
    testMaterialIds: uniqueIds(draft?.testMaterialIds).sort(),
    splitMode: String(draft?.splitMode || 'random_test_from_training_pool'),
    labels: uniqueIds(draft?.newLabelCodes).sort(),
    model: String(draft?.config?.model || ''),
    experimentPercent: draft?.experimentPercent ?? null,
    validationPercent: draft?.validationPercent ?? null,
    duplicateReview: draft?.duplicateReview || null,
  });
}

export function excludeTrainingMaterialFromDraft(trainingDraftRuntime, draft, imageId, diagnosis = null) {
  const key = String(imageId || '').trim();
  if (!key || !trainingDraftRuntime?.update) return draft || null;
  const item = diagnosis?.items?.find(row => String(row.image_id) === key);
  if (item?.issue_type === 'content_hash_leakage') throw new Error('同 SHA 跨训练/试验集，必须先重新调整数据角色，不能直接排除来掩盖泄漏');
  const duplicateReview = item?.issue_type === 'duplicate_annotation_conflict' ? {
    original_train_image_ids: draft?.duplicateReview?.original_train_image_ids || uniqueIds(draft?.materialIds),
    original_test_image_ids: draft?.duplicateReview?.original_test_image_ids || uniqueIds(draft?.testMaterialIds),
    excluded_image_ids: uniqueIds([...(draft?.duplicateReview?.excluded_image_ids || []), key]),
    material_revision: draft?.duplicateReview?.material_revision ?? diagnosis.material_revision,
    annotation_revision: draft?.duplicateReview?.annotation_revision ?? diagnosis.annotation_revision,
  } : null;
  return trainingDraftRuntime.update({
    materialIds: uniqueIds(draft?.materialIds).filter(id => id !== key),
    testMaterialIds: uniqueIds(draft?.testMaterialIds).filter(id => id !== key),
    ...(duplicateReview ? {duplicateReview} : {}),
  });
}

function responseMessage(body, fallback) {
  if (typeof body?.detail === 'string') {
    try { return JSON.parse(body.detail)?.message || body.detail; } catch (_error) { return body.detail; }
  }
  if (typeof body?.detail?.message === 'string') return body.detail.message;
  return fallback;
}

async function readJson(response, fallback) {
  let body = null;
  try { body = await response.json(); } catch (_error) {}
  if (!response.ok) throw new Error(responseMessage(body, fallback));
  return body || {};
}

function setTextIfChanged(element, value) {
  if (!element) return false;
  const next = String(value ?? '');
  if (element.textContent === next) return false;
  element.textContent = next;
  return true;
}

export function installTrainingMaterialSummaryRuntime({
  getState,
  projectId,
  trainingDraftRuntime,
  notify = () => {},
  fetchImpl = (...args) => fetch(...args),
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingMaterialSummaryRuntimeInstalled) return window.TrainingMaterialSummaryRuntime;
  if (typeof getState !== 'function' || typeof projectId !== 'function' || !trainingDraftRuntime) {
    throw new Error('TrainingMaterialSummaryRuntime missing dependencies');
  }

  const state = () => getState() || {};
  let destroyed = false;
  let requestSequence = 0;
  let compatibilitySequence = 0;
  let activeController = null;
  let currentSignature = null;
  let pendingSignature = null;
  let summary = null;
  let lastError = '';
  let decorateQueued = false;
  let compatibilitySignature = null;
  let compatibilityPendingSignature = null;
  let compatibility = null;
  let compatibilityController = null;
  let compatibilityQuery = '';
  let compatibilityIssueType = '';
  let compatibilityPage = 1;
  let compatibilityPageSize = 50;
  let comparison = null;
  let historicalDiagnosis = null;
  let diagnosticSequence = 0;

  function currentIds() {
    return uniqueIds(trainingDraftRuntime.materialIds?.() || state().trainingDraft?.materialIds || []);
  }

  function currentDraft() {
    return state().trainingDraft || trainingDraftRuntime.current?.() || null;
  }

  function compatibilityPayload(draft = currentDraft(), overrides = {}) {
    return {
      algorithm_asset_id: String(draft?.algorithmId || ''),
      split_mode: String(draft?.splitMode || 'random_test_from_training_pool'),
      train_image_ids: uniqueIds(draft?.materialIds),
      test_image_ids: uniqueIds(draft?.testMaterialIds),
      train_labels: uniqueIds(draft?.newLabelCodes),
      model: String(draft?.config?.model || 'yolo11n.pt'),
      framework: String(draft?.config?.framework || 'ultralytics'),
      experiment_percent: draft?.experimentPercent ?? 20,
      validation_percent: draft?.validationPercent ?? 20,
      ...(draft?.duplicateReview ? {duplicate_review: draft.duplicateReview} : {}),
      limit: 50,
      ...overrides,
    };
  }

  function compatibilityFor(draft = currentDraft()) {
    const signature = trainingCompatibilitySignature(draft || {});
    if (compatibilityPendingSignature === signature) {
      return {ready: false, loading: true, issue_count: null, signature};
    }
    if (compatibilitySignature !== signature || !compatibility) {
      return {ready: false, loading: false, issue_count: null, signature};
    }
    return {...compatibility, ready: true, loading: false, signature};
  }

  function labelDisplay(code) {
    const row = (state().labels || []).find(item => String(item?.code || '') === String(code));
    return String(row?.display_name || row?.display_name_zh || row?.name || code || '');
  }

  function summaryReadyFor(ids = currentIds()) {
    return currentSignature === trainingMaterialSelectionSignature(ids) && Boolean(summary) && !pendingSignature;
  }

  function summaryFor(ids = currentIds()) {
    return summaryReadyFor(ids) ? summary : null;
  }

  function selectedLabelCodes(ids = currentIds()) {
    return uniqueIds(summaryFor(ids)?.label_codes || []);
  }

  function decorateTrainingCreateUi() {
    if (destroyed || typeof document === 'undefined') return;
    const ids = currentIds();
    const ready = summaryReadyFor(ids);
    const labels = ready ? selectedLabelCodes(ids) : [];
    const labelElement = document.getElementById('tr429Labels');
    if (labelElement) {
      const baseLabels = labels.map(labelDisplay).filter(Boolean).join('、') || '无标签';
      const labelText = !ids.length ? '—' : ready
        ? `${baseLabels} · 可直接训练 ${summary.eligible_count} / 待标注 ${summary.pending_annotation_count}`
        : '读取中…';
      setTextIfChanged(labelElement, labelText);
    }

    const cards = document.querySelectorAll('.train-v3-summary > div');
    for (const card of cards) {
      const title = card.querySelector('span');
      const value = card.querySelector('b');
      if (title?.textContent?.trim() === '可选素材' && value) {
        const totalText = summary ? String(Math.max(0, Number(summary.selectable_total || 0))) : '…';
        setTextIfChanged(value, totalText);
        if (value.dataset.serverTruth !== 'training-material-summary') {
          value.dataset.serverTruth = 'training-material-summary';
        }
      }
    }
    const host = document.querySelector?.('.train429-data-summary');
    if (host) {
      let row = host.querySelector?.('[data-training-compatibility-summary]');
      if (!row) {
        row = document.createElement('div');
        row.dataset.trainingCompatibilitySummary = '1';
        host.appendChild(row);
      }
      const truth = compatibilityFor();
      const count = Number(truth.affected_image_count ?? truth.issue_count ?? 0);
      row.innerHTML = truth.loading || !truth.ready
        ? '<span>标签适配</span><b>检查中…</b>'
        : count
          ? `<span>训练输入检查</span><b class="warn">${count} 张需处理</b><button class="btn mini" type="button" data-training-compatibility-open>查看并处理冲突</button>`
          : '<span>标签适配</span><b>已通过</b>';
      row.querySelector?.('[data-training-compatibility-open]')?.addEventListener?.('click', () => openCompatibilityIssues());
    }
  }

  function queueDecorate() {
    if (destroyed || decorateQueued) return;
    decorateQueued = true;
    queueMicrotask(() => {
      decorateQueued = false;
      decorateTrainingCreateUi();
    });
  }

  async function refresh(ids = currentIds(), {force = false} = {}) {
    const normalizedIds = uniqueIds(ids);
    const signature = trainingMaterialSelectionSignature(normalizedIds);
    if (!force && currentSignature === signature && summary) {
      queueDecorate();
      return summary;
    }
    if (!force && pendingSignature === signature) return null;
    const pid = String(projectId() || '');
    if (!pid) {
      currentSignature = signature;
      pendingSignature = null;
      summary = null;
      queueDecorate();
      return null;
    }

    const sequence = ++requestSequence;
    activeController?.abort?.();
    activeController = new AbortController();
    pendingSignature = signature;
    lastError = '';
    queueDecorate();
    try {
      const response = await fetchImpl(
        `/api/v62/projects/${encodeURIComponent(pid)}/training-materials/selection-summary`,
        {
          method: 'POST',
          signal: activeController.signal,
          headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
          body: JSON.stringify({image_ids: normalizedIds}),
        },
      );
      const body = await readJson(response, '训练素材摘要读取失败');
      if (destroyed || sequence !== requestSequence) return null;
      currentSignature = signature;
      pendingSignature = null;
      summary = {
        requested_count: Math.max(0, Number(body.requested_count || 0)),
        matched_count: Math.max(0, Number(body.matched_count || 0)),
        selectable_count: Math.max(0, Number(body.selectable_count || 0)),
        eligible_count: Math.max(0, Number(body.eligible_count || 0)),
        pending_annotation_count: Math.max(0, Number(body.pending_annotation_count || 0)),
        selectable_total: Math.max(0, Number(body.selectable_total || 0)),
        eligible_total: Math.max(0, Number(body.eligible_total || 0)),
        pending_annotation_total: Math.max(0, Number(body.pending_annotation_total || 0)),
        box_count: Math.max(0, Number(body.box_count || 0)),
        size_bytes: Math.max(0, Number(body.size_bytes || 0)),
        label_codes: uniqueIds(body.label_codes),
        label_counts: body.label_counts && typeof body.label_counts === 'object' ? {...body.label_counts} : {},
        repository_revision: body.repository_revision ?? null,
      };
      queueDecorate();
      window.TrainingLabelRuntime?.queueRefresh?.();
      return summary;
    } catch (error) {
      if (error?.name === 'AbortError' || sequence !== requestSequence) return null;
      pendingSignature = null;
      lastError = String(error?.message || error || '训练素材摘要读取失败');
      queueDecorate();
      notify(lastError);
      return null;
    }
  }

  async function refreshCompatibility({force = false, payload = null, query = '', issueType = '', page = 1, pageSize = 50} = {}) {
    const draft = currentDraft();
    const signature = trainingCompatibilitySignature(draft || {});
    if (!draft?.algorithmId || !uniqueIds(draft?.materialIds).length) {
      compatibilitySignature = signature;
      compatibilityPendingSignature = null;
      compatibility = {compatible: false, issue_count: 0, items: [], skipped: true};
      queueDecorate();
      return compatibility;
    }
    if (!force && compatibilitySignature === signature && compatibility) return compatibility;
    if (!force && compatibilityPendingSignature === signature) return null;
    const pid = String(projectId() || '');
    if (!pid) return null;
    const sequence = ++compatibilitySequence;
    compatibilityController?.abort?.();
    compatibilityController = new AbortController();
    compatibilityPendingSignature = signature;
    queueDecorate();
    try {
      const requestBody = payload ? {...payload} : compatibilityPayload(draft);
      Object.assign(requestBody, {
        query,
        issue_type: issueType,
        page,
        page_size: pageSize,
      });
      const response = await fetchImpl(
        `/api/v62/projects/${encodeURIComponent(pid)}/training-materials/compatibility`,
        {
          method: 'POST',
          signal: compatibilityController.signal,
          headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
          body: JSON.stringify(requestBody),
        },
      );
      const body = await readJson(response, '训练标签适配检查失败');
      if (destroyed || sequence !== compatibilitySequence || String(projectId() || '') !== pid) return null;
      compatibilitySignature = signature;
      compatibilityPendingSignature = null;
      compatibility = {
        ...body,
        compatible: body.compatible === true,
        issue_count: Math.max(0, Number(body.issue_count || 0)),
        items: Array.isArray(body.items) ? body.items.map(item => ({...item})) : [],
      };
      compatibilityQuery = String(query || '');
      compatibilityIssueType = String(issueType || '');
      compatibilityPage = Math.max(1, Number(body.page || page || 1));
      compatibilityPageSize = Math.max(1, Math.min(100, Number(body.page_size || pageSize || 50)));
      queueDecorate();
      window.TrainingSubmitRuntime?.updateReadiness?.();
      return compatibility;
    } catch (error) {
      if (error?.name === 'AbortError' || sequence !== compatibilitySequence) return null;
      compatibilityPendingSignature = null;
      compatibility = null;
      lastError = String(error?.message || error || '训练标签适配检查失败');
      queueDecorate();
      window.TrainingSubmitRuntime?.updateReadiness?.();
      notify(lastError);
      return null;
    }
  }

  function issueHtml(item) {
    if (['duplicate_annotation_conflict','content_hash_leakage'].includes(item?.issue_type)) {
      const leakage = item.issue_type === 'content_hash_leakage';
      return `<article class="training-compatibility-item"><img src="${htmlEscape(item.thumbnail_url||item.content_url||'')}" alt="${htmlEscape(item.filename||item.image_id)}" loading="lazy"><div><b>${htmlEscape(item.filename||item.image_id)}</b><small>${htmlEscape(item.image_id)} · ${htmlEscape(item.role||'')}</small><p>${leakage?'同 SHA 跨训练/试验集：必须调整数据角色，不能直接忽略':'原始正式标注冲突：'+htmlEscape((item.conflict_types||[]).join('、'))}</p><p>${htmlEscape(item.annotation_state)} · 范围 ${htmlEscape((item.annotation_scope||[]).join('、'))} · ${Number(item.box_count||0)} 框</p><code>${htmlEscape(item.content_sha256)}</code><div class="row"><button class="btn primary" data-duplicate-compare="${htmlEscape(item.content_sha256)}" ${leakage?'disabled':''}>查看标注差异</button><button class="btn" data-conflict-review="${htmlEscape(item.image_id)}">去补审 / 核对当前标注</button><button class="btn" data-conflict-exclude="${htmlEscape(item.image_id)}" ${leakage?'disabled':''}>仅排除本次训练</button></div></div></article>`;
    }
    const reviewed = uniqueIds(item?.annotation_scope).join('、') || '无';
    const required = uniqueIds(item?.required_label_codes).join('、') || '无';
    const missing = uniqueIds(item?.missing_label_codes).join('、') || '无';
    const imageId = String(item?.image_id || '');
    const preview = String(item?.thumbnail_url || item?.content_url || '');
    return `<article class="training-compatibility-item"><img src="${htmlEscape(preview)}" loading="lazy"><div><b>${htmlEscape(item?.filename || imageId)}</b><small>${htmlEscape(item?.dataset_name || item?.dataset_id || '-')} · ${htmlEscape(item?.annotation_state || '-')}</small><p>已审核：${htmlEscape(reviewed)}</p><p>本次要求：${htmlEscape(required)}</p><p class="warn">缺失：${htmlEscape(missing)}</p><div class="row"><button class="btn mini primary" onclick="TrainingMaterialSummaryRuntime.openReview('${htmlEscape(imageId)}')">去补审</button><button class="btn mini" onclick="TrainingMaterialSummaryRuntime.excludeFromDraft('${htmlEscape(imageId)}')">排除本次训练</button></div></div></article>`;
  }

  function openCompatibilityIssues() {
    diagnosticSequence += 1;
    historicalDiagnosis = null;
    comparison = null;
    const truth = compatibilityFor();
    if (!truth.ready) return void refreshCompatibility({force: true});
    const rows = truth.items || [];
    const issueTypes = Object.keys(truth.issue_counts || {});
    const offset = Math.max(0, (compatibilityPage - 1) * compatibilityPageSize);
    const html = `<div class="training-compatibility-list"><div class="alert warn"><b>${truth.issue_count} 张素材不适配本次训练</b><span>补审只记录你明确检查过的标签；AI 未检出不会自动确认不存在。</span></div><div class="row"><input id="trainingCompatibilityQuery" class="input" value="${htmlEscape(compatibilityQuery)}" placeholder="搜索文件名 / image_id"><select id="trainingCompatibilityType" class="select"><option value="">全部异常</option>${issueTypes.map(type=>`<option value="${htmlEscape(type)}" ${type===compatibilityIssueType?'selected':''}>${htmlEscape(type)} · ${Number(truth.issue_counts[type]||0)}</option>`).join('')}</select><button class="btn" type="button" onclick="TrainingMaterialSummaryRuntime.applyIssueFilters()">筛选</button></div><div class="item-sub">筛选结果 ${Number(truth.filtered_count||0)} 条 · 当前 ${rows.length?offset+1:0}-${offset+rows.length}</div>${rows.map(issueHtml).join('') || '<div class="empty">当前筛选没有问题素材</div>'}<div id="trainingCompatibilityPager"></div></div>`;
    showDiagnosticDialog(Number(truth.duplicate_conflict_group_count||truth.duplicate_group_count||0)?'训练素材冲突诊断':'训练标签适配问题', `<div data-training-compatibility-dialog>${html}<div class="row end"><button class="btn" data-training-recheck>重新预检</button>${currentDraft()?.duplicateReview?'<button class="btn" data-training-undo-exclusions>撤销本次排除并重新检查</button>':''}<button class="btn" onclick="closeModal()">返回训练配置 · 保留草稿</button></div></div>`);
    bindDiagnosticActions();
    window.PlatformCore?.pagination?.mountPagination?.(
      document.getElementById('trainingCompatibilityPager'),
      {
        page: compatibilityPage,
        pageSize: compatibilityPageSize,
        total: Number(truth.filtered_count || 0),
        totalPages: Number(truth.total_pages || 1),
        hasPrevious: truth.has_previous === true,
        hasNext: truth.has_next === true,
        loading: false,
      },
      {
        label: '训练兼容性问题分页',
        showPageSize: true,
        pageSizes: [10, 20, 50, 100],
        onPageChange: targetPage => loadIssuePage(targetPage),
        onPageSizeChange: pageSize => {
          compatibilityPageSize = pageSize;
          return loadIssuePage(1);
        },
      },
    );
  }

  function showDiagnosticDialog(title, html) {
    const existing=[...document.querySelectorAll('[data-training-compatibility-dialog]')].find(root=>!root.closest('.hidden'));
    const body=existing?.closest('.modal-body');
    if(body){body.innerHTML=html;const heading=body.parentElement.querySelector('.modal-title');if(heading)heading.textContent=title}
    else window.modal?.(title,html,true);
  }

  function bindDiagnosticActions() {
    const root=document.querySelector('[data-training-compatibility-dialog]');if(!root)return;
    root.querySelectorAll('[data-duplicate-compare]').forEach(button=>button.onclick=()=>openDuplicateComparison(button.dataset.duplicateCompare));
    root.querySelectorAll('[data-conflict-review]').forEach(button=>button.onclick=()=>openReview(button.dataset.conflictReview));
    root.querySelectorAll('[data-conflict-exclude]').forEach(button=>{if(historicalDiagnosis)button.disabled=true;button.onclick=()=>excludeFromDraft(button.dataset.conflictExclude)});
    root.querySelector('[data-training-recheck]')?.addEventListener('click',async()=>{if(historicalDiagnosis)return openTaskDiagnosis(historicalDiagnosis.task_id);const result=await refreshCompatibility({force:true});if(result)openCompatibilityIssues()});
    root.querySelector('[data-training-undo-exclusions]')?.addEventListener('click',async()=>{
      const review=currentDraft()?.duplicateReview;if(!review)return;
      trainingDraftRuntime.update({materialIds:review.original_train_image_ids,testMaterialIds:review.original_test_image_ids,duplicateReview:null});
      invalidateCompatibility();const result=await refreshCompatibility({force:true});if(result)openCompatibilityIssues();
    });
    root.querySelector('[data-comparison-back]')?.addEventListener('click',async()=>{if(historicalDiagnosis)return openTaskDiagnosis(historicalDiagnosis.task_id);const result=await refreshCompatibility({force:true});if(result)openCompatibilityIssues()});
    root.querySelectorAll('[data-comparison-page]').forEach(button=>button.onclick=()=>openDuplicateComparison(comparison.hash,Number(button.dataset.comparisonPage)));
    root.querySelectorAll('[data-task-diagnosis-page]').forEach(button=>button.onclick=()=>openTaskDiagnosis(historicalDiagnosis.task_id,Number(button.dataset.taskDiagnosisPage)));
  }

  async function openDuplicateComparison(hash, page=1) {
    const pid=String(projectId()||'');
    const sequence=++diagnosticSequence,sourceTask=historicalDiagnosis?.task_id;
    const anchor=document.querySelector('[data-training-compatibility-dialog]');
    try{
      let result, history;
      if(sourceTask){
        history=await readJson(await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-tasks/${encodeURIComponent(sourceTask)}/input-diagnosis?page=${page}&limit=2&query=${encodeURIComponent(hash)}`),'当前冲突组读取失败');
        result=history.current_diagnosis;
      }else{
        const issueType=compatibility?.items?.find(item=>item.content_sha256===hash)?.issue_type||'duplicate_annotation_conflict';
        result=await refreshCompatibility({force:true,query:String(hash),issueType,page,pageSize:2});
      }
      if(!result||String(projectId()||'')!==pid||sequence!==diagnosticSequence)return false;
      const rows=await Promise.all(result.items.map(async item=>{
        const detail=await readJson(await fetchImpl(`/api/projects/${encodeURIComponent(pid)}/annotations/${encodeURIComponent(item.image_id)}`), '正式标注读取失败');
        if(String(detail.image?.id)!==String(item.image_id)||String(detail.image?.content_sha256||'').toLowerCase()!==String(item.content_sha256||'').toLowerCase())throw new Error('素材身份已变化，请重新预检');
        const annotation=detail.annotation||detail;
        if(item.annotation_version!=null&&Number(annotation.version)!==Number(item.annotation_version))throw new Error('正式标注版本已变化，请重新预检');
        return {...item,width:detail.image.width,height:detail.image.height,boxes:annotation.boxes||[],annotation_scope:annotation.annotation_scope||[]};
      }));
      if(String(projectId()||'')!==pid||destroyed||sequence!==diagnosticSequence||anchor&&(!anchor.isConnected||anchor.closest('.hidden')))return false;
      comparison={hash:String(hash),page,items:rows};historicalDiagnosis=sourceTask?history:null;
      const cards=rows.map(item=>`<article>${window.materialIntegrityImage47?.(item)||`<img src="${htmlEscape(item.content_url)}" alt="${htmlEscape(item.filename)}">`}<div class="material-integrity47-meta"><b>${htmlEscape(item.filename)}</b><code>${htmlEscape(item.image_id)}</code><p>原始正式 GT · ${htmlEscape(item.role)} · ${htmlEscape(item.annotation_state)} · ${Number(item.box_count)} 框</p><p>类别 ${htmlEscape((item.labels||[]).join('、'))} · 范围 ${htmlEscape((item.annotation_scope||[]).join('、'))}</p><small>差异 ${htmlEscape((item.conflict_types||[]).join('、'))}</small><code>${htmlEscape(item.annotation_digest)}</code><p>${htmlEscape((item.reference_reasons||[]).map(reason=>window.materialIntegrityProtectionText47?.(reason)||reason.reason).join('；')||'本页未返回历史保护原因；不是删除许可')}</p><div class="row"><button class="btn primary" data-conflict-review="${htmlEscape(item.image_id)}">人工核对这份标注</button><button class="btn" data-conflict-exclude="${htmlEscape(item.image_id)}">仅排除本次训练</button></div></div></article>`).join('');
      showDiagnosticDialog('重复素材标注差异',`<div data-training-compatibility-dialog class="training-duplicate-comparison"><div class="alert warn"><b>同一图片内容，不同正式 Ground Truth</b><p>系统不判断哪份正确，也不会覆盖历史模型、Snapshot 或 Test。修改通过原标注工作台保存；排除只影响本次新训练，保留可审计记录。</p><code>SHA256 ${htmlEscape(hash)}</code></div>${rows.length?`<div class="material-integrity47-grid">${cards}</div>`:'<div class="alert ok">本组当前冲突已解除，请重新检查完整训练选择。</div>'}<div class="row between"><button class="btn" data-comparison-back>返回完整预检</button><div class="row"><button class="btn" data-comparison-page="${page-1}" ${page>1?'':'disabled'}>上一页对比</button><span>第 ${page} / ${result.total_pages||1} 页 · 每页最多 2 张</span><button class="btn" data-comparison-page="${page+1}" ${result.has_next?'':'disabled'}>下一页对比</button></div><button class="btn" data-training-recheck>重新预检</button></div></div>`);
      bindDiagnosticActions();return true;
    }catch(error){notify(String(error.message||error));return false}
  }

  async function openTaskDiagnosis(taskId,page=1) {
    const pid=String(projectId()||'');
    const sequence=++diagnosticSequence;
    showDiagnosticDialog('训练输入冲突诊断','<div data-training-compatibility-dialog role="status">正在读取持久任务证据和当前正式标注…</div>');
    const anchor=document.querySelector('[data-training-compatibility-dialog]');
    try{
      const body=await readJson(await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-tasks/${encodeURIComponent(taskId)}/input-diagnosis?page=${page}&limit=24`),'训练输入诊断读取失败');
      if(String(projectId()||'')!==pid||destroyed||sequence!==diagnosticSequence||!anchor?.isConnected||anchor.closest('.hidden'))return false;
      historicalDiagnosis=body;comparison=null;
      const current=body.current_diagnosis||{},history=body.historical_evidence||{};
      showDiagnosticDialog('训练输入冲突诊断',`<div data-training-compatibility-dialog><div class="alert warn"><b>训练输入检查失败 · 请先修复后创建新任务</b><p>${htmlEscape(history.message||history.status)}</p><small>历史证据状态：${htmlEscape(history.status)}；以下仅为当前正式索引/标注，不冒充旧任务冻结时的数据。</small></div>${current.available===false?`<div class="alert err">${htmlEscape(current.message||'当前素材不足以重建诊断')}</div>`:`<div class="training-compatibility-list">${(current.items||[]).map(item=>issueHtml(item).replaceAll('data-conflict-exclude=','disabled data-conflict-exclude=')).join('')||'<p>当前未发现相同冲突；请在新训练中重新预检，不恢复原失败任务。</p>'}</div>`}<div class="row between"><button class="btn" data-task-diagnosis-page="${page-1}" ${page>1?'':'disabled'}>上一页问题</button><span>第 ${page} / ${current.total_pages||1} 页</span><button class="btn" data-task-diagnosis-page="${page+1}" ${current.has_next?'':'disabled'}>下一页问题</button></div><div class="row end"><button class="btn" data-training-recheck>重新检查当前数据</button><button class="btn" onclick="closeModal()">返回失败任务</button></div></div>`);
      bindDiagnosticActions();return true;
    }catch(error){notify(String(error.message||error));return false}
  }

  async function returnFromReview() {
    if(historicalDiagnosis)return openTaskDiagnosis(historicalDiagnosis.task_id);
    const result=await refreshCompatibility({force:true});if(result)openCompatibilityIssues();
  }

  async function loadIssuePage(page = 1) {
    const result = await refreshCompatibility({
      force: true,
      query: compatibilityQuery,
      issueType: compatibilityIssueType,
      page,
      pageSize: compatibilityPageSize,
    });
    if (result) openCompatibilityIssues();
    return result;
  }

  function applyIssueFilters() {
    compatibilityQuery = String(document.getElementById('trainingCompatibilityQuery')?.value || '').trim();
    compatibilityIssueType = String(document.getElementById('trainingCompatibilityType')?.value || '').trim();
    return loadIssuePage(1);
  }

  async function openReview(imageId) {
    const item = (historicalDiagnosis?.current_diagnosis?.items || comparison?.items || compatibility?.items || []).find(row => String(row?.image_id || '') === String(imageId));
    if (!item) return false;
    const s = state();
    if (!(s.images || []).some(row => String(row?.id || '') === String(imageId))) {
      s.images = [...(s.images || []), {
        id: String(imageId), filename: item.filename, dataset_id: item.dataset_id,
        url: item.content_url || item.thumbnail_url, content_sha256: item.content_sha256,
      }];
    }
    s.trainingAnnotationReviewContext = {
      imageId: String(imageId),
      requiredLabelCodes: uniqueIds(item.required_label_codes),
      missingLabelCodes: uniqueIds(item.missing_label_codes),
      returnSource: 'training',
      projectId: String(projectId()||''),
    };
    return window.openAnnotation?.(String(imageId));
  }

  function excludeFromDraft(imageId) {
    if(historicalDiagnosis)return false;
    if(typeof window.confirm==='function'&&!window.confirm('仅从本次新训练选择中排除这条身份，不删除素材、标注或历史证据。确认后将重新预检。'))return false;
    const next = excludeTrainingMaterialFromDraft(trainingDraftRuntime, currentDraft(), imageId, compatibility);
    invalidateCompatibility();
    void refreshCompatibility({force: true}).then(result=>{if(result)openCompatibilityIssues()});
    return next;
  }

  function invalidateCompatibility() {
    compatibilitySequence += 1;
    compatibilityController?.abort?.();
    compatibilityController = null;
    compatibilitySignature = null;
    compatibilityPendingSignature = null;
    compatibility = null;
    queueDecorate();
    window.TrainingSubmitRuntime?.updateReadiness?.();
  }

  function invalidate() {
    requestSequence += 1;
    activeController?.abort?.();
    activeController = null;
    currentSignature = null;
    pendingSignature = null;
    summary = null;
    lastError = '';
    invalidateCompatibility();
    queueDecorate();
    window.TrainingLabelRuntime?.queueRefresh?.();
  }

  function syncSelection() {
    const ids = currentIds();
    const signature = trainingMaterialSelectionSignature(ids);
    if (signature !== currentSignature && signature !== pendingSignature) void refresh(ids);
    else queueDecorate();
    const draft = currentDraft();
    const compatibilityKey = trainingCompatibilitySignature(draft || {});
    if (compatibilityKey !== compatibilitySignature && compatibilityKey !== compatibilityPendingSignature) {
      void refreshCompatibility();
    }
  }

  const unsubscribeDraft = trainingDraftRuntime.subscribe?.(() => syncSelection()) || (() => {});
  const observer = typeof MutationObserver !== 'undefined'
    ? new MutationObserver(() => queueDecorate())
    : null;
  observer?.observe(document.body, {childList: true, subtree: true});

  const runtime = {
    build: 'training-material-summary-runtime-422604',
    refresh,
    refreshCompatibility,
    invalidateCompatibility,
    compatibilityFor,
    openCompatibilityIssues,
    loadIssuePage,
    applyIssueFilters,
    openReview,
    openDuplicateComparison,
    openTaskDiagnosis,
    returnFromReview,
    excludeFromDraft,
    invalidate,
    summaryReadyFor,
    summaryFor,
    selectedLabelCodes,
    decorateTrainingCreateUi,
    state() {
      return {
        signature: currentSignature,
        pendingSignature,
        loading: Boolean(pendingSignature),
        selectableTotal: summary?.selectable_total ?? null,
        eligibleTotal: summary?.eligible_total ?? null,
        pendingAnnotation: summary?.pending_annotation_count ?? null,
        selectedLabels: summary?.label_codes?.length || 0,
        lastError,
        compatibility: compatibilityFor(),
        networkOwner: true,
        fullPoolHydration: false,
      };
    },
    destroy() {
      destroyed = true;
      activeController?.abort?.();
      compatibilityController?.abort?.();
      unsubscribeDraft();
      observer?.disconnect();
      if (window.TrainingMaterialSummaryRuntime === runtime) window.TrainingMaterialSummaryRuntime = null;
      window.__trainingMaterialSummaryRuntimeInstalled = false;
    },
  };

  window.TrainingMaterialSummaryRuntime = runtime;
  window.__trainingMaterialSummaryRuntimeInstalled = true;
  syncSelection();
  return runtime;
}
