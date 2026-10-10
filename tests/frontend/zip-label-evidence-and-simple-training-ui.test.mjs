import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const zip = readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url), 'utf8');
const app = readFileSync(new URL('../../app.py',import.meta.url), 'utf8');
const css = readFileSync(new URL('../../static/styles.css',import.meta.url), 'utf8');
const training = readFileSync(new URL('../../static/app.js',import.meta.url), 'utf8');
const modalStyles = readFileSync(new URL('../../static/training-create-modal.css',import.meta.url), 'utf8');

test('ZIP source class offers real source image and box preview before manual mapping', () => {
  assert.match(zip,/showLabelSamples\('/);
  assert.match(zip,/data-zip-class-samples/);
  assert.match(zip,/sample\.bboxes/);
  assert.match(zip,/label-mapping-sample-load-error/);
  assert.match(zip,/addEventListener\('error'/);
  assert.match(zip,/labelSampleOverlay\(bbox\|\|\{\}\)/);
  assert.match(zip,/classes\/\$\{encodeURIComponent\(String\(classId\)\)\}\/samples/);
  assert.match(zip,/classSampleCache/);
  assert.match(app,/def v19_label_samples\(/);
  assert.match(app,/def v19_label_sample_content\(/);
  assert.match(app,/v19_write_class_samples\(project_id, upload_id, scan_class_samples\)/);
  assert.match(app,/v19_write_class_samples\(project_id, job_id, scan_class_samples\)/);
  assert.match(css,/\.label-mapping-sample-box/);
});

test('ZIP category mapping preserves preview while user decides destination', () => {
  assert.match(zip,/oldPanel\.remove\(\)/);
  assert.match(zip,/replaceWith\(oldPanel\)/);
  assert.match(zip,/buildManualLabelMapping\(review\)/);
  assert.match(zip,/data-zip-confirm-button/);
  assert.doesNotMatch(zip,/automaticLabelGuess/);
});

test('training first-open exposes four modes and visible canonical labels without duplicate tech fields', () => {
  const start = training.indexOf('window.openTrainingCreateDialog429=function');
  const end = training.indexOf('window.openTrainingCreateDialog423=', start);
  assert.ok(start >= 0 && end > start);
  const creation = training.slice(start, end);
  for (const part of [
    'train-create-saas-v2', 'train-v3-mode-options',
    "setTrainingModeV3('quick')", "setTrainingModeV3('full')",
    "setTrainingModeV3('complex')", "setTrainingModeV3('custom')",
    'tr429MotherModel', 'tr429Priority', 'tr429Target', 'tr429TaskId',
    'trainUiLabelSlot', 'trainUiLabelSearch', '训练标签',
    '智能自动化调度', 'train350-auto-schedule',
  ]) assert.ok(creation.includes(part), part);
  assert.doesNotMatch(creation,/id="tr429QuickEpoch"/);
  assert.doesNotMatch(creation,/编辑全部训练参数/);
  assert.match(creation,/train-v3-internals" hidden/);
  assert.match(modalStyles,/train-create-saas-v2/);
  assert.match(modalStyles,/training-label-choice b\{font-size:15px/);
  assert.match(training,/const labelPanel=document\.getElementById\('trainingLabelContractPanel'\)/);
  assert.match(training,/labelSlot\.appendChild\(labelPanel\)/);
});
