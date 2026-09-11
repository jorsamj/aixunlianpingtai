function required(value, message) {
  if (value === null || value === undefined || String(value).trim() === '') throw new Error(message);
  return value;
}

function numberOr(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
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
    batch: draft.resource?.batch ?? config.batch ?? algorithm.default_batch ?? 8,
    device: draft.resource?.device || config.device || 'auto',
    include_empty: false,
    patience: config.patience ?? 100,
    workers: draft.resource?.workers ?? config.workers ?? 0,
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

  const submit = async function () {
    if (destroyed) throw new Error('训练提交模块已销毁');
    try {
      const state = getState?.() || {};
      const draft = trainingDraftRuntime.sync();
      if (!draft) throw new Error('训练草稿尚未就绪，请关闭训练窗口后重新打开。');

      const asset = (state.algorithms || []).find(row => String(row?.id || '') === String(draft.algorithmId || ''));
      if (!asset) throw new Error('当前训练算法不存在，请刷新算法列表后重试');

      const targetId = document.getElementById('tr429Target')?.value || '';
      const target = (state.targets || []).find(row => String(row?.id || '') === String(targetId));
      if (!target) throw new Error('训练资源不可用，请重新打开训练窗口');

      const algorithmKey = document.getElementById('tr429Alg')?.value || '';
      const algorithm = (target.algorithms || []).find(row => String(row?.key || '') === String(algorithmKey))
        || (target.algorithms || [])[0];
      if (!algorithm) throw new Error('训练算法不可用，请重新选择训练资源');

      validateTrainingDevice(draft, state.trainingDevicesV3?.options || []);
      const payload = buildTrainingStartPayload({draft, target, algorithm, trainingDraftToRequest});
      const pid = projectId?.();
      if (!pid) throw new Error('当前项目不可用，请刷新页面后重试');

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
        throw new Error(String(message));
      }
      const body = await response.json();

      closeModal?.();
      await reloadRelated?.();
      state.alg428Expanded = state.alg428Expanded || {};
      state.alg428Expanded[asset.id] = true;
      renderAlgorithms?.();
      notify?.(`训练任务已进入后台队列${body.task?.id || body.job?.id ? ` · ${body.task?.id || body.job?.id}` : ''}`);
      return body;
    } catch (error) {
      notify?.(error?.message || error);
      return null;
    }
  };
  submit.__trainingSubmitRuntime = true;
  submit.__trainingSubmitOriginal = originalSubmit;
  window.submitTrain429 = submit;

  const runtime = {
    build: 'training-submit-422500',
    submit,
    destroy() {
      destroyed = true;
      if (window.submitTrain429 === submit) window.submitTrain429 = originalSubmit;
      if (window.TrainingSubmitRuntime === runtime) window.TrainingSubmitRuntime = null;
      window.__trainingSubmitRuntimeInstalled = false;
    },
  };
  window.TrainingSubmitRuntime = runtime;
  window.__trainingSubmitRuntimeInstalled = true;
  return runtime;
}
