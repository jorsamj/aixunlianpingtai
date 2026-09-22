import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('AI create and reference-select actions have one public owner each', () => {
  assert.equal((app.match(/window\.createAiLabel429=/g) || []).length, 1);
  assert.equal((app.match(/window\.createAiLabel427=/g) || []).length, 1);
  assert.equal((app.match(/window\.aiRefSelect412=/g) || []).length, 1);
  for (const token of [
    'const baseCreateAi417=window.createAiLabel429;',
    'const baseCreateAi412=window.createAiLabel429;',
    'const baseSelectReference417=window.aiRefSelect412;',
  ]) assert.equal(app.includes(token), false, token);
});

test('AI create owner composes core and decorators explicitly', () => {
  assert.match(app, /window\.createAiLabelCore429=function\(opts=\{\}\)/);
  assert.match(app, /window\.decorateAiReferenceLabels417=function\(\)/);
  assert.match(app, /window\.decorateAiReferenceBulk412=function\(\)/);
  assert.match(app, /window\.createAiLabel429=function createAiLabelCanonical429\(opts=\{\}\)/);
  assert.match(app, /window\.createAiLabel427=window\.createAiLabel429/);
});

test('reference bulk selection updates label text through one canonical path', () => {
  assert.match(app, /window\.aiRefSelectCore412=function\(mode\)/);
  assert.match(app, /window\.syncReferenceLabels417=syncReferenceLabels417/);
  assert.match(app, /window\.aiRefSelect412=function aiRefSelectCanonical412\(mode\)/);
});
