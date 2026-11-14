import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('v36 does not wrap the final aggregate loader', () => {
  assert.equal(app.includes('const _v36LoadAll = loadAll;'), false);
  assert.equal(app.includes('await _v36LoadAll();'), false);
  assert.match(app, /loadAll=async function loadAllCanonical426\(\)/);
});
