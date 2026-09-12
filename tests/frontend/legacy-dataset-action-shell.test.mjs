import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');
const index = fs.readFileSync('static/index.html', 'utf8');

const retired = [
  'window.uploadImages=',
  'window.autoSplit=',
  'window.buildYolo=',
  'window.checkDatasetQuality=',
  'window.setImageSplit=',
];

test('zero-reference legacy dataset action owners stay physically retired', () => {
  for (const token of retired) {
    assert.equal(app.includes(token), false, `retired dataset action owner reintroduced: ${token}`);
  }
});

test('R20j preserves the final dataset route and bounded renderer delegate', () => {
  assert.match(app, /if\(state\.page==='数据集'\)\{renderDatasets424\(\);return\}/);
  assert.match(app, /function renderDatasets\(\)\{return window\.renderDatasets424\?\.\(\)\}/);
});

test('R20j keeps the formal visible version independent from internal cache bumps', () => {
  assert.match(index, /id="versionBadge" class="version-badge">v42\.24\.0</);
  assert.match(index, /<script src="\/static\/app\.js\?v=42\.25\.\d+"><\/script>/);
});
