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


test('external ChangLian training re-reads algorithm truth in hydration before canonical form open and training log refresh stays modal-local', () => {
  const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const hydration = readFileSync(new URL('../../static/modules/training-create-hydration.js', import.meta.url), 'utf8');
  const main = readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
  const externalRuntime = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  assert.match(main, /preflight: algorithmId => externalAlgorithmPlatformRuntime\.preflightTraining/);
  assert.match(main, /openTrainingForm: window\.openTrainingCreateCanonical429/);
  assert.match(hydration, /externalChangLian/);
  assert.match(hydration, /externalChangLian && typeof preflight === 'function' \? preflight\(aid\)/);
  assert.match(externalRuntime, /training-preflight\?project_id=/);
  assert.match(externalRuntime, /algorithm_id=\$\{encodeURIComponent\(id\)\}/);
  const ownerStart = source.indexOf('window.openTrainingCreateCanonical429=async function(aid)');
  const ownerEnd = source.indexOf('\n  };', ownerStart);
  const owner = source.slice(ownerStart, ownerEnd);
  assert.ok(ownerStart >= 0 && ownerEnd > ownerStart);
  assert.doesNotMatch(owner, /preflightTraining|training-preflight/);
  assert.match(owner, /训练算法不存在或已被删除/);
  assert.match(source, /refreshTrainRunCenter429/);
  assert.match(source, /data-train-run-center/);
  assert.match(source, /训练已完成/);
});

test('legacy training shell uses same-scope status helper before final visibility runtime takes ownership', () => {
  const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const start = source.indexOf('function trainRows428(rows){');
  const end = source.indexOf('window.renderTraining425=window.renderTraining424=window.renderTraining423', start);
  assert.ok(start >= 0 && end > start);
  const block = source.slice(start, end);
  assert.match(block, /statusText428\(j\.status\)/);
  assert.doesNotMatch(block, /status429\(/);
});

test('annotation workbench has one save owner, explicit empty confirmation, and one manual advance', () => {
  const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /function ensureShell\(\)\{[\s\S]*?ann420-stable[\s\S]*?ann420ConfirmEmpty[\s\S]*?确认无目标/);
  assert.match(source, /confirmEmptyAnnotation420=\(\)=>window\.saveAnn\(false,\{confirmEmpty:true\}\)/);
  assert.equal((source.match(/window\.saveAnn=/g) || []).length, 1);
  assert.equal(source.includes('const baseSaveAnnotation417=window.saveAnn;'), false);
  assert.equal(source.includes('const saveAnn411=window.saveAnn;'), false);
  assert.equal(source.includes('const previousSave=window.saveAnn;'), false);
  const coreStart = source.indexOf('window.saveAnnotationCore420=async function(silent=false,options={})');
  const coreEnd = source.indexOf('// ---------- dataset: labels strictly from label library ----------', coreStart);
  const core = source.slice(coreStart, coreEnd);
  assert.ok(coreStart >= 0 && coreEnd > coreStart);
  assert.match(core, /confirmEmpty=options\?\.confirmEmpty===true/);
  assert.match(core, /annotation_state:boxes\.length\?'annotated':'confirmed_empty'/);
  assert.match(core, /patchMaterialCard412\(state\.activeImage\)/);
  assert.doesNotMatch(core, /await loadRelated\(\)/);
  const stableStart = source.lastIndexOf('Stable single-instance manual\/batch annotation workbench');
  const stableEnd = source.indexOf('Persistent v60 AI annotation UI', stableStart);
  const stable = source.slice(stableStart, stableEnd);
  assert.match(stable, /window\.saveAnn=async function saveAnnotationCanonical420\(silent=false,options=\{\}\)/);
  assert.match(stable, /window\.saveAnnotationCore420\?\.\(silent,options\)/);
  assert.equal((stable.match(/annotationWorkbench\?\.open\(ids\[at\+1\]\)/g) || []).length, 1);
  assert.doesNotMatch(stable, /setTimeout\(\(\)=>goAnnotation417/);
  assert.equal(source.includes('const previousMarkDirty=window.markDirty;'), false);
  assert.match(source, /window\.markDirty=function markAnnotationDirtyCanonical420\(\)/);
  assert.doesNotMatch(source, /await Promise\.all\(\[apiRequestAnnotation420\(id\),preload\(image\.url\)\]\)/);
});

test('dashboard training task success rate distinguishes no-data and successful status aliases in final owners', () => {
  const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const dashboardStart = source.indexOf('function dashboardData422()');
  const dashboardEnd = source.indexOf('// -------- Dashboard --------', dashboardStart);
  const dashboard = source.slice(dashboardStart, dashboardEnd);
  assert.match(dashboard, /'done','finished','completed','succeeded','success'/);
  assert.match(dashboard, /String\(j\.status\|\|''\)\.toLowerCase\(\)/);
  assert.match(dashboard, /endedStatuses422=new Set\(\[\.\.\.successStatuses422,'failed','stopped','cancelled','canceled'\]\)/);
  assert.match(dashboard, /successRate=endedJobs\.length\?doneJobs\.length\/endedJobs\.length:null/);
  const renderDashboardEnd = source.indexOf('function renderDashboard422()', dashboardEnd);
  const renderDashboard = source.slice(renderDashboardEnd, source.indexOf('function ', renderDashboardEnd + 20));
  assert.match(renderDashboard, /其他已结束/);
  assert.doesNotMatch(dashboard, /successRate=.*:0/);

  const legacyDashboardStart = source.indexOf('function dashboardData42()');
  const legacyDashboardEnd = source.indexOf('function dashPct42', legacyDashboardStart);
  const legacyDashboard = source.slice(legacyDashboardStart, legacyDashboardEnd);
  assert.match(legacyDashboard, /endedStatuses42=new Set\(\[\.\.\.successStatuses42,'failed','stopped','cancelled','canceled'\]\)/);
  assert.match(legacyDashboard, /successRate=endedJobs\.length\?doneJobs\.length\/endedJobs\.length:null/);
  assert.match(legacyDashboard, /ended:endedJobs\.length/);

  const qualityStart = source.indexOf('function qualityHtml411(r){');
  const qualityEnd = source.indexOf('window.renderQualityCenter424=async function()', qualityStart);
  const quality = source.slice(qualityStart, qualityEnd);
  assert.ok(qualityStart >= 0 && qualityEnd > qualityStart);
  assert.match(quality, /a\.train_success_rate==null\?'—'/);
  assert.match(quality, /暂无已结束训练可统计/);
  assert.doesNotMatch(quality, /train_success_rate\?\?0/);
  const qualityOwnerStart = qualityEnd;
  const qualityOwnerEnd = source.indexOf('window.refreshQuality411=async function()', qualityOwnerStart);
  const qualityOwner = source.slice(qualityOwnerStart, qualityOwnerEnd);
  assert.match(qualityOwner, /qualityHtml411\(cached\.data\)/);
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
