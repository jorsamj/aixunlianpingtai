from pathlib import Path

app_path = Path('static/app.js')
index_path = Path('static/index.html')
test_path = Path('tests/frontend/import-refresh-owner.test.mjs')

app = app_path.read_text(encoding='utf-8')

# Final v42.11 ZIP owner only: the last doUploadZip426 assignment is live.
zip_start_marker = '  window.doUploadZip426=function(inp){'
zip_start = app.rfind(zip_start_marker)
zip_end_marker = '\n  // Run the one initial load only after every version override above has been installed.'
zip_end = app.find(zip_end_marker, zip_start)
if zip_start < 0 or zip_end < 0:
    raise SystemExit('final v42.11 ZIP owner boundary not found')
zip_owner = app[zip_start:zip_end]
old_zip = 'window.completeZipImportReview412?.(job.id);invalidateQuality411();await related411();if(state.page===\'数据集\')renderDatasets424()'
new_zip = 'window.completeZipImportReview412?.(job.id);invalidateQuality411();await window.refreshLabels414?.(false);if(state.page===\'数据集\')await window.reloadMaterialPage61?.()'
if zip_owner.count(old_zip) != 1:
    raise SystemExit(f'expected one final ZIP broad refresh tail, got {zip_owner.count(old_zip)}')
if 'reloadMaterialPage61' in zip_owner or 'refreshLabels414' in zip_owner:
    raise SystemExit('final ZIP owner already appears migrated')
zip_owner = zip_owner.replace(old_zip, new_zip, 1)
if 'related411()' in zip_owner or 'loadRelated()' in zip_owner or 'loadAll()' in zip_owner:
    raise SystemExit('broad refresh remains in final ZIP owner')
app = app[:zip_start] + zip_owner + app[zip_end:]

# Final server-storage confirmation owner is unique and live.
storage_start_marker = '    window.confirmStorageImport61=async function(taskId){'
storage_start = app.find(storage_start_marker)
storage_end_marker = '\n\n    const previousCloseImport=window.closeModal;'
storage_end = app.find(storage_end_marker, storage_start)
if storage_start < 0 or storage_end < 0:
    raise SystemExit('storage import confirmation owner boundary not found')
storage_owner = app[storage_start:storage_end]
old_storage = "if(completed?.status==='SUCCEEDED'){await loadRelated();toast(`素材索引已建立：${safeCount(completed.result?.imported)} 条`);if(state.page==='数据集')renderDatasets424()}"
new_storage = "if(completed?.status==='SUCCEEDED'){if(rows.some(row=>row.create))await window.refreshLabels414?.(false);if(state.page==='数据集')await window.reloadMaterialPage61?.();toast(`素材索引已建立：${safeCount(completed.result?.imported)} 条`)}"
if storage_owner.count(old_storage) != 1:
    raise SystemExit(f'expected one storage broad refresh tail, got {storage_owner.count(old_storage)}')
if 'reloadMaterialPage61' in storage_owner or 'refreshLabels414' in storage_owner:
    raise SystemExit('storage import owner already appears migrated')
storage_owner = storage_owner.replace(old_storage, new_storage, 1)
if 'loadRelated()' in storage_owner or 'loadAll()' in storage_owner:
    raise SystemExit('broad refresh remains in storage import owner')
app = app[:storage_start] + storage_owner + app[storage_end:]
app_path.write_text(app, encoding='utf-8')

index = index_path.read_text(encoding='utf-8')
old_cache = '/static/app.js?v=42.25.82'
new_cache = '/static/app.js?v=42.25.83'
if index.count(old_cache) != 1:
    raise SystemExit(f'expected app cache {old_cache} exactly once, got {index.count(old_cache)}')
index_path.write_text(index.replace(old_cache, new_cache, 1), encoding='utf-8')

test_path.write_text(r'''import test from 'node:test';
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
''', encoding='utf-8')

print('R20g import refresh owners migrated')
