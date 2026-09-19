function required(value, message) {
  if (value === null || value === undefined || String(value).trim() === '') throw new Error(message);
  return value;
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

export function buildTrainingEngineParameters({draft, target, algorithm} = {}) {
  if (!draft) throw new Error('训练草稿尚未就绪，请关闭训练窗口后重新打开。');
  required(target?.id, '请选择可用训练资源');
  required(algorithm?.key, '请选择可用训练算法');

  const config = draft.config || {};
  return {
    framework: target.framework === 'paddle' ? 'paddle' : 'ultralytics',
    target: target.type === 'server' ? 'remote' : 'local',
    server_id: target.server_id,
    algorithm: algorithm.key || '',
    model: config.model || algorithm.base_model || '',
    epochs: config.epochs ?? algorithm.default_epochs ?? 100,
    imgsz: config.imgsz ?? algorithm.default_imgsz ?? 640,
    batch: integerParameter(draft.resource?.batch ?? config.batch ?? algorithm.default_batch, 8, 'Batch'),
    device: draft.resource?.device || config.device || 'auto',
    include_empty: false,
    patience: config.patience ?? 100,
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
    amp: config.amp !== false,
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
    resource_strategy: draft.resource?.strategy || config.resource_strategy || 'auto',
    gpu_policy: draft.resource?.gpuPolicy || config.gpu_policy || 'auto',
  };
}

export function buildTrainingStartPayload({draft, target, algorithm, trainingDraftToRequest} = {}) {
  if (typeof trainingDraftToRequest !== 'function') throw new Error('训练请求构建器不可用');
  const parameters = buildTrainingEngineParameters({draft, target, algorithm});
  return trainingDraftToRequest(draft, parameters);
}

export function validateTrainingDevice(draft, devices = []) {
  const device = String(draft?.resource?.device || '').trim();
  if (!device) throw new Error('请选择可用训练设备');
  const match = (devices || []).find(row => String(row?.id || '') === device);
  if (!match || match.available === false) {
    throw new Error('当前训练设备不可用，请重新打开训练窗口并选择可用设备');
  }
  return match;
}

export function trainingSubmitReadiness({draft, inheritance, benchmarkStatus, submitting = false} = {}) {
  if (submitting) return {ready: false, reason: 'submitting'};
  if (!String(draft?.algorithmId || '').trim()) return {ready: false, reason: 'algorithm'};
  if (draft?.benchmarkReuseEnabled && benchmarkStatus?.loading) return {ready: false, reason: 'benchmark-loading'};
  if (draft?.benchmarkReuseEnabled && benchmarkStatus?.load_error) return {ready: false, reason: 'benchmark-error'};
  if ((draft?.materialIds || []).length < 2) return {ready: false, reason: 'materials'};
  if (inheritance?.blocked) return {ready: false, reason: 'iteration'};
  return {ready: true, reason: ''};
}

export function supplementCandidateContext({asset, draft, inheritance} = {}) {
  if (!asset || !draft) return null;
  const versionId = String(
    draft.baseVersionId
    || inheritance?.versionId
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

export function benchmarkReuseContext({asset, draft, inheritance, benchmark} = {}) {
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
  const draftVersionId = String(draft.baseVersionId || inheritance?.versionId || currentVersionId || '').trim();
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

  function submitButton() {
    if (typeof document === 'undefined') return null;
    const primary = document.querySelector?.('.train429-create .train428-footer .btn.primary');
    if (primary) return primary;
    const buttons = [...(document.querySelectorAll?.('.train429-create button') || [])];
    return buttons.find(button => /开始训练/.test(String(button.textContent || ''))) || null;
  }

  function updateReadiness() {
    const state = getState?.() || {};
    const draft = state.trainingDraft || trainingDraftRuntime.current?.() || trainingDraftRuntime.sync();
    const inheritance = trainingDraftRuntime.inheritance?.() || state.trainingDraftInheritance || {};
    const benchmarkStatus = String(state.trainingBenchmarkReuse?.algorithm_id || '') === String(draft?.algorithmId || '')
      ? state.trainingBenchmarkReuse
      : null;
    const readiness = trainingSubmitReadiness({draft, inheritance, benchmarkStatus, submitting});
    const asset = (state.algorithms || []).find(
      row => String(row?.id || '') === String(draft?.algorithmId || '')
    );
    let supplementContext = null;
    try {
      supplementContext = supplementCandidateContext({asset, draft, inheritance});
    } catch (_) {
      supplementContext = null;
    }
    renderSupplementCandidateSummary(supplementContext);
    const button = submitButton();
    if (button) {
      button.disabled = !readiness.ready;
      button.dataset.trainingSubmitOwner = 'TrainingSubmitRuntime';
      button.dataset.trainingSubmitReason = readiness.reason;
    }
    return readiness;
  }

  const submit = async function () {
    if (destroyed) throw new Error('训练提交模块已销毁');
    if (submitting) {
      notify?.('训练任务正在创建，请勿重复提交');
      return null;
    }
    submitting = true;
    lastError = '';
    lastStage = 'sync-draft';
    updateReadiness();
    try {
      const state = getState?.() || {};
      const draft = trainingDraftRuntime.sync();
      if (!draft) throw new Error('训练草稿尚未就绪，请关闭训练窗口后重新打开。');

      lastStage = 'validate-inheritance';
      const inheritance = trainingDraftRuntime.inheritance?.() || state.trainingDraftInheritance || {};
      if (inheritance.blocked) {
        throw new Error('该算法已有版本，但没有成功且可继续训练的版本；平台不会回退母算法。');
      }

      lastStage = 'resolve-algorithm';
      const asset = (state.algorithms || []).find(row => String(row?.id || '') === String(draft.algorithmId || ''));
      if (!asset) throw new Error('当前训练算法不存在，请刷新算法列表后重试');
      const benchmarkContext = benchmarkReuseContext({asset, draft, inheritance, benchmark: state.trainingBenchmarkReuse});

      lastStage = 'resolve-target';
      const targetId = document.getElementById('tr429Target')?.value || '';
      const target = (state.targets || []).find(row => String(row?.id || '') === String(targetId));
      if (!target) throw new Error('训练资源不可用，请重新打开训练窗口');

      lastStage = 'resolve-engine';
      const algorithmKey = document.getElementById('tr429Alg')?.value || '';
      const algorithm = (target.algorithms || []).find(row => String(row?.key || '') === String(algorithmKey))
        || (target.algorithms || [])[0];
      if (!algorithm) throw new Error('训练算法不可用，请重新选择训练资源');

      lastStage = 'validate-device';
      validateTrainingDevice(draft, state.trainingDevicesV3?.options || []);
      lastStage = 'build-payload';
      const payload = buildTrainingStartPayload({draft, target, algorithm, trainingDraftToRequest});
      if (benchmarkContext) {
        if ((draft.testMaterialIds || []).length) throw new Error('复用固定评测基准时不能同时选择前端独立试验素材');
        delete payload.test_image_ids;
        delete payload.experiment_percent;
        payload.benchmark_source_version_id = benchmarkContext.sourceVersionId;
        payload.benchmark_scope_id = benchmarkContext.scopeId;
      }
      const supplementContext = supplementCandidateContext({asset, draft, inheritance});
      if (supplementContext?.active) {
        payload.supplement_candidate_set_id = supplementContext.candidateSetId;
      }
      const iterationAction = state.trainingIterationAction;
      let iterationTaskId = '';
      if (
        iterationAction
        && String(iterationAction?.source?.algorithm_id || '') === String(asset.id || '')
        && String(iterationAction?.source?.version_id || '') === String(draft.baseVersionId || inheritance.versionId || '')
      ) {
        payload.iteration_action = {
          action_id: String(iterationAction.action_id || ''),
          decision_id: String(iterationAction.source?.decision_id || ''),
          evaluation_id: String(iterationAction.source?.evaluation_id || ''),
          version_id: String(iterationAction.source?.version_id || ''),
          dataset_revision_id: String(iterationAction.source?.dataset_revision_id || ''),
          snapshot_id: String(iterationAction.source?.snapshot_id || ''),
        };
        iterationTaskId = String(iterationAction.training_draft?.task_id || '');
      }
      const externalAnalysisId = window.ExternalAlgorithmPlatformRuntime?.selectedAnalysisId?.(asset.id) || '';
      if (externalAnalysisId) payload.external_analysis_id = externalAnalysisId;
      const plannedTaskId = String(document.getElementById('tr429TaskId')?.value || '').trim();
      if (iterationTaskId) payload.task_id = iterationTaskId;
      else if (plannedTaskId) payload.task_id = plannedTaskId;
      const pid = projectId?.();
      if (!pid) throw new Error('当前项目不可用，请刷新页面后重试');

      lastStage = 'posting';
      const response = await window.fetch(`/api/v12/projects/${pid}/train/start`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const raw = await response.text();
        let body = {};
        try { body = JSON.parse(raw); } catch (_) { body = {detail: raw}; }
        const message = body.message || body.detail || `训练任务创建失败（HTTP ${response.status}）`;
        const validationDetail = body.code === 'VALIDATION_ERROR' ? formatTrainingValidationError(body) : '';
        throw new Error(validationDetail ? `${message}：${validationDetail}` : String(message));
      }
      const body = await response.json();
      lastStage = 'created';
      if (payload.iteration_action && state.trainingIterationAction) {
        state.trainingIterationAction = null;
      }

      closeModal?.();
      state.alg428Expanded = state.alg428Expanded || {};
      state.alg428Expanded[asset.id] = true;
      notify?.(`训练任务已进入后台队列${body.task?.id || body.job?.id ? ` · ${body.task?.id || body.job?.id}` : ''}`);

      try {
        await reloadRelated?.();
        renderAlgorithms?.();
      } catch (refreshError) {
        console.warn?.('training task created but list refresh failed', refreshError);
        notify?.('训练任务已创建；列表刷新失败，请稍后手动刷新查看');
      }
      return body;
    } catch (error) {
      lastError = String(error?.message || error || '未知训练提交错误');
      notify?.(lastError);
      return null;
    } finally {
      submitting = false;
      updateReadiness();
    }
  };
  submit.__trainingSubmitRuntime = true;
  submit.__trainingSubmitOriginal = originalSubmit;
  window.submitTrain429 = submit;

  const runtime = {
    build: 'training-submit-422506',
    submit,
    updateReadiness,
    isSubmitting: () => submitting,
    state: () => ({submitting, networkOwner: true, readiness: updateReadiness(), lastStage, lastError}),
    destroy() {
      destroyed = true;
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
