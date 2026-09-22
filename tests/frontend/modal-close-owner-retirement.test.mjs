import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('modal closing uses explicit core and before-close hooks', () => {
  assert.equal(app.includes('const previousCloseImport=window.closeModal;'), false);
  assert.equal(app.includes('const previousClose=window.closeModal;'), false);
  assert.match(app, /window\.closeModalCore424=closeModal/);
  assert.match(app, /window\.beforeCloseStorageImport61=function\(\)/);
  assert.match(app, /window\.closeModal=async function closeModalCanonical420\(\)/);
});

test('canonical close preserves storage polling cleanup and annotation dirty-save', () => {
  const start = app.indexOf('window.closeModal=async function closeModalCanonical420()');
  const end = app.indexOf('\n  };', start);
  const block = app.slice(start, end);
  assert.ok(start >= 0 && end > start);
  assert.match(block, /beforeCloseStorageImport61/);
  assert.match(block, /annotationWorkbench\?\.dirty/);
  assert.match(block, /await window\.saveAnn\(true\)/);
  assert.match(block, /annotationWorkbench\?\.invalidate/);
  assert.match(block, /closeModalCore424/);
});

test('storage import close hook stops progress polling without replacing closeModal', () => {
  const start = app.indexOf('window.installServerMaterialImport61=function()');
  const end = app.indexOf('window.openDataUpload426=async function()', start);
  const block = app.slice(start, end);
  assert.match(block, /window\.beforeCloseStorageImport61=function\(\)/);
  assert.match(block, /abortPolling\(\)/);
  assert.doesNotMatch(block, /window\.closeModal=async function/);
});
