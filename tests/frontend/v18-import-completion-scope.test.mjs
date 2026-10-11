import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');

function historicalImportBlock() {
  const start = app.indexOf('window.doImportData=');
  const end = app.indexOf('\n\nwindow.manageLabels=', start);
  assert.ok(start >= 0 && end > start, 'historical doImportData fallback block must exist');
  return app.slice(start, end);
}

function finalV36ImportOwner() {
  const start = app.lastIndexOf('window.importData=function(){');
  const end = app.indexOf('window.showImportTabV36=', start);
  assert.ok(start >= 0 && end > start, 'final v36 importData owner must exist');
  return app.slice(start, end);
}

test('final v36 ZIP import delegates to background v19 uploader and cannot fall back to synchronous v18 owner', () => {
  const owner = finalV36ImportOwner();
  assert.match(owner, /onclick="doImportUploadV19\(\)"/);
  assert.doesNotMatch(owner, /onclick="doImportData\(\)"/);
  assert.equal((app.match(/window\.doImportData=/g) || []).length, 1, 'compatibility import bridge must remain single-owner while retained');
});

test('historical import bridge delegates to durable ZIP runtime and cannot revive v18 synchronous import', () => {
  const block = historicalImportBlock();
  assert.match(block, /window\.ZipImportRuntime\?\.upload/);
  assert.doesNotMatch(block, /\/api\/v18\/projects\//);
  assert.doesNotMatch(block, /refreshLabels414/);
  assert.doesNotMatch(block, /reloadMaterialPage61/);
  for (const forbidden of ['await reload()', 'await loadAll()', 'await loadRelated()']) {
    assert.equal(block.includes(forbidden), false, `compatibility bridge must not use ${forbidden}`);
  }
});
