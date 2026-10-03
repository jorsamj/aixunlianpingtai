import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const draft = fs.readFileSync(new URL('../../static/modules/training-draft-runtime.js', import.meta.url), 'utf8');

test('AUTO stays simple while MANUAL exposes recommendation and hard-constraint guidance', () => {
  assert.match(app, /Batch：自动/);
  assert.match(app, /Workers：自动/);
  assert.match(app, /GPU：自动调度/);
  assert.match(app, /使用推荐值/);
  assert.match(app, /当前估算安全范围/);
  assert.match(app, /手动模式是硬约束/);
  assert.match(app, /启动 Trainer 前失败/);
});

test('manual Batch Workers and Precision join the canonical training draft', () => {
  assert.match(draft, /numericInput\('trV3ManualBatch'\)/);
  assert.match(draft, /numericInput\('trV3ManualWorkers'\)/);
  assert.match(draft, /inputValue\('trV3ManualPrecision'\)/);
});
