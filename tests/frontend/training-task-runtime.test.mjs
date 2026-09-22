import test from 'node:test';
import assert from 'node:assert/strict';

import {installTrainingTaskRuntime, trainingTaskRow} from '../../static/modules/training-task-runtime.js';

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

test('successive jobs responses replace status progress epoch and elapsed row truth without full render', async () => {
  const state = {page: '训练任务', project: {id: 'p1'}, jobs: [], train428Tab: 'active', __navigationEpoch: 4};
  const body = {innerHTML: ''};
  const activeCount = {textContent: ''};
  const historyCount = {textContent: ''};
  const buttons = [
    {querySelector: selector => selector === 'span' ? activeCount : null},
    {querySelector: selector => selector === 'span' ? historyCount : null},
  ];
  const root = {
    querySelector: selector => selector === '.train428-table tbody' ? body : null,
    querySelectorAll: selector => selector === '.train428-tabs button' ? buttons : [],
  };
  const backendRows = [
    [{id: 'j1', status: 'running', current_epoch: 3, total_epochs: 100, progress_percent: 3, elapsed_seconds: 30}],
    [{id: 'j1', status: 'running', current_epoch: 4, total_epochs: 100, progress_percent: 4, elapsed_seconds: 45}],
    [{id: 'j1', status: 'completed', current_epoch: 100, total_epochs: 100, progress_percent: 100, elapsed_seconds: 600}],
  ];
  let fullRenders = 0;
  globalThis.document = {
    querySelector: selector => selector === '.train428-page' ? root : null,
    addEventListener() {},
    removeEventListener() {},
  };
  globalThis.window = {
    async fetch() { return response(backendRows.shift()); },
    updateTrainingJobTable() { fullRenders += 1; },
  };

  const runtime = installTrainingTaskRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  await runtime.refresh({source: 'poll'});
  assert.match(body.innerHTML, /Epoch 3\/100/);
  assert.match(body.innerHTML, /3%/);
  assert.match(body.innerHTML, />30s</);

  await runtime.refresh({source: 'poll'});
  assert.match(body.innerHTML, /Epoch 4\/100/);
  assert.match(body.innerHTML, /4%/);
  assert.match(body.innerHTML, />45s</);

  state.train428Tab = 'history';
  await runtime.refresh({source: 'poll'});
  assert.match(body.innerHTML, /已完成/);
  assert.match(body.innerHTML, /Epoch 100\/100/);
  assert.match(body.innerHTML, /100%/);
  assert.doesNotMatch(body.innerHTML, /训练中/);
  assert.equal(activeCount.textContent, '0');
  assert.equal(historyCount.textContent, '1');
  assert.equal(fullRenders, 0);

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


test('training row prioritizes waiting-resource truth and suppresses an unproved rank', () => {
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  // trainingTaskRow is pure and does not require runtime installation.
  cleanup();
  return import('../../static/modules/training-task-runtime.js').then(({trainingTaskRow}) => {
    const html = trainingTaskRow({
      id: 'wait-1', status: 'waiting', queue_priority: 1, priority_scheme: 'lower_number_first',
      resource_queue_position: 2, resource_wait_reason: 'GPU_MEMORY_BUSY',
      resource_queue_position_exact: false, resource_pool_label: 'GPU 自动',
      task_worker_id: 'a800-worker-01', progress_percent: 18, current_item: '准备训练环境',
      framework: 'ultralytics', total_epochs: 30,
    });
    assert.match(html, /等待资源/);
    assert.match(html, /train428-priority-number">1<\/span>/);
    assert.match(html, /GPU 自动/);
    assert.match(html, /GPU_MEMORY_BUSY/);
    assert.doesNotMatch(html, /队列第 2 位/);
    assert.match(html, /执行节点 a800-worker-01/);
    assert.match(html, />18%<\/b>/);
    assert.match(html, /准备训练环境/);
    if (previousWindow !== undefined) globalThis.window = previousWindow;
    if (previousDocument !== undefined) globalThis.document = previousDocument;
  });
});

test('training row shows a numeric position only when the backend proves it exact', async () => {
  const {trainingTaskRow} = await import('../../static/modules/training-task-runtime.js');
  const exact = trainingTaskRow({
    id: 'cpu-2', status: 'queued', resource_pool_label: 'CPU',
    resource_queue_position: 2, resource_queue_position_exact: true,
    framework: 'ultralytics', total_epochs: 10,
  });
  const uncertain = trainingTaskRow({
    id: 'gpu-auto', status: 'queued', resource_pool_label: 'GPU 自动',
    resource_queue_position: 3, resource_queue_position_exact: false,
    framework: 'ultralytics', total_epochs: 10,
  });

  assert.match(exact, /CPU · 队列第 2 位/);
  assert.match(uncertain, /GPU 自动 · 排队中/);
  assert.doesNotMatch(uncertain, /队列第 3 位/);
});

test('completed training below requested epochs is shown as early completion instead of stuck running', async () => {
  const {trainingTaskRow} = await import('../../static/modules/training-task-runtime.js');
  const html = trainingTaskRow({
    id: 'done-180',
    status: 'done',
    current_epoch: 180,
    total_epochs: 300,
    progress_percent: 100,
    training_outcome: 'completed',
    completion_reason: 'early_stopping',
    framework: 'ultralytics',
  });
  assert.match(html, /已完成/);
  assert.match(html, /Early Stopping，提前完成/);
  assert.match(html, /Epoch 180\/300/);
  assert.match(html, /100%/);
  assert.doesNotMatch(html, /训练中/);
});


test('training list and row use canonical task_status over stale legacy status', async () => {
  const {trainingTaskRow, visibleTrainingJobs} = await import('../../static/modules/training-task-runtime.js');
  const task = {
    id: 'truth-1',
    status: 'completed',
    task_status: 'WAITING_RESOURCE',
    persisted_status: 'QUEUED',
    phase: 'resource_waiting',
    task_stage: 'committed',
    progress_percent: 12,
    resource_pool_label: 'GPU 自动',
    resource_wait_reason: 'GPU_MEMORY_BUSY',
    resource_queue_position: 4,
    resource_queue_position_exact: false,
    framework: 'ultralytics',
    total_epochs: 30,
  };

  assert.equal(visibleTrainingJobs([task], 'active').length, 1);
  assert.equal(visibleTrainingJobs([task], 'history').length, 0);
  const html = trainingTaskRow(task);
  assert.match(html, /等待资源/);
  assert.match(html, /GPU 自动/);
  assert.match(html, /GPU_MEMORY_BUSY/);
  assert.match(html, /12%/);
  assert.doesNotMatch(html, /队列第 4 位/);
});


test('visible training jobs match durable priority rank and FIFO order', async () => {
  const {visibleTrainingJobs} = await import('../../static/modules/training-task-runtime.js');
  const jobs = [
    {id: 'fifo-new', status: 'queued', queue_priority: 7, priority_scheme: 'lower_number_first', queue_rank: 0, queued_at: '2026-08-30T10:02:00Z'},
    {id: 'promoted', status: 'queued', queue_priority: 7, priority_scheme: 'lower_number_first', queue_rank: 2, queued_at: '2026-08-30T10:03:00Z'},
    {id: 'highest', status: 'queued', queue_priority: 1, priority_scheme: 'lower_number_first', queue_rank: 0, queued_at: '2026-08-30T10:04:00Z'},
    {id: 'fifo-old', status: 'queued', queue_priority: 7, priority_scheme: 'lower_number_first', queue_rank: 0, queued_at: '2026-08-30T10:01:00Z'},
  ];
  assert.deepEqual(
    visibleTrainingJobs(jobs, 'active').map(job => job.id),
    ['highest', 'promoted', 'fifo-old', 'fifo-new'],
  );
});


test('visible training jobs prefer backend-proven queue positions within one resource', async () => {
  const {visibleTrainingJobs} = await import('../../static/modules/training-task-runtime.js');
  const jobs = [
    {id: 'later-array', status: 'queued', resource_key: 'local:cpu', queue_priority: 7, priority_scheme: 'lower_number_first', resource_queue_position: 3, resource_queue_position_exact: true, queued_at: '2026-08-30T10:01:00Z'},
    {id: 'highest', status: 'queued', resource_key: 'local:cpu', queue_priority: 1, priority_scheme: 'lower_number_first', resource_queue_position: 1, resource_queue_position_exact: true, queued_at: '2026-08-30T10:03:00Z'},
    {id: 'middle', status: 'queued', resource_key: 'local:cpu', queue_priority: 7, priority_scheme: 'lower_number_first', resource_queue_position: 2, resource_queue_position_exact: true, queued_at: '2026-08-30T10:02:00Z'},
  ];
  assert.deepEqual(visibleTrainingJobs(jobs, 'active').map(job => job.id), ['highest', 'middle', 'later-array']);
});


test('active training row exposes the 10 product-facing task fields without internal ids or framework noise', () => {
  const html = trainingTaskRow({
    id: 'train-11',
    status: 'running',
    asset_algorithm_id: 'alg-11',
    asset_algorithm_name: '安全帽检测',
    task_name: '第 3 次迭代',
    queue_priority: 3,
    priority_scheme: 'lower_number_first',
    framework: 'ultralytics',
    resource_pool_label: 'GPU 0',
    progress_percent: 42,
    current_epoch: 12,
    total_epochs: 30,
    elapsed_seconds: 90,
    eta_seconds: 135,
    phase: 'training',
    current_item: 'Epoch 12/30',
    started_at: '2026-09-20T10:00:00Z',
  });
  assert.equal((html.match(/<td/g) || []).length, 10);
  assert.match(html, /安全帽检测/);
  assert.match(html, /第 3 次迭代/);
  assert.match(html, />3<\/span>/);
  assert.match(html, /42%/);
  assert.doesNotMatch(html, /<span[^>]*>alg-11<\/span>/);
  assert.doesNotMatch(html, /<span[^>]*>train-11<\/span>/);
  assert.doesNotMatch(html, /<b[^>]*>train-11<\/b>/);
  assert.doesNotMatch(html, /Ultralytics \/ YOLO/);
  assert.match(html, /详情/);
  assert.match(html, /日志/);
  assert.match(html, /暂停/);
  assert.match(html, /停止/);
  assert.match(html, /删除/);
});

test('transitioning training task disables conflicting controls until backend truth settles', () => {
  const html = trainingTaskRow({
    id: 'train-pausing',
    status: 'pausing',
    task_status: 'PAUSING',
    asset_algorithm_name: '烟火检测',
    framework: 'ultralytics',
    progress_percent: 36,
  });
  assert.match(html, /暂停中/);
  assert.match(html, /状态切换中/);
  assert.match(html, /日志/);
  assert.doesNotMatch(html, /pauseTrain428/);
  assert.doesNotMatch(html, /stopTrain428/);
});

test('durable create response is merged immediately without a confirmation request', () => {
  const state = {page: '算法列表', jobs: [{id: 'older', status: 'done'}]};
  let fetchCalls = 0;
  globalThis.document = {
    addEventListener() {}, removeEventListener() {}, querySelector() { return null; },
  };
  globalThis.window = {
    fetch: async () => { fetchCalls += 1; throw new Error('must not fetch'); },
  };
  const runtime = installTrainingTaskRuntime({
    getState: () => state,
    projectId: () => 'project-1',
  });

  const row = runtime.acceptCreatedTask({
    task_id: 'train_aaaaaaaaaaaaaaaaaaaa',
    kind: 'TRAINING',
    task_type: 'TRAINING',
    status: 'QUEUED',
    persisted_status: 'QUEUED',
    phase: 'queued',
    progress_percent: 0,
    created_at: '2026-09-21T00:00:00Z',
  }, {algorithmId: 'alg-1', framework: 'ultralytics'});

  assert.equal(fetchCalls, 0);
  assert.equal(row.id, 'train_aaaaaaaaaaaaaaaaaaaa');
  assert.equal(state.jobs[0].id, 'train_aaaaaaaaaaaaaaaaaaaa');
  assert.equal(state.jobs[0].asset_algorithm_id, 'alg-1');
  assert.equal(state.jobs[0].status, 'queued');
  runtime.destroy();
  cleanup();
});


test('batch mode adds selection inside the algorithm cell without adding a permanent checkbox column', () => {
  const job = {
    id:'batch-row-1', status:'running', asset_algorithm_name:'烟火检测',
    task_name:'训练任务 A', queue_priority:2, progress_percent:25,
  };
  const normal = trainingTaskRow(job);
  const batch = trainingTaskRow(job, {batchMode:true, selected:true});
  assert.equal((normal.match(/<td/g) || []).length, 10);
  assert.equal((batch.match(/<td/g) || []).length, 10);
  assert.doesNotMatch(normal, /data-training-batch-select/);
  assert.match(batch, /data-training-batch-select="batch-row-1"/);
  assert.match(batch, /checked/);
  assert.match(batch, /is-selected/);
});

test('batch pause uses only eligible real endpoints and performs one final jobs refresh', async () => {
  const state = {
    page:'训练任务', project:{id:'p1'}, __navigationEpoch:1,
    jobs:[
      {id:'run-1', status:'running'},
      {id:'pause-1', status:'paused'},
    ],
  };
  const calls=[];
  globalThis.window={
    async fetch(url, init={}) {
      calls.push(`${String(init.method || 'GET').toUpperCase()} ${url}`);
      if (String(url).endsWith('/pause')) return response({ok:true});
      if (String(url).endsWith('/jobs')) return response([
        {id:'run-1', status:'paused'},
        {id:'pause-1', status:'paused'},
      ]);
      throw new Error(`unexpected URL: ${url}`);
    },
  };
  const runtime=installTrainingTaskRuntime({
    getState:()=>state,
    projectId:()=>state.project.id,
  });
  const result=await runtime.batchAction('pause',['run-1','pause-1']);
  assert.equal(result.succeeded,1);
  assert.equal(result.skipped,1);
  assert.deepEqual(calls,[
    'POST /api/v48/projects/p1/jobs/run-1/pause',
    'GET /api/projects/p1/jobs',
  ]);
  runtime.destroy();
  cleanup();
});
