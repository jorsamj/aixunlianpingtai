import {withRequestDeadline} from './api.js?v=20261021s';

function required(value, message) {
  if (value === null || value === undefined || String(value).trim() === '') throw new Error(message);
  return value;
}

const TRAINING_TASK_ID_PATTERN = /^train_[0-9a-f]{16,32}$/;

export function isCanonicalTrainingTaskId(value) {
  return TRAINING_TASK_ID_PATTERN.test(String(value || '').trim());
}

export function createCanonicalTrainingTaskId({
  cryptoSource = globalThis.crypto,
  random = Math.random,
} = {}) {
  const taskId = globalThis.BrowserCapabilityRuntime?.createClientId?.(
    'train_', 24, {cryptoSource, random},
  );
  if (!isCanonicalTrainingTaskId(taskId)) {
    throw new Error('训练任务 ID 生成失败，请刷新页面后重试');
  }
  return taskId;
}

export function normalizeTrainingPrecision(value) {
  const precision = String(value || 'auto').trim().toLowerCase();
  return ['auto', 'fp16', 'fp32'].includes(precision) ? precision : 'auto';
}

function integerParameter(value, fallback, label) {
  const raw = value === null || value === undefined || value === '' ? fallback : value;
  const parsed = Number(raw);
  if (!Number.isInteger(parsed)) throw new Error(`${label}必须是整数`);
  return parsed;
}

export function formatTrainingValidationError(body = {}) {
  let detail = body?.detail;
  if (typeof detail === 'string') {
    try { detail = JSON.parse(detail); } catch (_) { return detail; }
  }
  if (!Array.isArray(detail)) return '';
  return detail.map(item => {
    const path = (item?.loc || []).filter(part => String(part) !== 'body').join('.');
    const message = String(item?.msg || '格式不正确');
    return `${path || '请求参数'}：${message}`;
  }).join('；');
}

export function validatePreparedMotherModel({draft, target} = {}) {
  // Current training version is the only allowed iteration base. The selected
  // mother checkpoint matters only when there is no previous version.
  if (String(draft?.baseVersionId || '').trim()) return true;
  if (!Array.isArray(target?.base_models)) return true; // legacy standalone builder
  const selected = String(draft?.config?.model || '').trim();
  const available = target.base_models.some(model =>
    String(model?.value || '') === selected
    && String(model?.model_status || '').toUpperCase() === 'FOUND'
    && /\.pt$/i.test(selected)
  );
  if (!available) throw new Error('首次训练母模型尚未预置；请先到训练资源上传并选择已就绪的 .pt 权重');
  return true;
}

// The sole predefined-mode policy. No resource resolution is done in the browser:
// the assigned Worker owns final Batch/Workers/Cache decisions at execution time.
export function trainingModePreset(mode, hasPrevious = false) {
  const iteration = Boolean(hasPrevious);
  switch (String(mode || 'full')) {
    case 'quick': return {epochs: iteration ? 20 : 30, imgsz: 640};
    case 'complex': return {epochs: iteration ? 150 : 250, imgsz: 800};
    case 'full': return {epochs: iteration ? 80 : 150, imgsz: 640};
    default: return null;
  }
}

export function buildTrainingEngineParameters({draft, target, algorithm} = {}) {
  if (!draft) throw new Error('训练草稿尚未就绪，请关闭训练窗口后重新打开。');
  required(target?.id, '请选择可用训练资源');
  required(algorithm?.key, '请选择可用训练算法');
  validatePreparedMotherModel({draft,target});

  const rawConfig = draft.config || {};
  const mode = String(draft.trainingMode || (draft.resource?.strategy === 'manual' ? 'custom' : 'full'));
  const preset = trainingModePreset(mode, Boolean(draft.baseVersionId));
  // Presets never inherit hidden manual/advanced values from a previous custom
  // task or an old dialog session. Keep the explicitly selected mother model and precision;
  // existing optimizer, augmentation and quality defaults remain canonical here.
  const config = preset
    ? {model: rawConfig.model, imgsz: rawConfig.imgsz, precision: rawConfig.precision, amp: rawConfig.amp, stop_threshold: .90, eval_interval: 10, eval_metric: 'map50'}
    : rawConfig;
  return {
    framework: target.framework === 'paddle' ? 'paddle' : 'ultralytics',
    target: target.type === 'server' ? 'remote' : 'local',
    server_id: target.server_id,
    algorithm: algorithm.key || '',
    model: config.model || algorithm.base_model || '',
    epochs: preset?.epochs ?? config.epochs ?? (draft.baseVersionId ? 80 : (algorithm.default_epochs ?? 150)),
    imgsz: config.imgsz ?? preset?.imgsz ?? algorithm.default_imgsz ?? 640,
    batch: integerParameter(draft.resource?.batch ?? config.batch ?? algorithm.default_batch, 8, 'Batch'),
    device: draft.resource?.device || config.device || 'auto',
    include_empty: false,
    patience: config.patience ?? 40,
    early_stopping_enabled: config.early_stopping_enabled === true,
    time: config.time ?? null,
    precision: normalizeTrainingPrecision(config.precision),
    workers: integerParameter(draft.resource?.workers ?? config.workers, 0, 'Workers'),
    optimizer: config.optimizer || 'auto',
    lr0: config.lr0 ?? .01,
    lrf: config.lrf ?? .01,
    momentum: config.momentum ?? .937,
    weight_decay: config.weight_decay ?? .0005,
    warmup_epochs: config.warmup_epochs ?? 3,
    close_mosaic: config.close_mosaic ?? 10,
    mosaic: config.mosaic ?? 1,
    mixup: config.mixup ?? 0,
    hsv_h: config.hsv_h ?? .015,
    hsv_s: config.hsv_s ?? .7,
    hsv_v: config.hsv_v ?? .4,
    degrees: config.degrees ?? 0,
    translate: config.translate ?? .1,
    scale: config.scale ?? .5,
    shear: config.shear ?? 0,
    perspective: config.perspective ?? 0,
    flipud: config.flipud ?? 0,
    fliplr: config.fliplr ?? .5,
    cache: draft.resource?.cache ?? config.cache ?? false,
    pretrained: config.pretrained !== false,
    amp: normalizeTrainingPrecision(config.precision) === 'fp32' ? false : normalizeTrainingPrecision(config.precision) === 'fp16' ? true : config.amp !== false,
    single_cls: Boolean(config.single_cls),
    rect: Boolean(config.rect),
    cos_lr: Boolean(config.cos_lr),
    freeze: config.freeze ?? 0,
    multi_scale: config.multi_scale ?? 0,
    save_period: config.save_period ?? -1,
    seed: config.seed ?? 0,
    deterministic: config.deterministic !== false,
    val_max_samples: config.val_max_samples ?? 0,
    eval_interval: config.eval_interval ?? 0,
    eval_metric: config.eval_metric || 'map50',
    continue_threshold: config.continue_threshold ?? 0,
    stop_threshold: config.stop_threshold ?? 0,
    auto_convert_targets: config.auto_convert_targets || [],
    ai_intervention_enabled: false,
    resource_strategy: preset ? 'auto' : (draft.resource?.strategy || config.resource_strategy || 'manual'),
    resource_profile: preset ? 'performance' : (draft.resource?.profile || config.resource_profile || 'performance'),
    gpu_policy: 'exclusive',
  };
}

