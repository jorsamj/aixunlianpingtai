import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');

const zipStartMarker = '  window.doUploadZip426=function(inp){';
const zipStart = app.lastIndexOf(zipStartMarker);
const zipEnd = app.indexOf('\n  // Run the one initial load only after every version override above has been installed.', zipStart);
assert.ok(zipStart >= 0 && zipEnd > zipStart, 'final v42.11 ZIP owner must remain addressable');
const zipOwner = app.slice(zipStart, zipEnd);

const storageStartMarker = '    window.confirmStorageImport61=async function(taskId){';
const storageStart = app.indexOf(storageStartMarker);
const storageEnd = app.indexOf('\n\n    const previousCloseImport=window.closeModal;', storageStart);
assert.ok(storageStart >= 0 && storageEnd > storageStart, 'storage import confirmation owner must remain addressable');
const storageOwner = app.slice(storageStart, storageEnd);

test('final ZIP completion keeps review ownership and refreshes only label/material domains', () => {
  assert.ok((app.match(/window\.doUploadZip426=function/g) || []).length >= 1);
  assert.match(zipOwner, /completeZipImportReview412\?\.\(job\.id\)/);
  assert.match(zipOwner, /refreshLabels414\?\.\(false\)/);
  assert.match(zipOwner, /state\.page==='数据集'\)await window\.reloadMaterialPage61\?\.\(\)/);
  assert.doesNotMatch(zipOwner, /related411\s*\(/);
  assert.doesNotMatch(zipOwner, /loadRelated\s*\(/);
  assert.doesNotMatch(zipOwner, /loadAll\s*\(/);
});

test('server storage import confirmation refreshes labels only when created and never broad-loads', () => {
  assert.equal((app.match(/window\.confirmStorageImport61=async function/g) || []).length, 1);
  assert.match(storageOwner, /rows\.some\(row=>row\.create\).*refreshLabels414\?\.\(false\)/);
  assert.match(storageOwner, /state\.page==='数据集'\)await window\.reloadMaterialPage61\?\.\(\)/);
  assert.doesNotMatch(storageOwner, /loadRelated\s*\(/);
  assert.doesNotMatch(storageOwner, /loadAll\s*\(/);
});

test('historical related411 alias may remain only outside the final ZIP mutation owner', () => {
  assert.match(app, /const related411=loadRelated/);
  assert.doesNotMatch(zipOwner, /related411\s*\(/);
});
