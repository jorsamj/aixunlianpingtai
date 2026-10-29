import {withRequestDeadline} from './api.js?v=20261021s';
function uniqueIds(values) {
  return [...new Set((values || []).map(value => String(value || '').trim()).filter(Boolean))];
}

export function updateTrainingGovernanceSelection(previous, {mode='read', key, total=0, allTotal=total, ids=[], id='', checked=false}) {
  const value = previous?.key === key ? previous : {key, all_filtered:false, image_ids:[], excluded_image_ids:[]};
  const selected = new Set(value.image_ids), excluded = new Set(value.excluded_image_ids);
  let all = value.all_filtered;
  let issues=Boolean(value.all_issues);
  if (['all','issues','clear'].includes(mode)) { all = mode === 'all';issues=mode==='issues'; selected.clear(); excluded.clear(); }
  if (mode === 'page') ids.forEach(imageId => all||issues ? excluded.delete(String(imageId)) : selected.add(String(imageId)));
  if (mode === 'toggle') {
    if (all||issues) checked ? excluded.delete(id) : excluded.add(id);
    else checked ? selected.add(id) : selected.delete(id);
  }
  return {key, all_filtered:all, all_issues:issues, image_ids:[...selected], excluded_image_ids:[...excluded],
    ...(mode==='read'&&value.previous_execution_task_id?{previous_execution_task_id:value.previous_execution_task_id}:{}),
    count:mode==='read'&&value.previous_execution_task_id ? value.count : all||issues ? Math.max(0,(issues?allTotal:total)-excluded.size) : selected.size};
}

export function removeResolvedTrainingMaterials(runtime,draft,imageIds,diagnosis=null){
  const removed=new Set(uniqueIds(imageIds));
  const duplicateReview=diagnosis?{
    review_kind:'EXPLICIT_SELECTION_ADJUSTMENT',
    original_train_image_ids:draft?.duplicateReview?.original_train_image_ids||uniqueIds(draft?.materialIds),
    original_test_image_ids:draft?.duplicateReview?.original_test_image_ids||uniqueIds(draft?.testMaterialIds),
    excluded_image_ids:uniqueIds([...(draft?.duplicateReview?.excluded_image_ids||[]),...removed]),
    material_revision:diagnosis.material_revision,annotation_revision:diagnosis.annotation_revision,
  }:null;
  return runtime.update({materialIds:uniqueIds(draft?.materialIds).filter(id=>!removed.has(id)),
    testMaterialIds:uniqueIds(draft?.testMaterialIds).filter(id=>!removed.has(id)),duplicateReview});
}

const ISSUE_NAMES=Object.freeze({missing_annotation:'缺少正式标注',partial_review_scope:'标注审核范围不完整',
  stale_ground_truth:'正式标注与素材身份不一致',material_unavailable:'素材当前不可用',
  duplicate_annotation_conflict:'同图不同标注',content_hash_leakage:'训练与试验集内容重叠'});

export function trainingMaterialSelectionSignature(ids = []) {
  return uniqueIds(ids).sort().join('\u0000');
}

