import test from 'node:test';
import assert from 'node:assert/strict';

import {createTrainingDraft, trainingDraftToRequest} from '../../static/modules/training-draft.js';
import {
  buildTrainingEngineParameters,
  buildTrainingStartPayload,
  installTrainingSubmitRuntime,
  trainingSubmitReadiness,
  validateTrainingDevice,
} from '../../static/modules/training-submit.js';

function draft(overrides = {}) {
  return createTrainingDraft({
    algorithmId: 'alg-1',
    materialIds: ['img-1', 'img-2'],
    newLabelCodes: ['fire'],
    experimentPercent: 35,
    validationPercent: 18,
    resource: {strategy: 'manual', device: '0', gpuPolicy: 'exclusive', batch: 16, workers: 4, cache: false},
    config: {
      model: 'custom.pt', epochs: 30, imgsz: 640, optimizer: 'auto',
      lr0: .01, lrf: .01, momentum: .937, weight_decay: .0005,
      warmup_epochs: 3, close_mosaic: 10, mosaic: 1, mixup: 0,
      hsv_h: .015, hsv_s: .7, hsv_v: .4, degrees: 0, translate: .1,
      scale: .5, shear: 0, perspective: 0, flipud: 0, fliplr: .5,
      pretrained: true, amp: true, single_cls: false, rect: false,
      cos_lr: false, freeze: 0, multi_scale: 0, save_period: -1,
      seed: 0, deterministic: true, val_max_samples: 0, eval_interval: 0,
      eval_metric: 'map50', continue_threshold: 0, stop_threshold: 0,
      auto_convert_targets: [],
    },
    priority: 7,
    ...overrides,
  });
}

const target = {
  id: 'gpu-local', type: 'local', framework: 'ultralytics',
  algorithms: [{key: 'yolo_detect', base_model: 'yolo11n.pt'}],
};
const algorithm = target.algorithms[0];

function installDom() {
  const controls = {
    tr429Target: {value: 'gpu-local'},
    tr429Alg: {value: 'yolo_detect'},
  };
  const submitButton = {disabled: true, dataset: {}, textContent: '开始训练'};
  globalThis.document = {
    getElementById: id => controls[id] || null,
    querySelector(selector) {
      return selector === '.train429-create .train428-footer .btn.primary' ? submitButton : null;
    },
    querySelectorAll() { return [submitButton]; },
  };
  return {controls, submitButton};
}

function baseState() {
  return {
    algorithms: [{id: 'alg-1'}],
    targets: [target],
    trainingDevicesV3: {options: [{id: '0', available: true}]},
    alg428Expanded: {},
  };
}

function cleanup(runtime) {
  runtime?.destroy();
  delete globalThis.window;
  delete globalThis.document;
}

test('engine parameters preserve explicit false/zero resource and YOLO settings', () => {
  const value = draft({
    resource: {strategy: 'manual', device: '0', gpuPolicy: 'exclusive', batch: 16, workers: 0, cache: false},
    config: {mosaic: 0, mixup: 0, flipud: 0, fliplr: 0, pretrained: false, amp: false, deterministic: false},
  });
  const parameters = buildTrainingEngineParameters({draft: value, target, algorithm});

  assert.equal(parameters.batch, 16);
  assert.equal(parameters.workers, 0);
  assert.equal(parameters.cache, false);
  assert.equal(parameters.mosaic, 0);
  assert.equal(parameters.fliplr, 0);
  assert.equal(parameters.pretrained, false);
  assert.equal(parameters.amp, false);
  assert.equal(parameters.deterministic, false);
});

