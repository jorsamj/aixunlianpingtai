import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('detection public actions have one final owner each', () => {
  for (const [name, pattern] of [
    ['predict', /window\.predict\s*=/g],
    ['benchPredictOne', /window\.benchPredictOne\s*=/g],
    ['benchSingle', /window\.benchSingle\s*=/g],
    ['benchCompare', /window\.benchCompare\s*=/g],
    ['renderTest', /window\.renderTest\s*=/g],
  ]) assert.equal((app.match(pattern) || []).length, 1, name);
});

test('feedback predictor delegates to latest pre-feedback detection core', () => {
  assert.match(app, /window\.predictCore30 = async function\(\)/);
  assert.match(app, /window\.predict=async function predictCanonicalFeedback63\(\)/);
  const start=app.indexOf('window.predict=async function predictCanonicalFeedback63()');
  const end=app.indexOf('\n  };',start);
  const block=app.slice(start,end);
  assert.match(block, /window\.predictCore30\?\.apply\(this,arguments\)/);
  assert.doesNotMatch(block, /predictCore12/);
});

test('v61 owns deployment-aware benchmark execution', () => {
  assert.match(app, /window\.benchPredictOne=async function\(selectId,file,conf,batchMeta=null\)/);
  assert.match(app, /form\.append\('detection_batch_id',String\(batchMeta\.batch_id\)\)/);
  assert.match(app, /form\.append\('detection_side',String\(batchMeta\.side\|\|''\)\)/);
  assert.equal(app.includes('try { benchPredictOne = window.benchPredictOne; }'), false);
  assert.match(app, /renderTest=window\.renderTest=function renderTestCanonical63\(\)/);
});
