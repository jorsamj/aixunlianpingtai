import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  filterTrainingTaskJobs,
  installTrainingTaskVisibilityRuntime,
  tickTrainingClockRows,
  trainingTaskStatusCounts,
} from '../../static/modules/training-task-visibility-runtime.js';

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
    dataset: {},
    classList: {toggle() {}},
    addEventListener() {},
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
    querySelector(selector) {
      return ['.train428-page', '.train428-page[data-training-task-shell="canonical"]'].includes(selector)
        ? dom.root
        : null;
    },
    getElementById() { return null; },
  };
  const calls = [];
  let pollRearms = 0;
  let viewAdapter = null;
  let refreshImpl = async options => {
    calls.push(options);
    return {stale: false, jobs: state.jobs};
  };
  const refreshDriver = async (options = {}) => {
    const result = await refreshImpl(options);
    if (!result?.stale) {
      if (options.render !== false) viewAdapter?.render?.();
      viewAdapter?.afterRefresh?.(result, options);
    }
    return result;
  };
  const runtime = {
    get refresh() { return refreshDriver; },
    set refresh(fn) { refreshImpl = fn; },
    setViewAdapter(adapter) {
      viewAdapter = adapter || null;
      return () => {
        if (viewAdapter === adapter) viewAdapter = null;
      };
    },
  };
  globalThis.window = {
    PlatformCore: {runtime: {}},
    TrainingTaskRuntime: runtime,
    PollRegistryRuntime: {replaceTrainingJobTimer() { pollRearms += 1; }},
    loadRelated: async () => undefined,
    renderTraining423() {},
  };
  return {state, dom, runtime, calls, pollRearms: () => pollRearms};
}

test('visibility leaves broad loadRelated ownership untouched', async () => {
  const fixture = installFixture({page: '数据集'});
  let legacyCalls = 0;
  const broadLoader = async () => {
    legacyCalls += 1;
    fixture.state.labels = [{id: 'label-1'}];
    return 'related-loaded';
  };
  window.loadRelated = broadLoader;

  const visibility = installTrainingTaskVisibilityRuntime({
    getState: () => fixture.state,
    trainingTaskRuntime: fixture.runtime,
    pollRegistry: window.PollRegistryRuntime,
  });

  assert.equal(window.loadRelated, broadLoader);
  const result = await window.loadRelated();
  assert.equal(result, 'related-loaded');
  assert.equal(legacyCalls, 1);
  assert.deepEqual(fixture.state.labels, [{id: 'label-1'}]);

  visibility.destroy();
  cleanup();
});

test('training-page related refresh routes explicitly through the canonical task runtime', async () => {
  const fixture = installFixture();

  const visibility = installTrainingTaskVisibilityRuntime({
    getState: () => fixture.state,
    trainingTaskRuntime: fixture.runtime,
    pollRegistry: window.PollRegistryRuntime,
  });
  fixture.calls.length = 0;
  await visibility.refresh({render: true, force: true, source: 'related'});

  assert.equal(fixture.calls.length, 1);
  assert.equal(fixture.calls[0].force, true);
  assert.equal(fixture.calls[0].source, 'related');
  assert.deepEqual(fixture.state.jobs, [{id: 'run-1', status: 'running'}]);

  visibility.destroy();
  cleanup();
});

test('canonical refresh re-arms polling after an empty stale snapshot discovers a running task', async () => {
  const fixture = installFixture({page: '数据集', jobs: []});
  fixture.runtime.refresh = async options => {
    fixture.calls.push(options);
    fixture.state.jobs = [{id: 'live-run', status: 'running', progress_percent: 37}];
    return {stale: false, jobs: fixture.state.jobs};
  };

  const visibility = installTrainingTaskVisibilityRuntime({
    getState: () => fixture.state,
    trainingTaskRuntime: fixture.runtime,
    pollRegistry: window.PollRegistryRuntime,
  });
  fixture.state.page = '训练任务';
  const before = fixture.pollRearms();
  await visibility.refresh({render: true, force: true, source: 'page-owner'});

  assert.equal(fixture.pollRearms(), before + 1);
  assert.match(fixture.dom.body.innerHTML, /live-run/);
  assert.match(fixture.dom.body.innerHTML, /37%/);

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
  window.setTrainTab428('active');

  assert.match(fixture.dom.body.innerHTML, /starting-1/);
  assert.match(fixture.dom.body.innerHTML, /stopping-1/);
  assert.doesNotMatch(fixture.dom.body.innerHTML, /done-1/);
  window.setTrainTab428('history');
  assert.doesNotMatch(fixture.dom.body.innerHTML, /starting-1/);
  assert.match(fixture.dom.body.innerHTML, /done-1/);

  visibility.destroy();
  cleanup();
});


