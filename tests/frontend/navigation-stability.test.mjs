import test from 'node:test';
import assert from 'node:assert/strict';

import {
  NavigationEpochGuard,
  installNavigationStability,
} from '../../static/modules/navigation-stability.js';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
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

test('stale async training action repairs the current page after navigation', async () => {
  const state = {page: '训练任务'};
  const work = deferred();
  let staleTrainingRender = 0;
  let currentPageRepairs = 0;
  let observerCallback = null;

  const view = {dataset: {}};
  globalThis.document = {
    getElementById(id) { return id === 'view' ? view : null; },
  };
  globalThis.MutationObserver = class {
    constructor(callback) { observerCallback = callback; }
    observe() {}
    disconnect() {}
  };
  globalThis.window = {
    setPage(page) { state.page = page; },
    render() { currentPageRepairs += 1; },
    refreshTrainPage428: async function () {
      await work.promise;
      staleTrainingRender += 1;
      observerCallback?.();
    },
  };

  const runtime = installNavigationStability({getState: () => state});
  const staleAction = globalThis.window.refreshTrainPage428();

  globalThis.window.setPage('数据集');
  assert.equal(state.page, '数据集');

  work.resolve();
  await staleAction;
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(staleTrainingRender, 1);
  assert.ok(currentPageRepairs >= 1, 'stale render should trigger current-page repair');
  assert.equal(state.page, '数据集');
  assert.equal(runtime.guard.page, '数据集');

  runtime.destroy();
  delete globalThis.window;
  delete globalThis.document;
  delete globalThis.MutationObserver;
});

test('same-page async action is not treated as stale', async () => {
  const state = {page: '训练任务'};
  let repairs = 0;
  const view = {dataset: {}};

  globalThis.document = {
    getElementById(id) { return id === 'view' ? view : null; },
  };
  globalThis.MutationObserver = class {
    constructor() {}
    observe() {}
    disconnect() {}
  };
  globalThis.window = {
    setPage(page) { state.page = page; },
    render() { repairs += 1; },
    refreshTrainPage428: async function () { return 'ok'; },
  };

  const runtime = installNavigationStability({getState: () => state});
  await globalThis.window.refreshTrainPage428();
  await Promise.resolve();

  assert.equal(repairs, 0);
  assert.equal(state.page, '训练任务');

  runtime.destroy();
  delete globalThis.window;
  delete globalThis.document;
  delete globalThis.MutationObserver;
});