export function buildTrainingStartPayload({draft, target, algorithm, trainingDraftToRequest} = {}) {
  if (typeof trainingDraftToRequest !== 'function') throw new Error('训练请求构建器不可用');
  const parameters = buildTrainingEngineParameters({draft, target, algorithm});
  return trainingDraftToRequest(draft, parameters);
}

export function validateTrainingDevice(draft, devices = [], target = null) {
  if (target?.scheduler_owned === true) {
    return {id: 'auto', type: 'scheduler', available: true};
  }
  const device = String(draft?.resource?.device || '').trim();
  if (!device) throw new Error('请选择可用训练设备');
  const match = (devices || []).find(row => String(row?.id || '') === device);
  if (!match || match.available === false) {
    throw new Error('当前训练设备不可用，请重新打开训练窗口并选择可用设备');
  }
  return match;
}

export const TRAINING_ADMISSION_ISSUE_NAMES = Object.freeze({
  missing_annotation:'缺少正式标注', partial_review_scope:'标签审核范围不完整',
  stale_ground_truth:'标注与当前图片不一致', material_unavailable:'素材不可读取',
  duplicate_annotation_conflict:'同图不同GT冲突', content_hash_leakage:'Train / Val / Test 内容交叉',
});

export function collectTrainingAdmissionBlockers({draft,base,target,benchmarkStatus,compatibility,
  submitting=false,externalReadiness,additional=[]}={}) {
  const blockers=[];
  const add=(code,message,{transient=false,count=null,...details}={})=>blockers.push({code,message,transient,count,...details});
  if(submitting)add('submitting','训练任务正在创建，请等待服务端确认',{transient:true});
  if(!String(draft?.algorithmId||'').trim())add('algorithm','请选择有效算法');
  if(draft?.benchmarkReuseEnabled&&benchmarkStatus?.loading)add('benchmark-loading','正在读取固定Test基准',{transient:true});
  if(draft?.benchmarkReuseEnabled&&benchmarkStatus?.load_error)add('benchmark-error',String(benchmarkStatus.load_error));
  if((draft?.materialIds||[]).length<2)add('materials','至少需要2张有效训练素材',{count:(draft?.materialIds||[]).length});
  if(base?.blocked)add('iteration','历史算法没有成功且成果有效的可迭代版本，请核对模型版本');
  if(!base?.hasPrevious&&Array.isArray(target?.base_models)){
    try{validatePreparedMotherModel({draft,target})}catch(error){add('mother-model-not-ready',error.message||'母模型未就绪')}
  }
  if(compatibility!==undefined&&compatibility?.ready!==true){
    if(compatibility?.error)add('material-compatibility-error',`训练素材检查失败：${compatibility.error}，可重新检查`);
    else add('material-compatibility-loading','正在检查训练素材，请稍候',{transient:true});
  }
  if(compatibility?.ready===true&&Number(compatibility.issue_count||0)>0){
    const raw=compatibility.affected_image_count;
    const count=raw!==undefined&&raw!==null&&Number.isFinite(Number(raw))?Number(raw):null;
    add('material-compatibility',count===null?'训练素材存在未处理问题':`本次有 ${count} 张素材不符合训练条件`,{count,issue_count:Number(compatibility.issue_count)});
    for(const [code,value] of Object.entries(compatibility.issue_counts||{}))if(Number(value)>0){
      const labelText=(compatibility.effective_label_codes||[]).join('、');
      const message=code==='partial_review_scope'&&labelText?`${value} 张素材尚未确认是否包含 ${labelText}`:TRAINING_ADMISSION_ISSUE_NAMES[code]||`其他素材问题（${code}）`;
      add(code,message,{count:Number(value),count_unit:'问题条目'});
    }
  }
  if(externalReadiness?.ready===false)add(externalReadiness.reason||'external-master-data',externalReadiness.message||'畅联云算法主数据尚未就绪，请重新同步');
  for(const item of additional)if(item?.code&&!blockers.some(row=>row.code===item.code||row.message===item.message))add(item.code,item.message||item.code,item);
  return blockers;
}

export function trainingSubmitReadiness(options={}) {
  const first=collectTrainingAdmissionBlockers(options)[0];
  return first?{ready:false,reason:first.code}:{ready:true,reason:''};
}

export function supplementCandidateContext({asset, draft, base} = {}) {
  if (!asset || !draft) return null;
  const versionId = String(
    draft.baseVersionId
    || base?.versionId
    || asset.current_version_id
    || ''
  ).trim();
  const version = (asset.versions || []).find(row =>
    String(row?.id || row?.version_id || '').trim() === versionId
  );
  const candidateSet = version?.supplement_data_candidate_set;
  const candidateSetId = String(candidateSet?.candidate_set_id || '').trim().toLowerCase();
  if (!candidateSetId) return null;
  if (!/^[0-9a-f]{64}$/.test(candidateSetId)) {
    throw new Error('补数据 Candidate Set 状态异常，请刷新算法版本后重试');
  }
  const candidateIds = [...new Set(
    (candidateSet?.material_ids || []).map(value => String(value || '').trim()).filter(Boolean)
  )];
  const selectedIds = new Set([
    ...(draft.materialIds || []),
    ...(draft.testMaterialIds || []),
  ].map(value => String(value || '').trim()).filter(Boolean));
  const adoptedMaterialIds = candidateIds.filter(id => selectedIds.has(id));
  return {
    candidateSetId,
    versionId,
    sourceCandidateCount: candidateIds.length,
    adoptedMaterialIds,
    adoptedCount: adoptedMaterialIds.length,
    active: adoptedMaterialIds.length > 0,
  };
}

export function benchmarkReuseContext({asset, draft, base, benchmark} = {}) {
  if (!draft?.benchmarkReuseEnabled) return null;
  if (!asset || !draft) throw new Error('固定评测基准所属算法不存在，请刷新后重试');
  if (!benchmark || benchmark.loading) throw new Error('固定评测基准正在校验，请稍后再提交训练');
  if (benchmark.load_error) throw new Error(benchmark.reason || '固定评测基准读取失败，请刷新后重试');
  if (benchmark.available !== true) throw new Error(benchmark.reason || '当前版本没有可复用的固定评测基准');
  const algorithmId = String(asset.id || '').trim();
  if (String(benchmark.algorithm_id || '').trim() !== algorithmId) {
    throw new Error('固定评测基准所属算法已变化，请重新打开训练窗口');
  }
  const currentVersionId = String(asset.current_version_id || '').trim();
  const sourceVersionId = String(benchmark.source_version_id || '').trim();
  const draftVersionId = String(draft.baseVersionId || base?.versionId || currentVersionId || '').trim();
  if (!sourceVersionId || !currentVersionId || sourceVersionId !== currentVersionId
      || (draftVersionId && draftVersionId !== sourceVersionId)) {
    throw new Error('固定评测基准来源版本已变化，请重新打开训练窗口');
  }
  const scopeId = String(benchmark.scope_id || '').trim().toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(scopeId)) throw new Error('固定评测基准 Scope 状态异常，请重新评测后再训练');
  if (String(benchmark.binding_level || '') !== 'bundle_verified') {
    throw new Error('当前评测基准未绑定已校验 Test Bundle，不能用于严格复用');
  }
  const testImageCount = Number(benchmark.test_image_count || 0);
  if (!Number.isInteger(testImageCount) || testImageCount <= 0) {
    throw new Error('固定评测基准试验素材数量异常，请重新评测后再训练');
  }
  return {
    algorithmId,
    sourceVersionId,
    scopeId,
    snapshotId: String(benchmark.snapshot_id || '').trim(),
    testImageCount,
    bindingLevel: 'bundle_verified',
  };
}

