import test from 'node:test';
import assert from 'node:assert/strict';

import {isUploadTaskActive, mergeUploadTask} from '../../static/modules/upload-task-center.js';

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
