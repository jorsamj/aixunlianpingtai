import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  hasActiveAutoLabelTask,
  installAutoLabelPollRuntime,
  renderAutoLabelTaskRows,
} from '../../static/modules/auto-label-poll-runtime.js';

function taskView(task = {}) {
  const active = ['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(String(task.status || '').toUpperCase());
  const status = String(task.status || '').toUpperCase();
  const total = Number(task.summary?.total || 0);
  const completed = Number(task.summary?.completed || 0);
  return {
    active,
    status,
    statusText: status === 'RUNNING' ? 'AI标注中' : status === 'SUCCEEDED' ? '已完成' : status,
    percent: total ? completed / total * 100 : 0,
    progressText: `${completed} / ${total}`,
    boxes: Number(task.summary?.boxes || 0),
    canReview: status === 'AWAITING_CONFIRMATION',
    canRetry: ['SUCCEEDED', 'FAILED'].includes(status),
  };
}

test('auto-label task rows render label names and task actions without page markup', () => {
  const html = renderAutoLabelTaskRows([{
    id: 'task-1',
    name: '烟火自动标注',
    status: 'SUCCEEDED',
    requested_labels: ['fire', 'smoke'],
    created_at: '2026-09-11T00:00:00Z',
    updated_at: '2026-09-11T00:00:12Z',
    summary: {total: 2, completed: 2, boxes: 5},
  }], {
    state: {labels: [{code: 'fire', display_name: '明火'}, {code: 'smoke', display_name: '烟雾'}]},
    annotationTaskView: taskView,
  });

  assert.match(html, /烟火自动标注/);
  assert.match(html, /明火、烟雾/);
  assert.match(html, /已完成/);
  assert.match(html, /100\.0%/);
  assert.match(html, /详情/);
  assert.match(html, /重试/);
  assert.doesNotMatch(html, /<section/);
});

test('active detection follows annotation task view contract', () => {
  assert.equal(hasActiveAutoLabelTask([{status: 'RUNNING'}], taskView), true);
  assert.equal(hasActiveAutoLabelTask([{status: 'SUCCEEDED'}], taskView), false);
});

test('runtime leaves renderer untouched and owns polling only through PollRegistry', async () => {
  const state = {
    page: '自动标注及清洗',
    project: {id: 'project-1'},
    v427OpsTab: 'label',
    labels: [{code: 'fire', display_name: '明火'}],
    annotationTasks60: [{
      id: 'running-1', status: 'RUNNING', requested_labels: ['fire'],
      summary: {total: 10, completed: 2, boxes: 3},
    }],
  };
  const tbody = {innerHTML: '<tr><td>old</td></tr>'};
  const rootView = {marker: 'same-view'};
  globalThis.document = {
    getElementById(id) {
      if (id === 'ai60TaskRows') return tbody;
      if (id === 'view') return rootView;
      return null;
    },
  };

  let managed = null;
  const cleared = [];
  const pollRegistry = {
    startTimeout(key, owners, callback, delay) {
      managed = {key, owners, callback, delay, managed: true};
      return 501;
    },
    clear(key) {
      cleared.push(key);
      if (managed?.key === key) managed = null;
      return true;
    },
    snapshot() {
      return managed ? [{key: managed.key, owners: [managed.owners], active: true, managed: true, delay: managed.delay}] : [];
    },
  };

  const originalRenderOps = async () => 'app-owned-render';
  globalThis.window = {
    renderOps427: originalRenderOps,
    fetch: async () => ({
      ok: true,
      async json() {
        return {items: [{
          id: 'done-1', name: '完成任务', status: 'SUCCEEDED', requested_labels: ['fire'],
          created_at: '2026-09-11T00:00:00Z', updated_at: '2026-09-11T00:00:05Z',
          summary: {total: 10, completed: 10, boxes: 12},
        }]};
      },
    }),
  };

  const runtime = installAutoLabelPollRuntime({
    getState: () => state,
    pollRegistry,
    annotationTaskView: taskView,
    pollDelay: 1800,
  });

  await Promise.resolve();
  assert.equal(window.renderOps427, originalRenderOps, 'runtime must not wrap the page renderer');
  assert.equal(managed?.key, 'auto-label-v60');
  assert.equal(managed?.delay, 1800);
  assert.equal(runtime.snapshot().classicWrapperOwner, false);
  assert.equal(runtime.snapshot().timerOwner, false);

  const currentView = document.getElementById('view');
  await managed.callback();

  assert.equal(document.getElementById('view'), currentView, 'polling must not replace the page root');
  assert.match(tbody.innerHTML, /完成任务/);
  assert.match(tbody.innerHTML, /已完成/);
  assert.deepEqual(state.annotationTasks60.map(task => task.id), ['done-1']);
  assert.equal(managed, null, 'completed task should not re-arm polling');
  assert.ok(cleared.includes('auto-label-v60'));

  state.page = '数据集';
  assert.equal(runtime.activate(), false);
  assert.equal(managed, null);

  runtime.destroy();
  assert.equal(window.renderOps427, originalRenderOps);
  delete globalThis.window;
  delete globalThis.document;
});

test('AutoLabelPollRuntime stays wrapper-free and timer-free', () => {
  const source = readFileSync(new URL('../../static/modules/auto-label-poll-runtime.js', import.meta.url), 'utf8');
  for (const token of [
    'renderOps427',
    '__autoLabelPollRuntimeWrapped',
    'originalRenderOps',
    'wrappedRenderOps',
    'rebindTimers',
    'ai60ListTimer',
    'setTimeout(',
    'clearTimeout(',
  ]) {
    assert.equal(source.includes(token), false, `retired AutoLabel lifecycle token remains: ${token}`);
  }
  assert.match(source, /classicWrapperOwner: false/);
  assert.match(source, /timerOwner: false/);
  assert.match(source, /build: 'auto-label-poll-422501'/);
});