const CREATED_TRAINING_STATUSES = new Set(['QUEUED', 'WAITING_RESOURCE', 'RUNNING', 'PAUSED']);
// A repository lookup proves persistence even if execution has already ended.
const PERSISTED_TRAINING_STATUSES = new Set([...CREATED_TRAINING_STATUSES,'AWAITING_CONFIRMATION','PARTIAL_SUCCESS','SUCCEEDED','CANCEL_REQUESTED','CANCELLED','FAILED','BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE']);

const TRAINING_SUBMIT_PRESENTATIONS = Object.freeze({
  configuration: Object.freeze({
    tone: 'working', activeStep: 0, completedSteps: 0,
    title: '正在校验训练配置', detail: '正在核验训练设备与算法版本',
  }),
  materials: Object.freeze({
    tone: 'working', activeStep: 1, completedSteps: 1,
    title: '正在核验训练素材', detail: '正在确认素材、标签与训练范围',
  }),
  submit: Object.freeze({
    tone: 'working', activeStep: 2, completedSteps: 2,
    title: '正在提交训练任务', detail: '服务端正在创建可恢复的持久任务',
  }),
  success: Object.freeze({
    tone: 'success', activeStep: 2, completedSteps: 3,
    title: '训练任务创建成功', detail: '任务已持久化，执行状态请在训练任务列表查看',
  }),
});

export function trainingSubmitPresentation(stage, options = {}) {
  const value = String(stage || 'idle');
  if (value === 'blocked') return {tone:'error',activeStep:1,completedSteps:1,title:'训练暂不可开始',detail:'请查看完整阻塞原因，调整配置后重新检查',retrySafe:true};
  if (value === 'checking-materials') return {...TRAINING_SUBMIT_PRESENTATIONS.materials,title:'正在检查训练素材、标签与 GT'};
  if (value === 'verifying') return {tone:'working',activeStep:2,completedSteps:2,title:'正在确认创建结果',detail:'创建请求已中断，正在按原任务 ID 核对持久化结果'};
  if (value === 'created') return {...TRAINING_SUBMIT_PRESENTATIONS.success};
  if (value === 'failed') {
    const failedAt = String(options.failedAt || '');
    const fallback = trainingSubmitPresentation(failedAt || 'sync-draft');
    const uncertain = options.outcomeUncertain === true;
    const taskId = String(options.taskId || '').trim();
    return {
      tone: uncertain ? 'uncertain' : 'error',
      activeStep: fallback.activeStep,
      completedSteps: fallback.completedSteps,
      title: uncertain ? '创建结果暂未确认' : '训练任务未创建',
      detail: uncertain
        ? `创建结果尚未确认：${String(options.error || '网络连接中断')}。请先到任务列表核对 ${taskId || '本次任务 ID'}，不要重复提交。`
        : String(options.error || '请检查训练配置后重试'),
      retrySafe: !uncertain,
      taskId,
    };
  }
  if (value === 'build-payload') return {...TRAINING_SUBMIT_PRESENTATIONS.materials};
  if (value === 'posting') return {...TRAINING_SUBMIT_PRESENTATIONS.submit};
  return {...TRAINING_SUBMIT_PRESENTATIONS.configuration};
}

