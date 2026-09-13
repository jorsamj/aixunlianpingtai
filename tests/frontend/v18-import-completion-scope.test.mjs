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
  assert.equal((app.match(/window\.doImportData=/g) || []).length, 1, 'historical v18 fallback must remain single-owner while retained');
});

test('historical v18 fallback completion refreshes only labels and paged materials', () => {
  const block = historicalImportBlock();
  const endpoint = '/api/v18/projects/${pid()}/datasets/${state.datasetId}/import';
  assert.equal(block.split(endpoint).length - 1, 1, 'historical fallback must submit the v18 import endpoint exactly once');
  assert.match(block, /await window\.refreshLabels414\?\.\(false\)/);
  assert.match(block, /if\(state\.page==='数据集'\)await window\.reloadMaterialPage61\?\.\(\)/);
  for (const forbidden of ['await reload()', 'await loadAll()', 'await loadRelated()']) {
    assert.equal(block.includes(forbidden), false, `v18 fallback completion must not use ${forbidden}`);
  }
});
