import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');
const index = fs.readFileSync('static/index.html', 'utf8');

const retired = [
  'window.selectDataset=',
  'window.newDataset=',
  'window.saveDataset=',
  'window.editDataset=',
  'window.saveEditDataset=',
  'window.delDataset=',
  'oldSelectDataset',
  'currentDataset()',
];

test('legacy dataset-group CRUD owners stay physically retired', () => {
  for (const token of retired) {
    assert.equal(app.includes(token), false, `retired dataset-group owner reintroduced: ${token}`);
  }
});

test('historical render maps retain only a bounded dataset delegate', () => {
  assert.equal((app.match(/function renderDatasets\(\)\{/g) || []).length, 1);
  assert.match(app, /function renderDatasets\(\)\{return window\.renderDatasets424\?\.\(\)\}/);
  assert.match(app, /if\(state\.page==='数据集'\)\{renderDatasets424\(\);return\}/);
});

test('R20i cache moves without changing the formal visible version', () => {
  assert.match(index, /app\.js\?v=42\.25\.85/);
  assert.match(index, /id="versionBadge" class="version-badge">v42\.24\.0</);
});
