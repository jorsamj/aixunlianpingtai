import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {overallZipProgress} from '../../static/modules/zip-import-runtime.js';

const runtime = readFileSync(new URL('../../static/modules/zip-import-runtime.js', import.meta.url), 'utf8');

test('ZIP whole-task progress reserves terminal 100 for done', () => {
  assert.equal(overallZipProgress({status:'uploading',upload_progress:0}),0);
  assert.equal(overallZipProgress({status:'uploading',upload_progress:100}),35);
  assert.equal(overallZipProgress({status:'merging'}),36);
  assert.equal(overallZipProgress({status:'validating'}),37);
  assert.equal(overallZipProgress({status:'queued'}),38);
  assert.equal(overallZipProgress({status:'running',progress:100}),99);
  assert.equal(overallZipProgress({status:'done',progress:100}),100);
});

test('durable ZIP polling is page-scoped and centrally owned', () => {
  const start=runtime.indexOf('function arm(){');
  const end=runtime.indexOf('async function refreshKnown',start);
  const arm=runtime.slice(start,end);
  assert.ok(start>=0&&end>start);
  assert.match(arm,/PollRegistryRuntime\?\.startTimeout/);
  assert.match(arm,/'zip-import-runtime'/);
  assert.match(arm,/activeZipJobs\(jobs\)/);
  assert.doesNotMatch(arm,/while\s*\(true\)/);
});

test('multipart upload distinguishes browser transfer from server merge and import phases', () => {
  assert.match(runtime,/onPhase\(\{stage:'正在合并与校验 ZIP'/);
  assert.match(runtime,/uploading=\{\.\.\.uploading,progress:36,message:phase\.message\}/);
  assert.match(runtime,/status:'MERGING',progress:36/);
  assert.match(runtime,/if\(s==='running'\) return Math\.round\(\(3800\+backend\*61\)\/10\)\/10/);
});
