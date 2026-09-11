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

test('manual refresh reuses a poll result that completed in the same interaction window', async () => {
  const state = {page: '训练任务', project: {id: 'p1'}, jobs: [], __navigationEpoch: 1};
  let requests = 0;
  const originalNow = Date.now;
  let now = 1_000;
  Date.now = () => now;
  globalThis.window = {
    async fetch() { requests += 1; return response([{id: 'j1', status: 'running'}]); },
    updateTrainingJobTable() {},
  };

  const runtime = installTrainingTaskRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  await runtime.refresh({source: 'poll'});
  now += 60;
  const result = await runtime.refresh({source: 'manual'});

  assert.equal(requests, 1);
  assert.equal(result.reused, true);
  assert.equal(runtime.state().lastRefreshSource, 'poll');

  runtime.destroy();
  Date.now = originalNow;
  cleanup();
});

test('task mutation forces a fresh jobs request even after a very recent poll', async () => {
  const state = {page: '训练任务', project: {id: 'p1'}, jobs: [{id: 'j1', status: 'running'}], __navigationEpoch: 1};
  const calls = [];
  const originalNow = Date.now;
  let now = 2_000;
  Date.now = () => now;
  globalThis.window = {
    async fetch(url, init = {}) {
      calls.push(`${String(init.method || 'GET').toUpperCase()} ${url}`);
      if (url.endsWith('/pause')) return response({ok: true});
      if (url.endsWith('/jobs')) return response([{id: 'j1', status: calls.some(row => row.includes('/pause')) ? 'paused' : 'running'}]);
      throw new Error(`unexpected URL: ${url}`);
    },
  };

  const runtime = installTrainingTaskRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  await runtime.refresh({source: 'poll'});
  now += 20;
  await window.pauseTrain428('j1');

  assert.deepEqual(calls, [
    'GET /api/projects/p1/jobs',
    'POST /api/v48/projects/p1/jobs/j1/pause',
    'GET /api/projects/p1/jobs',
  ]);
  assert.equal(state.jobs[0].status, 'paused');

  runtime.destroy();
  Date.now = originalNow;
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

test('pause action mutates only the task endpoint then performs one focused jobs refresh', async () => {
  const state = {page: '训练任务', project: {id: 'p1'}, jobs: [{id: 'j1', status: 'running'}], __navigationEpoch: 2};
  const calls = [];
  const notices = [];
  globalThis.window = {
    async fetch(url, init = {}) {
      calls.push(`${String(init.method || 'GET').toUpperCase()} ${url}`);
      if (url.endsWith('/pause')) return response({ok: true});
      if (url.endsWith('/jobs')) return response([{id: 'j1', status: 'paused'}]);
      throw new Error(`unexpected URL: ${url}`);
    },
  };

  const runtime = installTrainingTaskRuntime({
    getState: () => state,
    projectId: () => state.project.id,
    notify: message => notices.push(String(message)),
  });
  const ok = await window.pauseTrain428('j1');

  assert.equal(ok, true);
  assert.deepEqual(calls, [
    'POST /api/v48/projects/p1/jobs/j1/pause',
    'GET /api/projects/p1/jobs',
  ]);
  assert.equal(state.jobs[0].status, 'paused');
  assert.deepEqual(notices, ['训练已暂停']);

  runtime.destroy();
  cleanup();
});

test('deleting an active task stops it, deletes it, then refreshes only jobs', async () => {
  const state = {page: '训练任务', project: {id: 'p1'}, jobs: [{id: 'j1', status: 'running'}], __navigationEpoch: 2};
  const calls = [];
  globalThis.window = {
    confirm: () => true,
    async fetch(url, init = {}) {
      calls.push(`${String(init.method || 'GET').toUpperCase()} ${url}`);
      if (url.endsWith('/stop')) return response({ok: true});
      if (String(init.method || '').toUpperCase() === 'DELETE') return response({ok: true});
      if (url.endsWith('/jobs')) return response([]);
      throw new Error(`unexpected URL: ${url}`);
    },
  };

  const runtime = installTrainingTaskRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  const ok = await window.deleteTrain428('j1');

  assert.equal(ok, true);
  assert.deepEqual(calls, [
    'POST /api/v48/projects/p1/jobs/j1/stop',
    'DELETE /api/v12/projects/p1/jobs/j1',
    'GET /api/projects/p1/jobs',
  ]);
  assert.deepEqual(state.jobs, []);

  runtime.destroy();
  cleanup();
});
