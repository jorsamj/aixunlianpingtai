import test from 'node:test';
import assert from 'node:assert/strict';

import {
  NavigationEpochGuard,
  installNavigationStability,
  normalizeNavigationPage,
} from '../../static/modules/navigation-stability.js';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}

function cleanup() {
  delete globalThis.window;
  delete globalThis.document;
}

test('navigation epoch invalidates work started on the previous page', () => {
  const guard = new NavigationEpochGuard('训练任务');
  const old = guard.token('训练任务');
  assert.equal(guard.isCurrent(old, '训练任务'), true);

  guard.navigate('数据集');

  assert.equal(guard.isCurrent(old, '数据集'), false);
  const current = guard.token('数据集');
  assert.equal(guard.isCurrent(current, '数据集'), true);
});

test('legacy navigation aliases normalize to canonical pages', () => {
  assert.equal(normalizeNavigationPage('自动标注'), '自动标注及清洗');
  assert.equal(normalizeNavigationPage('自动标注及清洗'), '自动标注及清洗');
  assert.equal(normalizeNavigationPage('数据集'), '数据集');
  assert.equal(normalizeNavigationPage(''), '');
});

test('final navigation coordinates legacy alias lifecycle with the canonical page only', () => {
  const state = {page: '算法列表'};
  const calls = [];
  const view = {dataset: {}};
  const requestScope = {
    navigate(page) { calls.push(`request:navigate:${page}`); },
    alignPage(page) { calls.push(`request:align:${page}`); },
  };
  const pollRegistry = {
    beforeNavigate(page) { calls.push(`poll:before:${page}`); },
    afterNavigate(page) { calls.push(`poll:after:${page}`); },
  };

  globalThis.document = {
    getElementById(id) { return id === 'view' ? view : null; },
  };
  globalThis.window = {
    setPage(page) {
      calls.push(`classic:${page}`);
      state.page = page;
    },
  };

  const runtime = installNavigationStability({getState: () => state, requestScope, pollRegistry});
  globalThis.window.setPage('自动标注');

  assert.equal(state.page, '自动标注及清洗');
  assert.equal(runtime.guard.page, '自动标注及清洗');
  assert.equal(view.dataset.navigationPage, '自动标注及清洗');
  assert.deepEqual(calls, [
    'request:navigate:自动标注及清洗',
    'poll:before:自动标注及清洗',
    'classic:自动标注及清洗',
    'request:align:自动标注及清洗',
    'poll:after:自动标注及清洗',
  ]);

  runtime.destroy();
  cleanup();
});

test('readiness gate runs after navigation intent but before classic page mutation', async () => {
  const state = {page: '算法列表'};
  const calls = [];
  const ready = deferred();
  const view = {dataset: {}};
  const requestScope = {
    navigate(page) { calls.push(`request:navigate:${page}`); },
    alignPage(page) { calls.push(`request:align:${page}`); },
  };
  const pollRegistry = {
    beforeNavigate(page) { calls.push(`poll:before:${page}`); },
    afterNavigate(page) { calls.push(`poll:after:${page}`); },
  };

  globalThis.document = {
    getElementById(id) { return id === 'view' ? view : null; },
  };
  globalThis.window = {
    setPage(page) {
      calls.push(`classic:${page}`);
      state.page = page;
      return 'navigated';
    },
  };

  const runtime = installNavigationStability({
    getState: () => state,
    requestScope,
    pollRegistry,
    waitForNavigationReady(page) {
      calls.push(`ready:${page}`);
      return ready.promise;
    },
  });

  const navigation = globalThis.window.setPage('数据集');
  assert.equal(state.page, '算法列表');
  assert.deepEqual(calls, [
    'request:navigate:数据集',
    'poll:before:数据集',
    'ready:数据集',
  ]);

  ready.resolve();
  assert.equal(await navigation, 'navigated');
  assert.equal(state.page, '数据集');
  assert.deepEqual(calls, [
    'request:navigate:数据集',
    'poll:before:数据集',
    'ready:数据集',
    'classic:数据集',
    'request:align:数据集',
    'poll:after:数据集',
  ]);

  runtime.destroy();
  cleanup();
});

