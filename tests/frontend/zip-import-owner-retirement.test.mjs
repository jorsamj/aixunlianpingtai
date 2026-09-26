import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app=await readFile(new URL('../../static/app.js',import.meta.url),'utf8');
const runtime=await readFile(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
const bootstrap=await readFile(new URL('../../static/zip-import-bootstrap.mjs',import.meta.url),'utf8');
const pagination=await readFile(new URL('../../static/modules/material-pagination-runtime.js',import.meta.url),'utf8');

test('classic app has one import page owner and no ZIP upload public owner',()=>{
  assert.equal((app.match(/window\.importData\s*=/g)||[]).length,1);
  assert.equal((app.match(/window\.doUploadZip426\s*=/g)||[]).length,0);
  assert.match(app,/v36: source path \/ server URL import/);
  assert.match(app,/window\.importData=function\(\)/);
});

test('durable ZIP runtime exclusively owns doUploadZip426 and does not replace importData',()=>{
  assert.equal((runtime.match(/window\.doUploadZip426\s*=/g)||[]).length,1);
  assert.equal((runtime.match(/window\.importData\s*=/g)||[]).length,0);
  assert.equal(runtime.includes('classicImportData'),false);
  assert.match(runtime,/window\.ZipImportRuntime=runtime/);
});

test('bootstrap bridges classic ZIP submit to durable runtime',()=>{
  assert.match(bootstrap,/window\.doImportUploadV19 = durableUploadFromImportModal/);
  assert.match(bootstrap,/runtime\.upload\(input\)/);
});


test('material reload remains a direct owner and calls durable ZIP reconcile through an explicit hook',()=>{
  assert.doesNotMatch(runtime,/originalReload|__zipImportDurableWrapped/);
  assert.doesNotMatch(runtime,/window\.reloadMaterialPage61\s*=/);
  assert.match(pagination,/window\.reloadMaterialPage61 = async \(\) =>/);
  assert.match(pagination,/window\.ZipImportRuntime\?\.reconcile\?\.\('material-page'\)/);
});
