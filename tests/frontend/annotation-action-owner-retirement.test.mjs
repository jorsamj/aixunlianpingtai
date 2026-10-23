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

test('manual save distinguishes pending empty from explicit negative and advances only once', () => {
  const coreStart = app.indexOf('window.saveAnnotationCore420=async function');
  const coreEnd = app.indexOf('// ---------- dataset: labels strictly from label library ----------', coreStart);
  const core = app.slice(coreStart, coreEnd);
  assert.match(core, /confirmEmpty=options\?\.confirmEmpty===true/);
  assert.match(core, /annotation_state:boxes\.length\?'annotated':confirmEmpty\?'confirmed_empty':'unannotated'/);
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


test('manual annotation delegates editable shapes to one official kernel and preserves explicit review', () => {
  assert.match(app, /function drawBoxes\(\)\{return window\.syncAnnotationEditor420\?\.\(\)\}/);
  assert.match(app, /function bindAnnotationEvents\(\)\{return window\.syncAnnotationEditor420\?\.\(\)\}/);
  assert.equal((app.match(/function ensureAnnotationEditor420\(/g)||[]).length,1);
  assert.doesNotMatch(app, /className='box box424'|className='drawBox'|annPointerAbort|bound411|bound424/);
  assert.doesNotMatch(app, /window\.addEventListener\(['"]mouse(?:move|up)/);

  const stableStart = app.lastIndexOf('Stable single-instance manual\/batch annotation workbench');
  const stableEnd = app.indexOf('Persistent v60 AI annotation UI', stableStart);
  const stable = app.slice(stableStart, stableEnd);
  assert.match(stable, /window\.saveAndConfirmAnnotationReview420=async function/);
  assert.doesNotMatch(app, /ann420ConfirmEmpty|confirmEmptyAnnotation420/);
  assert.match(stable, /button\.textContent='提交中…'/);
  assert.match(stable, /confirmReview:true,reviewedLabelCodes:selected/);
  assert.match(stable, /未检查类别（默认不勾选）/);
  assert.match(stable, /<details[^>]*id="ann420ReviewPanel"/);
  assert.match(stable, /显式全选未检查类别/);
  assert.match(stable, /restoreLabelSchema414/);
  assert.match(stable, /createAnnotoriousEditor/);
  assert.match(stable, /state\.annotationEditor\?\.flush\?\.\(\)/);
  assert.match(stable, /window\.destroyAnnotationEditor420\?\.\(\);clearTimeout\(state\.annAutoSaveTimer\)/);
  assert.match(stable, /resetAnnotationZoom420/);
  assert.match(stable, /fitAnnotation420/);
  assert.match(stable, /适应窗口/);
});
