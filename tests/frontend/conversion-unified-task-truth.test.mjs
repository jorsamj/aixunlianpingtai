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


test('deployment conversion progress is keyed and compositor-friendly', () => {
  const start = source.lastIndexOf('function jobRow(j)');
  const end = source.indexOf('window.renderDeployCenter', start);
  assert.ok(start >= 0 && end > start);
  const finalLayer = source.slice(start, end);
  assert.match(finalLayer, /data-deploy-job-id=/);
  assert.match(finalLayer, /function patchDeployJobNode\(current,next\)/);
  assert.match(finalLayer, /currentBar\.style\.transform=nextBar\.style\.transform/);
  assert.match(finalLayer, /data-progress=/);
  assert.match(finalLayer, /window\.refreshDeployJobsV39=pollDeployJobs/);
  assert.doesNotMatch(finalLayer, /deployJobList'\);if\(!box\)return;box\.innerHTML=/);
  assert.doesNotMatch(finalLayer, /progress-bar"><i style="width:/);
});
