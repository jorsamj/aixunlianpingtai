import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');

function count(token) {
  return app.split(token).length - 1;
}

test('shadowed v423 algorithm create/edit generation stays physically retired', () => {
  const retired = [
    'window.openNewAlgorithm423=async function(){',
    'window.saveNewAlgorithm423=async function(){',
    'onclick="saveNewAlgorithm423()"',
    'window.saveEditAlgorithm423=async function(id)',
    'onclick="saveEditAlgorithm423(',
  ];
  for (const token of retired) {
    assert.equal(app.includes(token), false, `shadowed v423 algorithm CRUD owner must be retired: ${token}`);
  }

  assert.equal(count('window.openNewAlgorithm423='), 1, 'openNewAlgorithm423 must have one final owner');
  assert.equal(count('window.editAlgorithm423='), 1, 'editAlgorithm423 must have one final owner');
});

test('stable 414 algorithm create/edit owners remain authoritative and broad-refresh free', () => {
  const createStart = app.indexOf('window.saveNewAlgorithm414=async function()');
  const editOwner = app.indexOf('window.editAlgorithm423=function(id)', createStart);
  const editStart = app.indexOf('window.saveEditAlgorithm414=async id=>', editOwner);
  const deleteStart = app.indexOf('window.delAlgorithm=async id=>', editStart);
  assert.ok(createStart >= 0 && editOwner > createStart && editStart > editOwner && deleteStart > editStart);

  const createBlock = app.slice(createStart, editOwner);
  const editBlock = app.slice(editStart, deleteStart);
  for (const [name, block] of [['create', createBlock], ['edit', editBlock]]) {
    assert.equal(block.includes('await reload()'), false, `${name} must not use reload()`);
    assert.equal(block.includes('await loadAll()'), false, `${name} must not use loadAll()`);
    assert.equal(block.includes('await loadRelated()'), false, `${name} must not use loadRelated()`);
  }

  assert.match(createBlock, /state\.algorithms=\[item,/);
  assert.match(editBlock, /state\.algorithms\[i\]=item/);
});
