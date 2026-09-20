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
  assert.match(source, /\/api\/v63\/external-algorithm-platform\/training-preflight\?project_id=/);
  assert.match(source, /algorithm_id=\$\{encodeURIComponent\(algorithmId\)\}/);
  assert.match(source, /训练算法不存在或已被删除/);
  assert.match(source, /refreshTrainRunCenter429/);
  assert.match(source, /data-train-run-center/);
  assert.match(source, /训练已完成/);
});

test('annotation workbench saves locally without full reload and cleans pointer listeners', () => {
  const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /function ensureShell\(\)\{[\s\S]*?ann420-stable[\s\S]*?ann420ConfirmEmpty[\s\S]*?确认无目标/);
  assert.match(source, /confirmEmptyAnnotation420/);
  assert.match(source, /annotation_state:boxes\.length\?'annotated':'confirmed_empty'/);
  assert.match(source, /annPointerAbort/);
  assert.doesNotMatch(source, /await Promise\.all\(\[apiRequestAnnotation420\(id\),preload\(image\.url\)\]\)/);
  const focusedSave = source.match(/window\.saveAnn=async\(silent=false,options=\{\}\)=>\{[^\n]+/s)?.[0] || '';
  assert.doesNotMatch(focusedSave, /await loadRelated\(\)/);
});


test('dashboard training task success rate distinguishes no-data and successful status aliases', () => {
  const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /'succeeded','success'/);
  assert.match(source, /训练任务成功率/);
  assert.match(source, /successRate=\(doneJobs\.length\+failed\).*:null/);
  assert.doesNotMatch(source, /successRate=\(doneJobs\.length\+failed\).*:0/);
});


test('algorithm detail modal exposes summary facts without stale failure reason', () => {
  const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const detail = source.match(/window\.viewAlgorithm429=function\(id\)\{[^\n]+/s)?.[0] || '';
  assert.match(detail, /alg429-detail-stats/);
  assert.match(detail, /成功训练/);
  assert.match(detail, /当前版本/);
  assert.match(detail, /当前 mAP50/);
  assert.doesNotMatch(detail, /失败原因/);
});


test('algorithm card keeps training transition states active and empty confirmation appears immediately', () => {
  const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /'starting','running','pausing','paused','resuming','stopping','cancel_requested'/);
  assert.match(source, /pausing:'暂停中'/);
  assert.match(source, /resuming:'恢复中'/);
  assert.match(source, /stopping:'停止中'/);
  const deleteOwner = source.match(/window\.deleteActiveBox=\(\)=>\{[^\n]+/s)?.[0] || '';
  assert.match(deleteOwner, /ann420ConfirmEmpty/);
  assert.match(deleteOwner, /confirmEmpty\.hidden=/);
});
