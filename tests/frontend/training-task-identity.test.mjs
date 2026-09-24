import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const appSource = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const submitSource = fs.readFileSync(new URL('../../static/modules/training-submit.js', import.meta.url), 'utf8');

test('training modal shows algorithm name and planned task id', () => {
  assert.match(appSource, /<label>算法名称<\/label>/);
  assert.match(appSource, /id="tr429TaskId"/);
  assert.match(appSource, /plannedTaskId='train_'/);
});

test('training submit sends the planned task id through the canonical submit owner', () => {
  assert.match(submitSource, /getElementById\('tr429TaskId'\)/);
  assert.match(submitSource, /payload\.task_id = plannedTaskId/);
});
