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

const sourceImportStartMarker = "const SOURCE_IMPORT_POLL_KEY_V36='source-import-v36';";
const sourceImportStart = app.indexOf(sourceImportStartMarker);
const sourceImportEnd = app.indexOf('\n\n  // Keep the existing dataset page clean;', sourceImportStart);
assert.ok(sourceImportStart >= 0 && sourceImportEnd > sourceImportStart, 'v36 source-import poll owner must remain addressable');
const sourceImportOwner = app.slice(sourceImportStart, sourceImportEnd);

test('final ZIP completion keeps review ownership and refreshes only label/material domains', () => {
  assert.ok((app.match(/window\.doUploadZip426=function/g) || []).length >= 1);
  assert.match(zipOwner, /completeZipImportReview412\?\.\(job\.id\)/);
  assert.match(zipOwner, /refreshLabels414\?\.\(false\)/);
  assert.match(zipOwner, /state\.page==='数据集'\)await window\.reloadMaterialPage61\?\.\(\)/);
  assert.doesNotMatch(zipOwner, /related411\s*\(/);
  assert.doesNotMatch(zipOwner, /loadRelated\s*\(/);
  assert.doesNotMatch(zipOwner, /loadAll\s*\(/);
});

test('server storage import confirmation stays mapping-only and never broad-loads', () => {
  assert.equal((app.match(/window\.confirmStorageImport61=async function/g) || []).length, 1);
  assert.match(storageOwner, /serverApi\(\)\.buildImportConfirmation\(rows/);
  assert.doesNotMatch(storageOwner, /refreshLabels414/);
  assert.match(storageOwner, /state\.page==='数据集'\)await window\.reloadMaterialPage61\?\.\(\)/);
  assert.doesNotMatch(storageOwner, /loadRelated\s*\(/);
  assert.doesNotMatch(storageOwner, /loadAll\s*\(/);
});

test('v36 source import polling is page-scoped through PollRegistry and never owns a raw timer', () => {
  assert.match(sourceImportOwner, /SOURCE_IMPORT_POLL_KEY_V36='source-import-v36'/);
  assert.match(sourceImportOwner, /PollRegistryRuntime\?\.startTimeout\?\.\(/);
  assert.match(sourceImportOwner, /'数据集'/);
  assert.match(sourceImportOwner, /PollRegistryRuntime\?\.clear\?\.\(SOURCE_IMPORT_POLL_KEY_V36\)/);
  assert.doesNotMatch(sourceImportOwner, /__sourceImportTimerV36/);
  assert.doesNotMatch(sourceImportOwner, /setTimeout\s*\(/);
});

test('historical related411 alias may remain only outside the final ZIP mutation owner', () => {
  assert.match(app, /const related411=loadRelated/);
  assert.doesNotMatch(zipOwner, /related411\s*\(/);
});
