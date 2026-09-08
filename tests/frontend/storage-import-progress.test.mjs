import test from 'node:test';
import assert from 'node:assert/strict';

import {storageImportProgressText} from '../../static/modules/storage-import-progress.js';


test('storage scan progress prefers real counters instead of fabricated percent', () => {
  const text = storageImportProgressText({
    status: 'RUNNING',
    stage: 'SCANNING',
    progress: 37.5,
    current_item: '已扫描 12531 / 可导入 9824 / 重复 2694 / 失败 13 / camera.jpg',
  });

  assert.equal(
    text,
    'SCANNING · 已扫描 12531 / 可导入 9824 / 重复 2694 / 失败 13 / camera.jpg',
  );
  assert.equal(text.includes('37.5%'), false);
});


test('queued and finalizing scans use indeterminate human-readable status', () => {
  assert.equal(storageImportProgressText({status: 'QUEUED'}), '已进入扫描队列');
  assert.equal(storageImportProgressText({stage: 'FINALIZING'}), '正在整理扫描结果');
});
