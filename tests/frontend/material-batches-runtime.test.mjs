import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../../static/modules/material-batches.js', import.meta.url), 'utf8');
const main = readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');

test('material batch polling is centrally owned and resumes only on relevant pages', () => {
  assert.match(source, /pollRegistry \|\| window\.PollRegistryRuntime/);
  assert.match(source, /registry\.startTimeout\(pollKey\(id\), POLL_OWNERS, tick, 1500\)/);
  assert.match(source, /const POLL_OWNERS = \['数据集', '自动标注及清洗'\]/);
  assert.match(source, /build: 'material-batch-runtime-422402'/);
  assert.doesNotMatch(source, /setTimeout\(/);
  assert.doesNotMatch(source, /clearTimeout\(/);
  assert.doesNotMatch(source, /const timers = new Map/);
  assert.match(main, /window\.MaterialBatchRuntime62\?\.resume\?\.\(\)/);
});
