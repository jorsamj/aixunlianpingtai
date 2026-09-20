import test from 'node:test';
import assert from 'node:assert/strict';

import {installTrainingTaskVisibilityRuntime} from '../../static/modules/training-task-visibility-runtime.js';

function cleanup() {
  delete globalThis.window;
  delete globalThis.document;
}

function fakeRoot() {
  const body = {innerHTML: ''};
  const activeCount = {textContent: ''};
  const historyCount = {textContent: ''};
  const activeClasses = new Set();
  const historyClasses = new Set();
  const button = (count, classes) => ({
    querySelector: selector => selector === 'span' ? count : null,
    classList: {
      toggle(name, on) {
        if (on) classes.add(name);
        else classes.delete(name);
      },
    },
  });
  const buttons = [button(activeCount, activeClasses), button(historyCount, historyClasses)];
  const root = {
    querySelector: selector => selector === '.train428-table tbody' ? body : null,
    querySelectorAll: selector => selector === '.train428-tabs button' ? buttons : [],
  };
  return {root, body, activeCount, historyCount, activeClasses, historyClasses};
}

function installFixture({page = '训练任务', jobs = [{id: 'run-1', status: 'running'}]} = {}) {
  const state = {
    page,
    project: {id: 'p1'},
    jobs,
    train428Tab: 'active',
  };
  const dom = fakeRoot();
  globalThis.document = {
    querySelector: selector => selector === '.train428-page' ? dom.root : null,
  };
  const calls = [];
  const runtime = {
    async refresh(options = {}) {
      calls.push(options);
      return {stale: false, jobs: state.jobs};
    },
  };
  globalThis.window = {
    PlatformCore: {runtime: {}},
    TrainingTaskRuntime: runtime,
    PollRegistryRuntime: {replaceTrainingJobTimer() {}},
    loadRelated: async () => undefined,
    renderTraining423() {},
  };
  return {state, dom, runtime, calls};
}

test('generic loadRelated cannot overwrite canonical training jobs after runtime ownership', async () => {
  const fixture = installFixture({page: '数据集'});
  fixture.state.jobs = [{id: 'run-1', status: 'running'}];
  window.loadRelated = async () => {
    fixture.state.jobs = [];
    fixture.state.labels = [{id: 'label-1'}];
    return 'legacy-loaded';
  };

  const visibility = installTrainingTaskVisibilityRuntime({
    getState: () => fixture.state,
    trainingTaskRuntime: fixture.runtime,
    pollRegistry: window.PollRegistryRuntime,
  });
  const result = await window.loadRelated();

  assert.equal(result, 'legacy-loaded');
  assert.deepEqual(fixture.state.jobs, [{id: 'run-1', status: 'running'}]);
  assert.deepEqual(fixture.state.labels, [{id: 'label-1'}]);
  assert.equal(window.loadRelated.__trainingJobsPreserved, true);

  visibility.destroy();
  cleanup();
});

test('loadRelated on training page routes to canonical jobs refresh instead of project aggregate', async () => {
  const fixture = installFixture();
  let legacyCalls = 0;
  window.loadRelated = async () => {
    legacyCalls += 1;
    fixture.state.jobs = [];
  };

  const visibility = installTrainingTaskVisibilityRuntime({
    getState: () => fixture.state,
    trainingTaskRuntime: fixture.runtime,
    pollRegistry: window.PollRegistryRuntime,
  });
  fixture.calls.length = 0;
  await window.loadRelated();

  assert.equal(legacyCalls, 0);
  assert.equal(fixture.calls.length, 1);
  assert.equal(fixture.calls[0].force, true);
  assert.equal(fixture.calls[0].source, 'related');
  assert.deepEqual(fixture.state.jobs, [{id: 'run-1', status: 'running'}]);

  visibility.destroy();
  cleanup();
});