test('stale training renderer is blocked after navigation without global rerender repair', async () => {
  const state = {page: '训练任务'};
  const work = deferred();
  let trainingRenders = 0;
  let globalRenders = 0;
  const view = {dataset: {}};

  globalThis.document = {
    getElementById(id) { return id === 'view' ? view : null; },
  };
  globalThis.window = {
    setPage(page) { state.page = page; },
    render() { globalRenders += 1; },
    renderTraining428() { trainingRenders += 1; },
    refreshTrainPage428: async function () {
      await work.promise;
      globalThis.window.renderTraining428();
    },
  };

  const runtime = installNavigationStability({getState: () => state});
  const staleAction = globalThis.window.refreshTrainPage428();

  globalThis.window.setPage('数据集');
  assert.equal(state.page, '数据集');

  work.resolve();
  await staleAction;

  assert.equal(trainingRenders, 0, 'renderer owned by 训练任务 must not paint after leaving the page');
  assert.equal(globalRenders, 0, 'stale completion must not trigger an expensive global repair render');
  assert.equal(state.page, '数据集');
  assert.equal(runtime.guard.page, '数据集');

  runtime.destroy();
  cleanup();
});

test('same-page renderer is still allowed', async () => {
  const state = {page: '训练任务'};
  let trainingRenders = 0;
  const view = {dataset: {}};

  globalThis.document = {
    getElementById(id) { return id === 'view' ? view : null; },
  };
  globalThis.window = {
    setPage(page) { state.page = page; },
    renderTraining428() { trainingRenders += 1; },
    refreshTrainPage428: async function () {
      globalThis.window.renderTraining428();
      return 'ok';
    },
  };

  const runtime = installNavigationStability({getState: () => state});
  await globalThis.window.refreshTrainPage428();

  assert.equal(trainingRenders, 1);
  assert.equal(state.page, '训练任务');

  runtime.destroy();
  cleanup();
});

test('final dataset, auto-label and video renderers are page-owned', () => {
  const state = {page: '数据集'};
  const calls = [];
  const view = {dataset: {}};

  globalThis.document = {
    getElementById(id) { return id === 'view' ? view : null; },
  };
  globalThis.window = {
    setPage(page) { state.page = page; },
    renderDatasets424() { calls.push('dataset'); },
    renderOps427() { calls.push('auto'); },
    renderVideo424() { calls.push('video'); },
  };

  const runtime = installNavigationStability({getState: () => state});

  assert.equal(globalThis.window.renderDatasets424(), undefined);
  assert.equal(globalThis.window.renderOps427(), false);
  assert.equal(globalThis.window.renderVideo424(), false);
  assert.deepEqual(calls, ['dataset']);

  globalThis.window.setPage('自动标注及清洗');
  assert.equal(globalThis.window.renderDatasets424(), false);
  globalThis.window.renderOps427();
  assert.equal(globalThis.window.renderVideo424(), false);
  assert.deepEqual(calls, ['dataset', 'auto']);

  globalThis.window.setPage('视频切帧');
  assert.equal(globalThis.window.renderDatasets424(), false);
  assert.equal(globalThis.window.renderOps427(), false);
  globalThis.window.renderVideo424();
  assert.deepEqual(calls, ['dataset', 'auto', 'video']);

  runtime.destroy();
  cleanup();
});

test('navigation without PollRegistry has no legacy timer fallback side effects', () => {
  const state = {page: '训练任务'};
  const cleared = [];
  const originalClearInterval = globalThis.clearInterval;
  globalThis.clearInterval = value => cleared.push(value);

  globalThis.document = {
    getElementById() { return {dataset: {}}; },
  };
  globalThis.window = {
    setPage(page) { state.page = page; },
  };

  const runtime = installNavigationStability({getState: () => state});
  globalThis.window.setPage('算法列表');

  assert.deepEqual(cleared, []);
  assert.equal(state.page, '算法列表');

  runtime.destroy();
  globalThis.clearInterval = originalClearInterval;
  cleanup();
});

test('navigation coordinates request cancellation and centralized polling lifecycle', () => {
  const state = {page: '训练任务'};
  const calls = [];
  const requestScope = {
    navigate(page) { calls.push(`request:navigate:${page}`); },
    alignPage(page) { calls.push(`request:align:${page}`); },
  };
  const pollRegistry = {
    beforeNavigate(page) { calls.push(`poll:before:${page}`); },
    afterNavigate(page) { calls.push(`poll:after:${page}`); },
  };

  globalThis.document = {
    getElementById() { return {dataset: {}}; },
  };
  globalThis.window = {
    setPage(page) { state.page = page; },
  };

  const runtime = installNavigationStability({getState: () => state, requestScope, pollRegistry});
  globalThis.window.setPage('数据集');

  assert.deepEqual(calls, [
    'request:navigate:数据集',
    'poll:before:数据集',
    'request:align:数据集',
    'poll:after:数据集',
  ]);

  runtime.destroy();
  cleanup();
});
