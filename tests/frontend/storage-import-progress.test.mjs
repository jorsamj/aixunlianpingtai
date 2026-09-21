import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {
  installStorageImportProgressRuntime,
  storageImportProgressText,
} from '../../static/modules/storage-import-progress.js';


test('storage scan renders authoritative unified runtime progress', () => {
  const text = storageImportProgressText({
    status: 'RUNNING',
    phase: 'SCANNING',
    progress_percent: 37.5,
    current_item: '已扫描 12531 / 可导入 9824 / 重复 2694 / 失败 13 / camera.jpg',
    worker_id: 'storage-worker-01',
  });
  assert.equal(text, '正在扫描素材 · 38% · 已扫描 12531 / 可导入 9824 / 重复 2694 / 失败 13 / camera.jpg · 执行节点 storage-worker-01');
});


test('queued and resource-waiting scans expose real queue state', () => {
  assert.equal(storageImportProgressText({status: 'QUEUED', resource_queue_position: 3, resource_queue_position_exact: true, priority: 1}), '排队中 · 队列第 3 位 · 优先级 1');
  assert.equal(storageImportProgressText({status: 'WAITING_RESOURCE', resource_queue_position: 2, resource_queue_position_exact: true, resource_wait_reason: 'RESOURCE_BUSY'}), '等待资源 · 队列第 2 位 · RESOURCE_BUSY');
  assert.equal(storageImportProgressText({status: 'RUNNING', phase: 'FINALIZING', progress_percent: 91}), '正在整理扫描结果 · 91%');
  assert.equal(
    storageImportProgressText({
      status: 'RUNNING', phase: 'REMOTE_MATERIAL_SCANNING',
      execution_mode: 'agent', current_item: 'datasets/fire/a.jpg',
      worker_id: 'agent:material-01',
    }),
    '正在扫描对象存储 · datasets/fire/a.jpg · 执行节点 agent:material-01',
  );
  assert.equal(
    storageImportProgressText({
      status: 'WAITING_RESOURCE', execution_mode: 'agent',
      resource_wait_reason: 'NO_COMPATIBLE_NODE',
    }),
    '等待远程素材节点 · NO_COMPATIBLE_NODE',
  );
  assert.equal(
    storageImportProgressText({
      status: 'AWAITING_CONFIRMATION', execution_mode: 'agent',
      phase: 'REMOTE_MATERIAL_REVIEWING', current_item: 'datasets/fire/a.jpg',
    }),
    '扫描完成，等待确认建立素材索引',
  );
});


test('storage import polling runtime installs independently of classic start function', () => {
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  try {
    globalThis.window = {};
    globalThis.document = {getElementById: () => null};
    const calls = [];
    const pollRegistry = {
      startTimeout: (...args) => { calls.push(args); return 1; },
      clear: () => false,
    };
    const runtime = installStorageImportProgressRuntime({
      pollRegistry,
      getState: () => ({page: '素材存储配置', project: {id: 'p1'}}),
    });
    assert.ok(runtime, 'managed storage import runtime must install before classic storage UI wiring');
    assert.equal(window.StorageImportProgressRuntime, runtime);
    assert.equal(typeof runtime.track, 'function');
    assert.equal(typeof runtime.stop, 'function');
  } finally {
    if (previousWindow === undefined) delete globalThis.window; else globalThis.window = previousWindow;
    if (previousDocument === undefined) delete globalThis.document; else globalThis.document = previousDocument;
  }
});


test('storage import active task uses one PollRegistry-managed one-shot and re-arms through WAITING_RESOURCE', async () => {
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  const previousFetch = globalThis.fetch;
  try {
    const status = {isConnected: true, textContent: '', innerHTML: ''};
    globalThis.document = {getElementById: id => id === 'si61Status' ? status : null};
    const scheduled = [];
    const cleared = [];
    const pollRegistry = {
      startTimeout(key, owners, callback, delay) {
        const row = {key, owners, callback, delay};
        scheduled.push(row);
        return scheduled.length;
      },
      clear(key) { cleared.push(key); return true; },
    };
    const rendered = [];
    const taskCenterRows = [];
    globalThis.window = {
      renderStorageImportTask61: task => rendered.push(task),
      UploadTaskCenterRuntime: {upsert: row => taskCenterRows.push(row)},
    };
    globalThis.fetch = async url => {
      if (String(url).includes('/api/v62/')) {
        return {
          ok: true,
          json: async () => ({
            task_id: 'scan-1', status: 'WAITING_RESOURCE', progress_percent: 12,
            resource_queue_position: 4, resource_queue_position_exact: true, resource_wait_reason: 'STORAGE_WORKER_BUSY',
          }),
        };
      }
      throw new Error(`unexpected fetch ${url}`);
    };

    const runtime = installStorageImportProgressRuntime({
      pollRegistry,
      getState: () => ({page: '素材存储配置', project: {id: 'p1'}}),
    });
    runtime.track('scan-1', {task_id: 'scan-1', status: 'QUEUED'});

    assert.equal(scheduled.length, 1);
    assert.equal(scheduled[0].key, 'storage-import-scan-v61');
    assert.deepEqual(scheduled[0].owners, '素材存储配置');
    assert.equal(scheduled[0].delay, 1200);

    await scheduled[0].callback();
    assert.match(status.textContent, /等待资源/);
    assert.match(status.textContent, /队列第 4 位/);
    assert.equal(scheduled.length, 2, 'WAITING_RESOURCE must remain active and re-arm the same managed poll');
    assert.equal(scheduled[1].key, 'storage-import-scan-v61');

    assert.equal(taskCenterRows.at(-1)?.pollOwner, 'storage-import-progress');
    runtime.stop();
    assert.equal(cleared.includes('storage-import-scan-v61'), true);
    assert.equal(taskCenterRows.at(-1)?.pollOwner, '', 'closing the focused tracker must hand active polling back to the task center');
  } finally {
    if (previousWindow === undefined) delete globalThis.window; else globalThis.window = previousWindow;
    if (previousDocument === undefined) delete globalThis.document; else globalThis.document = previousDocument;
    if (previousFetch === undefined) delete globalThis.fetch; else globalThis.fetch = previousFetch;
  }
});


