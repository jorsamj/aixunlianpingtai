import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('annotation and cleaning task details use direct canonical routing', () => {
  assert.equal((app.match(/window\.showTaskProgress427=/g) || []).length, 1);
  for (const token of [
    'const showTaskBase429=window.showTaskProgress427;',
    'const previousShowTask=window.showTaskProgress427;',
  ]) assert.equal(app.includes(token), false, token);
  assert.match(app, /window\.showTaskProgressCore427=async function\(type,id\)/);
  assert.match(app, /window\.showCleanTaskProgress429=async function\(id\)/);
  assert.match(app, /window\.showTaskProgress427=function showTaskProgressCanonical60\(type,id\)/);
});

test('cleaning result detail uses explicit core and one public owner', () => {
  assert.equal(app.includes('const baseCleanDetail412=window.cleanDetail429;'), false);
  assert.equal((app.match(/window\.cleanDetail429=/g) || []).length, 1);
  assert.match(app, /window\.cleanDetailCore429=async function\(id\)/);
  assert.match(app, /window\.decorateCleanDetailSelection412=function\(\)/);
  assert.match(app, /window\.cleanDetail429=async function cleanDetailCanonical429\(id\)/);
});

test('v60 AI tasks never fall through the legacy v47 progress modal', () => {
  const start = app.lastIndexOf('Persistent v60 AI annotation UI');
  const block = app.slice(start);
  assert.match(block, /if\(type==='label'\)return showAiTask60\(id\)/);
  assert.match(block, /if\(type==='clean'\)return window\.showCleanTaskProgress429\?\.\(id\)/);
});
