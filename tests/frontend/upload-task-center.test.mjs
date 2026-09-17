import test from 'node:test';
import assert from 'node:assert/strict';

import {
  isUploadTaskActive,
  mergeUploadTask,
  normalizeDurableUploadTask,
} from '../../static/modules/upload-task-center.js';

test('mergeUploadTask keeps truthful progress and terminal success becomes 100%', () => {
  const active = mergeUploadTask({}, {id:'u1', status:'UPLOADING', progress:37.5, stage:'文件上传'});
  assert.equal(active.progress, 37.5);
  assert.equal(isUploadTaskActive(active), true);
  const done = mergeUploadTask(active, {status:'SUCCEEDED', stage:'完成'});
  assert.equal(done.progress, 100);
  assert.equal(isUploadTaskActive(done), false);
});

test('task center treats label mapping/indexing stages as active', () => {
  for (const status of ['MAPPING_LABELS','WRITING_ANNOTATIONS','INDEXING']) {
    assert.equal(isUploadTaskActive({status}), true, status);
  }
});

test('refresh keeps an interrupted browser ZIP session waiting instead of pretending bytes are still moving', () => {
  const row = mergeUploadTask({}, {
    id:'zip:u1', kind:'zip', status:'WAITING', progress:17.5,
    stage:'上传已暂停，等待继续', resumeRequired:true, browserTransfer:false,
  });
  const next = normalizeDurableUploadTask({
    status:'uploading', progress:17.5, updated_at:'2026-09-17T10:00:00Z',
    stage:'正在上传 ZIP', message:'server still has resumable parts',
  }, row);

  assert.equal(next.status, 'WAITING');
  assert.equal(next.progress, 17.5);
  assert.equal(next.resumeRequired, true);
  assert.match(next.stage, /等待继续/);
});

test('durable task can leave resume wait once backend advances beyond upload phase', () => {
  const row = mergeUploadTask({}, {
    id:'zip:u1', kind:'zip', status:'WAITING', progress:17.5,
    resumeRequired:true,
  });
  const next = normalizeDurableUploadTask({status:'selecting', progress:38, stage:'等待启动后台导入'}, row);

  assert.equal(next.status, 'SELECTING');
  assert.equal(next.progress, 38);
});
