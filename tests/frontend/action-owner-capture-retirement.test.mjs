import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('detection feedback owner calls an explicit predict core', () => {
  assert.equal(app.includes('const predictBeforeFeedback63=window.predict;'), false);
  assert.equal((app.match(/window\.predict=/g) || []).length, 1);
  assert.match(app, /window\.predictCore12=async\(\)=>/);
  assert.match(app, /window\.predict=async function predictCanonicalFeedback63\(\)/);
  assert.match(app, /window\.predictCore12\?\.apply\(this,arguments\)/);
});

test('iteration resume uses explicit core instead of captured previous owner', () => {
  assert.equal(app.includes('const resumeConfirmedIterationActionFeedback63=window.resumeConfirmedIterationAction429;'), false);
  assert.equal((app.match(/window\.resumeConfirmedIterationAction429=/g) || []).length, 1);
  assert.match(app, /window\.resumeConfirmedIterationActionCore429=async function\(aid,vid\)/);
  assert.match(app, /window\.resumeConfirmedIterationAction429=async function resumeConfirmedIterationActionCanonical63\(aid,vid\)/);
  assert.match(app, /window\.resumeConfirmedIterationActionCore429\?\.\(aid,vid\)/);
});

test('feedback supplement branch stays ahead of generic iteration fallback', () => {
  const start = app.indexOf('window.resumeConfirmedIterationAction429=async function resumeConfirmedIterationActionCanonical63');
  const end = app.indexOf('\n  };', start);
  const block = app.slice(start, end);
  const supplement = block.indexOf("confirmed.action==='supplement_data'");
  const fallback = block.indexOf('resumeConfirmedIterationActionCore429');
  assert.ok(supplement >= 0 && fallback > supplement);
});
