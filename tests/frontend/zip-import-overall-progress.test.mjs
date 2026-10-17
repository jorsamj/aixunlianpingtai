import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {overallZipProgress, zipPhaseDetail} from '../../static/modules/zip-import-runtime.js';

const runtime = readFileSync(new URL('../../static/modules/zip-import-runtime.js', import.meta.url), 'utf8');

test('ZIP browser consumes server-owned overall progress and does not remap lifecycle status', () => {
  assert.equal(overallZipProgress({
    status:'uploading',
    progress:17,
    zip_display_progress:{overall_progress:12.5},
  }),12.5);
  assert.equal(overallZipProgress({status:'merging',progress:36}),36);
  assert.equal(overallZipProgress({status:'validating',progress:41}),41);
  assert.equal(overallZipProgress({status:'running',progress:73}),73);
  assert.equal(overallZipProgress({status:'done',progress:100}),100);
});

test('ZIP phase detail preserves unknown percent and ETA instead of coercing null to zero', () => {
  assert.deepEqual(zipPhaseDetail({
    zip_display_progress:{
      phase:'SCAN',
      phase_progress:null,
      completed:null,
      total:null,
      eta_seconds:null,
    },
  }),{
    text:'',
    phaseProgress:null,
    etaSeconds:null,
  });
  assert.deepEqual(zipPhaseDetail({
    zip_display_progress:{
      phase:'EXTRACT',
      phase_progress:25,
      completed:25,
      total:100,
      unit:'files',
      eta_seconds:12,
    },
  }),{
    text:'阶段 25% · 25 / 100 文件 · 预计剩余 12 秒',
    phaseProgress:25,
    etaSeconds:12,
  });
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

test('browser upload reports only real transfer percent and delegates later phases to server', () => {
  assert.match(runtime,/const resumedUpload=Math\.max\(0,Math\.min\(100,Number\(session\.upload_progress\)\|\|0\)\)/);
  assert.match(runtime,/uploading=\{\.\.\.uploading,progress:networkPercent/);
  assert.match(runtime,/status:'MERGING',progress:null/);
  assert.match(runtime,/仅显示当前网络上传的真实进度/);
  assert.doesNotMatch(runtime,/upload\*3\.5/);
  assert.doesNotMatch(runtime,/e\.ratio\*350/);
  assert.doesNotMatch(runtime,/3800\+backend/);
  assert.doesNotMatch(runtime,/progress:36,message:phase\.message/);
});

test('server canonical ZIP display projection remains the first progress source', () => {
  const job={
    status:'running',
    progress:5,
    zip_display_progress:{
      phase:'EXTRACT',
      phase_label:'解压导入范围',
      phase_progress:25,
      overall_progress:53,
      completed:25,
      total:100,
      unit:'files',
      eta_seconds:12,
    },
  };
  assert.equal(overallZipProgress(job),53);
  assert.equal(zipPhaseDetail(job).text,'阶段 25% · 25 / 100 文件 · 预计剩余 12 秒');
  const start=runtime.indexOf('export function overallZipProgress(job)');
  const end=runtime.indexOf('export function zipPhaseDetail(job)',start);
  const block=runtime.slice(start,end);
  assert.match(block,/zipDisplayProgress\(job\)/);
  assert.doesNotMatch(block,/s==='uploading'/);
  assert.doesNotMatch(block,/s==='merging'/);
  assert.doesNotMatch(block,/s==='validating'/);
});
