import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const negative = fs.readFileSync(new URL('../../static/modules/negative-samples.js', import.meta.url), 'utf8');
const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');

test('negative sample runtime is decorator-only and never captures annotation owners', () => {
  for (const token of [
    '__negativeWrapped',
    'const original = window.',
    'window.renderAnnotator =',
    'window.saveAnn =',
    'wrapNavigation',
    'setTimeout(',
  ]) assert.equal(negative.includes(token), false, token);
  assert.match(negative, /document\.getElementById\?\.\('ann420ConfirmEmpty'\)/);
  assert.match(negative, /window\.NegativeSampleRuntime = runtime/);
  assert.match(negative, /confirmed_empty/);
});

test('canonical annotation owners explicitly decorate and confirm empty truth', () => {
  assert.match(app, /window\.saveAnn=async function saveAnnotationCanonical420/);
  assert.match(app, /window\.confirmEmptyAnnotation420=async function confirmEmptyAnnotationCanonical420\(\)/);
  assert.match(app, /if\(!selected\.size\)\{toast\('请在“类别审核范围”中勾选已经确认无目标的标签'/);
  assert.match(app, /return window\.saveAndConfirmAnnotationReview420\(\)/);
  assert.match(app, /confirmEmpty:\(state\.ann\?\.boxes\?\.length\|\|0\)===0,confirmReview:true,reviewedLabelCodes:selected/);
  assert.ok((app.match(/window\.NegativeSampleRuntime\?\.decorate\?\.\(\);/g) || []).length >= 2);
  assert.match(main, /negative-samples\.js\?v=422544/);
});
