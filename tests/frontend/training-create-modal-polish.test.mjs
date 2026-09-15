import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const read = path => readFile(new URL(`../../${path}`, import.meta.url), 'utf8');

test('create-training product polish is loaded and suppresses prompt-only chrome', async () => {
  const [index, css] = await Promise.all([
    read('static/index.html'),
    read('static/training-create-modal-polish.css'),
  ]);

  assert.match(index, /training-create-modal-polish\.css\?v=422401/);
  assert.match(css, /\.train-create-saas \.train-ui-card > header small/);
  assert.match(css, /\.train-create-saas \.field > small/);
  assert.match(css, /\.train-create-saas \.train-v3-note/);
  assert.match(css, /\.train-create-saas #tr429Estimate/);
});

test('training label selector stays text-only in create-training modal', async () => {
  const css = await read('static/training-create-modal-polish.css');
  assert.match(css, /\.train-ui-label-slot \.training-label-choice small/);
  assert.match(css, /\.train-ui-label-slot \.training-label-contract-count/);
  assert.match(css, /\.train-ui-label-slot img/);
});

test('training summary keeps the requested real training parameters', async () => {
  const app = await read('static/app.js');
  for (const label of ['训练轮次', 'Batch 大小', '图片尺寸', '优化器', '训练设备', '模型']) {
    assert.ok(app.includes(`'${label}'`), `training summary must include ${label}`);
  }
  assert.match(app, /function trainingSummaryHtml\(\)/);
  assert.match(app, /summary\.innerHTML=trainingSummaryHtml\(\)/);
});
