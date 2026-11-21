import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {installNavigationStability} from '../../static/modules/navigation-stability.js';

function cleanup() {
  delete globalThis.window;
  delete globalThis.document;
}

test('navigation action fence commits only while its owner page epoch is current', () => {
  const state = {page: '训练资源'};
  const view = {dataset: {}};
  globalThis.document = {getElementById(id) { return id === 'view' ? view : null; }};
  globalThis.window = {setPage(page) { state.page = page; }};

  const runtime = installNavigationStability({getState: () => state});
  assert.equal(typeof runtime.action, 'function', 'NavigationStability must expose a named action fence owner');

  const action = runtime.action('训练资源');
  let commits = 0;
  assert.equal(action.isCurrent(), true);
  assert.equal(action.commit(() => { commits += 1; }), true);
  assert.equal(commits, 1);

  globalThis.window.setPage('数据集');
  assert.equal(action.isCurrent(), false);
  assert.equal(action.commit(() => { commits += 1; }), false);
  assert.equal(commits, 1, 'stale action must not commit UI effects after navigation');
  assert.equal(state.page, '数据集');

  runtime.destroy();
  cleanup();
});

test('classic app has no fixed-page business writes and resource save is explicitly fenced', () => {
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  for (const page of ['训练资源', '模型配置', '部署转换', '训练任务']) {
    assert.equal(
      new RegExp(`state\\.page\\s*=\\s*['\"]${page}['\"]`).test(app),
      false,
      `business code must navigate to ${page} through NavigationStability instead of direct state.page assignment`,
    );
  }
  assert.equal(
    /if\(state\.page==='新建算法'\|\|state\.page==='自动迭代'\)state\.page='算法列表'/.test(app),
    false,
    'renderer must not directly rewrite legacy route state',
  );

  const saveServer = app.match(/window\.saveServer=async\(\)=>\{[^\n]+\};/)?.[0] || '';
  assert.match(saveServer, /NavigationStability\?\.action\?\./, 'saveServer must capture a navigation action fence');
  assert.match(saveServer, /action\.isCurrent\(\)/, 'saveServer must reject stale completion effects');
});

test('two navigations queued during core startup only perform the latest route after readiness', async () => {
  const state = {page: '算法列表'};
  const performed = [];
  let release;
  const ready = new Promise(resolve => {release = resolve;});
  globalThis.document = {getElementById: () => ({dataset: {}})};
  globalThis.window = {setPage(page) {state.page = page;}};
  const runtime = installNavigationStability({
    getState: () => state,
    waitForNavigationReady: () => ready,
    performNavigation(page) {performed.push(page); state.page = page;},
  });
  try {
    const first = window.setPage('数据集');
    const second = window.setPage('训练任务');
    release(true);
    assert.equal(await first, false);
    await second;
    assert.deepEqual(performed, ['训练任务']);
    assert.equal(state.page, '训练任务');
  } finally {runtime.destroy(); cleanup();}
});

test('failed startup readiness does not activate a pending business page', async () => {
  const state = {page: '算法列表'};
  let count = 0;
  globalThis.document = {getElementById: () => ({dataset: {}})};
  globalThis.window = {setPage(page) {state.page = page;}};
  const runtime = installNavigationStability({
    getState: () => state,
    waitForNavigationReady: () => Promise.resolve(false),
    performNavigation(page) {count++; state.page = page;},
  });
  try {
    assert.equal(await window.setPage('训练任务'), false);
    assert.equal(count, 0);
    assert.equal(state.page, '算法列表');
  } finally {runtime.destroy(); cleanup();}
});
