import test from 'node:test';
import assert from 'node:assert/strict';

import {installTrainingProgressStream} from '../../static/modules/training-progress-stream.js';

class FakeEventSource {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.listeners = new Map();
    this.closed = false;
    FakeEventSource.instances.push(this);
  }

  addEventListener(name, handler) {
    this.listeners.set(name, handler);
  }

  emit(name, payload) {
    this.listeners.get(name)?.({data: JSON.stringify(payload)});
  }

  open() {
    this.onopen?.({});
  }

  fail() {
    this.onerror?.(new Error('stream failed'));
  }

  close() {
    this.closed = true;
  }
}

function cleanup() {
  FakeEventSource.instances.length = 0;
  delete globalThis.window;
  delete globalThis.document;
}

test('durable stream updates a known training row without a canonical GET per progress event', async () => {
  const state = {
    page: '训练任务',
    project: {id: 'p1'},
    jobs: [{
      id: 'train-1',
      task_id: 'train-1',
      status: 'running',
      task_status: 'RUNNING',
      progress_percent: 10,
      updated_at: '2026-09-22T00:00:00Z',
    }],
  };
  let renders = 0;
  let refreshes = 0;
  const realtime = [];
  const detailUpdates = [];
  globalThis.document = {
    visibilityState: 'visible',
    addEventListener() {},
    removeEventListener() {},
  };
  globalThis.window = {
    TrainingTaskVisibilityRuntime: {render() { renders += 1; return true; }},
    TrainingRecoveryRuntime: {acceptLiveTask(job) { detailUpdates.push(job); }},
  };

  const runtime = installTrainingProgressStream({
    getState: () => state,
    projectId: () => state.project.id,
    trainingTaskRuntime: {
      async refresh() { refreshes += 1; return {stale: false, jobs: state.jobs}; },
    },
    pollRegistry: {
      setTrainingRealtimeActive(value) { realtime.push(Boolean(value)); },
      clear() {},
    },
    EventSourceImpl: FakeEventSource,
    documentImpl: globalThis.document,
  });
  runtime.syncPage('训练任务');
  const source = FakeEventSource.instances.at(-1);
  assert.equal(source.url, '/api/v64/projects/p1/training-events');
  source.open();
  source.emit('training.ready', {task_ids: ['train-1'], interval_ms: 750});
  source.emit('training.task', {
    task_id: 'train-1',
    project_id: 'p1',
    status: 'RUNNING',
    persisted_status: 'RUNNING',
    phase: 'training',
    progress_percent: 42.5,
    current_item: 'Epoch 12/30 · Batch 20/100',
    worker_id: 'gpu-worker-1',
    updated_at: '2026-09-22T00:00:01Z',
  });

  assert.equal(realtime.at(-1), true);
  assert.equal(state.jobs[0].progress_percent, 42.5);
  assert.equal(state.jobs[0].current_epoch, 12);
  assert.equal(state.jobs[0].total_epochs, 30);
  assert.equal(state.jobs[0].current_batch, 20);
  assert.equal(state.jobs[0].total_batches, 100);
  assert.equal(state.jobs[0].task_worker_id, 'gpu-worker-1');
  assert.equal(renders, 1);
  assert.equal(refreshes, 0);
  assert.equal(detailUpdates.length, 1);
  assert.equal(detailUpdates[0].progress_percent, 42.5);

  runtime.destroy();
  cleanup();
});

test('unknown and terminal stream tasks reconcile through the canonical jobs endpoint', async () => {
  const state = {
    page: '训练任务',
    project: {id: 'p1'},
    jobs: [{id: 'train-1', task_id: 'train-1', status: 'running', task_status: 'RUNNING'}],
  };
  let refreshes = 0;
  globalThis.document = {
    visibilityState: 'visible',
    addEventListener() {},
    removeEventListener() {},
  };
  globalThis.window = {TrainingTaskVisibilityRuntime: {render() { return true; }}};

  const runtime = installTrainingProgressStream({
    getState: () => state,
    projectId: () => state.project.id,
    trainingTaskRuntime: {
      async refresh() {
        refreshes += 1;
        return {stale: false, jobs: state.jobs};
      },
    },
    pollRegistry: {setTrainingRealtimeActive() {}, clear() {}},
    EventSourceImpl: FakeEventSource,
    documentImpl: globalThis.document,
  });
  runtime.syncPage('训练任务');
  const source = FakeEventSource.instances.at(-1);

  source.emit('training.task', {
    task_id: 'unknown-task',
    project_id: 'p1',
    status: 'RUNNING',
    progress_percent: 4,
    updated_at: '2026-09-22T00:00:01Z',
  });
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(refreshes, 1);

  source.emit('training.task', {
    task_id: 'train-1',
    project_id: 'p1',
    status: 'SUCCEEDED',
    persisted_status: 'SUCCEEDED',
    phase: 'completed',
    progress_percent: 100,
    updated_at: '2026-09-22T00:00:02Z',
    finished_at: '2026-09-22T00:00:02Z',
  });
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(refreshes, 2);

  runtime.destroy();
  cleanup();
});

test('stream errors restore polling and leaving the page closes the connection', () => {
  const state = {
    page: '训练任务',
    project: {id: 'p1'},
    jobs: [{id: 'train-1', task_id: 'train-1', status: 'running'}],
  };
  const realtime = [];
  const cleared = [];
  globalThis.document = {
    visibilityState: 'visible',
    addEventListener() {},
    removeEventListener() {},
  };
  globalThis.window = {};

  const runtime = installTrainingProgressStream({
    getState: () => state,
    projectId: () => state.project.id,
    trainingTaskRuntime: {async refresh() {}},
    pollRegistry: {
      setTrainingRealtimeActive(value) { realtime.push(Boolean(value)); },
      clear(key) { cleared.push(key); },
    },
    EventSourceImpl: FakeEventSource,
    documentImpl: globalThis.document,
  });
  runtime.syncPage('训练任务');
  const source = FakeEventSource.instances.at(-1);
  source.emit('training.ready', {task_ids: ['train-1']});
  assert.equal(realtime.at(-1), true);

  source.fail();
  assert.equal(realtime.at(-1), false);

  state.page = '数据集';
  runtime.syncPage('数据集');
  assert.equal(source.closed, true);
  assert.equal(cleared.includes('training-jobs'), true);

  runtime.destroy();
  cleanup();
});
