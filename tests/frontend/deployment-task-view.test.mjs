import test from 'node:test';
import assert from 'node:assert/strict';
import {deploymentTaskView} from '../../static/modules/deployment-tests.js';


test('deployment task view preserves durable waiting-resource truth', () => {
  const view = deploymentTaskView({
    status: 'WAITING_RESOURCE',
    status_text: '等待资源',
    progress_percent: 17.5,
    phase: 'resource_waiting',
    resource_queue_position: 3,
    resource_wait_reason: 'DEPLOYMENT_RUNTIME_BUSY',
  });
  assert.equal(view.status, 'WAITING_RESOURCE');
  assert.equal(view.statusText, '等待资源');
  assert.equal(view.percent, 17.5);
  assert.equal(view.phase, 'resource_waiting');
  assert.equal(view.runtimeText, '资源队列第 3 位 · DEPLOYMENT_RUNTIME_BUSY');
  assert.equal(view.active, true);
});


test('deployment task view preserves worker and server progress while running', () => {
  const view = deploymentTaskView({
    status: 'RUNNING',
    progress_percent: 63,
    phase: 'inference',
    worker_id: 'deployment-worker-1',
    current_item: 'sample.jpg',
  });
  assert.equal(view.statusText, '测试中');
  assert.equal(view.percent, 63);
  assert.equal(view.runtimeText, 'Worker deployment-worker-1 · sample.jpg');
  assert.equal(view.active, true);
});
