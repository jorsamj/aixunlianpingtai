import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function sliceBetween(startNeedle, endNeedle, from = 0) {
  const start = app.indexOf(startNeedle, from);
  assert.notEqual(start, -1, `missing ${startNeedle}`);
  const end = app.indexOf(endNeedle, start + startNeedle.length);
  assert.notEqual(end, -1, `missing ${endNeedle}`);
  return app.slice(start, end);
}

test('final v36 data import owner uses background v19 uploader, never synchronous v18 doImportData', () => {
  const start = app.lastIndexOf('window.importData=function(){');
  assert.ok(start >= 0);
  const end = app.indexOf('window.showImportTabV36=', start);
  assert.ok(end > start);
  const owner = app.slice(start, end);
  assert.match(owner, /onclick="doImportUploadV19\(\)"/);
  assert.doesNotMatch(owner, /onclick="doImportData\(\)"/);
});

test('background import polling performs one scoped terminal refresh without broad reload', () => {
  const owner = sliceBetween('function startImportPolling(seedJobId){', 'window.openImportDock=');
  assert.match(owner, /tracked=new Set/);
  assert.match(owner, /refreshLabels414\?\.\(false\)/);
  assert.match(owner, /state\.page==='数据集'/);
  assert.match(owner, /reloadMaterialPage61\?\.\(\)/);
  assert.doesNotMatch(owner, /loadRelated\(/);
  assert.doesNotMatch(owner, /reload\(/);
});

test('10k picker reports full image_count while rendering only bounded preview', () => {
  const owner = sliceBetween('function renderImportPicker(job){', 'window.toggleImportChecks=');
  assert.match(owner, /imgs\.slice\(0,500\)/);
  assert.match(owner, /Number\(job\.image_count\|\|0\)/);
  assert.match(owner, /全部 \$\{total\} 张图片/);
});