export function validateTrainingCreatedResponse(body, expectedTaskId = '', expectedIdentity = {}) {
  const task = body?.task;
  const taskId = String(task?.task_id || '').trim();
  const kind = String(task?.kind || task?.task_type || '').trim().toUpperCase();
  const taskType = String(task?.task_type || task?.kind || '').trim().toUpperCase();
  const status = String(task?.status || '').trim().toUpperCase();
  if (body?.ok !== true || !taskId || kind !== 'TRAINING' || taskType !== 'TRAINING' || !(expectedIdentity.persistedLookup?PERSISTED_TRAINING_STATUSES:CREATED_TRAINING_STATUSES).has(status)) {
    throw new Error('训练创建响应缺少正式任务身份，请保留当前窗口并重试');
  }
  const expected = String(expectedTaskId || '').trim();
  if (expected && taskId !== expected) {
    throw new Error(`训练创建返回的任务身份不一致：期望 ${expected}，实际 ${taskId}`);
  }
  for (const [field, expectedValue] of [['project_id', expectedIdentity.projectId], ['algorithm_id', expectedIdentity.algorithmId]]) {
    const actual = String(task[field] || (field === 'algorithm_id' ? task.algorithm_asset_id : '') || '').trim();
    if (expectedValue && (field === 'project_id' || actual) && actual !== String(expectedValue)) {
      throw new Error('训练创建返回的项目或算法身份不一致，请查询任务状态');
    }
  }
  return task;
}
function renderSupplementCandidateSummary(context) {
  if (typeof document === 'undefined') return;
  const root = document.querySelector?.('.train-v3-summary');
  if (!root) return;
  let card = root.querySelector?.('[data-supplement-candidate-summary]') || null;
  if (!context?.candidateSetId) {
    card?.remove?.();
    return;
  }
  if (!card) {
    card = document.createElement?.('div');
    if (!card) return;
    card.dataset.supplementCandidateSummary = 'true';
    const label = document.createElement('span');
    label.textContent = '反馈补数据';
    const value = document.createElement('b');
    value.dataset.supplementCandidateValue = 'true';
    card.append(label, value);
    root.append(card);
  }
  const value = card.querySelector?.('[data-supplement-candidate-value]');
  if (value) value.textContent = String(context.adoptedCount) + ' / ' + String(context.sourceCandidateCount) + ' 张';
  card.title = context.active
    ? '提交训练时由后端再次核验候选素材与标注，最终采用范围以 Snapshot 为准'
    : '当前训练素材未包含已冻结反馈候选';
}
export function installTrainingSubmitRuntime({
  getState,
  projectId,
  trainingDraftRuntime,
  trainingDraftToRequest,
  reloadRelated,
  renderAlgorithms,
  trainingTaskRuntime,
  materialSummaryRuntime,
  closeModal,
  notify,
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingSubmitRuntimeInstalled) return window.TrainingSubmitRuntime;
  if (!trainingDraftRuntime?.sync || typeof trainingDraftToRequest !== 'function') {
    throw new Error('TrainingSubmitRuntime missing canonical draft dependencies');
  }

  const originalSubmit = window.submitTrain429;
  let destroyed = false;
  let submitting = false;
  let lastStage = 'idle';
  let lastError = '';
  let lastPresentation = null;
  let serverRejection = null;
  let submissionRoot = null;
  let submissionButton = null;
  // UI request receipts only: the TaskRepository remains execution truth.
  const uncertainSubmissions = new Map();
  const receiptKey = pid => `training-create-pending:${pid}`;
  function pendingOutcome() {
    const pid=String(projectId?.()||'');
    if(!uncertainSubmissions.has(pid)){
      let receipt=null;
      try{
        const saved=JSON.parse(window.sessionStorage?.getItem(receiptKey(pid))||'null');
        if(saved?.projectId===pid && isCanonicalTrainingTaskId(saved.taskId) && typeof saved.algorithmId==='string')receipt=saved;
      }catch(error){console.warn('training creation receipt unavailable',error);}
      uncertainSubmissions.set(pid,receipt);
    }
    return uncertainSubmissions.get(pid);
  }
  function rememberPending(project,algorithmId,taskId) {
    const pid=String(project),receipt={projectId:pid,algorithmId:String(algorithmId),taskId};
    uncertainSubmissions.set(pid,receipt);
    try{window.sessionStorage?.setItem(receiptKey(pid),JSON.stringify(receipt));}
    catch(error){console.warn('training creation receipt could not be saved',error);}
  }
  function clearPending(project) {
    const pid=String(project);uncertainSubmissions.set(pid,null);
    try{window.sessionStorage?.removeItem(receiptKey(pid));}
    catch(error){console.warn('training creation receipt could not be cleared',error);}
  }
  const createdTaskIds = new Set();
  let submittedProjectId = '';
  let submittedAlgorithmId = '';
  let admissionOperation = null;
  function admissionSignature() {
    return JSON.stringify([(getState?.()||{}).trainingDraft||trainingDraftRuntime.current?.()||{},
      document.getElementById?.('tr429Target')?.value||'',document.getElementById?.('tr429Alg')?.value||'']);
  }
  function admissionIsCurrent(operation=admissionOperation) {
    return !!operation&&!destroyed&&String(projectId?.()||'')===operation.projectId
      &&document.querySelector?.('.train429-create')===operation.root&&operation.root?.isConnected!==false
      &&String(document.getElementById?.('tr429TaskId')?.value||'')===operation.taskId
      &&admissionSignature()===operation.signature&&ownsSubmissionModal();
  }
  function cancelStaleCheck() {
    if(admissionOperation&&lastStage!=='posting'&&!admissionIsCurrent())admissionOperation.controller.abort();
  }


  function ownsSubmissionModal() {
    if (destroyed || (submittedProjectId && String(projectId?.()||'')!==String(submittedProjectId))) return false;
    const currentRoot = document.querySelector?.('.train429-create');
    if (submissionRoot) {
      if (submissionRoot.isConnected === false || currentRoot !== submissionRoot) return false;
      const owner = submissionRoot.closest?.('[role=dialog],.modal');
      if (owner) {
        const layers = [...(document.querySelectorAll?.('.v424-modal-layer') || [])];
        const top = layers.at(-1) || document.getElementById?.('modal');
        if (top !== owner || owner.classList?.contains('hidden')) return false;
      }
      return true;
    }
    return !!submissionButton && document.querySelector?.('.train429-create .train428-footer .btn.primary') === submissionButton;
  }

  function notifyUser(message) {
    try { notify?.(message); }
    catch(error) { console.error('training notification failed',error); }
  }

  function closeCreatedModal() {
    try {
      if (!ownsSubmissionModal() || (admissionOperation&&!admissionIsCurrent())) return;
      closeModal?.();
    }
    catch(error) { console.error('training modal close failed',error); }
  }

  function refreshCreatedLists(pid) {
    Promise.resolve().then(() => {
      if (destroyed || String(projectId?.() || '') !== String(pid)) return;
      return reloadRelated?.();
    }).then(() => {
      if (!destroyed && String(projectId?.() || '') === String(pid)) renderAlgorithms?.();
    }).catch(refreshError => {
      console.warn?.('training task created but list refresh failed', refreshError);
      if (!destroyed && String(projectId?.() || '') === String(pid)) notifyUser('训练任务已创建；列表刷新失败，请稍后手动刷新查看');
    });
  }
  const SUBMIT_STAGE_TEXT = Object.freeze({
    idle: '开始训练',
    'sync-draft': '正在检查训练条件…',
    'checking-materials': '正在检查训练条件…',
    'validate-version': '正在核验算法版本…',
    'resolve-algorithm': '正在核验算法主数据…',
    'resolve-target': '正在核验训练资源…',
    'resolve-engine': '正在核验训练引擎…',
    'validate-device': '正在核验训练设备…',
    'build-payload': '正在整理训练素材与参数…',
    posting: '正在创建训练任务…',
    created: '训练任务已创建',
  });

  function submitButton() {
    if (submitting && !ownsSubmissionModal()) return null;
    if (typeof document === 'undefined') return null;
    const primary = document.querySelector?.('.train429-create .train428-footer .btn.primary');
    if (primary) return primary;
    const buttons = [...(document.querySelectorAll?.('.train429-create button') || [])];
    return buttons.find(button => /开始训练|正在.*训练|持久任务|训练任务已创建/.test(String(button.textContent || ''))) || null;
  }

  function renderPendingActions(panel) {
    if(!pendingOutcome() || !panel)return;
    if(!panel.querySelector?.('[data-training-query-result]')){
      const query=document.createElement('button');query.type='button';query.className='btn';query.dataset.trainingQueryResult='1';query.textContent='查询任务状态';
      query.addEventListener('click',()=>{void verifyPendingTask();});panel.append(query);
    }
    if(!panel.querySelector?.('[data-training-view-tasks]')){
      const view=document.createElement('button');view.type='button';view.className='btn';view.dataset.trainingViewTasks='1';view.textContent='查看训练任务列表';
      view.addEventListener('click',()=>{
        if(!ownsSubmissionModal() || typeof window.setPage!=='function')return;
        try{closeModal?.();window.setPage('训练任务');}
        catch(error){console.error('training task navigation failed',error);notifyUser('任务列表打开失败，请从导航重新进入');}
      });panel.append(view);
    }
  }

  function renderSubmitFeedback(stage, options = {}) {
    const root = stage !== 'idle' && !ownsSubmissionModal() ? null : document.querySelector?.('.train429-create');
    const panel = root?.querySelector?.('[data-training-submit-feedback]');
    if (stage === 'idle') {
      if (panel) {
        panel.hidden = true;
        panel.removeAttribute?.('data-tone');
      }
      root?.classList?.remove?.('training-submit-active', 'training-submit-complete', 'training-submit-failed');
      return null;
    }
    const presentation = trainingSubmitPresentation(stage, options);
    lastPresentation = presentation;
    if (!panel) return presentation;
    if(presentation.tone==='uncertain')renderPendingActions(panel);
    panel.hidden = false;
    panel.dataset.tone = presentation.tone;
    panel.setAttribute?.('aria-busy', presentation.tone === 'working' ? 'true' : 'false');
    const title = panel.querySelector?.('[data-training-submit-title]');
    const detail = panel.querySelector?.('[data-training-submit-detail]');
    if (title) title.textContent = presentation.title;
    if (detail) detail.textContent = presentation.detail;
    [...(panel.querySelectorAll?.('[data-training-submit-step]') || [])].forEach((item, index) => {
      const status = index < presentation.completedSteps ? 'done' : presentation.tone==='working' && index === presentation.activeStep ? 'active' : 'pending';
      item.dataset.status = status;
      item.setAttribute?.('aria-current', status === 'active' ? 'step' : 'false');
    });
    root?.classList?.toggle?.('training-submit-active', presentation.tone === 'working');
    root?.classList?.toggle?.('training-submit-complete', presentation.tone === 'success');
    root?.classList?.toggle?.('training-submit-failed', ['error', 'uncertain'].includes(presentation.tone));
    return presentation;
  }

  function setSubmitStage(stage, options = {}) {
    lastStage = String(stage || 'idle');
    renderSubmitFeedback(lastStage, options);
    const button = submitButton();
    if (!button) return lastStage;
    if (!button.dataset.trainingSubmitIdleText) {
      button.dataset.trainingSubmitIdleText = String(button.textContent || '开始训练');
    }
    button.dataset.trainingSubmitStage = lastStage;
    button.textContent = submitting
      ? (lastStage==='verifying'?'正在确认创建结果…':lastStage==='posting'?'正在创建训练任务…':lastStage==='created'?'训练任务已创建':'正在检查训练条件…')
      : button.dataset.trainingSubmitIdleText;
    if (typeof button.setAttribute === 'function') button.setAttribute('aria-busy', submitting ? 'true' : 'false');
    return lastStage;
  }

  function updateReadiness({checked=false,reset=false}={}) {
    cancelStaleCheck();
    const currentRoot = document.querySelector?.('.train429-create') || null;
    if (!submitting && currentRoot && currentRoot !== submissionRoot) {
      if(pendingOutcome()){
        const pending=pendingOutcome();
        submissionRoot=currentRoot;
        submissionButton=currentRoot.querySelector?.('.train428-footer .btn.primary')||null;
        submittedProjectId=pending.projectId;submittedAlgorithmId=pending.algorithmId;
        lastStage='failed';
        renderSubmitFeedback('failed',{taskId:pending.taskId,outcomeUncertain:true,error:'前一次创建请求尚未确认，请先查询原任务'});
      }else{
        lastStage = 'idle';lastError = '';lastPresentation = null;
      }
    }
    const state = getState?.() || {};
    const draft = state.trainingDraft || trainingDraftRuntime.current?.() || trainingDraftRuntime.sync();
    const base = trainingDraftRuntime.base?.() || state.trainingDraftBase || {};
    const benchmarkStatus = String(state.trainingBenchmarkReuse?.algorithm_id || '') === String(draft?.algorithmId || '')
      ? state.trainingBenchmarkReuse
      : null;
    const compatibility = materialSummaryRuntime?.compatibilityFor?.(draft);
    const selectedTargetId = document.getElementById?.('tr429Target')?.value || '';
    const selectedTarget = (state.targets || []).find(row => String(row?.id || '') === String(selectedTargetId));
    const asset = (state.algorithms || []).find(row=>String(row?.id||'')===String(draft?.algorithmId||''));
    const externalReadiness = asset ? window.ExternalAlgorithmPlatformRuntime?.trainingReadiness?.(asset.id) : null;
    const additional=[];
    const add=(code,error,transient=false)=>additional.push({code,message:String(error?.message||error),transient});
    const resourceLoad=currentRoot?.dataset?.workbenchMounted==='true'&&String(state.trainingCreationLoading?.projectId||'')===String(projectId?.()||'')?state.trainingCreationLoading?.resources:null;
    if(resourceLoad&&resourceLoad.status!=='ready')add('resource-'+resourceLoad.status,resourceLoad.status==='loading'?'训练资源正在读取，请稍候':resourceLoad.error||'训练资源未就绪，请重新读取资源',resourceLoad.status==='loading');
    if(draft?.algorithmId&&!asset)add('algorithm-unavailable','当前算法身份不存在，请刷新算法列表');
    if(!projectId?.())add('project-unavailable','当前项目不可用，请重新选择项目');
    if(!selectedTarget)add('resource-unavailable','训练资源尚未就绪，请等待或重新读取配置',!selectedTargetId);
    if(selectedTarget){
      const engineKey=document.getElementById?.('tr429Alg')?.value||'';
      const engine=(selectedTarget.algorithms||[]).find(row=>String(row.key)===String(engineKey))||(selectedTarget.algorithms||[])[0];
      if(!engine)add('engine-unavailable','当前资源没有可用训练引擎');
      try{validateTrainingDevice(draft,state.trainingDevicesV3?.options||[],selectedTarget)}catch(error){add('device-unavailable',error)}
      if(engine)try{buildTrainingEngineParameters({draft,target:selectedTarget,algorithm:engine})}catch(error){
        add('training-config',error);
      }
    }
    if(draft?.benchmarkReuseEnabled&&!benchmarkStatus?.loading){
      try{benchmarkReuseContext({asset,draft,base,benchmark:benchmarkStatus});if((draft.testMaterialIds||[]).length)add('fixed-test-conflict','复用固定Test基准时不能同时选择独立Test素材')}
      catch(error){add('fixed-test-benchmark',error)}
    }
    if(draft?.splitMode==='independent_test_set'&&!draft?.benchmarkReuseEnabled&&!(draft.testMaterialIds||[]).length)add('independent-test-insufficient','独立Test素材不足，请补充后重新预检');
    if(serverRejection?.root!==currentRoot||serverRejection?.signature!==admissionSignature())serverRejection=null;
    if(serverRejection)add(serverRejection.code,serverRejection.message);
    const blockers=collectTrainingAdmissionBlockers({draft,base,target:selectedTarget,benchmarkStatus,compatibility,submitting,externalReadiness,additional});
    if(pendingOutcome()){
      blockers.unshift({code:'outcome-uncertain',message:'创建结果尚未确认，请先查询原任务，不能盲目重试',transient:true,count:null});
    }
    const readiness={ready:!blockers.length,reason:blockers[0]?.code||'',blockers,
      checking:blockers.some(row=>row.transient),signature:JSON.stringify([draft,blockers])};
    materialSummaryRuntime?.updateAdmissionDiagnosis?.({root:currentRoot,
      taskId:String(document.getElementById?.('tr429TaskId')?.value||''),projectId:String(projectId?.()||''),
      draft,algorithmName:asset?.name||'',readiness,checked,reset,signature:admissionSignature()});
    let supplementContext = null;
    try {
      supplementContext = supplementCandidateContext({asset, draft, base});
    } catch (_) {
      supplementContext = null;
    }
    renderSupplementCandidateSummary(supplementContext);
    const button = submitButton();
    if (button) {
      button.disabled = submitting || Boolean(pendingOutcome()) || Boolean(resourceLoad&&resourceLoad.status!=='ready');
      button.setAttribute?.('aria-busy',submitting?'true':'false');
      button.dataset.trainingSubmitOwner = 'TrainingSubmitRuntime';
      button.dataset.trainingSubmitReason = readiness.reason;
      if (!submitting && lastStage === 'created') setSubmitStage('created');
      else if (!submitting && lastStage === 'failed') button.textContent=pendingOutcome()?.taskId?'结果待确认':'重新检查';
      else if (!submitting && lastStage === 'blocked') button.textContent=button.dataset.trainingSubmitIdleText||'开始训练';
      else if (!submitting) setSubmitStage('idle');
    }
    return readiness;
  }

  function restoreSubmissionUI() {
    try { updateReadiness(); }
    catch (error) { console.error('training readiness recovery failed', error); }
    if (!ownsSubmissionModal()) return;
    const button=submissionButton;
    if(button){
      button.disabled=Boolean(pendingOutcome()?.taskId);
      button.setAttribute?.('aria-busy','false');
      button.classList?.remove?.('loading');
      button.textContent=pendingOutcome()?.taskId?'结果待确认':lastStage==='created'?(button.dataset.trainingSubmitIdleText||'开始训练'):lastStage==='failed'?'重新检查':button.dataset.trainingSubmitIdleText||'开始训练';
    }
    submissionRoot?.classList?.remove?.('training-submit-active');
    submissionRoot?.classList?.toggle?.('training-submit-failed',lastStage==='failed');
    const panel=submissionRoot?.querySelector?.('[data-training-submit-feedback]');
    panel?.setAttribute?.('aria-busy','false');
    if(panel && lastStage==='idle')panel.hidden=true;
    if(panel && lastStage==='failed'){
      panel.hidden=false;panel.dataset.tone=pendingOutcome()?.taskId?'uncertain':'error';
      const title=panel.querySelector?.('[data-training-submit-title]');
      const detail=panel.querySelector?.('[data-training-submit-detail]');
      if(title)title.textContent=pendingOutcome()?.taskId?'创建结果暂未确认':'训练任务创建失败';
      if(detail)detail.textContent=['error','uncertain'].includes(lastPresentation?.tone)?lastPresentation.detail:lastError;
      panel.querySelectorAll?.('[data-training-submit-step]').forEach(item=>{if(item.dataset.status==='active')item.dataset.status='pending';});
      renderPendingActions(panel);
    }
  }

  async function verifyPendingTask() {
    if(submitting || !pendingOutcome()?.taskId || !ownsSubmissionModal())return null;
    const pending=pendingOutcome();
    const taskId=pending.taskId,pid=pending.projectId,aid=pending.algorithmId;
    const sameTaskForm=String(document.getElementById?.('tr429TaskId')?.value||'')===taskId;
    submitting=true;
    try{
      setSubmitStage('verifying');
      const body=await withRequestDeadline(async signal=>{
        const response=await window.fetch(`/api/v62/projects/${encodeURIComponent(pid)}/tasks/${encodeURIComponent(taskId)}`,{signal,headers:{Accept:'application/json'}});
        if(!response.ok)throw new Error(`查询任务失败（HTTP ${response.status}）；请保留原任务 ID，稍后再次查询`);
        return response.json();
      },{label:'训练任务核验'});
      const task=validateTrainingCreatedResponse({ok:true,task:body?.task||body},taskId,{projectId:pid,algorithmId:aid,persistedLookup:true});
      createdTaskIds.add(taskId);clearPending(pid);lastStage=sameTaskForm?'created':'idle';
      if(String(projectId?.()||'')===String(pid))trainingTaskRuntime?.acceptCreatedTask?.(task,{recoveredAfterNetworkError:true});
      if(sameTaskForm)closeCreatedModal();
      refreshCreatedLists(pid);notifyUser(`已确认训练任务创建 · ${taskId} · 当前状态 ${task.status}`);
      return task;
    }catch(error){
      console.warn('training task status query failed',error);
      if(createdTaskIds.has(taskId)){
        lastStage=sameTaskForm?'created':'idle';if(sameTaskForm)closeCreatedModal();refreshCreatedLists(pid);
        return {task_id:taskId};
      }
      lastStage='failed';lastError=String(error?.message||error);
      lastPresentation=trainingSubmitPresentation('failed',{error:lastError,failedAt:'posting',outcomeUncertain:true,taskId});
      if(ownsSubmissionModal())notifyUser(lastError);
      return null;
    }finally{submitting=false;restoreSubmissionUI();}
  }

  const submit = async function () {
    if (destroyed) throw new Error('训练提交模块已销毁');
    if (submitting) {
      notifyUser('训练任务正在创建，请勿重复提交');
      return null;
    }
    const plannedId = String(document.getElementById?.('tr429TaskId')?.value || '').trim();
    if (createdTaskIds.has(plannedId)) {
      notifyUser(`训练任务已创建，请在任务列表查看 ${plannedId}`);
      return null;
    }
    if (pendingOutcome()) {
      notifyUser(`创建结果尚未确认，请先在任务列表查询 ${pendingOutcome()?.taskId}，不要重复创建`);
      return null;
    }
    const workbench=document.querySelector?.('.train429-create');
    if(workbench?.dataset?.workbenchMounted==='true'&&workbench.dataset.trainingStep!=='3'){
      window.setTrainingWorkbenchStep?.(3);notifyUser('请在确认创建步骤核对本次配置后，再点击开始训练');return null;
    }
    submittedProjectId=String(projectId?.()||'');
    submissionRoot = document.querySelector?.('.train429-create') || null;
    submissionButton = document.querySelector?.('.train429-create .train428-footer .btn.primary') || null;
    submitting = true;
    lastError = '';
    lastPresentation = null;
    serverRejection = null;
    let submittedTaskId = '';
    let responseReceived = false;
    let responseStatus = 0;
    let rejectionBodyDecoded = false;
    let creationAccepted = false;
    try {
      const resources=(getState?.()||{}).trainingCreationLoading;
      if(submissionRoot?.dataset?.workbenchMounted==='true'&&resources&&String(resources.projectId||'')===String(projectId?.()||'')&&resources.resources?.status!=='ready'){
        notifyUser(resources.resources?.error||'训练资源尚未准备完成，请等待或重试');window.focusTrainingWorkbenchField?.('resource');return null;
      }
      setSubmitStage('sync-draft');
      updateReadiness({reset:true});
      setSubmitStage('sync-draft');
      const state = getState?.() || {};
      const draft = trainingDraftRuntime.sync();
      if (!draft) throw new Error('训练草稿尚未就绪，请关闭训练窗口后重新打开。');
      const operation={root:submissionRoot,taskId:plannedId,projectId:String(projectId?.()||''),signature:admissionSignature(),controller:new AbortController()};
      admissionOperation=operation;
      const showBlockers=readiness=>{
        const blockers=readiness.blockers.filter(row=>!row.transient);
        if(!blockers.length)return false;
        setSubmitStage('blocked');updateReadiness({checked:true});
        if(!materialSummaryRuntime?.openAdmissionDiagnosis?.())notifyUser(blockers.map(row=>row.message).join('；'));
        return true;
      };
      const localAdmission=updateReadiness();
      if(draft.benchmarkReuseEnabled&&localAdmission.blockers.some(row=>['fixed-test-benchmark','benchmark-error'].includes(row.code))){
        showBlockers(localAdmission);return null;
      }
      if(draft.benchmarkReuseEnabled&&localAdmission.blockers.some(row=>row.code==='benchmark-loading'))throw new Error('固定Test基准仍在读取，检查尚未完成，请稍后重新检查');
      setSubmitStage('checking-materials');
      let checkedCompatibility;
      if(materialSummaryRuntime?.refreshCompatibility){
        checkedCompatibility=await materialSummaryRuntime.refreshCompatibility({force:true,signal:operation.controller.signal});
        if(!admissionIsCurrent(operation))throw Object.assign(new Error('训练配置或窗口已变化，本次检查已取消'),{name:'AbortError'});
        if(!checkedCompatibility){const truth=materialSummaryRuntime.compatibilityFor?.(draft);throw new Error(truth?.error||'训练准入检查未完成，请重新检查');}
        if(checkedCompatibility.compatible===false&&!checkedCompatibility.skipped&&!Number(checkedCompatibility.issue_count||0))throw new Error('训练准入检查未完成：未获得明确通过结果，请重新检查');
      }
      const admission=updateReadiness();
      if(showBlockers(admission))return null;
      if(admission.blockers.some(row=>row.transient&&row.code!=='submitting'))throw new Error('训练条件检查尚未完成，请等待基础配置就绪后重新检查');


      setSubmitStage('validate-version');
      const base = trainingDraftRuntime.base?.() || state.trainingDraftBase || {};
      if (base.blocked) {
        throw new Error('该算法已有版本，但没有成功且可继续训练的版本；平台不会回退母算法。');
      }

      setSubmitStage('resolve-algorithm');
      const asset = (state.algorithms || []).find(row => String(row?.id || '') === String(draft.algorithmId || ''));
      if (!asset) throw new Error('当前训练算法不存在，请刷新算法列表后重试');
      const externalReadiness = window.ExternalAlgorithmPlatformRuntime?.trainingReadiness?.(asset.id);
      if (externalReadiness?.ready === false) {
        throw new Error(externalReadiness.message || '当前畅联云算法主数据未就绪，请重新同步后再训练');
      }
      const benchmarkContext = benchmarkReuseContext({asset, draft, base, benchmark: state.trainingBenchmarkReuse});

      setSubmitStage('resolve-target');
      const targetId = document.getElementById('tr429Target')?.value || '';
      const target = (state.targets || []).find(row => String(row?.id || '') === String(targetId));
      if (!target) throw new Error('训练资源不可用，请重新打开训练窗口');

      setSubmitStage('resolve-engine');
      const algorithmKey = document.getElementById('tr429Alg')?.value || '';
      const algorithm = (target.algorithms || []).find(row => String(row?.key || '') === String(algorithmKey))
        || (target.algorithms || [])[0];
      if (!algorithm) throw new Error('训练算法不可用，请重新选择训练资源');

      setSubmitStage('validate-device');
      validateTrainingDevice(draft, state.trainingDevicesV3?.options || [], target);
      setSubmitStage('build-payload');
      const payload = buildTrainingStartPayload({draft, target, algorithm, trainingDraftToRequest});
      if (benchmarkContext) {
        if ((draft.testMaterialIds || []).length) throw new Error('复用固定评测基准时不能同时选择前端独立试验素材');
        delete payload.test_image_ids;
        delete payload.experiment_percent;
        payload.benchmark_source_version_id = benchmarkContext.sourceVersionId;
        payload.benchmark_scope_id = benchmarkContext.scopeId;
      }
      const supplementContext = supplementCandidateContext({asset, draft, base});
      if (supplementContext?.active) {
        payload.supplement_candidate_set_id = supplementContext.candidateSetId;
      }
      const iterationAction = state.trainingIterationAction;
      let iterationTaskId = '';
      if (iterationAction) {
        const source = iterationAction.source || {};
        const currentId = String(asset.current_version_id || '');
        const version = (asset.versions || []).find(row => String(row.id || '') === currentId);
        const stored = version?.confirmed_iteration_action;
        const sameSource = ['algorithm_id', 'version_id', 'decision_id', 'evaluation_id', 'dataset_revision_id', 'snapshot_id']
          .every(key => String(source[key] || '') === String(stored?.source?.[key] || ''));
        if (
          iterationAction.action !== 'continue_training' || iterationAction.status !== 'confirmed'
          || iterationAction.automatic_execution !== false
          || !currentId || String(source.algorithm_id || '') !== String(asset.id || '')
          || String(source.version_id || '') !== currentId
          || String(draft.baseVersionId || base.versionId || '') !== currentId
          || !source.decision_id || !source.evaluation_id
          || source.decision_id !== version?.iteration_decision?.decision_id
          || source.evaluation_id !== version?.iteration_decision?.evaluation_id
          || source.evaluation_id !== version?.evaluation?.evaluation_id
          || !stored || stored.action_id !== iterationAction.action_id
          || stored.status !== 'confirmed' || stored.action !== 'continue_training' || !sameSource
        ) {
          throw new Error('迭代动作已过期或与当前训练草稿不一致，请从当前版本独立评测重新确认继续训练');
        }
        payload.iteration_action = {
          action_id: String(iterationAction.action_id || ''),
          decision_id: String(iterationAction.source?.decision_id || ''),
          evaluation_id: String(iterationAction.source?.evaluation_id || ''),
          version_id: String(iterationAction.source?.version_id || ''),
          dataset_revision_id: String(iterationAction.source?.dataset_revision_id || ''),
          snapshot_id: String(iterationAction.source?.snapshot_id || ''),
        };
        iterationTaskId = String(iterationAction.training_draft?.task_id || '').trim();
        if (!isCanonicalTrainingTaskId(iterationTaskId)) {
          throw new Error('历史迭代任务 ID 格式异常');
        }
      }
      const externalAnalysisId = window.ExternalAlgorithmPlatformRuntime?.selectedAnalysisId?.(asset.id) || '';
      if (externalAnalysisId) payload.external_analysis_id = externalAnalysisId;
      const plannedTaskId = String(document.getElementById('tr429TaskId')?.value || '').trim();
      if (iterationTaskId) payload.task_id = iterationTaskId;
      else {
        if (!isCanonicalTrainingTaskId(plannedTaskId)) {
          throw new Error('训练任务 ID 格式异常，请关闭训练窗口后重新打开');
        }
        payload.task_id = plannedTaskId;
      }
      const pid = projectId?.();
      submittedProjectId = pid;
      submittedAlgorithmId = asset.id;
      if (!pid) throw new Error('当前项目不可用，请刷新页面后重试');

      if(!admissionIsCurrent(operation))throw Object.assign(new Error('训练配置或窗口已变化，本次检查已取消'),{name:'AbortError'});
      if(checkedCompatibility){
        payload.expected_material_revision=checkedCompatibility.material_revision;
        payload.expected_annotation_revision=checkedCompatibility.annotation_revision;
      }

      setSubmitStage('posting');
      submittedTaskId = String(payload.task_id || '');
      rememberPending(pid,asset.id,submittedTaskId);
      const body = await withRequestDeadline(async signal => {
      const response = await window.fetch(`/api/v12/projects/${pid}/train/start`, {
        method: 'POST',
        signal,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      responseReceived = true;
      responseStatus = Number(response.status) || 0;
      if (!response.ok) {
        const raw = await response.text();
        let body = {};
        try {
          body = JSON.parse(raw);
          rejectionBodyDecoded = Boolean(body) && typeof body === 'object' && !Array.isArray(body);
        } catch (_) { body = {detail: raw}; }
        const detail=body.detail;
        const message=body.message||detail?.message||(typeof detail==='string'?detail:'')||`训练任务创建失败（HTTP ${response.status}）`;
        const validationDetail = body.code === 'VALIDATION_ERROR' ? formatTrainingValidationError(body) : '';
        throw Object.assign(new Error(validationDetail?`${message}：${validationDetail}`:String(message)),{code:body.code||detail?.code||`HTTP_${response.status}`,detail,solution:body.solution||detail?.solution||'',serverRejected:true,httpStatus:response.status});
      }
      creationAccepted = true;
      return await response.json();
      }, {label: '训练创建'});
      const createdTask = validateTrainingCreatedResponse(body, payload.task_id, {projectId: pid, algorithmId: asset.id});
      createdTaskIds.add(createdTask.task_id);
      clearPending(pid);
      if(admissionIsCurrent())setSubmitStage('created');
      else{lastStage='idle';lastError='';lastPresentation=null;}
      const currentProjectMatches = !destroyed && String(projectId?.() || '') === String(pid);
      if (currentProjectMatches && payload.iteration_action && state.trainingIterationAction) {
        state.trainingIterationAction = null;
      }

      if (currentProjectMatches) trainingTaskRuntime?.acceptCreatedTask?.(createdTask, {
        algorithmId: asset.id,
        algorithmName: String(asset.name || '已删除算法'),
        framework: String(payload.framework || target.framework || ''),
        queuePriority: payload.queue_priority,
      });
      if (currentProjectMatches) {
        state.alg428Expanded = state.alg428Expanded || {};
        state.alg428Expanded[asset.id] = true;
      }
      const selection = body?.selection && typeof body.selection === 'object' ? body.selection : null;
      let createdMessage = `训练任务已进入后台队列 · ${createdTask.task_id}`;
      if (selection && Number.isFinite(Number(selection.effective_train_count))) {
        createdMessage += ` · 本轮有效 ${Math.max(0, Number(selection.effective_train_count))} 张`;
      }
      if (selection && Number(selection.pending_annotation_count || 0) > 0) {
        createdMessage += ` · 待标注 ${Math.max(0, Number(selection.pending_annotation_count))} 张已保留`;
      }
      closeCreatedModal();
      notifyUser(createdMessage);
      refreshCreatedLists(pid);
      return body;
    } catch (error) {
      if(submittedTaskId&&createdTaskIds.has(submittedTaskId)){
        console.error('training created; completion callback failed',error);
        lastStage='created';
        closeCreatedModal();
        refreshCreatedLists(submittedProjectId);
        return {ok:true,task_id:submittedTaskId};
      }
      if(error?.name==='AbortError'&&lastStage!=='posting')return null;
      lastError = String(error?.message || error || '未知训练提交错误');
      const failedAt = lastStage;
      let currentErrorView=ownsSubmissionModal();
      try{if(admissionOperation)currentErrorView=admissionIsCurrent();}
      catch(contextError){console.error('training error context unavailable',contextError);}
      if(error?.serverRejected&&[400,409,422].includes(error.httpStatus)&&admissionOperation&&currentErrorView)serverRejection={root:submissionRoot,signature:admissionOperation.signature,code:error.code,message:lastError};
      let outcomeUncertain = failedAt === 'posting' && (!responseReceived || !rejectionBodyDecoded || creationAccepted || responseStatus>=500 || Number(error?.httpStatus)>=500 || error?.code==='TRAINING_CREATE_IN_PROGRESS');
      if(outcomeUncertain)serverRejection=null;
      else if(submittedTaskId)clearPending(submittedProjectId);
      if (outcomeUncertain && submittedTaskId) {
        rememberPending(submittedProjectId,submittedAlgorithmId,submittedTaskId);
        try {
          setSubmitStage('verifying');
          const pid = submittedProjectId;
          const verification = await withRequestDeadline(async signal => { const response = await window.fetch(
            `/api/v62/projects/${encodeURIComponent(pid)}/tasks/${encodeURIComponent(submittedTaskId)}`,
            {headers: {'Accept': 'application/json'}, signal},
          ); return {ok: response.ok, body: response.ok ? await response.json() : null}; }, {label: '训练任务核验'});
          if (verification.ok) {
            const taskBody = verification.body;
            const createdTask = validateTrainingCreatedResponse(
              {ok: true, task: taskBody?.task || taskBody}, submittedTaskId,
              {projectId: pid, algorithmId: submittedAlgorithmId,persistedLookup:true},
            );
            createdTaskIds.add(createdTask.task_id);clearPending(pid);
            if(admissionIsCurrent())setSubmitStage('created');
            else{lastStage='idle';lastError='';lastPresentation=null;}
            if (!destroyed && String(projectId?.() || '') === String(pid)) {
              trainingTaskRuntime?.acceptCreatedTask?.(createdTask, {recoveredAfterNetworkError: true});
            }
            closeCreatedModal();
            notifyUser(`已确认训练任务创建 · ${createdTask.task_id} · 当前状态 ${createdTask.status}`);
            refreshCreatedLists(pid);
            return {ok: true, task: createdTask, recovered: true};
          }
        } catch (verificationError) {
          if(createdTaskIds.has(submittedTaskId)){
            console.error('training verified; completion callback failed',verificationError);
            closeCreatedModal();refreshCreatedLists(submittedProjectId);return {ok:true,task_id:submittedTaskId};
          }
          console.warn('training creation verification failed', verificationError);
          outcomeUncertain = true;
        }
      }
      if (outcomeUncertain) rememberPending(submittedProjectId,submittedAlgorithmId,submittedTaskId);
      try{if(admissionOperation)currentErrorView=admissionIsCurrent();}
      catch(contextError){console.error('training final error context unavailable',contextError);}
      if(!currentErrorView || !ownsSubmissionModal()){lastStage='idle';lastError='';return null;}
      try {
        setSubmitStage('failed', {error:lastError,failedAt,taskId:submittedTaskId,outcomeUncertain});
        updateReadiness({reset:!serverRejection});
        if(!outcomeUncertain)window.focusTrainingWorkbenchField?.(error?.field||error?.message||lastError);
      } catch (presentationError) {
        console.error('training failure presentation failed',presentationError);
        lastStage='failed';
      }
      if(error?.serverRejected&&serverRejection&&ownsSubmissionModal()){
        try{updateReadiness({checked:true});materialSummaryRuntime?.openAdmissionDiagnosis?.();}
        catch(diagnosisError){console.error('training diagnosis presentation failed',diagnosisError);}
      }
      if(ownsSubmissionModal())notifyUser(['error','uncertain'].includes(lastPresentation?.tone)?lastPresentation.detail:lastError);
      return null;
    } finally {
      admissionOperation=null;
      submitting = false;
      restoreSubmissionUI();
    }
  };
  submit.__trainingSubmitRuntime = true;
  submit.__trainingSubmitOriginal = originalSubmit;
  window.submitTrain429 = submit;

  const runtime = {
    build: 'training-submit-422596',
    submit,
    createTaskId: createCanonicalTrainingTaskId,
    modePreset: trainingModePreset,
    isCanonicalTaskId: isCanonicalTrainingTaskId,
    updateReadiness,
    verifyPendingTask,
    cancelStaleCheck,
    clearAdmissionError:()=>{serverRejection=null;},
    isSubmitting: () => submitting,
    state: () => ({submitting, networkOwner: true, readiness: updateReadiness(), lastStage, lastError, presentation: lastPresentation}),
    destroy() {
      submitting=false;lastStage='idle';
      restoreSubmissionUI();
      destroyed = true;
      admissionOperation?.controller.abort();
      if (window.submitTrain429 === submit) window.submitTrain429 = originalSubmit;
      if (window.TrainingSubmitRuntime === runtime) window.TrainingSubmitRuntime = null;
      window.__trainingSubmitRuntimeInstalled = false;
    },
  };
  window.TrainingSubmitRuntime = runtime;
  window.__trainingSubmitRuntimeInstalled = true;
  updateReadiness();
  return runtime;
}
