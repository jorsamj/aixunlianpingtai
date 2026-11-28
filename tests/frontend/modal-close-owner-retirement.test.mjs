import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('modal closing uses explicit core and before-close hooks', () => {
  assert.equal(app.includes('const previousCloseImport=window.closeModal;'), false);
  assert.equal(app.includes('const previousClose=window.closeModal;'), false);
  assert.equal(app.includes('const oldModal424=modal, oldClose424=closeModal;'), false);
  assert.match(app, /function modalBase\(title,body,wide=false\)/);
  assert.match(app, /function closeModalBase\(\)/);
  assert.match(app, /modal=function modalStackCanonical424\(title,body,wide=false\)/);
  assert.match(app, /closeModal=function closeModalStackCore424\(\)/);
  assert.match(app, /window\.closeModalCore424=closeModal/);
  assert.match(app, /window\.beforeCloseStorageImport61=function\(\)/);
  assert.match(app, /window\.closeModal=async function closeModalCanonical420\(\)/);
});

test('canonical close preserves storage polling cleanup and annotation dirty-save', () => {
  const start = app.indexOf('window.closeModal=async function closeModalCanonical420()');
  const end = app.indexOf('\n  };', start);
  const block = app.slice(start, end);
  assert.ok(start >= 0 && end > start);
  assert.match(block, /beforeCloseStorageImport61/);
  assert.match(block, /annotationWorkbench\?\.dirty/);
  assert.match(block, /await window\.saveAnn\(true\)/);
  assert.match(block, /const closeOwner=window\.ModalContentRuntime\?\.captureOwner\?\.\(\)/);
  assert.match(block, /if\(closeOwner&&!closeOwner\.isCurrent\(\)\)return false/);
  assert.ok(block.indexOf('const closeOwner=') < block.indexOf('await window.saveAnn(true)'));
  assert.ok(block.indexOf('if(closeOwner&&!closeOwner.isCurrent())return false') > block.indexOf('await window.saveAnn(true)'));
  assert.ok(block.indexOf('if(closeOwner&&!closeOwner.isCurrent())return false') < block.indexOf('window.closeModalCore424?.()'));
  assert.match(block, /const workbench=state\.annotationWorkbench/);
  assert.match(block, /typeof workbench\?\.cancel==='function'/);
  assert.match(block, /workbench\.cancel\(\);else workbench\?\.invalidate\?\.\(\)/);
  assert.match(block, /closeModalCore424/);
});

test('storage import close hook stops progress polling without replacing closeModal', () => {
  const start = app.indexOf('window.installServerMaterialImport61=function()');
  const end = app.indexOf('window.openDataUploadStorage61=async function()', start);
  const block = app.slice(start, end);
  assert.match(block, /window\.beforeCloseStorageImport61=function\(\)/);
  assert.match(block, /abortPolling\(\)/);
  assert.doesNotMatch(block, /window\.closeModal=async function/);
});


test('modal and closeModal each expose one public owner', () => {
  assert.equal((app.match(/window\.modal\s*=/g) || []).length, 1);
  assert.equal((app.match(/window\.closeModal\s*=/g) || []).length, 1);
  assert.match(app, /window\.modal=modal/);
  assert.match(app, /window\.closeModal=async function closeModalCanonical420\(\)/);
});


test('bulk close retires import polling and restores the original outer focus only',()=>{
  const start=app.indexOf('window.closeAllModals424=function(){');
  const end=app.indexOf('\n  };',start);
  assert.ok(start>=0&&end>start);
  const block=app.slice(start,end);
  assert.match(block,/window\.beforeCloseStorageImport61\?\.\(\)/);
  assert.match(block,/const rootLayer=baseModal&&!baseModal\.classList\.contains\('hidden'\)\?baseModal:dynamicModalStack\[0\]/);
  assert.match(block,/beforeCloseModal424\(layer\)/);
  assert.match(block,/modalReturnFocus424\.delete\(layer\)/);
  assert.match(block,/if\(rootLayer\)restoreModalFocus424\(rootLayer\)/);
  assert.ok(block.indexOf('window.beforeCloseStorageImport61?.()')<block.indexOf('for(const layer of'));
  assert.ok(block.indexOf('if(rootLayer)restoreModalFocus424(rootLayer)')>block.indexOf('closeModalBase()'));
});