test('start payload is derived from canonical TrainingDraft instead of legacy ids', () => {
  const payload = buildTrainingStartPayload({draft: draft(), target, algorithm, trainingDraftToRequest});
  assert.equal(payload.algorithm_asset_id, 'alg-1');
  assert.deepEqual(payload.train_image_ids, ['img-1', 'img-2']);
  assert.deepEqual(payload.train_labels, ['fire']);
  assert.equal(payload.experiment_percent, 35);
  assert.equal(payload.validation_percent, 18);
  assert.equal(payload.queue_priority, 7);
  assert.equal(payload.device, '0');
  assert.equal(payload.batch, 16);
  assert.equal(payload.workers, 4);
  assert.equal(payload.cache, false);
  assert.equal(payload.model, 'custom.pt');
});

test('submit readiness depends only on canonical draft, inheritance and submitting state', () => {
  assert.deepEqual(trainingSubmitReadiness({draft: draft(), inheritance: {blocked: false}}), {ready: true, reason: ''});
  assert.deepEqual(trainingSubmitReadiness({draft: draft({materialIds: ['only-one']}), inheritance: {blocked: false}}), {ready: false, reason: 'materials'});
  assert.deepEqual(trainingSubmitReadiness({draft: draft(), inheritance: {blocked: true}}), {ready: false, reason: 'iteration'});
  assert.deepEqual(trainingSubmitReadiness({draft: draft(), inheritance: {blocked: false}, submitting: true}), {ready: false, reason: 'submitting'});
});

test('device validation fails closed for missing or unavailable device', () => {
  assert.equal(validateTrainingDevice(draft(), [{id: '0', available: true}]).id, '0');
  assert.throws(() => validateTrainingDevice(draft(), [{id: 'cpu', available: true}]), /设备不可用/);
  assert.throws(() => validateTrainingDevice(draft(), [{id: '0', available: false}]), /设备不可用/);
});

test('submit runtime owns button readiness instead of legacy train428/train429 mirrors', () => {
  const state = baseState();
  state.trainingDraft = draft();
  state.train428AlgorithmId = 'stale-algorithm';
  state.train429Selected = new Set(['stale-material']);
  state.train428Config = {batch: 1, device: 'stale-device'};
  const {submitButton} = installDom();
  globalThis.window = {submitTrain429: () => 'legacy', fetch: async () => ({ok: true, async json() { return {}; }})};

  const runtime = installTrainingSubmitRuntime({
    getState: () => state,
    projectId: () => 'project-1',
    trainingDraftRuntime: {sync: () => state.trainingDraft, current: () => state.trainingDraft, inheritance: () => ({blocked: false})},
    trainingDraftToRequest,
  });

  assert.equal(submitButton.disabled, false);
  assert.equal(submitButton.dataset.trainingSubmitOwner, 'TrainingSubmitRuntime');
  assert.equal(submitButton.dataset.trainingSubmitReason, '');

  state.trainingDraft = draft({materialIds: ['one']});
  runtime.updateReadiness();
  assert.equal(submitButton.disabled, true);
  assert.equal(submitButton.dataset.trainingSubmitReason, 'materials');
  cleanup(runtime);
});

test('submit runtime is the sole train-start network owner and uses canonical draft end-to-end', async () => {
  const state = baseState();
  const {submitButton} = installDom();

  let sent;
  let reloaded = 0;
  let rendered = 0;
  let closed = 0;
  const notices = [];
  const oldSubmit = () => 'legacy';
  globalThis.window = {
    submitTrain429: oldSubmit,
    fetch: async (_url, init) => {
      sent = JSON.parse(init.body);
      return {ok: true, async json() { return {task: {id: 'task-1'}}; }};
    },
  };
  const runtime = installTrainingSubmitRuntime({
    getState: () => state,
    projectId: () => 'project-1',
    trainingDraftRuntime: {sync: () => draft(), current: () => draft(), inheritance: () => ({blocked: false})},
    trainingDraftToRequest,
    reloadRelated: async () => { reloaded += 1; },
    renderAlgorithms: () => { rendered += 1; },
    closeModal: () => { closed += 1; },
    notify: message => notices.push(String(message)),
  });

  assert.equal(window.submitTrain429.__trainingSubmitRuntime, true);
  assert.equal(runtime.state().networkOwner, true);
  assert.equal(submitButton.disabled, false);
  const result = await window.submitTrain429();

  assert.equal(result.task.id, 'task-1');
  assert.deepEqual(sent.train_image_ids, ['img-1', 'img-2']);
  assert.deepEqual(sent.train_labels, ['fire']);
  assert.equal(sent.queue_priority, 7);
  assert.equal(reloaded, 1);
  assert.equal(rendered, 1);
  assert.equal(closed, 1);
  assert.equal(state.alg428Expanded['alg-1'], true);
  assert.match(notices[0], /训练任务已进入后台队列/);

  runtime.destroy();
  assert.equal(window.submitTrain429, oldSubmit);
  cleanup();
});

