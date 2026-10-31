import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const zip = readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url), 'utf8');
const app = readFileSync(new URL('../../app.py',import.meta.url), 'utf8');
const css = readFileSync(new URL('../../static/styles.css',import.meta.url), 'utf8');
const training = readFileSync(new URL('../../static/app.js',import.meta.url), 'utf8');
const modalStyles = readFileSync(new URL('../../static/training-create-modal.css',import.meta.url), 'utf8');

test('ZIP source class offers real source image and box preview before manual mapping', () => {
  assert.match(zip,/showLabelSamples\(\$\{jsArg\(id\)\},\$\{jsArg\(row\.classId\)\},\$\{jsArg\(encodeURIComponent\(source\)\)\}\)/);
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
  const scopedPreview=css.match(/\.zip-label-confirm \.zip-label-workspace \.label-mapping-sample-panel:not\(\[hidden\]\)\{([^}]*)\}/);
  assert.ok(scopedPreview, 'ZIP sample viewer must be contained within its layout');
  assert.match(scopedPreview[1],/position:static/);
  assert.match(scopedPreview[1],/z-index:auto/);
  assert.match(scopedPreview[1],/width:100%/);
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
  assert.match(modalStyles,/\.training-create-modal-card/);
  assert.match(modalStyles,/training-label-choice b\{font-size:13px/);
  assert.match(training,/const labelPanel=document\.getElementById\('trainingLabelContractPanel'\)/);
  assert.match(training,/labelSlot\.appendChild\(labelPanel\)/);
});

test('ZIP labels have one batch source plan with explicit durable creation and readable evidence layout',()=>{
  assert.match(zip,/确认素材标签/);
  assert.match(zip,/一键使用原始标签/);
  assert.match(zip,/previewOriginalLabels/);
  assert.match(zip,/confirmOriginalLabels/);
  assert.match(zip,/planOriginalLabelMappings\(review,labelItems\(\)\)/);
  const previewStart=zip.indexOf('function previewOriginalLabels(jobId)');
  const previewEnd=zip.indexOf('function cancelOriginalLabels(jobId)',previewStart);
  assert.ok(previewStart>=0&&previewEnd>previewStart,'ZIP original-label selection must exist');
  const preview=zip.slice(previewStart,previewEnd);
  assert.match(preview,/setLabelMapping\(review,item\.classId,item\.code\)/);
  assert.match(preview,/review\.pendingCreate\[item\.classId\]=item\.code/);
  assert.doesNotMatch(preview,/createPlatformLabel\(/,'selection must not create platform labels prematurely');
  const confirmStart=zip.indexOf('async function confirmLabels(jobId)');
  const confirmEnd=zip.indexOf('async function maybeStart(project)',confirmStart);
  assert.ok(confirmStart>=0&&confirmEnd>confirmStart,'ZIP final confirmation must exist');
  const confirmation=zip.slice(confirmStart,confirmEnd);
  assert.match(confirmation,/buildManualLabelMapping\(review\)/);
  const create=confirmation.indexOf('await createPlatformLabel(project,code,name)');
  const verify=confirmation.indexOf('verified.has(String(code))');
  const submit=confirmation.indexOf('await startZipJob(project,id,{fetchImpl,confirmation:{label_mapping}})');
  assert.ok(create>=0&&create<verify&&verify<submit,
    'final confirmation creates and verifies canonical labels before admitting the ZIP import');
  assert.match(zip,/zip-label-workspace/);
  assert.match(css,/\.zip-label-confirm \.zip-label-workspace/);
});

test('ZIP labels have one direct mapping screen and pending formal creation summary',()=>{
  assert.match(zip,/每行可以直接修改目标标签/);
  assert.match(zip,/确认导入时将新建/);
  assert.match(zip,/创建标签并导入/);
  assert.doesNotMatch(zip,/原始标签批量确认预览/);
  assert.doesNotMatch(zip,/完成手动调整/);
});
