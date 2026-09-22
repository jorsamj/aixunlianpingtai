import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('historical data-load wrapper chains are physically retired', () => {
  for (const token of [
    'const _oldLoadRelatedV33 = loadRelated;',
    'const oldLoadAll = loadAll;',
    'const _v35OldLoadAll = loadAll;',
    'const baseLoadRelated424=loadRelated;',
    'const prevLoad425=loadRelated;',
  ]) assert.equal(app.includes(token), false, token);
});

test('v42.6 owns the final related-data loader directly and in parallel', () => {
  assert.match(app, /loadRelated=async function loadRelatedCanonical426\(\)/);
  const start=app.indexOf('loadRelated=async function loadRelatedCanonical426()');
  const end=app.indexOf('loadAll=async function loadAllCanonical426()',start);
  const block=app.slice(start,end);
  assert.match(block, /Promise\.all\(\[/);
  assert.match(block, /\/api\/projects\/\$\{id\}\/images/);
  assert.match(block, /\/api\/v12\/projects\/\$\{id\}\/labels/);
  assert.match(block, /\/api\/v12\/projects\/\$\{id\}\/algorithms/);
  assert.match(block, /\/api\/v35\/model-configs/);
  assert.match(block, /\/api\/v35\/prompt-templates/);
});

test('v42.6 owns the final aggregate loader directly and keeps independent requests parallel', () => {
  assert.match(app, /loadAll=async function loadAllCanonical426\(\)/);
  const start=app.indexOf('loadAll=async function loadAllCanonical426()');
  const end=app.indexOf('// Replace all native file selectors',start);
  const block=app.slice(start,end);
  assert.match(block, /Promise\.all\(\[loadRelated\(\)/);
  assert.match(block, /training_options/);
  assert.match(block, /inference_envs/);
  assert.match(block, /system\/recommendation/);
  assert.match(block, /local_models/);
});
