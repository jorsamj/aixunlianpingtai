import test from 'node:test';
import assert from 'node:assert/strict';

import {installTrainingTaskRuntime} from '../../static/modules/training-task-runtime.js';

function response(body) {
  return {
    ok: true,
    status: 200,
    async json() { return body; },
    async text() { return JSON.stringify(body); },
  };
}

function cleanup() {
  delete globalThis.window;
  delete globalThis.document;
}

test('focused training refresh fetches jobs only and patches the task table', async () => {
  const state = {page: '训练任务', project: {id: 'p 1'}, jobs: [], __navigationEpoch: 4};
  const urls = [];
  let patches = 0;
  globalThis.document = {
    querySelector() { return null; },
    addEventListener() {},
    removeEventListener() {},
  };
  globalThis.window = {
    async fetch(url) { urls.push(url); return response([{id: 'j1', status: 'running'}]); },
    updateTrainingJobTable() { patches += 1; },
  };

  const runtime = installTrainingTaskRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  const result = await runtime.refresh();

  assert.deepEqual(urls, ['/api/projects/p%201/jobs']);
  assert.deepEqual(state.jobs, [{id: 'j1', status: 'running'}]);
  assert.equal(patches, 1);
  assert.equal(result.stale, false);

  runtime.destroy();
  cleanup();
});

test('concurrent training refreshes share one jobs request', async () => {
  const state = {page: '训练任务', project: {id: 'p1'}, jobs: [], __navigationEpoch: 1};
  let requests = 0;
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  globalThis.window = {
    async fetch() { requests += 1; await gate; return response([]); },
    updateTrainingJobTable() {},
  };

  const runtime = installTrainingTaskRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  const first = runtime.refresh();
  const second = runtime.refresh();
  await Promise.resolve();
  assert.equal(requests, 1);
  release();
  await Promise.all([first, second]);
  assert.equal(requests, 1);

  runtime.destroy();
  cleanup();
});

test('training refresh discards response after navigation and always releases inflight lock', async () => {
  const state = {page: '训练任务', project: {id: 'p1'}, jobs: [{id: 'old'}], __navigationEpoch: 8};
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let patches = 0;
  globalThis.window = {
    async fetch() { await gate; return response([{id: 'stale'}]); },
    updateTrainingJobTable() { patches += 1; },
  };

  const runtime = installTrainingTaskRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  const pending = runtime.refresh();
  state.page = '数据集';
  state.__navigationEpoch = 9;
  release();
  const result = await pending;

  assert.equal(result.stale, true);
  assert.deepEqual(state.jobs, [{id: 'old'}]);
  assert.equal(patches, 0);
  assert.equal(runtime.state().inflight, false);

  runtime.destroy();
  cleanup();
});

test('runtime replaces legacy refreshJobsOnly and restores it on destroy', async () => {
  const state = {page: '训练任务', project: {id: 'p1'}, jobs: [], __navigationEpoch: 1};
  const legacy = async () => 'legacy';
  globalThis.window = {
    fetch: async () => response([]),
    refreshJobsOnly: legacy,
    updateTrainingJobTable() {},
  };

  const runtime = installTrainingTaskRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  assert.equal(window.refreshJobsOnly.__trainingTaskRuntime, true);
  await window.refreshJobsOnly();
  runtime.destroy();
  assert.equal(window.refreshJobsOnly, legacy);
  cleanup();
});
