import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  buildTrainingEngineParameters,
  formatTrainingValidationError,
} from '../../static/modules/training-submit.js';

test('training submit normalizes string batch and workers before strict backend validation', () => {
  const draft = {
    resource: {
      batch: '8',
      workers: '0',
      device: 'cuda:0',
      strategy: 'auto',
      gpuPolicy: 'auto',
      cache: false,
    },
    config: {},
  };
  const target = {id: 'local-gpu', framework: 'ultralytics', type: 'local'};
  const algorithm = {key: 'yolo11n_det', base_model: 'yolo11n.pt'};

  const result = buildTrainingEngineParameters({draft, target, algorithm});

  assert.equal(result.batch, 8);
  assert.equal(typeof result.batch, 'number');
  assert.equal(result.workers, 0);
  assert.equal(typeof result.workers, 'number');
});

test('training submit rejects non-integer strict parameters before POST', () => {
  const draft = {
    resource: {batch: '8.5', workers: '0', device: 'cpu'},
    config: {},
  };
  const target = {id: 'cpu', framework: 'ultralytics', type: 'local'};
  const algorithm = {key: 'yolo11n_det', base_model: 'yolo11n.pt'};

  assert.throws(
    () => buildTrainingEngineParameters({draft, target, algorithm}),
    /Batch必须是整数/,
  );
});

test('backend 422 validation detail exposes the exact failing field', () => {
  const detail = formatTrainingValidationError({
    code: 'VALIDATION_ERROR',
    detail: JSON.stringify([
      {loc: ['body', 'batch'], msg: 'Input should be a valid integer'},
      {loc: ['body', 'workers'], msg: 'Input should be a valid integer'},
    ]),
  });

  assert.match(detail, /batch：Input should be a valid integer/);
  assert.match(detail, /workers：Input should be a valid integer/);
});


test('training create re-reads algorithm truth before opening and training log refresh stays modal-local', () => {
  const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /\/api\/v12\/projects\/\$\{pid\(\)\}\/algorithms\/\$\{encodeURIComponent\(algorithmId\)\}/);
  assert.match(source, /ExternalAlgorithmPlatformRuntime\?\.trainingReadiness\?\.\(algorithmId\)/);
  assert.match(source, /训练算法不存在或已被删除/);
  assert.match(source, /refreshTrainRunCenter429/);
  assert.match(source, /data-train-run-center/);
  assert.match(source, /训练已完成/);
});

test('annotation workbench saves locally without full reload and cleans pointer listeners', () => {
  const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /ann420ConfirmEmpty/);
  assert.match(source, /confirmEmptyAnnotation420/);
  assert.match(source, /annotation_state:boxes\.length\?'annotated':'confirmed_empty'/);
  assert.match(source, /annPointerAbort/);
  assert.doesNotMatch(source, /await Promise\.all\(\[apiRequestAnnotation420\(id\),preload\(image\.url\)\]\)/);
  const focusedSave = source.match(/window\.saveAnn=async\(silent=false,options=\{\}\)=>\{[^\n]+/s)?.[0] || '';
  assert.doesNotMatch(focusedSave, /await loadRelated\(\)/);
});
