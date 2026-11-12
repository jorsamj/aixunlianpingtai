import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const resources = readFileSync(new URL('../../static/modules/resource-discovery.js', import.meta.url), 'utf8');
const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const backend = readFileSync(new URL('../../app.py', import.meta.url), 'utf8');
const controlPlane = readFileSync(new URL('../../platform_core/remote_training_tasks.py', import.meta.url), 'utf8');

test('training resources allow explicit trusted .pt preload into the existing durable model directory', () => {
  assert.match(resources,/data-rd-prepared-models/);
  assert.match(resources,/preparedMotherModels\(\)/);
  assert.match(resources,/uploadResourceMotherModel\(this\)/);
  assert.match(resources,/\/api\/v63\/base-models\/upload/);
  assert.match(backend,/root = DATA_DIR \/ "models"/);
  assert.match(backend,/sha256_file\(path\)/);
  assert.match(backend,/os\.replace\(temp, path\)/);
});

test('mother-model verifier displays distinct environment, interrupted and model errors without extra modal owners', () => {
  assert.match(resources,/verificationEnvironment=assets\?\.verification_environment/);
  assert.match(resources,/PT_SANDBOX_NOT_CONFIGURED/);
  assert.match(resources,/PT_VERIFY_DEPENDENCY_MISSING/);
  assert.match(resources,/PT_VERIFY_INTERRUPTED/);
  assert.match(resources,/校验运行环境已配置/);
  assert.match(resources,/校验已中断/);
  assert.match(backend,/_public_mother_model_asset_status\(item\)/);
  assert.match(backend,/_mother_model_verifier_environment\(\)/);
  assert.doesNotMatch(resources,/window\.openMotherModelVerifierModal\s*=/);
});

test('first train task selects an actually prepared model; iteration remains version-owned', () => {
  assert.match(app,/id="tr429MotherModel"/);
  assert.match(app,/selectTrainingMotherModel429/);
  assert.match(app,/base\.hasPrevious/);
  assert.match(app,/model_status\|\|''\)\.toUpperCase\(\)==='FOUND'/);
  assert.match(backend,/payload\.model = prepared_model/);
  assert.match(backend,/raw_request\["model"\] = prepared_model/);
});

test('remote scheduler offers local preinstalled weights not downloadable official names', () => {
  assert.match(backend,/scheduler_models = _prepared_mother_model_rows\(\)/);
  assert.match(controlPlane,/REMOTE_TRAINING_BASE_MODEL_NOT_PREPARED/);
  assert.match(controlPlane,/self\._stage_direct_model\(/);
});

test('training resource rehydration delegates inherited base-model display to the single renderer', () => {
  const start = app.indexOf('window.applyTrainingCreationResources=function()');
  const end = app.indexOf('function eligibleFor(role)', start);
  assert.ok(start !== -1 && end > start);
  const resourceRefresh = app.slice(start, end);
  assert.match(resourceRefresh, /window\.syncTrainingMotherModel429\(\)/);
  assert.doesNotMatch(resourceRefresh, /modelSelect\.value\s*=/);
  assert.match(app, /window\.syncTrainingMotherModel429=syncMotherModel429/);
  assert.match(app, /select\.innerHTML='<option value="">从当前有效算法版本的 best\.pt 继续训练<\/option>'/);
});

test('unverified uploaded weights remain visible but disabled in first-training model picker', () => {
  assert.match(app, /window\.visibleTrainingTargets429=visibleTargets429/);
  assert.match(app, /m\.source==='preinstalled'/);
  assert.match(app, /id="tr429MotherModelHint"/);
  assert.match(app, /pending\.map\(m=>`<option[^`]*disabled>/);
  assert.match(app, /motherModelReason429\(pending\[0\]\)/);
  assert.match(resources, /官方可信 YOLO11n\/s\/m 权重按发布 SHA256 自动校验/);
});
