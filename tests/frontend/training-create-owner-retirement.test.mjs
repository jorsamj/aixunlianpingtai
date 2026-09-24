import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');
const hydration = await readFile(new URL('../../static/modules/training-create-hydration.js', import.meta.url), 'utf8');
const main = await readFile(new URL('../../static/main.mjs', import.meta.url), 'utf8');

test('training creation uses one canonical app owner instead of start-owner wrapper chains', () => {
  for (const token of [
    'const startAlg414=window.startAlgorithmTraining429;',
    'const baseStartTraining415=window.startAlgorithmTraining429;',
    'const baseStartTraining417=window.startAlgorithmTraining429;',
    'const previousStart=window.startAlgorithmTraining429;',
    'const baseRefreshTraining415=window.refreshTrain429;',
    'const baseRefreshTraining417=window.refreshTrain429;',
    'const baseToggleTrain417=window.toggleTrainImage429;',
    'const baseShowIteration417=window.showIterationBase414;',
    'const baseOpenSettings415=window.openTrainSettings429||window.openTrainSettings428;',
    'const baseOpenSettings417=window.openTrainSettings429;',
    'const _oldSaveTrainSettings429 = window.saveTrainSettings428;',
    'const baseSaveSettings415=window.saveTrainSettings428;',
  ]) assert.equal(app.includes(token), false, token);
  assert.equal((app.match(/window\.startAlgorithmTraining429=/g) || []).length, 1);
  assert.match(app, /window\.openTrainingCreateDialog429=function\(aid\)/);
  assert.match(app, /window\.loadTrainingIterationBase414=async function\(aid\)/);
  assert.match(app, /window\.prepareTrainingExperiment415=function\(\)/);
  assert.match(app, /window\.syncTrainingIteration417=function\(aid\)/);
  assert.match(app, /window\.openTrainingCreateCanonical429=async function\(aid\)/);
  assert.match(app, /window\.startAlgorithmTraining429=window\.openTrainingCreateCanonical429/);
  assert.match(app, /window\.refreshTrain429=function refreshTrainingCreateCanonical429\(\)/);
  assert.match(app, /window\.toggleTrainImage429=function toggleTrainingImageCanonical429\(id\)/);
  assert.match(app, /window\.showIterationBase414=function showTrainingIterationCanonical414\(aid\)/);
  assert.match(app, /window\.openTrainSettings429=function openTrainingSettingsCanonical429\(\)/);
  assert.match(app, /window\.refreshTrainCore429=function\(\)/);
  assert.match(app, /window\.toggleTrainImageCore429=function\(id\)/);
  assert.match(app, /window\.showIterationBaseCore414=function\(aid\)/);
  assert.match(app, /window\.saveTrainSettingsCore428=function\(\)/);
  assert.match(app, /window\.saveTrainSettings428=function saveTrainingSettingsCanonical428\(\)/);
});

test('hydration runtime depends on the canonical form owner explicitly', () => {
  assert.equal(hydration.includes('const previousStart = window.startAlgorithmTraining429;'), false);
  assert.match(hydration, /openTrainingForm/);
  assert.match(hydration, /const openForm = openTrainingForm \|\| window\.openTrainingCreateCanonical429/);
  assert.match(main, /openTrainingForm: window\.openTrainingCreateCanonical429/);
});

test('external training preflight is owned by hydration instead of duplicated in app canonical owner', () => {
  const start = app.indexOf('window.openTrainingCreateCanonical429=async function(aid)');
  const end = app.indexOf('\n  };', start);
  assert.ok(start >= 0 && end > start);
  const owner = app.slice(start, end);
  assert.doesNotMatch(owner, /training-preflight/);
  assert.doesNotMatch(owner, /preflightTraining/);
  assert.doesNotMatch(owner, /training_options/);
});


test('training create canonical owner uses deterministic repaint points instead of delayed repaint cascades', () => {
  const openStart = app.indexOf('window.openTrainingCreateCanonical429=async function(aid)');
  const openEnd = app.indexOf('\n  };', openStart);
  assert.ok(openStart >= 0 && openEnd > openStart);
  const openOwner = app.slice(openStart, openEnd);
  assert.doesNotMatch(openOwner, /\[40,140,340,650\]/);
  assert.doesNotMatch(openOwner, /setTimeout\(renderSplit/);

  const dialogStart = app.indexOf('window.openTrainingCreateDialog429=function(aid)');
  const dialogEnd = app.indexOf('\n  window.openTrainingCreateDialog423=', dialogStart);
  assert.ok(dialogStart >= 0 && dialogEnd > dialogStart);
  const dialogOwner = app.slice(dialogStart, dialogEnd);
  assert.match(dialogOwner, /trainTarget429\(\)\};/);
  assert.doesNotMatch(dialogOwner, /setTimeout\(trainTarget429/);

  const iterationStart = app.indexOf('window.loadTrainingIterationBase414=async function(aid)');
  const iterationEnd = app.indexOf('\n  window.showIterationBaseCore414=', iterationStart);
  const iterationOwner = app.slice(iterationStart, iterationEnd);
  assert.match(iterationOwner, /showIterationBase414\(aid\);/);
  assert.doesNotMatch(iterationOwner, /setTimeout\(\(\)=>showIterationBase414/);

  const syncStart = app.indexOf('window.syncTrainingIteration417=function(aid)');
  const syncEnd = app.indexOf('\n  window.decorateTrainSettingsIteration417=', syncStart);
  const syncOwner = app.slice(syncStart, syncEnd);
  assert.doesNotMatch(syncOwner, /\[30,180\]/);


  const experimentStart = app.indexOf('window.prepareTrainingExperiment415=function()');
  const experimentEnd = app.indexOf('\n  window.decorateTrainingExperiment415=', experimentStart);
  assert.ok(experimentStart >= 0 && experimentEnd > experimentStart);
  assert.doesNotMatch(app.slice(experimentStart, experimentEnd), /setTimeout/);

  const settingsStart = app.indexOf('window.openTrainSettings429=function openTrainingSettingsCanonical429()');
  const settingsEnd = app.indexOf('\n\n/* Durable v3 exact-material training split UI.', settingsStart);
  assert.ok(settingsStart >= 0 && settingsEnd > settingsStart);
  const settingsOwner = app.slice(settingsStart, settingsEnd);
  assert.doesNotMatch(settingsOwner, /setTimeout/);
  assert.match(settingsOwner, /decorateTrainSettingsAdvanced415/);
  assert.match(settingsOwner, /decorateTrainSettingsIteration417/);

  const benchmarkStart = app.indexOf('async function loadTrainingBenchmarkReuseV1(aid,{paint=true}={})');
  const benchmarkEnd = app.indexOf('\n  const TRAINING_DEVICE_CACHE_TTL_MS=', benchmarkStart);
  assert.ok(benchmarkStart >= 0 && benchmarkEnd > benchmarkStart);
  assert.match(app.slice(benchmarkStart, benchmarkEnd), /if\(paint\)renderSplit\(\)/);

  assert.match(openOwner, /applyDevices\(cachedDevices,\{persist:false,paint:false\}\)/);
  assert.match(openOwner, /loadTrainingBenchmarkReuseV1\(algorithmId,\{paint:false\}\)/);
  assert.equal((openOwner.match(/renderSplit\(\);/g) || []).length, 1);
});
