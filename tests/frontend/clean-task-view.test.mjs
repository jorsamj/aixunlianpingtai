import fs from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import * as cleaning from '../../static/modules/cleaning.js';

test('clean task view preserves durable waiting-resource queue truth and server progress', () => {
  assert.equal(typeof cleaning.cleanTaskView, 'function', 'cleaning runtime must expose one durable task view');

  const view = cleaning.cleanTaskView({
    id: 'c1',
    status: 'queued',
    status_text: '等待资源',
    progress: 37.5,
    processed_images: 3,
    total_images: 8,
    flagged_images: 2,
    resource_queue_position: 4,
    resource_queue_position_exact: true,
    resource_wait_reason: '等待 materials 资源',
  });

  assert.equal(view.status, 'queued');
  assert.equal(view.statusText, '等待资源');
  assert.equal(view.percent, 37.5);
  assert.equal(view.processed, 3);
  assert.equal(view.total, 8);
  assert.equal(view.flagged, 2);
  assert.equal(view.progressText, '3/8');
  assert.equal(view.runtimeText, '资源队列第 4 位 · 等待 materials 资源');
  assert.equal(view.active, true);
});

test('clean task view does not present an unproven queue rank as exact position', () => {
  const view = cleaning.cleanTaskView({
    status: 'queued',
    resource_queue_position: 4,
    resource_queue_position_exact: false,
    resource_wait_reason: '等待 materials 资源',
  });
  assert.equal(view.runtimeText, '等待 materials 资源');
});

test('clean task view consumes backend stage and current item without inventing progress', () => {
  assert.equal(typeof cleaning.cleanTaskView, 'function');

  const view = cleaning.cleanTaskView({
    status: 'running',
    status_text: '清洗中',
    progress: 84,
    processed_images: 27,
    total_images: 32,
    phase: 'analyzing',
    current_item: 'image-28',
    worker_id: 'worker-materials-1',
  });

  assert.equal(view.statusText, '清洗中');
  assert.equal(view.percent, 84);
  assert.equal(view.progressText, '27/32');
  assert.equal(view.stage, 'analyzing');
  assert.equal(view.currentItem, 'image-28');
  assert.equal(view.runtimeText, '正在分析图片 · 当前 image-28 · Worker worker-materials-1');
  assert.equal(view.active, true);
});

test('final clean tab consumes the clean task view and PollRegistry lifecycle', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /function cleanTaskView427\(t\)/);
  assert.match(source, /PlatformCore\?\.cleaning\?\.cleanTaskView\?\.\(t\)/);
  assert.match(source, /window\.PollRegistryRuntime\?\.replaceCleanTaskTimer\?\.\(\)/);
  assert.match(source, /function renderCleanOps427\(\)/);
  assert.match(source, /window\.renderCleanOps427=renderCleanOps427/);
  assert.match(source, /id="clean427TaskRows"/);
  assert.match(source, /function patchCleanTaskRows427\(body,tasks\)/);
  assert.match(source, /patchCleanTaskRows427\(body,state\.clean427\|\|\[\]\)/);
  assert.match(source, /data-progress=/);
  assert.match(source, /style="transform:scaleX/);
  assert.doesNotMatch(source, /body\.innerHTML=cleanTaskRows427\(state\.clean427\|\|\[\]\)/);
  assert.doesNotMatch(source, /setTimeout\(\(\)=>\{if\(state\.page==='自动标注及清洗'\)renderOps427\(\)\},2200\)/);
  const progressStart = source.indexOf("const CLEAN_PROGRESS_POLL_PREFIX429='clean-task-progress:'");
  const progressEnd = source.indexOf('\n  async function fetchTask429', progressStart);
  assert.ok(progressStart >= 0 && progressEnd > progressStart);
  const progress = source.slice(progressStart, progressEnd);
  assert.match(progress, /PollRegistryRuntime/);
  assert.match(progress, /registry\.startTimeout\(key,ownerPage/);
  assert.match(progress, /data-clean-progress-task/);
  assert.match(progress, /renderCleanProgress429\(task,id\)/);
  assert.doesNotMatch(progress, /showTaskProgressCore427|setTimeout\(|setInterval\(/);
});


test('clean execution choices are backend-preflight driven and fail closed', () => {
  const localOnly = cleaning.cleanExecutionChoices({
    agent_available: false,
    reason: '本次范围包含不可远程读取的素材存储：default_local',
  });
  assert.equal(localOnly.defaultMode, 'local');
  assert.equal(localOnly.local.available, true);
  assert.equal(localOnly.agent.available, false);
  assert.match(localOnly.agent.detail, /default_local/);
  assert.equal(cleaning.cleanExecutionMode('local', localOnly), 'local');
  assert.throws(
    () => cleaning.cleanExecutionMode('agent', {
      agent_available: false,
      reason: '没有远程清洗节点',
    }),
    /没有远程清洗节点/,
  );

  const remote = {
    agent_available: true,
    eligible_nodes: [{node_id: 'clean-1'}, {node_id: 'clean-2'}],
  };
  assert.equal(cleaning.cleanExecutionChoices(remote).agent.detail, '已检测到 2 个可用节点');
  assert.equal(cleaning.cleanExecutionMode('agent', remote), 'agent');
});

test('remote clean task view maps Agent stages without inventing progress', () => {
  const view = cleaning.cleanTaskView({
    status: 'running',
    status_text: '清洗中',
    execution_mode: 'agent',
    progress: 55,
    processed_images: 5,
    total_images: 10,
    phase: 'REMOTE_CLEANING_ANALYZING',
    current_item: 'img-6',
  });
  assert.equal(view.percent, 55);
  assert.equal(view.runtimeText, '正在远程分析图片 · 当前 img-6');
});
