import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('deployment conversion UI keeps queued and waiting-resource tasks live and visible', () => {
  assert.match(source, /queued:'排队中'/);
  assert.match(source, /waiting_resource:'等待资源'/);
  assert.match(source, /\['queued','waiting_resource','running'\]\.includes\(j\.status\)/);
  assert.match(source, /\['queued','waiting_resource'\]\.includes\(j\.status\)/);
  assert.match(source, /资源队列第 \$\{Number\(j\.resource_queue_position\|\|0\)\|\|'-'\} 位/);
  assert.match(source, /j\.status==='waiting_resource'&&j\.resource_wait_reason/);
  assert.match(source, /j\.worker_id\?` · Worker/);
});


test('version conversion progress is keyed and patches live rows in place', () => {
  const start = source.indexOf('function historyHtml428(aid,vid,r)');
  const end = source.indexOf('\n  function scheduleVersionConversionPoll428', start);
  assert.ok(start >= 0 && end > start);
  const finalLayer = source.slice(start, end);
  assert.match(finalLayer, /data-conversion-job-id=/);
  assert.match(finalLayer, /data-conversion-progress data-progress=/);
  assert.match(finalLayer, /function patchVersionConversionLive428\(aid,vid,r\)/);
  assert.match(finalLayer, /card\.dataset\.conversionStatus=next/);
  assert.match(finalLayer, /bar\.dataset\.progress=progress\.toFixed\(2\)/);
  assert.doesNotMatch(finalLayer, /deployJobList/);
});


test('version conversion polling is PollRegistry-owned and scoped to the current page', () => {
  const start = source.indexOf('function scheduleVersionConversionPoll428(aid,vid,r)');
  const end = source.indexOf('\n  window.openVersionConvert428=', start);
  assert.ok(start >= 0 && end > start);
  const finalPoll = source.slice(start, end);
  assert.match(finalPoll, /const registry=window\.PollRegistryRuntime/);
  assert.match(finalPoll, /registry\.startTimeout\(key,String\(state\.page\|\|'算法列表'\)/);
  assert.match(finalPoll, /registry\?\.clear\?\.\(key\)/);
  assert.match(finalPoll, /versionConversionRoot428\(aid,vid\)/);
  assert.doesNotMatch(finalPoll, /setTimeout\(/);
});
