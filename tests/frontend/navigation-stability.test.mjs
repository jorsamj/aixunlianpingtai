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

test('navigation clears page-owned polling timers when leaving the page', () => {
  const state = {page: '训练任务', jobPollTimer: 101, source422Timer: 202, auto422Timer: 303};
  const cleared = [];
  const originalClearInterval = globalThis.clearInterval;
  globalThis.clearInterval = value => cleared.push(value);

  globalThis.document = {
    getElementById() { return {dataset: {}}; },
  };
  globalThis.window = {
    setPage(page) { state.page = page; },
    __videoFramePollTimer: 404,
    __prelabelPollTimer: 505,
  };

  const runtime = installNavigationStability({getState: () => state});
  globalThis.window.setPage('算法列表');

  assert.deepEqual(new Set(cleared), new Set([101, 202, 303, 404, 505]));
  assert.equal(state.jobPollTimer, null);
  assert.equal(state.source422Timer, null);
  assert.equal(state.auto422Timer, null);

  runtime.destroy();
  globalThis.clearInterval = originalClearInterval;
  cleanup();
});