test('storage import final wiring retires direct polling loops and installs managed runtime after classic UI owner', () => {
  const progressSource = fs.readFileSync('static/modules/storage-import-progress.js', 'utf8');
  const serverSource = fs.readFileSync('static/modules/server-material-import.js', 'utf8');
  const appSource = fs.readFileSync('static/app.js', 'utf8');
  const mainSource = fs.readFileSync('static/main.mjs', 'utf8');

  assert.doesNotMatch(progressSource, /while \(isTaskActive\(current\.status\)\)/);
  assert.doesNotMatch(serverSource, /waitForNextPoll\(|pollServerImport\(/);
  assert.match(appSource, /StorageImportProgressRuntime\?\.track/);
  assert.match(appSource, /StorageImportProgressRuntime\?\.stop/);
  assert.match(progressSource, /pollOwner = 'storage-import-progress'/);
  assert.match(progressSource, /stop\(\{handoff: false\}\)/);
  assert.match(appSource, /data-import-mode="storage_scan"/);
  assert.match(appSource, /si61RemoteSource/);
  assert.match(appSource, /长期存储凭据/);
  assert.doesNotMatch(appSource, /=async function\s*(?:\r?\n)\s*window\./);
  assert.match(mainSource, /window\.installServerMaterialImport61\?\.\(\);[\s\S]*installStorageImportProgressRuntime/);
});


test('storage import canonical task_status wins and inexact queue rank is never shown as position', () => {
  const text = storageImportProgressText({
    status: 'SUCCEEDED', task_status: 'WAITING_RESOURCE', phase: 'resource_waiting',
    resource_queue_position: 7, resource_queue_position_exact: false,
    resource_wait_reason: 'STORAGE_WORKER_BUSY',
  });
  assert.match(text, /等待资源/);
  assert.match(text, /STORAGE_WORKER_BUSY/);
  assert.doesNotMatch(text, /队列第 7 位/);
});


test('active storage import progress stays lightweight and full detail renderer runs only at terminal state', async () => {
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  const previousFetch = globalThis.fetch;
  try {
    const status = {textContent: '', dataset: {}};
    globalThis.document = {getElementById: id => id === 'si61Status' ? status : null};

    const scheduled = [];
    const pollRegistry = {
      startTimeout(key, owners, callback, delay) {
        scheduled.push({key, owners, callback, delay});
        return scheduled.length;
      },
      clear() { return true; },
    };

    const rendered = [];
    globalThis.window = {
      renderStorageImportTask61: task => rendered.push(task),
      UploadTaskCenterRuntime: {upsert() {}},
    };

    let response = {
      task_id:'scan-light-1',
      status:'RUNNING',
      phase:'SCANNING',
      progress_percent:35,
      current_item:'35 / 100',
    };
    globalThis.fetch = async () => ({
      ok:true,
      json:async () => response,
    });

    const runtime = installStorageImportProgressRuntime({
      pollRegistry,
      getState: () => ({page:'素材存储配置', project:{id:'p1'}}),
    });
    runtime.track('scan-light-1', {
      task_id:'scan-light-1',
      status:'QUEUED',
      progress_percent:0,
    });

    assert.equal(rendered.length, 0);
    assert.equal(status.dataset.storageImportLive, '1');

    await scheduled[0].callback();
    assert.equal(rendered.length, 0);
    assert.match(status.textContent, /35%/);

    response = {
      task_id:'scan-light-1',
      status:'AWAITING_CONFIRMATION',
      phase:'REVIEWING',
      progress_percent:100,
      result:{scanned_files:100, importable_images:90},
    };
    await scheduled[1].callback();
    assert.equal(rendered.length, 1);
    assert.equal(rendered[0].status, 'AWAITING_CONFIRMATION');
    assert.equal(status.dataset.storageImportLive, '0');
  } finally {
    if (previousWindow === undefined) delete globalThis.window; else globalThis.window = previousWindow;
    if (previousDocument === undefined) delete globalThis.document; else globalThis.document = previousDocument;
    if (previousFetch === undefined) delete globalThis.fetch; else globalThis.fetch = previousFetch;
  }
});
