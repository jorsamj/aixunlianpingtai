import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('legacy training settings compose explicit cores instead of previous-owner capture', () => {
  for (const token of [
    'const baseCfg427=window.cfg425;',
    'const baseOpenSettings427=window.openTrainSettings425;',
    'const baseSaveSettings427=window.saveTrainSettings425;',
  ]) assert.equal(app.includes(token), false, token);
  assert.match(app, /window\.cfg425Core=cfg425/);
  assert.match(app, /window\.cfg425=function cfgCanonical427\(\)/);
  assert.match(app, /window\.openTrainSettingsCore425=function\(\)/);
  assert.match(app, /window\.openTrainSettings425=function openTrainSettingsCanonical427\(\)/);
  assert.match(app, /window\.saveTrainSettingsCore425=function\(\)/);
  assert.match(app, /window\.saveTrainSettings425=function saveTrainSettingsCanonical427\(\)/);
});

test('training report has an explicit core and one canonical compatibility owner', () => {
  assert.equal(app.includes('const report425Base428=window.trainingReport425;'), false);
  assert.match(app, /window\.trainingReportCore425=async function\(id\)/);
  assert.match(app, /window\.trainingReport425=window\.trainingReport424=async function trainingReportCanonical428\(id\)/);
});

test('training material picker has one public owner plus one decorator', () => {
  assert.equal(app.includes('const baseOpenTrainPicker412=window.openTrainPicker429;'), false);
  assert.equal((app.match(/window\.openTrainPicker429=/g) || []).length, 1);
  assert.match(app, /window\.openTrainPickerCore429=function\(\)/);
  assert.match(app, /window\.decorateTrainPickerBulk412=function\(\)/);
  assert.match(app, /window\.openTrainPicker429=function openTrainPickerCanonical412\(\)/);
});

test('legacy training run center is fully retired in favor of TrainingRecoveryRuntime', () => {
  for (const token of [
    'function trainRunCenter429(',
    'function replaceTrainRunCenter429(',
    'async function readTrainRunCenter429(',
    'window.showTrainLog423=async function',
    'window.refreshTrainRunCenter429=async function',
  ]) assert.equal(app.includes(token), false, token);
  assert.match(app, /Training detail\/log rendering is exclusively owned by TrainingRecoveryRuntime/);
});