function htmlEscape(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

export function renderTrainingSampleRoles(summary) {
  const counts=summary?.sample_role_counts,labels=uniqueIds(summary?.effective_label_codes);
  if(!counts||!labels.length)return '';
  const n=key=>Math.max(0,Number(counts[key])||0);
  return `<div data-training-sample-roles><span>本次训练标签 ${htmlEscape(labels.join('、'))}</span><b>正样本 ${n('positive')} · 已确认负样本 ${n('confirmed_negative')} · 待确认负样本 ${n('pending_negative')}</b>${n('pending_review')?`<small>另有 ${n('pending_review')} 张素材需修复标注或来源问题。</small>`:''}${n('pending_negative')?'<small>仅在最终创建时确认这些图片不含本次目标；原标注不会修改。</small>':''}${n('confirmed_negative')>n('positive')*3?'<small>负样本比例较高，请结合独立评测判断；不会自动减少所选素材。</small>':''}</div>`;
}

export const GT_CONFLICT_NAMES = Object.freeze({
  LABEL_SCOPE_COUNT_COMPOUND:'类别、范围与框数量复合冲突', COORDINATE_ONLY:'仅框坐标不同',
  SCOPE_AND_GEOMETRY:'范围与框坐标同时不同', OTHER:'其他差异组合',
  LABEL_SET_DIFFERENCE:'标签类别不同', SCOPE_DIFFERENCE:'标注范围不同', BOX_COUNT_DIFFERENCE:'框数量不同',
  PER_CLASS_BOX_COUNT_DIFFERENCE:'同类别框数不同', COORDINATE_DIFFERENCE:'坐标不同',
  SCOPE_BOX_MISMATCH:'框类别不在标注范围内', CANONICAL_ID_MISMATCH:'正式类别ID映射矛盾',
  DIFFERENT_IMPORT_BATCHES:'来自不同导入批次', CROSS_SPLIT_IDENTITY:'跨Train/Val/Test身份',
  UNMATCHED_BOXES_REVIEW_REQUIRED:'未配对框 · 漏标/多标待核验',
  VERIFIED_IMPORT_MAPPING_DIFFERENCE:'已核验导入确认映射不同',
  CURRENT_GT_DIFFERS_FROM_IMPORT_CONFIRMATION:'当前GT已偏离导入确认 · 不判定为错误',
});

export function renderGtConflictEvidence(diagnosis={}, items=[]) {
  const metric=diagnosis.iou_summary||{}, show=value=>value==null?'未核验':htmlEscape(Number(value).toFixed(3));
  const options=items.map((item,index)=>`<option value="${index}">${htmlEscape(item.filename||item.image_id)}</option>`).join('');
  return `<section class="gt-conflict-evidence" data-gt-evidence><header><b>GT 差异证据</b><span>${(diagnosis.proven_mapping_error_count||diagnosis.verified_import_mapping_difference_count)?'已证实映射差异；其他根因仍需核验':'根因待核验'}</span></header><div class="gt-conflict-facts">${(diagnosis.observations||[]).map(code=>`<span>${htmlEscape(GT_CONFLICT_NAMES[code]||code)}</span>`).join('')}</div><div class="gt-conflict-metrics"><span>候选配对 ${Number(metric.matched_count||0)}</span><span>最小 IoU ${show(metric.min)}</span><span>最大坐标差 ${show(metric.max_pixel_delta)} px</span><span>未配对 ${Number(metric.unmatched_count||0)}</span></div>${items.length>1?`<div class="row"><label>A <select class="select" data-gt-source="a" aria-label="叠加参考GT">${options}</select></label><label>B <select class="select" data-gt-source="b" aria-label="叠加对比GT">${options}</select></label><span>A 实线 · B 虚线；框标签分别标明来源</span></div><div data-gt-overlay></div>`:''}<details><summary>来源、状态与坐标明细</summary>${items.map(item=>`<article><b>${htmlEscape(item.filename||item.image_id)}</b><p>来源 ${htmlEscape(item.storage_source_id||'未记录')} · 导入批次 ${htmlEscape(item.import_batch_id||'未记录')} · ${htmlEscape(item.annotation_state||'未记录')} · ${htmlEscape(item.split||item.role||'角色未记录')}</p><p>范围 ${htmlEscape((item.annotation_scope||[]).join('、'))}</p><code>${htmlEscape(JSON.stringify(item.boxes||[]))}</code></article>`).join('')}</details><small>IoU 为候选配对，不证明同一目标或哪份正确；不会自动覆盖GT。</small></section>`;
}

export function bindGtConflictEvidence(root, items) {
  const section=root?.querySelector('[data-gt-evidence]');if(!section)return;
  const a=section.querySelector('[data-gt-source="a"]'),b=section.querySelector('[data-gt-source="b"]');
  if(!a||!b)return;b.value=String(Math.min(1,items.length-1));
  const update=()=>{
    const first=items[Number(a.value)],second=items[Number(b.value)],target=section.querySelector('[data-gt-overlay]');
    const same=first?.content_sha256&&first.content_sha256===second?.content_sha256&&first.width>0&&first.height>0&&first.width===second.width&&first.height===second.height;
    const valid=box=>['x1','y1','x2','y2'].every(key=>Number.isFinite(Number(box[key])))&&box.x2>box.x1&&box.y2>box.y1;
    if(!same||![...(first.boxes||[]),...(second.boxes||[])].every(valid)){target.textContent='原图身份、尺寸或坐标未核验，暂不叠加';return}
    target.innerHTML=window.materialIntegrityImage47({...first,boxes:[
      ...(first.boxes||[]).map(box=>({...box,label:`A · ${box.label||box.code||''}`,review_source:1})),
      ...(second.boxes||[]).map(box=>({...box,label:`B · ${box.label||box.code||''}`,review_source:2})),
    ]});
  };
  a.onchange=update;b.onchange=update;update();
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
    benchmarkReuseEnabled: Boolean(draft?.benchmarkReuseEnabled),
    baseVersionId: String(draft?.baseVersionId || ''),
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
  resolveBenchmarkContext,
  notify = () => {},
  fetchImpl = (...args) => fetch(...args),
  requestTimeoutMs = 30000,
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingMaterialSummaryRuntimeInstalled) return window.TrainingMaterialSummaryRuntime;
  if (typeof getState !== 'function' || typeof projectId !== 'function' || !trainingDraftRuntime) {
    throw new Error('TrainingMaterialSummaryRuntime missing dependencies');
  }

  const state = () => getState() || {};
  let destroyed = false;
  let negativeCheck = null;
  let negativeDialog = null;
  let requestSequence = 0;
  let compatibilitySequence = 0;
  let activeController = null;
  let currentSignature = null;
  let pendingSignature = null;
  let summary = null;
  let lastError = '';
  let decorateQueued = false;
  let observedCompatibilityKey = null;
  let compatibilitySignature = null;
  let compatibilityPendingSignature = null;
  let compatibility = null;
  let compatibilityFailure=null;
  let admissionContext=null;
  const admissionSessions=new WeakMap();
  let compatibilityController = null;
  let compatibilityQuery = '';
  let compatibilityIssueType = '';
  let compatibilityPage = 1;
  let compatibilityPageSize = 50;
  let comparison = null;
  let historicalDiagnosis = null;
  let diagnosticSequence = 0;
  let governanceSelection = null;
  let governanceContext = null;
  let governanceDecisions = {};
  let governanceDecisionRevision = '';
  let governanceRetainedTask = null;
  const deletionSessions=new Map();
  const topOwns=anchor=>!!anchor?.isConnected&&!anchor.closest('.hidden')&&[...document.querySelectorAll('.modal:not(.hidden)')].at(-1)?.contains(anchor);

  function captureDeletionContext(){
    return ownsAdmission()?{...admissionContext,signature:trainingCompatibilitySignature(currentDraft())}:null;
  }

  function trackMaterialDeletion(task,context){
    if(!context||!task?.task_id||task.operation!=='DELETE_INDEX'||!ownsAdmission(context)
        ||trainingCompatibilitySignature(currentDraft())!==context.signature)return;
    deletionSessions.set(task.task_id,context);
  }

  async function onMaterialBatchCompleted(task){
    const context=deletionSessions.get(task?.task_id);
    if(!context)return false;
    if(!ownsAdmission(context)||trainingCompatibilitySignature(currentDraft())!==context.signature
        ||task.project_id&&String(task.project_id)!==context.projectId){deletionSessions.delete(task.task_id);return false;}
    const succeeded=new Set();let cursor='';const cursors=new Set();
    do{
      if(cursors.has(cursor))throw new Error('删除结果分页异常，请重新查询任务');cursors.add(cursor);
      const page=await withRequestDeadline(async signal=>readJson(await fetchImpl(`/api/v62/projects/${encodeURIComponent(context.projectId)}/material-batches/${encodeURIComponent(task.task_id)}/results?limit=100&cursor=${encodeURIComponent(cursor)}`,{signal}),'删除结果读取失败'),{timeoutMs:30000,label:'删除结果核验'});
      for(const item of page.items||[])if((item.item_state||item.state)==='succeeded'&&item.logical_removed===true)succeeded.add(String(item.image_id));
      cursor=page.next_cursor||'';
    }while(cursor);
    if(!ownsAdmission(context)||trainingCompatibilitySignature(currentDraft())!==context.signature){deletionSessions.delete(task.task_id);return false;}
    deletionSessions.delete(task.task_id);
    if(succeeded.size)removeResolvedTrainingMaterials(trainingDraftRuntime,currentDraft(),[...succeeded]);
    invalidate();await refresh(currentIds(),{force:true});
    window.TrainingSubmitRuntime?.updateReadiness?.();
    notify(`删除任务已核验：实际移除 ${succeeded.size} 张；失败或未处理项继续保留在训练选择中`);
    return true;
  }

  async function excludeSelectedFromDraft(imageId){
    if(historicalDiagnosis||!governanceContext)return false;
    const anchor=document.querySelector('[data-training-compatibility-dialog]'),pid=String(projectId()||'');
    const draft=currentDraft(),signature=trainingCompatibilitySignature(draft),context=governanceContext;
    const selected=imageId?{image_ids:[imageId]}:governanceSelection;
    if(!imageId&&!selected?.count)return notify('请先选择问题素材');
    const controls=[...(anchor?.querySelectorAll('button')||[])];controls.forEach(button=>button.disabled=true);
    try{
      const resolved=await withRequestDeadline(async signal=>readJson(await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-materials/compatibility`,{
        method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({...compatibilityPayload(draft),selection_action:'RESOLVE_SELECTION',
          expected_material_revision:context.truth.material_revision,expected_annotation_revision:context.truth.annotation_revision,
          selection:{...selected,query:compatibilityQuery,issue_type:compatibilityIssueType}})}),'训练问题选择解析失败'),{timeoutMs:30000,label:'核验排除范围'});
      if(destroyed||String(projectId()||'')!==pid||trainingCompatibilitySignature(currentDraft())!==signature||!topOwns(anchor))return false;
      const ids=uniqueIds(resolved.matching_image_ids);
      if(!ids.length)return notify('当前选择没有可排除的问题素材，请重新检查');
      if(!window.confirm(`仅从本次训练排除 ${ids.length} 张问题素材，保留素材库、GT 和历史证据；随后重新检查全部准入条件。确认继续？`))return false;
      removeResolvedTrainingMaterials(trainingDraftRuntime,draft,ids,resolved);
      invalidate();await refresh(currentIds(),{force:true});const result=await refreshCompatibility({force:true});
      if(result&&String(projectId()||'')===pid&&topOwns(anchor))openCompatibilityIssues();
      return true;
    }catch(error){notify(error.message||String(error));return false}
    finally{controls.forEach(button=>{if(button.isConnected)button.disabled=false})}
  }

  function governanceTools(truth, source='draft') {
    const decisionRevision=JSON.stringify([projectId(),truth.material_revision,truth.annotation_revision]);
    if(governanceDecisionRevision!==decisionRevision){governanceDecisions={};governanceDecisionRevision=decisionRevision;}
    const key=JSON.stringify([projectId(),source,compatibilityQuery,compatibilityIssueType,
      truth.material_revision,truth.annotation_revision,source==='draft'?trainingCompatibilitySignature(currentDraft()):'']);
    governanceContext={key,total:Number(truth.filtered_affected_image_count??truth.governance_eligible_count??0),allTotal:Number(truth.affected_image_count||0),rows:truth.items||[],truth,source};
    governanceSelection=updateTrainingGovernanceSelection(governanceSelection,governanceContext);
    if(governanceRetainedTask?.projectId===String(projectId()||'')&&governanceRetainedTask.source===source){
      governanceSelection={...governanceSelection,all_filtered:false,image_ids:[],excluded_image_ids:[],
        count:governanceRetainedTask.count,previous_execution_task_id:governanceRetainedTask.task_id};
      governanceRetainedTask=null;
    }
    return `<section class="training-governance-tools"><div class="row"><button class="btn" data-governance-mode="page">全选当前页</button><button class="btn" data-governance-mode="all">全选当前筛选结果</button><button class="btn" data-governance-mode="issues">全选全部训练问题</button><button class="btn" data-governance-mode="clear">取消全选</button><span data-governance-selected aria-live="polite">已选 ${governanceSelection.count} 张 · 排除 ${governanceSelection.excluded_image_ids.length} 张</span>${source==='draft'?'<button class="btn" data-governance-exclude>批量排除本次训练</button>':''}<select class="select" data-governance-delete-mode aria-label="删除模式"><option value="DISCARD">丢弃所选 · 可整组删除</option><option value="KEEP_ONE">保留一份 · 人工指定保留项</option></select><button class="btn danger" data-governance-preview>删除已选 · 安全预览</button></div><p>排除只调整当前训练草稿；删除会移除当前素材及 GT。整组删除无需保留项；历史证据保留，活动或共享图片物理字节延后保留。范围由服务端冻结并复验。</p><div data-governance-error role="alert" hidden></div></section>`;
  }

  function refreshGovernanceChecks() {
    const root=document.querySelector('[data-training-compatibility-dialog]');
    root?.querySelectorAll('[data-governance-check]').forEach(input=>{
      input.checked=governanceSelection?.all_filtered||governanceSelection?.all_issues
        ? !governanceSelection.excluded_image_ids.includes(input.dataset.governanceCheck)
        : governanceSelection?.image_ids.includes(input.dataset.governanceCheck);
    });
    const label=root?.querySelector('[data-governance-selected]');
    if(label)label.textContent=governanceSelection.previous_execution_task_id
      ? `原任务未删除 ${governanceSelection.count} 张 · 服务端冻结选择已保留（重新勾选可调整）`
      : `已选 ${governanceSelection.count} 张 · 排除 ${governanceSelection.excluded_image_ids.length} 张`;
  }

  async function previewGovernance(imageId) {
    if(!governanceContext)return;
    const selected=imageId?{all_filtered:false,image_ids:[imageId],excluded_image_ids:[],count:1}:governanceSelection;
    if(!selected?.count)return notify('请先选择素材');
    const context=governanceContext,pid=String(projectId()||''),sourceTask=historicalDiagnosis?.task_id;
    const sequence=diagnosticSequence,draftSignature=trainingCompatibilitySignature(currentDraft());
    const deletionContext=captureDeletionContext();
    const dialog=document.querySelector('[data-training-compatibility-dialog]')?.closest('[role="dialog"]');
    const filters={query:compatibilityQuery,issueType:compatibilityIssueType};
    const body={...selected, query:compatibilityQuery,issue_type:compatibilityIssueType,
      expected_material_revision:context.truth.material_revision,
      expected_annotation_revision:context.truth.annotation_revision,manual_decisions:governanceDecisions,
      delete_mode:document.querySelector('[data-governance-delete-mode]')?.value||'DISCARD',
      ...(sourceTask?{training_task_id:sourceTask}:{training_selection:compatibilityPayload()})};
    const errorBox=document.querySelector('[data-governance-error]');
    const buttons=[...document.querySelectorAll('[data-governance-preview],[data-conflict-delete]')];
    buttons.forEach(button=>button.disabled=true);
    if(errorBox)errorBox.hidden=true;
    try {
      await window.previewTrainingIntegrityGovernance47({payload:body,projectId:pid,
        onCreated:task=>trackMaterialDeletion(task,deletionContext),
        isCurrent:()=>!destroyed&&String(projectId()||'')===pid&&governanceContext===context&&diagnosticSequence===sequence
          &&Boolean(dialog?.isConnected&&!dialog.closest('.hidden'))
          &&[...document.querySelectorAll('.modal:not(.hidden)')].at(-1)===dialog
          &&(sourceTask||trainingCompatibilitySignature(currentDraft())===draftSignature),
        onReturn:async(task)=>{
          const returnAnchor=document.querySelector('.material-integrity47-plan');
          if(task&&['PARTIAL_SUCCESS','FAILED','CANCELLED'].includes(task.status)&&Number(task.total||0)>Number(task.succeeded||0)){
            governanceRetainedTask={projectId:pid,source:context.source,task_id:task.task_id,count:Number(task.total||0)-Number(task.succeeded||0)};
          }
          if(sourceTask)return openTaskDiagnosis(sourceTask);
          if(String(projectId()||'')!==pid||!ownsAdmission())return;
          if(task)await onMaterialBatchCompleted(task);
          const result=await refreshCompatibility({force:true,...filters});if(result&&topOwns(returnAnchor))openCompatibilityIssues();
        }});
    } catch(error) { if(errorBox?.isConnected){errorBox.hidden=false;errorBox.textContent=error.message||String(error)}notify(error.message||String(error)); }
    finally {buttons.forEach(button=>button.disabled=false);}
  }

  function ownsAdmission(context=admissionContext){
    return !!context&&!destroyed&&context.root?.isConnected&&!context.root.closest?.('.hidden')&&String(projectId()||'')===context.projectId
      &&document.querySelector('.train429-create')===context.root
      &&String(document.getElementById('tr429TaskId')?.value||'')===context.taskId;
  }

  function openAdmissionDiagnosis(){
    const context=admissionContext;if(!ownsAdmission(context))return false;
    const session=admissionSessions.get(context.root);
    if(session?.checkedSignature!==context.signature||!context.readiness.blockers.some(row=>!row.transient))return false;
    const {readiness,draft,algorithmName}=context;
    const details=readiness.blockers.filter(row=>!row.transient);
    const title=readiness.ready?'训练准入检查已通过':'训练暂不可开始';
    const html=`<div data-training-compatibility-dialog data-training-admission-dialog>
      <div class="alert ${readiness.ready?'success':'warn'}"><b>${title}</b><p>${htmlEscape(algorithmName)} · 本次选择 ${uniqueIds(draft?.materialIds).length} 张训练素材</p></div>
      <ul class="training-admission-reasons">${details.map(row=>`<li data-admission-code="${htmlEscape(row.code)}"><b>${htmlEscape(row.message)}</b>${row.count!=null?`<span> · ${Number(row.count)} ${htmlEscape(row.count_unit||'张')}</span>`:''}</li>`).join('')||(readiness.ready?'<li>已完成全部已知准入检查，可返回训练配置开始训练。</li>':'<li>正在完成准入检查，请稍候</li>')}</ul>
      <div class="row"><button class="btn" data-admission-materials>查看全部问题 · 批量处理</button><button class="btn" data-admission-recheck>重新检查</button><button class="btn primary" data-admission-return>返回训练配置</button></div><div data-admission-status aria-live="polite"></div></div>`;
    showDiagnosticDialog(title,html);
    const root=document.querySelector('[data-training-admission-dialog]');
    root?.querySelector('[data-admission-return]')?.addEventListener('click',()=>window.closeModal?.());
    root?.querySelector('[data-admission-materials]')?.addEventListener('click',()=>{if(ownsAdmission(context))openCompatibilityIssues()});
    root?.querySelector('[data-admission-recheck]')?.addEventListener('click',()=>{
      if(!ownsAdmission(context))return;
      window.closeModal?.();
      void window.TrainingSubmitRuntime?.submit?.();
    });
    return true;
  }

  function updateAdmissionDiagnosis(context){
    if(!context?.root){admissionContext=null;return;}
    admissionContext=context;if(!ownsAdmission(context))return;
    const {root,taskId,readiness}=context;
    let session=admissionSessions.get(root);
    if(!session||session.taskId!==taskId){session={taskId,checkedSignature:null};admissionSessions.set(root,session);}
    if(context.checked)session.checkedSignature=context.signature;
    if(context.reset||session.checkedSignature!==context.signature)session.checkedSignature=null;
    const valid=session.checkedSignature===context.signature;
    const blocked=valid&&readiness.blockers.some(row=>!row.transient);
    const footer=root.querySelector('.train428-footer');
    let entry=footer?.querySelector('[data-training-admission-open]');
    if(footer&&!entry&&blocked){entry=document.createElement('button');entry.className='btn';entry.type='button';entry.dataset.trainingAdmissionOpen='1';entry.textContent='查看不能训练的原因';entry.onclick=()=>openAdmissionDiagnosis();footer.append(entry);}
    if(entry&&!blocked)entry.remove();
    const diagnostic=document.querySelector('[data-training-admission-dialog]');
    if(diagnostic&&!valid){const status=diagnostic.querySelector('[data-admission-status]');setTextIfChanged(status,'配置或素材已变化，此诊断已过期，请返回训练配置重新检查。');}
  }


  function currentIds() {
    return uniqueIds(trainingDraftRuntime.materialIds?.() || state().trainingDraft?.materialIds || []);
  }

  function currentDraft() {
    return state().trainingDraft || trainingDraftRuntime.current?.() || null;
  }

  function compatibilityPayload(draft = currentDraft(), overrides = {}) {
    const benchmark = draft?.benchmarkReuseEnabled ? resolveBenchmarkContext?.({draft,
      asset:(state().algorithms||[]).find(item=>String(item.id)===String(draft.algorithmId)),benchmark:state().trainingBenchmarkReuse}) : null;
    if(draft?.benchmarkReuseEnabled&&!benchmark)throw new Error('固定评测基准尚未就绪，不能生成治理范围');
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
      ...(benchmark?{benchmark_source_version_id:benchmark.sourceVersionId,benchmark_scope_id:benchmark.scopeId}:{}),
      limit: 50,
      ...overrides,
    };
  }

  function beforeModalClose(layer) {
    if(negativeDialog?.node&&layer?.contains?.(negativeDialog.node))negativeDialog.finish(false,false);
    if(negativeCheck?.root&&layer?.contains?.(negativeCheck.root))negativeCheck.controller.abort();
  }
  async function confirmPendingNegatives({draft=currentDraft(),root,isCurrent=()=>true}={}) {
    // An insufficient selection cannot start training; the existing admission
    // owner must report its materials/label blockers together.
    if(uniqueIds(draft?.materialIds).length<2)return true;
    if(negativeCheck)throw new Error('负样本确认正在处理，请勿重复提交');
    const controller=new AbortController(),pid=String(projectId()||''),payload=compatibilityPayload(draft);
    const current=()=>!destroyed&&!controller.signal.aborted&&String(projectId()||'')===pid&&isCurrent();
    negativeCheck={root,controller};
    const post=(action,body)=>withRequestDeadline(async signal=>readJson(await fetchImpl(
      `/api/v62/projects/${encodeURIComponent(pid)}/training-materials/${action}`,{method:'POST',signal,
        headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),'负样本核验失败'),
      {timeoutMs:requestTimeoutMs,signal:controller.signal,label:'负样本核验'});
    try {
      const preview=await post('negative-preview',payload);
      if(!current())return false;
      // Invalid/stale GT must use the existing diagnosis, never an absence assertion.
      if(Number(preview.counts?.pending_review))return true;
      if(!Number(preview.counts?.positive)&&Object.values(preview.counts||{}).some(Number))throw new Error('本次素材没有所选目标的有效正样本，不能创建全负样本目标检测训练。');
      if(!Number(preview.pending_count))return true;
      if(typeof window.modal!=='function')throw new Error('负样本确认窗口不可用，请刷新后重试');
      const accepted=await new Promise(resolve=>{
        const c=preview.counts||{},layer=window.modal('本次训练包含待确认负样本',
          `<section data-training-negative-confirmation><p>本次目标：<b>${htmlEscape((preview.effective_label_codes||[]).join('、'))}</b></p><p>正样本 ${Number(c.positive)||0} · 已确认负样本 ${Number(c.confirmed_negative)||0} · 待确认负样本 ${Number(preview.pending_count)||0}</p><p>请确认待确认图片不包含本次目标类别，避免漏标影响模型效果。确认仅记录对应目标和素材版本，不修改原图或正式标注。</p><div class="training-negative-previews">${(preview.pending_preview||[]).map(row=>`<figure><img src="${htmlEscape(row.image_url||'')}" alt="待确认素材 ${htmlEscape(row.image_id)}" loading="lazy"><figcaption>${htmlEscape(row.image_id)}</figcaption></figure>`).join('')}</div><p class="muted">${Number(preview.pending_count)>20?'仅预览前20张；如尚未检查全部素材，请返回检查。':''}</p><div class="row end"><button type="button" class="btn" data-negative-return>返回检查</button><button type="button" class="btn primary" data-negative-confirm>确认并创建训练任务</button></div></section>`,true);
        const node=layer?.querySelector?.('[data-training-negative-confirmation]')||document.querySelector('[data-training-negative-confirmation]');
        if(!node){resolve(false);return;}
        let settled=false;
        const finish=(value,close=true)=>{if(settled)return;settled=true;negativeDialog=null;controller.signal.removeEventListener('abort',abort);if(close)window.closeModalLayer424?.(layer);resolve(value)};
        const abort=()=>finish(false);negativeDialog={node,finish};controller.signal.addEventListener('abort',abort,{once:true});
        node.querySelector('[data-negative-return]').onclick=()=>finish(false);
        node.querySelector('[data-negative-confirm]').onclick=()=>finish(true);
      });
      if(!accepted||!current())return false;
      await post('confirm-negatives',{...payload,confirmed:true,proof_digest:preview.proof_digest});
      if(!current())return false;
      invalidate();await refresh(currentIds(),{force:true});
      return current();
    }finally{negativeDialog?.finish(false);negativeCheck=null;}
  }

  function compatibilityFor(draft = currentDraft()) {
    const signature = trainingCompatibilitySignature(draft || {});
    if (compatibilityPendingSignature === signature) {
      return {ready: false, loading: true, issue_count: null, signature};
    }
    if(compatibilityFailure?.signature===signature)return {ready:false,loading:false,issue_count:null,signature,error:compatibilityFailure.message};
    if (compatibilitySignature !== signature || !compatibility) {
      return {ready: false, loading: false, issue_count: null, signature};
    }
    return {...compatibility, ready: true, loading: false, signature};
  }

  function labelDisplay(code) {
    const row = (state().labels || []).find(item => String(item?.code || '') === String(code));
    return String(row?.display_name || row?.display_name_zh || row?.name || code || '');
  }

  function pickerDraftPayload() {
    const draft=currentDraft();
    return {algorithm_asset_id:String(draft?.algorithmId||''),train_labels:uniqueIds(draft?.newLabelCodes),
      model:String(draft?.config?.model||'yolo11n.pt'),framework:String(draft?.config?.framework||'ultralytics'),
      base_version_id:String(draft?.baseVersionId||'')};
  }
  function summaryRequestSignature(ids) {
    return JSON.stringify([String(projectId()||''),trainingMaterialSelectionSignature(ids),pickerDraftPayload()]);
  }

  function summaryReadyFor(ids = currentIds()) {
    return currentSignature === summaryRequestSignature(ids) && Boolean(summary) && !pendingSignature;
  }

  function summaryFor(ids = currentIds()) {
    return summaryReadyFor(ids) ? summary : null;
  }

  function selectedLabelCodes(ids = currentIds()) {
    return uniqueIds(summaryFor(ids)?.positive_label_codes || []);
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
        ? `${baseLabels} · 正式标注 ${summary.eligible_count} / 待标注 ${summary.pending_annotation_count}`
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
    const host = document.querySelector?.('.train429-data-summary') || document.querySelector?.('.train429-create .train-v3-summary')?.parentElement;
    if (host) {
      let row = host.querySelector?.('[data-training-compatibility-summary]');
      if (!row) {
        row = document.createElement('div');
        row.dataset.trainingCompatibilitySummary = '1';
        host.appendChild(row);
      }
      const truth = compatibilityFor();
      const count = Number(truth.affected_image_count ?? truth.issue_count ?? 0);
      const sampleHtml=ready?renderTrainingSampleRoles(summary):'';
      const nextHtml = sampleHtml + (truth.error
        ? '<span>训练输入检查</span><b class="err">检查失败 · 可重试</b><button class="btn mini" type="button" data-training-compatibility-open>查看原因并重试</button>'
        : truth.loading || !truth.ready
        ? `<span>训练输入检查</span><b>${truth.loading?'检查中…':'点击开始训练后检查'}</b>`
        : count
          ? `<span>训练输入检查</span><b class="warn">${count} 张需处理</b><button class="btn mini" type="button" data-training-compatibility-open>查看并处理冲突</button>`
          : '<span>标签适配</span><b>已通过</b>');
      if(row.dataset.compatibilityRenderKey!==nextHtml){row.dataset.compatibilityRenderKey=nextHtml;row.innerHTML=nextHtml;row.querySelector?.('[data-training-compatibility-open]')?.addEventListener?.('click', () => openCompatibilityIssues());}
    }
  }

  function queueDecorate() {
    if (destroyed || decorateQueued) return;
    decorateQueued = true;
    queueMicrotask(() => {
      decorateQueued = false;
      window.TrainingSubmitRuntime?.cancelStaleCheck?.();
      decorateTrainingCreateUi();
    });
  }

  async function refresh(ids = currentIds(), {force = false} = {}) {
    const normalizedIds = uniqueIds(ids);
    const signature = summaryRequestSignature(normalizedIds);
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
      const body = await withRequestDeadline(async signal=>readJson(await fetchImpl(
        `/api/v62/projects/${encodeURIComponent(pid)}/training-materials/selection-summary`,
        {
          method: 'POST',
          signal,
          headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
          body: JSON.stringify({...pickerDraftPayload(),image_ids: normalizedIds}),
        },
      ),'训练素材摘要读取失败'),{timeoutMs:requestTimeoutMs,label:'训练素材摘要',signal:activeController.signal});
      if (destroyed || sequence !== requestSequence || String(projectId()||'')!==pid) return null;
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
        positive_label_codes: uniqueIds(body.positive_label_codes),
        effective_label_codes: uniqueIds(body.effective_label_codes),
        sample_role_counts: body.sample_role_counts || null,
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

  async function refreshCompatibility({force = false, payload = null, signal: externalSignal = null, query = '', issueType = '', page = 1, pageSize = 50} = {}) {
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
    if(externalSignal?.aborted)return null;
    const sequence = ++compatibilitySequence;
    compatibilityController?.abort?.();
    compatibilityController = new AbortController();
    const controller=compatibilityController;
    const abort=()=>controller.abort();
    externalSignal?.addEventListener('abort',abort,{once:true});
    compatibilityPendingSignature = signature;
    compatibilityFailure=null;
    queueDecorate();
    try {
      const requestBody = payload ? {...payload} : compatibilityPayload(draft);
      Object.assign(requestBody, {
        query,
        issue_type: issueType,
        page,
        page_size: pageSize,
      });
      const body = await withRequestDeadline(async signal=>readJson(await fetchImpl(
        `/api/v62/projects/${encodeURIComponent(pid)}/training-materials/compatibility`,
        {
          method: 'POST',
          signal,
          headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
          body: JSON.stringify(requestBody),
        },
      ),'训练标签适配检查失败'),{timeoutMs:requestTimeoutMs,label:'训练准入检查',signal:controller.signal});
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
      if (sequence !== compatibilitySequence) return null;
      if (error?.name === 'AbortError') { compatibilityPendingSignature=null;queueDecorate();return null; }
      compatibilityPendingSignature = null;
      compatibility = null;
      compatibilityFailure={signature,message:String(error?.message||error||'训练检查失败')};
      lastError = String(error?.message || error || '训练标签适配检查失败');
      queueDecorate();
      window.TrainingSubmitRuntime?.updateReadiness?.();
      notify(lastError);
      return null;
    } finally { externalSignal?.removeEventListener('abort',abort); }
  }

  function issueHtml(item) {
    if (['duplicate_annotation_conflict','content_hash_leakage'].includes(item?.issue_type)) {
      const leakage = item.issue_type === 'content_hash_leakage';
return `<article class="training-compatibility-item"><img src="${htmlEscape(item.thumbnail_url||item.content_url||'')}" alt="${htmlEscape(item.filename||item.image_id)}" loading="lazy"><div><b>${htmlEscape(item.filename||item.image_id)}</b><small>${htmlEscape(item.image_id)} · ${htmlEscape(item.role||'')}</small><p>${leakage?'同 SHA 跨训练/试验集：调整选择后必须完整复检，不能直接忽略':'原始正式标注冲突：'+htmlEscape((item.conflict_types||[]).join('、'))}</p><p>${htmlEscape(item.annotation_state)} · 范围 ${htmlEscape((item.annotation_scope||[]).join('、'))} · ${Number(item.box_count||0)} 框</p><code>${htmlEscape(item.content_sha256)}</code><div class="row"><button class="btn primary" data-duplicate-compare="${htmlEscape(item.content_sha256)}">查看标注差异</button><button class="btn" data-conflict-review="${htmlEscape(item.image_id)}">去补审 / 核对当前标注</button><button class="btn" data-conflict-exclude="${htmlEscape(item.image_id)}" >仅排除本次训练</button></div></div></article>`;
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
    const tools=governanceTools(truth);
    const html = `<div class="training-compatibility-list"><div class="alert warn"><b>${Number(truth.affected_image_count||0)} 张素材 · ${truth.issue_count} 条训练问题</b><span>补审只记录你明确检查过的标签；AI 未检出不会自动确认不存在。</span></div><div class="row"><input id="trainingCompatibilityQuery" class="input" value="${htmlEscape(compatibilityQuery)}" placeholder="搜索文件名 / image_id"><select id="trainingCompatibilityType" class="select"><option value="">全部异常</option>${issueTypes.map(type=>`<option value="${htmlEscape(type)}" ${type===compatibilityIssueType?'selected':''}>${htmlEscape(ISSUE_NAMES[type]||type)} · ${Number(truth.issue_counts[type]||0)}</option>`).join('')}</select><button class="btn" type="button" onclick="TrainingMaterialSummaryRuntime.applyIssueFilters()">筛选</button></div>${tools}<div class="item-sub">筛选 ${Number(truth.filtered_affected_image_count||0)} 张 · ${Number(truth.filtered_count||0)} 条问题 · 当前 ${rows.length?offset+1:0}-${offset+rows.length}</div>${rows.map(issueHtml).join('') || '<div class="empty">当前筛选没有问题素材</div>'}<div id="trainingCompatibilityPager"></div></div>`;
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
    const top=[...document.querySelectorAll('.modal:not(.hidden)')].at(-1);
    const existing=top?.querySelector('[data-training-compatibility-dialog]')
      ||(state().materialIntegrityTrainingContext47?.projectId===String(projectId()||'')?top?.querySelector('.material-integrity47-plan'):null);
    const body=existing?.closest('.modal-body');
    if(body){body.innerHTML=html;const heading=body.parentElement.querySelector('.modal-title');if(heading)heading.textContent=title}
    else window.modal?.(title,html,true);
  }

  function bindDiagnosticActions() {
    const root=document.querySelector('[data-training-compatibility-dialog]');if(!root)return;
    if(comparison)bindGtConflictEvidence(root,comparison.items);
    if(!root.querySelector('[data-project-gt-review]')){
      const reviewButton=document.createElement('button');reviewButton.className='btn';reviewButton.dataset.projectGtReview='';reviewButton.textContent='项目GT冲突 · 批量辅助审核';
      reviewButton.onclick=async()=>{
        const pid=String(projectId()||'');await window.openMaterialIntegrityAudit47();
        if(String(projectId()||'')!==pid||destroyed)return;
        await window.openGtConflictReview47();
        const workbench=document.querySelector('.gt-review-workbench');
        if(workbench){const back=document.createElement('button');back.className='btn';back.textContent='返回训练输入检查';back.onclick=()=>returnFromReview();workbench.querySelector('footer')?.append(back)}
      };
      root.prepend(reviewButton);
    }
    if(historicalDiagnosis&&!comparison&&!root.querySelector('.training-governance-tools')) {
      root.querySelector('.training-compatibility-list')?.insertAdjacentHTML('afterbegin',`<div class="row"><input id="trainingCompatibilityQuery" class="input" aria-label="搜索当前冲突" placeholder="搜索文件名 / SHA256 / Image ID" value="${htmlEscape(compatibilityQuery)}"><select id="trainingCompatibilityType" class="select" aria-label="冲突类型"><option value="">全部冲突</option><option value="duplicate_annotation_conflict">同图不同标注</option><option value="content_hash_leakage">Train / Test 内容冲突</option></select><button class="btn" data-history-filter>筛选</button></div>`+governanceTools(historicalDiagnosis.current_diagnosis||{},`task:${historicalDiagnosis.task_id}`));
      const select=root.querySelector('#trainingCompatibilityType');if(select)select.value=compatibilityIssueType;
      root.querySelector('[data-history-filter]')?.addEventListener('click',()=>{
        compatibilityQuery=String(root.querySelector('#trainingCompatibilityQuery')?.value||'').trim();
        compatibilityIssueType=String(root.querySelector('#trainingCompatibilityType')?.value||'');
        void openTaskDiagnosis(historicalDiagnosis.task_id);
      });
    }
    root.querySelectorAll('[data-duplicate-compare]').forEach(button=>button.onclick=()=>openDuplicateComparison(button.dataset.duplicateCompare));
    root.querySelectorAll('[data-conflict-review]').forEach(button=>button.onclick=()=>openReview(button.dataset.conflictReview));
    root.querySelectorAll('[data-conflict-exclude]').forEach(button=>{
      if(historicalDiagnosis)button.disabled=true;
      button.onclick=()=>{if(!button.disabled)excludeFromDraft(button.dataset.conflictExclude)};
    });
    root.querySelector('[data-training-recheck]')?.addEventListener('click',async()=>{
      if(historicalDiagnosis)return openTaskDiagnosis(historicalDiagnosis.task_id);
      const controls=[...root.querySelectorAll('[data-governance-check],[data-governance-mode],[data-governance-preview],[data-conflict-delete],[data-training-recheck]')];
      const disabled=controls.map(control=>control.disabled);controls.forEach(control=>control.disabled=true);root.setAttribute('aria-busy','true');
      const result=await refreshCompatibility({force:true,query:compatibilityQuery,issueType:compatibilityIssueType});
      if(result&&topOwns(root))openCompatibilityIssues();
      else if(root.isConnected){controls.forEach((control,index)=>control.disabled=disabled[index]);root.removeAttribute('aria-busy');}
    });
    root.querySelector('[data-training-undo-exclusions]')?.addEventListener('click',async()=>{
      const review=currentDraft()?.duplicateReview;if(!review)return;
      trainingDraftRuntime.update({materialIds:review.original_train_image_ids,testMaterialIds:review.original_test_image_ids,duplicateReview:null});
      invalidateCompatibility();const result=await refreshCompatibility({force:true});if(result)openCompatibilityIssues();
    });
    root.querySelector('[data-comparison-back]')?.addEventListener('click',async()=>{if(historicalDiagnosis)return openTaskDiagnosis(historicalDiagnosis.task_id);const result=await refreshCompatibility({force:true,...comparison?.origin});if(result)openCompatibilityIssues()});
    root.querySelectorAll('[data-comparison-page]').forEach(button=>button.onclick=()=>openDuplicateComparison(comparison.hash,Number(button.dataset.comparisonPage)));
    root.querySelectorAll('[data-task-diagnosis-page]').forEach(button=>button.onclick=()=>openTaskDiagnosis(historicalDiagnosis.task_id,Number(button.dataset.taskDiagnosisPage)));
    if(!comparison){
      root.querySelectorAll('.training-compatibility-item').forEach((article,index)=>{
        const item=governanceContext?.rows[index];
        if(!item)return;
        const label=document.createElement('label');label.className='training-governance-check';
        const input=document.createElement('input');input.type='checkbox';input.dataset.governanceCheck=item.image_id;
        input.setAttribute('aria-label',`选择 ${item.filename||item.image_id}`);
        input.onchange=()=>{governanceSelection=updateTrainingGovernanceSelection(governanceSelection,{...governanceContext,mode:'toggle',id:item.image_id,checked:input.checked});refreshGovernanceChecks()};
        label.append(input,document.createTextNode('选择图片'));article.prepend(label);
        const button=document.createElement('button');button.className='btn danger';button.textContent='单张删除 · 先预览';button.dataset.conflictDelete=item.image_id;button.onclick=()=>previewGovernance(item.image_id);article.querySelector('.row')?.append(button);
      });
    }
    root.querySelectorAll('[data-governance-mode]').forEach(button=>button.onclick=()=>{
      governanceSelection=updateTrainingGovernanceSelection(governanceSelection,{...governanceContext,mode:button.dataset.governanceMode,ids:uniqueIds(governanceContext.rows.map(item=>item.image_id))});
      refreshGovernanceChecks();
    });
    root.querySelector('[data-governance-preview]')?.addEventListener('click',()=>previewGovernance());
    root.querySelector('[data-governance-exclude]')?.addEventListener('click',()=>excludeSelectedFromDraft());
    root.querySelectorAll('[data-conflict-review]').forEach(button=>{
      if(!comparison)return;
      const item=comparison.items.find(row=>row.image_id===button.dataset.conflictReview);if(!item)return;
      const keeper=document.createElement('button');keeper.className='btn';keeper.dataset.conflictKeeper=item.image_id;
      keeper.textContent='人工确认 · 作为本组保留项';keeper.onclick=()=>{
        governanceDecisions[`DUPLICATE_ANNOTATION_CONFLICT:${item.content_sha256}`]=item.image_id;
        keeper.textContent='已明确保留 · 删除仍须安全预览';notify('已记录本组人工保留项；整组丢弃无需选择保留项');
      };button.parentElement.append(keeper);
    });
    if(comparison){
      const discard=document.createElement('button');discard.className='btn danger';discard.textContent='整组删除 · 不保留任何项';
      discard.onclick=()=>{
        const truth=comparison.truth;
        compatibilityQuery=comparison.hash;compatibilityIssueType=comparison.items[0]?.issue_type||'duplicate_annotation_conflict';
        governanceContext={...governanceContext,key:JSON.stringify([projectId(),comparison.hash,truth.material_revision,truth.annotation_revision]),
          total:Number(truth.filtered_affected_image_count||0),allTotal:Number(truth.affected_image_count||0),rows:comparison.items,truth};
        governanceSelection=updateTrainingGovernanceSelection(null,{...governanceContext,mode:'all'});
        void previewGovernance();
      };
      root.append(discard);
    }
    refreshGovernanceChecks();
  }

  async function openDuplicateComparison(hash, page=1) {
    const pid=String(projectId()||'');
    const origin=comparison?.origin||{query:compatibilityQuery,issueType:compatibilityIssueType,page:compatibilityPage,pageSize:compatibilityPageSize};
    const sequence=++diagnosticSequence,sourceTask=historicalDiagnosis?.task_id;
    const draftSignature=trainingCompatibilitySignature(currentDraft());
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
      const evidence=result.items.length?await readJson(await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/material-integrity/gt-comparison`,{
        method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:result.items.map(item=>item.image_id),
          expected_material_revision:result.material_revision,expected_annotation_revision:result.annotation_revision}),
      }), '正式GT差异读取失败'):{items:[],diagnosis:{}};
      const rows=result.items.map(item=>({...item,...evidence.items.find(row=>row.image_id===item.image_id)}));
      if(String(projectId()||'')!==pid||destroyed||sequence!==diagnosticSequence||anchor&&!topOwns(anchor)
          ||!sourceTask&&trainingCompatibilitySignature(currentDraft())!==draftSignature)return false;
      comparison={hash:String(hash),page,items:rows,origin,truth:result};historicalDiagnosis=sourceTask?history:null;
      const decisionRevision=JSON.stringify([pid,result.material_revision,result.annotation_revision]);
      if(governanceDecisionRevision!==decisionRevision){governanceDecisions={};governanceDecisionRevision=decisionRevision;}
      const cards=rows.map(item=>`<article>${window.materialIntegrityImage47?.(item)||`<img src="${htmlEscape(item.content_url)}" alt="${htmlEscape(item.filename)}">`}<div class="material-integrity47-meta"><b>${htmlEscape(item.filename)}</b><code>${htmlEscape(item.image_id)}</code><p>原始正式 GT · ${htmlEscape(item.role)} · ${htmlEscape(item.annotation_state)} · ${Number(item.box_count)} 框</p><p>类别 ${htmlEscape((item.labels||[]).join('、'))} · 范围 ${htmlEscape((item.annotation_scope||[]).join('、'))}</p><small>差异 ${htmlEscape((item.conflict_types||[]).join('、'))}</small><code>${htmlEscape(item.annotation_digest)}</code><p>${htmlEscape((item.reference_reasons||[]).map(reason=>window.materialIntegrityProtectionText47?.(reason)||reason.reason).join('；')||'本页未返回历史保护原因；不是删除许可')}</p><div class="row"><button class="btn primary" data-conflict-review="${htmlEscape(item.image_id)}">人工核对这份标注</button><button class="btn" data-conflict-exclude="${htmlEscape(item.image_id)}">仅排除本次训练</button></div></div></article>`).join('');
      showDiagnosticDialog('重复素材标注差异',`<div data-training-compatibility-dialog class="training-duplicate-comparison"><div class="alert warn"><b>同一图片内容，不同正式 Ground Truth</b><p>系统不判断哪份正确，也不会覆盖历史模型、Snapshot 或 Test。修改通过原标注工作台保存；排除只影响本次新训练，保留可审计记录。</p><code>SHA256 ${htmlEscape(hash)}</code></div>${rows.length?`<div class="material-integrity47-grid">${cards}</div>`:'<div class="alert ok">本组当前冲突已解除，请重新检查完整训练选择。</div>'}<div class="row between"><button class="btn" data-comparison-back>返回完整预检</button><div class="row"><button class="btn" data-comparison-page="${page-1}" ${page>1?'':'disabled'}>上一页对比</button><span>第 ${page} / ${result.total_pages||1} 页 · 每页最多 2 张</span><button class="btn" data-comparison-page="${page+1}" ${result.has_next?'':'disabled'}>下一页对比</button></div><button class="btn" data-training-recheck>重新预检</button></div></div>`);
      const comparisonRoot=document.querySelector('.training-duplicate-comparison');
      if(comparisonRoot)comparisonRoot.insertAdjacentHTML('afterbegin',renderGtConflictEvidence(evidence.diagnosis,rows));
      bindDiagnosticActions();return true;
    }catch(error){notify(String(error.message||error));return false}
  }

  async function openTaskDiagnosis(taskId,page=1) {
    const pid=String(projectId()||'');
    if(historicalDiagnosis?.task_id!==taskId){compatibilityQuery='';compatibilityIssueType='';}
    const sequence=++diagnosticSequence;
    showDiagnosticDialog('训练输入冲突诊断','<div data-training-compatibility-dialog role="status">正在读取持久任务证据和当前正式标注…</div>');
    const anchor=document.querySelector('[data-training-compatibility-dialog]');
    try{
      const body=await readJson(await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-tasks/${encodeURIComponent(taskId)}/input-diagnosis?page=${page}&limit=24&query=${encodeURIComponent(compatibilityQuery)}&issue_type=${encodeURIComponent(compatibilityIssueType)}`),'训练输入诊断读取失败');
      if(String(projectId()||'')!==pid||destroyed||sequence!==diagnosticSequence||!topOwns(anchor))return false;
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
    const anchor=document.querySelector('[data-training-compatibility-dialog]');
    const result = await refreshCompatibility({
      force: true,
      query: compatibilityQuery,
      issueType: compatibilityIssueType,
      page,
      pageSize: compatibilityPageSize,
    });
    if (result&&topOwns(anchor)) openCompatibilityIssues();
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
    return excludeSelectedFromDraft(imageId);
  }

  function invalidateCompatibility() {
    compatibilitySequence += 1;
    compatibilityController?.abort?.();
    compatibilityController = null;
    compatibilitySignature = null;
    compatibilityPendingSignature = null;
    compatibility = null;
    compatibilityFailure=null;
    queueDecorate();
    window.TrainingSubmitRuntime?.updateReadiness?.({reset:true});
  }

  function invalidate() {
    for(const [taskId,context] of deletionSessions)if(!ownsAdmission(context))deletionSessions.delete(taskId);
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
    const signature = summaryRequestSignature(ids);
    if (signature !== currentSignature && signature !== pendingSignature) void refresh(ids);
    else queueDecorate();
    const draft = currentDraft();
    const compatibilityKey = trainingCompatibilitySignature(draft || {});
    if (compatibilityKey !== observedCompatibilityKey) {
      observedCompatibilityKey=compatibilityKey;
      invalidateCompatibility();
    }
  }

  const unsubscribeDraft = trainingDraftRuntime.subscribe?.(() => syncSelection()) || (() => {});
  const observer = typeof MutationObserver !== 'undefined'
    ? new MutationObserver(() => queueDecorate())
    : null;
  observer?.observe(document.body, {childList: true, subtree: true});

  const runtime = {
    build: 'training-material-summary-runtime-422606',
    refresh,
    refreshCompatibility,
    confirmPendingNegatives,
    beforeModalClose,
    invalidateCompatibility,
    compatibilityFor,
    openCompatibilityIssues,
    updateAdmissionDiagnosis,
    openAdmissionDiagnosis,
    loadIssuePage,
    applyIssueFilters,
    openReview,
    openDuplicateComparison,
    renderGtConflictEvidence,
    bindGtConflictEvidence,
    gtConflictNames: GT_CONFLICT_NAMES,
    openTaskDiagnosis,
    returnFromReview,
    excludeFromDraft,
    excludeSelectedFromDraft,
    trackMaterialDeletion,
    captureDeletionContext,
    onMaterialBatchCompleted,
    invalidate,
    summaryReadyFor,
    summaryFor,
    selectedLabelCodes,
    decorateTrainingCreateUi,
    pickerDraftPayload,
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
      negativeCheck?.controller.abort();
      destroyed = true;
      deletionSessions.clear();
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
