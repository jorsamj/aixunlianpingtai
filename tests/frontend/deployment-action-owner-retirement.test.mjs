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


test('retired deployment page is no longer a public action target', () => {
  assert.equal(app.includes('onclick="setPage(\'部署转换\')"'), false);
  assert.equal(app.includes('closeModal();setPage(\'部署转换\')'), false);
  assert.doesNotMatch(app, /window\.startDeployVersion=.*setPage\?\.\('部署转换'\)/);
  assert.match(
    app,
    /window\.startDeployVersion=\(aid,vid\)=>\{closeModal\(\);return window\.openVersionConvert428\?\.\(aid,vid\)\}/,
  );
  assert.equal(
    app.includes("onclick=\"closeModal();openVersionConvert428('\${aid}','\${vid}')\""),
    true,
  );
});


test('retired deployment renderers and create action are not public owners', () => {
  assert.equal(app.includes('window.renderDeployCenter='), false);
  assert.equal(app.includes('window.renderDeployArtifacts='), false);
  assert.equal(app.includes('window.createDeployJob='), false);
  assert.equal(app.includes('window.createDeployJobM4='), false);
  assert.equal(app.includes('window.createDeployJobLegacyV39='), false);
  assert.equal(app.includes('window.__m4CreateDeployJob'), false);
  assert.equal((app.match(/window\.submitConvert428=/g) || []).length, 1);
});
