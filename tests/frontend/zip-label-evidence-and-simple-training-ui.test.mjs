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

test('training first-open uses compact visible model and epochs and expandable technical details', () => {
  const start = training.indexOf('window.openTrainingCreateDialog429=function');
  const end = training.indexOf('window.openTrainingCreateDialog423=',start);
  assert.ok(start >= 0 && end > start);
  const creation = training.slice(start,end);
  assert.match(creation,/train-create-technical/);
  assert.match(creation,/train-create-primary/);
  assert.match(creation,/tr429MotherModel/);
  assert.match(creation,/tr429QuickEpoch/);
  assert.match(creation,/tr429Target/);
  assert.match(creation,/tr429TaskId/);
  assert.match(creation,/data-train-advanced-toggle/);
  assert.match(creation,/train-ui-summary-card" hidden/);
  assert.match(training,/window\.toggleTrainAdvanced429=function/);
  assert.match(training,/if\(summary\)summary\.hidden=!advanced/);
  assert.match(training,/window\.setQuickEpoch429=function/);
  assert.match(modalStyles,/font-size:15px/);
  assert.match(modalStyles,/train-create-show-advanced/);
  assert.match(modalStyles,/train-create-split-details/);
});
