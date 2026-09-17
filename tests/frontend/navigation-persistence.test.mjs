import test from 'node:test';
import assert from 'node:assert/strict';

import {installNavigationStability} from '../../static/modules/navigation-stability.js';

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

test('async final setPage persists only after readiness navigation has completed', async () => {
  const state = {page: '算法列表'};
  const gate = deferred();
  const calls = [];
  const view = {dataset: {}};

  globalThis.document = {
    getElementById(id) { return id === 'view' ? view : null; },
  };
  globalThis.window = {
    async setPage(page) {
      await gate.promise;
      state.page = page;
      return 'navigated';
    },
  };

  const runtime = installNavigationStability({
    getState: () => state,
    requestScope: {
      navigate(page) { calls.push(`request:navigate:${page}`); },
      alignPage(page) { calls.push(`request:align:${page}`); },
    },
    pollRegistry: {
      beforeNavigate(page) { calls.push(`poll:before:${page}`); },
      afterNavigate(page) { calls.push(`poll:after:${page}`); },
    },
    persistNavigationState(currentState, actualPage) {
      calls.push(`persist:${currentState.page}:${actualPage}`);
    },
  });

  const navigation = globalThis.window.setPage('数据集');
  assert.equal(state.page, '算法列表');
  assert.deepEqual(calls, ['request:navigate:数据集', 'poll:before:数据集']);

  gate.resolve();
  assert.equal(await navigation, 'navigated');
  assert.equal(state.page, '数据集');
  assert.deepEqual(calls, [
    'request:navigate:数据集',
    'poll:before:数据集',
    'request:align:数据集',
    'poll:after:数据集',
    'persist:数据集:数据集',
  ]);
  assert.equal(view.dataset.navigationPage, '数据集');

  runtime.destroy();
  cleanup();
});