test('iteration block is enforced by TrainingSubmitRuntime before any POST', async () => {
  const state = baseState();
  const {submitButton} = installDom();
  const notices = [];
  let calls = 0;
  globalThis.window = {
    submitTrain429: () => 'legacy',
    fetch: async () => { calls += 1; return {ok: true, async json() { return {}; }}; },
  };
  const runtime = installTrainingSubmitRuntime({
    getState: () => state,
    projectId: () => 'project-1',
    trainingDraftRuntime: {
      sync: () => draft(),
      current: () => draft(),
      inheritance: () => ({blocked: true}),
    },
    trainingDraftToRequest,
    notify: message => notices.push(String(message)),
  });

  assert.equal(submitButton.disabled, true);
  assert.equal(submitButton.dataset.trainingSubmitReason, 'iteration');
  const result = await window.submitTrain429();
  assert.equal(result, null);
  assert.equal(calls, 0);
  assert.match(notices.at(-1), /不会回退母算法/);
  cleanup(runtime);
});

test('double click cannot create two independent training tasks', async () => {
  const state = baseState();
  const {submitButton} = installDom();
  const notices = [];
  let calls = 0;
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  globalThis.window = {
    submitTrain429: () => 'legacy',
    fetch: async () => {
      calls += 1;
      await pending;
      return {ok: true, async json() { return {task: {id: 'task-once'}}; }};
    },
  };
  const runtime = installTrainingSubmitRuntime({
    getState: () => state,
    projectId: () => 'project-1',
    trainingDraftRuntime: {sync: () => draft(), current: () => draft(), inheritance: () => ({blocked: false})},
    trainingDraftToRequest,
    notify: message => notices.push(String(message)),
  });

  const first = window.submitTrain429();
  assert.equal(submitButton.disabled, true);
  assert.equal(submitButton.dataset.trainingSubmitReason, 'submitting');
  const second = await window.submitTrain429();
  assert.equal(second, null);
  assert.equal(calls, 1);
  assert.equal(runtime.isSubmitting(), true);
  assert.match(notices.at(-1), /请勿重复提交/);

  release();
  await first;
  assert.equal(runtime.isSubmitting(), false);
  assert.equal(submitButton.disabled, false);
  assert.equal(calls, 1);
  cleanup(runtime);
});

test('refresh failure after successful POST does not invite a duplicate training task', async () => {
  const state = baseState();
  installDom();
  const notices = [];
  let calls = 0;
  globalThis.window = {
    submitTrain429: () => 'legacy',
    fetch: async () => {
      calls += 1;
      return {ok: true, async json() { return {task: {id: 'created'}}; }};
    },
  };
  const runtime = installTrainingSubmitRuntime({
    getState: () => state,
    projectId: () => 'project-1',
    trainingDraftRuntime: {sync: () => draft(), current: () => draft(), inheritance: () => ({blocked: false})},
    trainingDraftToRequest,
    reloadRelated: async () => { throw new Error('list offline'); },
    notify: message => notices.push(String(message)),
  });

  const result = await window.submitTrain429();
  assert.equal(result.task.id, 'created');
  assert.equal(calls, 1);
  assert.match(notices[0], /训练任务已进入后台队列/);
  assert.match(notices.at(-1), /列表刷新失败/);
  cleanup(runtime);
});
