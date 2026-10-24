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
