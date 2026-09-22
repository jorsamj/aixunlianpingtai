import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('deployment target selection has one canonical owner', () => {
  assert.equal(app.includes('const selectDeployM4=window.selectDeployTarget;'), false);
  assert.equal(app.includes('const baseSelect=window.selectDeployTarget;'), false);
  assert.equal((app.match(/window\.selectDeployTarget=/g) || []).length, 1);
  assert.match(app, /window\.selectDeployTargetCoreV39=k=>/);
  assert.match(app, /window\.decorateDeployTargetM4=function\(kind\)/);
  assert.match(app, /window\.selectDeployTarget=function selectDeployTargetCanonicalM4\(kind\)/);
});

test('deployment resource editor no longer wraps already-capable base modals', () => {
  assert.equal(app.includes('const oldOpen=window.openDeployResourceModal, oldEdit=window.editDeployResource;'), false);
  assert.equal((app.match(/window\.openDeployResourceModal=/g) || []).length, 1);
  assert.equal((app.match(/window\.editDeployResource=/g) || []).length, 1);
  assert.match(app, /<option value="rockchip"/);
  assert.match(app, /id="drPython"/);
});

test('version conversion uses explicit core and one public canonical owner', () => {
  assert.equal(app.includes('const baseOpenConvert417=window.openNewConvert428;'), false);
  assert.equal((app.match(/window\.openNewConvert428=/g) || []).length, 1);
  assert.match(app, /window\.openNewConvertCore416=async function\(aid,vid\)/);
  assert.match(app, /window\.decorateConvertResourceButton417=function\(\)/);
  assert.match(app, /window\.openNewConvert428=async function openNewConvertCanonical428\(\.\.\.args\)/);
});
