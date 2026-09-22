import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('manual annotation save has one public canonical owner', () => {
  assert.equal((app.match(/window\.saveAnn=/g) || []).length, 1);
  for (const token of [
    'const baseSaveAnnotation417=window.saveAnn;',
    'const saveAnn411=window.saveAnn;',
    'const previousSave=window.saveAnn;',
  ]) assert.equal(app.includes(token), false, token);
  assert.match(app, /window\.saveAnnotationCore420=async function\(silent=false,options=\{\}\)/);
  assert.match(app, /window\.saveAnn=async function saveAnnotationCanonical420\(silent=false,options=\{\}\)/);
});

test('manual save requires explicit empty confirmation and advances only once', () => {
  const coreStart = app.indexOf('window.saveAnnotationCore420=async function');
  const coreEnd = app.indexOf('// ---------- dataset: labels strictly from label library ----------', coreStart);
  const core = app.slice(coreStart, coreEnd);
  assert.match(core, /confirmEmpty=options\?\.confirmEmpty===true/);
  assert.match(core, /annotation_state:boxes\.length\?'annotated':'confirmed_empty'/);
  const stableStart = app.lastIndexOf('Stable single-instance manual\/batch annotation workbench');
  const stableEnd = app.indexOf('Persistent v60 AI annotation UI', stableStart);
  const stable = app.slice(stableStart, stableEnd);
  assert.equal((stable.match(/annotationWorkbench\?\.open\(ids\[at\+1\]\)/g) || []).length, 1);
  assert.doesNotMatch(app, /setTimeout\(\(\)=>goAnnotation417\(queue\[at\+1\]\),80\)/);
});

test('annotation dirty tracking uses explicit core instead of previous-owner capture', () => {
  assert.equal(app.includes('const previousMarkDirty=window.markDirty;'), false);
  assert.match(app, /function markAnnotationDirtyCore\(\)/);
  assert.match(app, /window\.markDirty=function markAnnotationDirtyCanonical420\(\)/);
});


test('manual annotation uses incremental box patching and explicit empty confirmation', () => {
  const drawStart = app.lastIndexOf('drawBoxes=function(){');
  const drawEnd = app.indexOf('bindAnnotationEvents=function()', drawStart);
  const draw = app.slice(drawStart, drawEnd);
  assert.match(draw, /querySelectorAll\('\.box424'\)/);
  assert.match(draw, /keep=new Set\(\)/);
  assert.doesNotMatch(draw, /querySelectorAll\('\.box,\.drawBox'\).*remove/);

  const stableStart = app.lastIndexOf('Stable single-instance manual\/batch annotation workbench');
  const stableEnd = app.indexOf('Persistent v60 AI annotation UI', stableStart);
  const stable = app.slice(stableStart, stableEnd);
  assert.match(stable, /confirmEmptyAnnotationCanonical420/);
  assert.match(stable, /button\.textContent='确认中…'/);
  assert.match(stable, /restoreLabelSchema414/);
  assert.match(stable, /wheelZoomBound/);
});
