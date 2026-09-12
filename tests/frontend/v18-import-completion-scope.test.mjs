import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');

function liveImportBlock() {
  const start = app.indexOf('window.doImportData=');
  const end = app.indexOf('\n\nwindow.manageLabels=', start);
  assert.ok(start >= 0 && end > start, 'live doImportData block must exist');
  return app.slice(start, end);
}

test('final v36 import UI still delegates ZIP upload to live doImportData', () => {
  assert.match(app, /modal\('导入素材 \/ 标注',[\s\S]*?onclick="doImportData\(\)"/);
  assert.equal((app.match(/window\.doImportData=/g) || []).length, 1);
});

test('live v18 import completion refreshes only labels and paged materials', () => {
  const block = liveImportBlock();
  const endpoint = '/api/v18/projects/${pid()}/datasets/${state.datasetId}/import';
  assert.equal(block.split(endpoint).length - 1, 1, 'live owner must submit the v18 import endpoint exactly once');
  assert.match(block, /await window\.refreshLabels414\?\.\(false\)/);
  assert.match(block, /if\(state\.page==='数据集'\)await window\.reloadMaterialPage61\?\.\(\)/);
  for (const forbidden of ['await reload()', 'await loadAll()', 'await loadRelated()']) {
    assert.equal(block.includes(forbidden), false, `v18 import completion must not use ${forbidden}`);
  }
});
