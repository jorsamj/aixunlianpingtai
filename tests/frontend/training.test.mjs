import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {unwrapAlgorithmResponse} from '../../static/modules/algorithms.js';
import {
  applyMaterialSelection,
  buildTrainingPayload,
  filterTrainingMaterials,
  iterationBasePresentation,
  projectedRandomSplit,
} from '../../static/modules/training.js';
import {qualityChartModel} from '../../static/modules/quality.js';
import {reportPresentation} from '../../static/modules/reports.js';

test('algorithm create and edit responses unwrap the persisted asset', () => {
  const algorithm = {id: 'fire', name: '烟火算法'};
  assert.equal(unwrapAlgorithmResponse({ok: true, algorithm}), algorithm);
  assert.equal(unwrapAlgorithmResponse(algorithm), algorithm);
});

test('training iteration presentation distinguishes loading, first train, and latest version', () => {
  assert.equal(iterationBasePresentation(null).title, '正在读取最新版本…');
  assert.equal(iterationBasePresentation({}).title, '首次训练：使用所选母模型');
  assert.deepEqual(iterationBasePresentation({version_name: 'v2', model_name: 'best.pt'}), {
    title: '从最新可训练版本继续：v2',
    detail: 'best.pt',
    status: 'version'
  });
});

test('training candidate summary projects this run instead of persisted split fields', () => {
  assert.deepEqual(projectedRandomSplit(10, 20), {train: 8, experiment: 2});
  assert.deepEqual(projectedRandomSplit(2, 20), {train: 1, experiment: 1});
  assert.deepEqual(projectedRandomSplit(0, 20), {train: 0, experiment: 0});
});

test('final training payload keeps three roles and never auto-selects hidden test rows', () => {
  const payload = buildTrainingPayload({
    splitMode: 'independent_test_set',
    trainImageIds: ['a', 'b', 'b'],
    testImageIds: ['c'],
    validationPercent: 20,
    parameters: {epochs: 50}
  });
  assert.deepEqual(payload.train_image_ids, ['a', 'b']);
  assert.deepEqual(payload.test_image_ids, ['c']);
  assert.equal(payload.validation_percent, 20);
  assert.equal(payload.experiment_percent, null);
  assert.equal(payload.epochs, 50);
  assert.equal('selected_image_ids' in payload, false);
  assert.equal('train_dataset_ids' in payload, false);
});

test('random test mode accepts an arbitrary bounded percentage', () => {
  const payload = buildTrainingPayload({
    splitMode: 'random_test_from_training_pool',
    trainImageIds: ['one', 'two', 'three'],
    testImageIds: ['must-not-leak'],
    experimentPercent: 12.5,
    validationPercent: 15,
  });
  assert.deepEqual(payload.train_image_ids, ['one', 'two', 'three']);
  assert.deepEqual(payload.test_image_ids, []);
  assert.equal(payload.experiment_percent, 12.5);
  assert.equal(payload.validation_percent, 15);
});

test('material training payload rejects empty and overlapping selections', () => {
  assert.throws(() => buildTrainingPayload({
    splitMode: 'random_test_from_training_pool',
    trainImageIds: [],
    experimentPercent: 20,
    validationPercent: 20,
  }), /请选择训练素材/);
  assert.throws(() => buildTrainingPayload({
    splitMode: 'independent_test_set',
    trainImageIds: ['same'],
    testImageIds: ['same'],
    validationPercent: 20,
  }), /不能重复/);
});

test('training material filter uses processed annotated images and OR label matching', () => {
  const rows = [
    {id: 'fire', filename: 'fire.jpg', annotated: true, processing_status: 'processed', labels: ['fire']},
    {id: 'smoke', filename: 'smoke.jpg', annotated: true, cleaned_at: 'now', labels: ['smoke']},
    {id: 'both', filename: 'scene.jpg', annotated: true, clean_skipped: true, labels: ['fire', 'smoke']},
    {id: 'raw', filename: 'raw.jpg', annotated: false, processing_status: 'processed', labels: []},
  ];
  assert.deepEqual(
    filterTrainingMaterials(rows, {labelCodes: ['fire', 'smoke']}).map(row => row.id),
    ['fire', 'smoke', 'both'],
  );
  assert.deepEqual(
    filterTrainingMaterials(rows, {query: 'scene', labelCodes: ['fire']}).map(row => row.id),
    ['both'],
  );
});

test('training material selection supports filtered, inverted, all, and none actions', () => {
  assert.deepEqual(applyMaterialSelection(['a'], ['b', 'c'], ['a', 'b', 'c', 'd'], 'select-filtered'), ['a', 'b', 'c']);
  assert.deepEqual(applyMaterialSelection(['a', 'b'], ['b', 'c'], ['a', 'b', 'c', 'd'], 'invert-filtered'), ['a', 'c']);
  assert.deepEqual(applyMaterialSelection([], ['b'], ['a', 'b', 'c'], 'select-all'), ['a', 'b', 'c']);
  assert.deepEqual(applyMaterialSelection(['a', 'b'], ['a'], ['a', 'b'], 'clear-all'), []);
});

test('final training dialog override selects materials instead of datasets', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const block = source.slice(source.indexOf('Durable v3 exact-material training split UI'), source.indexOf('Stable single-instance manual/batch annotation workbench'));
  assert.match(block, /openTrainMaterialPickerV3/);
  assert.match(block, /select-filtered/);
  assert.match(block, /clear-all/);
  assert.doesNotMatch(block, /datasetRows\(\)/);
  assert.doesNotMatch(block, /trainDatasetIds/);
});

test('legacy dataset selector and dataset prerequisite are absent from training creation', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.equal(source.includes('Legacy dataset split UI'), false);
  assert.equal(source.includes('trainDatasetIds'), false);
  assert.equal(source.includes("if(!(state.datasets||[]).length)return toast('当前项目没有可用数据集')"), false);
});

test('training dialog is not blocked by the legacy current-image pool guard', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.equal(source.includes("if(p.length<2)return toast('至少需要2张“已处理且已标注”的图片才能开始训练')"), false);
});

test('quality chart model clamps scores and sorts label counts', () => {
  assert.deepEqual(qualityChartModel({
    scores: {标注覆盖: 108, 框有效性: -3},
    label_boxes: {smoke: 2, fire: 7}
  }), {
    dimensions: [{label: '标注覆盖', score: 100}, {label: '框有效性', score: 0}],
    labels: [{label: 'fire', count: 7}, {label: 'smoke', count: 2}],
    maxLabelCount: 7
  });
});

test('report presentation keeps algorithm and version reports distinct', () => {
  assert.deepEqual(reportPresentation({report_type: 'algorithm'}), {
    title: '算法综合训练报告', scope: 'algorithm'
  });
  assert.deepEqual(reportPresentation({report_type: 'version'}), {
    title: '单版本训练报告', scope: 'version'
  });
});
