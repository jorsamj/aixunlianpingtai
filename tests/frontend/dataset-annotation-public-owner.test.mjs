import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('dataset and annotation public owners are unique', () => {
  for (const name of [
    'openAnnotation','goAnnotation417','renderAnnotator','previewData429',
    'renderData429Cards','renderDataCards426','setDataTab424',
    'confirmClean427','showImportReview412','submitAiLabel429','toggleRef429',
  ]) {
    const pattern=new RegExp('window\\.'+name+'\\s*=','g');
    assert.equal((app.match(pattern)||[]).length,1,name);
  }
});

test('stable annotation workbench owns annotation public actions', () => {
  assert.match(app,/Stable single-instance manual\/batch annotation workbench/);
  assert.match(app,/window\.openAnnotation=async function\(id\)\{\n    const key=String\(id\)/);
  assert.match(app,/window\.goAnnotation417=id=>window\.openAnnotation\(id\)/);
  assert.match(app,/window\.renderAnnotator=updateShell/);
});

test('AI submit and reference selection keep current owners', () => {
  assert.match(app,/Persistent v60 AI annotation UI/);
  assert.match(app,/window\.submitAiLabel429=async function\(ids=\[\]\)/);
  assert.match(app,/window\.toggleRefCore429=function\(id\)/);
  assert.match(app,/window\.toggleRef429=function\(id\)\{const key=String\(id\)/);
});


test('closing manual annotation preserves the short-lived workbench cache while cancelling stale apply', () => {
  const start = app.indexOf('window.closeModal=async function closeModalCanonical420()');
  const end = app.indexOf('\n  };', start);
  assert.ok(start >= 0 && end > start);
  const closeOwner = app.slice(start, end);
  assert.match(closeOwner, /typeof workbench\?\.cancel==='function'/);
  assert.match(closeOwner, /workbench\.cancel\(\)/);
  assert.doesNotMatch(closeOwner, /state\.annotationWorkbench=null/);
});


test('feedback candidate navigation waits for the canonical dataset route before opening annotation', () => {
  assert.match(app, /window\.openSupplementFeedbackAnnotation63=async function\(materialId\)/);
  const start = app.indexOf('window.openSupplementFeedbackAnnotation63=async function(materialId)');
  const end = app.indexOf('\n  window.openSupplementFeedbackCandidates63=', start);
  assert.ok(start >= 0 && end > start);
  const owner = app.slice(start, end);
  assert.match(owner, /await Promise\.resolve\(window\.closeModal\?\.\(\)\)/);
  assert.match(owner, /await Promise\.resolve\(window\.setPage\('数据集'\)\)/);
  assert.match(owner, /if\(state\.page!=='数据集'\)return false/);
  assert.match(owner, /return await window\.openAnnotation\(id\)/);
  assert.doesNotMatch(owner, /setTimeout/);
  assert.doesNotMatch(app, /setPage\('数据集'\);setTimeout\(\(\)=>openAnnotation/);
});