test('empty state spans all ten product columns and success alias is terminal metadata', () => {
  const fixture = installFixture({jobs: []});
  const visibility = installTrainingTaskVisibilityRuntime({
    getState: () => fixture.state,
    trainingTaskRuntime: fixture.runtime,
    pollRegistry: window.PollRegistryRuntime,
  });

  visibility.render();

  assert.match(fixture.dom.body.innerHTML, /colspan="10"/);
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


test('local training clock advances elapsed and ETA without a network refresh', () => {
  const elapsed = {dataset: {seconds: '80'}, textContent: '1m 20s'};
  const eta = {dataset: {seconds: '140'}, textContent: '2m 20s'};
  const row = {
    querySelector(selector) {
      if (selector === '[data-training-clock="elapsed"]') return elapsed;
      if (selector === '[data-training-clock="eta"]') return eta;
      return null;
    },
  };
  const root = {
    querySelectorAll(selector) {
      return selector === 'tr[data-clock-active="1"]' ? [row] : [];
    },
  };

  assert.equal(tickTrainingClockRows(root, 1), 2);
  assert.equal(elapsed.dataset.seconds, '81');
  assert.equal(elapsed.textContent, '1m 21s');
  assert.equal(eta.dataset.seconds, '139');
  assert.equal(eta.textContent, '2m 19s');
});


test('batch mode is transient and remains inside the canonical ten-column task table', () => {
  const source = readFileSync(new URL('../../static/modules/training-task-visibility-runtime.js', import.meta.url), 'utf8');
  assert.match(source, /data-training-batch-toggle/);
  assert.match(source, /data-training-batch-action="pause"/);
  assert.match(source, /data-training-batch-action="resume"/);
  assert.match(source, /data-training-batch-action="stop"/);
  assert.match(source, /data-training-batch-action="delete">删除记录/);
  assert.match(source, /\['pause', 'resume', 'stop', 'delete'\]/);
  assert.match(source, /selectedIds\.clear\(\)/);
  assert.match(source, /batchMode = false/);
  assert.doesNotMatch(source, /<th><input[^>]+data-training-batch/);
});

test('status tabs derive counts from the current authoritative task snapshot', () => {
  const jobs = [
    {id: 'r1', status: 'running'},
    {id: 'q1', status: 'queued'},
    {id: 'q2', status: 'waiting'},
    {id: 'd1', status: 'completed'},
    {id: 'f1', status: 'failed'},
    {id: 's1', status: 'stopped'},
  ];
  assert.deepEqual(trainingTaskStatusCounts(jobs), {
    all: 6, running: 1, queued: 2, completed: 1, failed: 1, stopped: 1,
  });
  jobs.push({id: 'r2', status: 'starting'});
  assert.equal(trainingTaskStatusCounts(jobs).running, 2);
});

test('task filters and pagination are pure view operations over the supplied snapshot', () => {
  const jobs = [
    {id: '1', task_name: '车辆夜间训练', asset_algorithm_name: '车辆检测', status: 'running', queue_priority: 20},
    {id: '2', task_name: '烟火训练', asset_algorithm_name: '烟火检测', status: 'queued', queue_priority: 50},
    {id: '3', task_name: '车辆历史训练', asset_algorithm_name: '车辆检测', status: 'completed', queue_priority: 20},
  ];
  const original = structuredClone(jobs);
  assert.deepEqual(filterTrainingTaskJobs(jobs, {tab: 'running', query: '车辆'}).map(row => row.id), ['1']);
  assert.deepEqual(filterTrainingTaskJobs(jobs, {tab: 'all', algorithm: '车辆检测', priority: '20'}).map(row => row.id), ['1', '3']);
  assert.deepEqual(jobs, original);
});

test('visibility runtime source owns presentation only and does not fetch or copy task truth', () => {
  const source = readFileSync(new URL('../../static/modules/training-task-visibility-runtime.js', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /fetch\s*\(|requestJson|setInterval\s*\(/);
  assert.doesNotMatch(source, /state\(\)\.jobs\s*=|const\s+jobsSnapshot\s*=\s*\[/);
  assert.match(source, /trainingTaskStatusCounts\(jobs\)/);
  assert.match(source, /filterTrainingTaskJobs\(jobs,/);
  assert.match(source, /PageHeader|entity-page-header/);
});


test('visibility composes through the explicit task view adapter without monkey-patching refresh or task actions', () => {
  const fixture = installFixture();
  const originalRefresh = fixture.runtime.refresh;
  const pauseOwner = async () => true;
  window.pauseTrain428 = pauseOwner;

  const visibility = installTrainingTaskVisibilityRuntime({
    getState: () => fixture.state,
    trainingTaskRuntime: fixture.runtime,
    pollRegistry: window.PollRegistryRuntime,
  });

  assert.equal(fixture.runtime.refresh, originalRefresh);
  assert.equal(window.pauseTrain428, pauseOwner);

  const source = readFileSync(new URL('../../static/modules/training-task-visibility-runtime.js', import.meta.url), 'utf8');
  assert.match(source, /runtime\.setViewAdapter\(viewAdapter\)/);
  assert.doesNotMatch(source, /runtime\.refresh\s*=\s*refreshOwned/);
  assert.doesNotMatch(source, /legacyRender/);
  assert.doesNotMatch(source, /for \(const name of \['promoteTrain428'/);

  visibility.destroy();
  cleanup();
});


test('visibility does not capture or replace broad loadRelated', () => {
  const source = readFileSync(new URL('../../static/modules/training-task-visibility-runtime.js', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /legacyLoadRelated/);
  assert.doesNotMatch(source, /window\.loadRelated\s*=/);
  assert.doesNotMatch(source, /__trainingJobsPreserved/);
});
