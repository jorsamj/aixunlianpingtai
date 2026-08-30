import test from 'node:test';
import assert from 'node:assert/strict';

import {unwrapAlgorithmResponse} from '../../static/modules/algorithms.js';
import {iterationBasePresentation, projectedRandomSplit} from '../../static/modules/training.js';
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
