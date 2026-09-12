import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');
const main = fs.readFileSync('static/main.mjs', 'utf8');

const retired = [
  'window.newAlgorithm=',
  'window.saveAlgorithm=',
  'window.editAlgorithm=',
  'window.saveEditAlgorithm=',
  'window.viewAlgorithm=',
  'const oldRenderAlgorithms = window.renderAlgorithms;',
  'function renderAlgorithmCards422(){',
  'window.renderAlgorithms422=',
  'window.openNewAlgorithm422=',
  'window.saveNewAlgorithm422=',
  "renderAlgorithms422();return",
];

test('legacy algorithm CRUD and shadowed renderer owners stay retired', () => {
  for (const token of retired) {
    assert.equal(app.includes(token), false, `retired algorithm owner reintroduced: ${token}`);
  }
});

test('current algorithm page is fenced to stable renderer and semantic create action', () => {
  assert.match(app, /if\(state\.page==='算法列表'\)\{renderAlgorithms423\(\);return\}/);
  assert.match(app, /function renderAlgorithms\(\)\{return window\.renderAlgorithms423\?\.\(\)\}/);
  assert.match(app, /data-action="algorithm\.create"/);
  assert.match(main, /registerAction\('algorithm\.create',[\s\S]*?window\.openNewAlgorithm423\(\)/);
});

test('stable algorithm mutations patch authoritative local state without broad reload', () => {
  const createStart = app.indexOf('window.saveNewAlgorithm414=async function()');
  const editStart = app.indexOf('window.saveEditAlgorithm414=async id=>');
  const deleteStart = app.indexOf('window.delAlgorithm=async id=>', editStart);
  assert.ok(createStart >= 0 && editStart > createStart && deleteStart > editStart);
  const createBlock = app.slice(createStart, editStart);
  const editBlock = app.slice(editStart, deleteStart);
  const deleteEnd = app.indexOf('// ---------- training iteration', deleteStart);
  assert.ok(deleteEnd > deleteStart);
  const deleteBlock = app.slice(deleteStart, deleteEnd);
  for (const [name, block] of [['create', createBlock], ['edit', editBlock], ['delete', deleteBlock]]) {
    assert.equal(block.includes('await reload()'), false, `${name} must not use reload()`);
    assert.equal(block.includes('await loadAll()'), false, `${name} must not use loadAll()`);
    assert.equal(block.includes('await loadRelated()'), false, `${name} must not use loadRelated()`);
  }
  assert.match(createBlock, /state\.algorithms=\[item,/);
  assert.match(editBlock, /state\.algorithms\[i\]=item/);
  assert.match(deleteBlock, /state\.algorithms=\(state\.algorithms\|\|\[\]\)\.filter/);
});
