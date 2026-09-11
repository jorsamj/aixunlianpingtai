import test from 'node:test';
import assert from 'node:assert/strict';

import {installAlgorithmListRuntime} from '../../static/modules/algorithm-list-runtime.js';

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

test('algorithm expand/collapse is local-only and never fetches the algorithm list', () => {
  const state = {
    page: '算法列表',
    project: {id: 'p1'},
    algorithms: [{id: 'a1', versions: [{id: 'v1'}]}],
    jobs: [],
    alg428Expanded: {},
  };
  let renders = 0;
  let requests = 0;
  globalThis.window = {
    fetch: async () => { requests += 1; return response({items: []}); },
    renderAlg412: () => { renders += 1; },
  };

  const runtime = installAlgorithmListRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });

  assert.equal(window.toggleAlgorithm412('a1'), true);
  assert.equal(state.alg428Expanded.a1, true);
  assert.equal(requests, 0);
  assert.equal(renders, 1);

  assert.equal(window.toggleAlgorithm428('a1'), false);
  assert.equal(state.alg428Expanded.a1, false);
  assert.equal(requests, 0);
  assert.equal(renders, 2);

  runtime.destroy();
  cleanup();
});

test('focused refresh fetches only algorithms and jobs and updates the visible cards', async () => {
  const state = {
    page: '算法列表',
    project: {id: 'project 1'},
    algorithms: [{id: 'old'}],
    jobs: [{id: 'old-job'}],
    alg428Expanded: {},
  };
  const urls = [];
  let renders = 0;
  globalThis.window = {
    async fetch(url) {
      urls.push(url);
      if (url.includes('/algorithms')) return response({items: [{id: 'a2', name: '烟火检测', versions: []}]});
      if (url.endsWith('/jobs')) return response([{id: 'j2', status: 'running'}]);
      throw new Error(`unexpected URL: ${url}`);
    },
    renderAlg412: () => { renders += 1; },
  };

  const runtime = installAlgorithmListRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  const result = await runtime.refresh();

  assert.deepEqual(urls.sort(), [
    '/api/projects/project%201/jobs',
    '/api/v12/projects/project%201/algorithms',
  ]);
  assert.deepEqual(state.algorithms.map(row => row.id), ['a2']);
  assert.deepEqual(state.jobs.map(row => row.id), ['j2']);
  assert.equal(result.cached, false);
  assert.equal(result.stale, false);
  assert.equal(renders, 1);

  runtime.destroy();
  cleanup();
});

test('concurrent focused refreshes share one request pair', async () => {
  const state = {
    page: '算法列表',
    project: {id: 'p1'},
    algorithms: [],
    jobs: [],
    alg428Expanded: {},
  };
  const urls = [];
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  globalThis.window = {
    async fetch(url) {
      urls.push(url);
      await gate;
      return url.includes('/algorithms') ? response({items: []}) : response([]);
    },
    renderAlg412: () => {},
  };

  const runtime = installAlgorithmListRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  const first = runtime.refresh();
  const second = runtime.refresh();
  await Promise.resolve();

  assert.equal(urls.length, 2);
  release();
  await Promise.all([first, second]);
  assert.equal(urls.length, 2);

  runtime.destroy();
  cleanup();
});

test('minimum refresh age can reuse fresh algorithm state without network traffic', async () => {
  const state = {
    page: '算法列表',
    project: {id: 'p1'},
    algorithms: [],
    jobs: [],
    alg428Expanded: {},
  };
  let requests = 0;
  globalThis.window = {
    async fetch(url) {
      requests += 1;
      return url.includes('/algorithms') ? response({items: []}) : response([]);
    },
    renderAlg412: () => {},
  };

  const runtime = installAlgorithmListRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  await runtime.refresh({render: false});
  const second = await runtime.refresh({render: false, minAgeMs: 10_000});

  assert.equal(requests, 2);
  assert.equal(second.cached, true);

  runtime.destroy();
  cleanup();
});

test('focused refresh uses raw fetch but discards results after navigation and always releases inflight', async () => {
  const state = {
    page: '算法列表',
    project: {id: 'p1'},
    algorithms: [{id: 'before'}],
    jobs: [{id: 'before-job'}],
    alg428Expanded: {},
  };
  let generation = 7;
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let rawRequests = 0;
  let scopedRequests = 0;
  const raw = async url => {
    rawRequests += 1;
    await gate;
    return url.includes('/algorithms')
      ? response({items: [{id: 'after'}]})
      : response([{id: 'after-job'}]);
  };
  const scoped = async () => {
    scopedRequests += 1;
    throw new Error('scoped fetch should not own modular algorithm refresh');
  };
  scoped.__pageRequestScopeOriginal = raw;
  globalThis.window = {
    fetch: scoped,
    PageRequestScopeRuntime: {stats: () => ({generation})},
    renderAlg412: () => { throw new Error('stale refresh must not render'); },
  };

  const runtime = installAlgorithmListRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  const pending = runtime.refresh();
  await Promise.resolve();
  state.page = '数据集';
  generation += 1;
  release();
  const result = await pending;

  assert.equal(rawRequests, 2);
  assert.equal(scopedRequests, 0);
  assert.equal(result.stale, true);
  assert.deepEqual(state.algorithms.map(row => row.id), ['before']);
  assert.deepEqual(state.jobs.map(row => row.id), ['before-job']);
  assert.equal(runtime.state().inflight, false);

  runtime.destroy();
  cleanup();
});
