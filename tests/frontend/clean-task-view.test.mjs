import fs from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import * as cleaning from '../../static/modules/cleaning.js';

test('clean task view preserves durable waiting-resource queue truth and server progress', () => {
  assert.equal(typeof cleaning.cleanTaskView, 'function', 'cleaning runtime must expose one durable task view');

  const view = cleaning.cleanTaskView({
    id: 'c1',
    status: 'queued',
    status_text: '等待资源',
    progress: 37.5,
    processed_images: 3,
    total_images: 8,
    flagged_images: 2,
    resource_queue_position: 4,
    resource_queue_position_exact: true,
    resource_wait_reason: '等待 materials 资源',
  });

  assert.equal(view.status, 'queued');
  assert.equal(view.statusText, '等待资源');
  assert.equal(view.percent, 37.5);
  assert.equal(view.processed, 3);
  assert.equal(view.total, 8);
  assert.equal(view.flagged, 2);
  assert.equal(view.progressText, '3/8');
  assert.equal(view.runtimeText, '资源队列第 4 位 · 等待 materials 资源');
  assert.equal(view.active, true);
});

test('clean task view does not present an unproven queue rank as exact position', () => {
  const view = cleaning.cleanTaskView({
    status: 'queued',
    resource_queue_position: 4,
    resource_queue_position_exact: false,
    resource_wait_reason: '等待 materials 资源',
  });
  assert.equal(view.runtimeText, '等待 materials 资源');
});

test('clean task view consumes backend stage and current item without inventing progress', () => {
  assert.equal(typeof cleaning.cleanTaskView, 'function');

  const view = cleaning.cleanTaskView({
    status: 'running',
    status_text: '清洗中',
    progress: 84,
    processed_images: 27,
    total_images: 32,
    phase: 'analyzing',
    current_item: 'image-28',
    worker_id: 'worker-materials-1',
  });

  assert.equal(view.statusText, '清洗中');
  assert.equal(view.percent, 84);
  assert.equal(view.progressText, '27/32');
  assert.equal(view.stage, 'analyzing');
  assert.equal(view.currentItem, 'image-28');
  assert.equal(view.runtimeText, '正在分析图片 · 当前 image-28 · Worker worker-materials-1');
  assert.equal(view.active, true);
});

test('final clean tab consumes the clean task view and PollRegistry lifecycle', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /function cleanTaskView427\(t\)/);
  assert.match(source, /PlatformCore\?\.cleaning\?\.cleanTaskView\?\.\(t\)/);
  assert.match(source, /window\.PollRegistryRuntime\?\.replaceCleanTaskTimer\?\.\(\)/);
  assert.match(source, /id="clean427TaskRows"/);
  assert.doesNotMatch(source, /setTimeout\(\(\)=>\{if\(state\.page==='自动标注及清洗'\)renderOps427\(\)\},2200\)/);
});