test('visibility renderer keeps transitional non-terminal training states in active tab', () => {
  const fixture = installFixture({jobs: [
    {id: 'starting-1', status: 'starting', current_item: '准备训练'},
    {id: 'stopping-1', status: 'cancel_requested', current_item: '正在停止'},
    {id: 'done-1', status: 'completed', progress_percent: 100},
  ]});

  const visibility = installTrainingTaskVisibilityRuntime({
    getState: () => fixture.state,
    trainingTaskRuntime: fixture.runtime,
    pollRegistry: window.PollRegistryRuntime,
  });
  visibility.render();

  assert.match(fixture.dom.body.innerHTML, /starting-1/);
  assert.match(fixture.dom.body.innerHTML, /stopping-1/);
  assert.doesNotMatch(fixture.dom.body.innerHTML, /done-1/);
  assert.equal(fixture.dom.activeCount.textContent, '2');
  assert.equal(fixture.dom.historyCount.textContent, '1');

  fixture.state.train428Tab = 'history';
  visibility.render();
  assert.doesNotMatch(fixture.dom.body.innerHTML, /starting-1/);
  assert.match(fixture.dom.body.innerHTML, /done-1/);

  visibility.destroy();
  cleanup();
});


test('empty state spans all eleven columns and success alias is terminal metadata', () => {
  const fixture = installFixture({jobs: []});
  const visibility = installTrainingTaskVisibilityRuntime({
    getState: () => fixture.state,
    trainingTaskRuntime: fixture.runtime,
    pollRegistry: window.PollRegistryRuntime,
  });

  visibility.render();

  assert.match(fixture.dom.body.innerHTML, /colspan="11"/);
  assert.equal(visibility.terminalStatuses.includes('success'), true);

  visibility.destroy();
  cleanup();
});

test('legacy training render can no longer replace the final task rows', () => {
  const fixture = installFixture();
  let legacyRenders = 0;
  window.renderTraining423 = () => {
    legacyRenders += 1;
    fixture.dom.body.innerHTML = '<tr><td>legacy-empty</td></tr>';
  };

  const visibility = installTrainingTaskVisibilityRuntime({
    getState: () => fixture.state,
    trainingTaskRuntime: fixture.runtime,
    pollRegistry: window.PollRegistryRuntime,
  });
  window.renderTraining423();

  assert.equal(legacyRenders, 0);
  assert.match(fixture.dom.body.innerHTML, /run-1/);
  assert.doesNotMatch(fixture.dom.body.innerHTML, /legacy-empty/);

  visibility.destroy();
  cleanup();
});

test('newer canonical refresh remains final render truth', async () => {
  const fixture = installFixture();
  let call = 0;
  fixture.runtime.refresh = async () => {
    call += 1;
    fixture.state.jobs = call === 1
      ? [{id: 'run-1', status: 'running', progress_percent: 10}]
      : [{id: 'run-1', status: 'running', progress_percent: 20}];
    return {stale: false, jobs: fixture.state.jobs};
  };

  const visibility = installTrainingTaskVisibilityRuntime({
    getState: () => fixture.state,
    trainingTaskRuntime: fixture.runtime,
    pollRegistry: window.PollRegistryRuntime,
  });
  await visibility.refresh({render: true, source: 'poll'});
  await visibility.refresh({render: true, source: 'poll'});

  assert.match(fixture.dom.body.innerHTML, /20%/);
  assert.doesNotMatch(fixture.dom.body.innerHTML, /10%/);

  visibility.destroy();
  cleanup();
});


test('visibility renderer reuses canonical durable queue order', () => {
  const fixture = installFixture({jobs: [
    {id: 'fifo-new', status: 'queued', resource_key: 'local:cpu', queue_priority: 7, priority_scheme: 'lower_number_first', resource_queue_position: 3, resource_queue_position_exact: true, queued_at: '2026-08-30T10:02:00Z'},
    {id: 'highest', status: 'queued', resource_key: 'local:cpu', queue_priority: 1, priority_scheme: 'lower_number_first', resource_queue_position: 1, resource_queue_position_exact: true, queued_at: '2026-08-30T10:03:00Z'},
    {id: 'fifo-old', status: 'queued', resource_key: 'local:cpu', queue_priority: 7, priority_scheme: 'lower_number_first', resource_queue_position: 2, resource_queue_position_exact: true, queued_at: '2026-08-30T10:01:00Z'},
  ]});
  const visibility = installTrainingTaskVisibilityRuntime({
    getState: () => fixture.state,
    trainingTaskRuntime: fixture.runtime,
    pollRegistry: window.PollRegistryRuntime,
  });
  visibility.render();
  const html = fixture.dom.body.innerHTML;
  assert.ok(html.indexOf('highest') < html.indexOf('fifo-old'));
  assert.ok(html.indexOf('fifo-old') < html.indexOf('fifo-new'));
  visibility.destroy();
  cleanup();
});
