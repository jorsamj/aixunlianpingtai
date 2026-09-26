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
  assert.match(progress, /data-clean-progress-bar style="transform:scaleX\(0\)/);
  assert.match(progress, /bar\.style\.transform=.*scaleX/);
  assert.doesNotMatch(progress, /bar\.style\.width/);
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

test('clean scheduling keeps capability-filtered node affinity and safe preemption explicit', () => {
  const runtime = {
    agent_available: true,
    eligible_nodes: [
      {node_id: 'idle-clean', idle: true, preemptible: false},
      {node_id: 'busy-clean', idle: false, preemptible: true},
      {node_id: 'busy-unsafe', idle: false, preemptible: false},
    ],
  };
  assert.deepEqual(
    cleaning.cleanSchedulingRequest({executionMode: 'agent', schedulingMode: 'auto'}, runtime),
    {scheduling_mode: 'auto', target_node_id: '', queue_policy: 'normal'},
  );
  assert.deepEqual(
    cleaning.cleanSchedulingRequest({
      executionMode: 'agent', schedulingMode: 'node', nodeId: 'busy-clean', queuePolicy: 'front',
    }, runtime),
    {scheduling_mode: 'node', target_node_id: 'busy-clean', queue_policy: 'front'},
  );
  assert.deepEqual(
    cleaning.cleanSchedulingRequest({
      executionMode: 'agent', schedulingMode: 'node', nodeId: 'busy-clean', queuePolicy: 'preempt',
    }, runtime),
    {scheduling_mode: 'node', target_node_id: 'busy-clean', queue_policy: 'preempt'},
  );
  assert.deepEqual(
    cleaning.cleanSchedulingRequest({
      executionMode: 'agent', schedulingMode: 'node', nodeId: 'idle-clean', queuePolicy: 'preempt',
    }, runtime),
    {scheduling_mode: 'node', target_node_id: 'idle-clean', queue_policy: 'normal'},
  );
  assert.throws(
    () => cleaning.cleanSchedulingRequest({
      executionMode: 'agent', schedulingMode: 'node', nodeId: 'busy-unsafe', queuePolicy: 'preempt',
    }, runtime),
    /不支持安全抢占/,
  );
  assert.throws(
    () => cleaning.cleanSchedulingRequest({
      executionMode: 'agent', schedulingMode: 'node', nodeId: 'not-clean-capable', queuePolicy: 'normal',
    }, runtime),
    /请选择当前在线/,
  );
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


test('clean scope choices use formal annotation states and selected IDs explicitly', () => {
  const choices = cleaning.cleanScopeChoices({selectedCount: 2});
  assert.deepEqual(
    choices.map(item => item.value),
    ['all', 'annotated', 'unannotated', 'confirmed_empty', 'selected'],
  );
  assert.equal(choices.find(item => item.value === 'selected').available, true);
  assert.deepEqual(
    cleaning.cleanScopeRequest('annotated', ['should-not-leak']),
    {clean_scope: 'annotated', image_ids: []},
  );
  assert.deepEqual(
    cleaning.cleanScopeRequest('selected', ['a', 'a', 'b']),
    {clean_scope: 'selected', image_ids: ['a', 'b']},
  );
  assert.equal(cleaning.cleanScopeSupportsAnnotationAudit('all'), true);
  assert.equal(cleaning.cleanScopeSupportsAnnotationAudit('annotated'), true);
  assert.equal(cleaning.cleanScopeSupportsAnnotationAudit('selected'), true);
  assert.equal(cleaning.cleanScopeSupportsAnnotationAudit('unannotated'), false);
  assert.equal(cleaning.cleanScopeSupportsAnnotationAudit('confirmed_empty'), false);
  assert.throws(() => cleaning.cleanScopeRequest('selected', []), /没有选中的图片/);

  const forced = cleaning.cleanScopeChoices({selectedCount: 1, forcedSelected: true});
  assert.equal(forced.find(item => item.value === 'selected').available, true);
  assert.equal(forced.find(item => item.value === 'all').available, false);
  assert.throws(
    () => cleaning.cleanScopeRequest('all', ['a'], {forcedSelected: true}),
    /锁定为当前选中图片/,
  );
});

test('cleaning UI keeps scope preflight and result review on canonical owners', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.equal((source.match(/window\.createClean427=/g) || []).length, 1);
  assert.equal((source.match(/window\.reviewClean427=/g) || []).length, 1);
  assert.match(source, /cleanScopeRequest427/);
  assert.match(source, /clean_scope/);
  assert.match(source, /annotation_provenance/);
  assert.match(source, /annotation_audit/);
  assert.match(source, /标注质量 · 逐图复核/);
  assert.match(source, /setCleanQualityTab429/);
  assert.match(source, /loadMoreCleanAudit429/);
  assert.match(source, /related_image_id/);
  assert.match(source, /cleanImageIssueText429/);
  assert.match(source, /CLEAN_IMAGE_REVIEW_BATCH_429=60/);
  assert.match(source, /setCleanImageReviewFilter429/);
  assert.match(source, /setCleanImageIssueFilter429/);
  assert.match(source, /loadMoreCleanImageReview429/);
  assert.match(source, /cleanImageReviewItems429/);
  assert.match(source, /cleanSchedulingModeChanged427/);
  assert.match(source, /cleanTargetNodeChanged427/);
  assert.match(source, /cleanQueuePolicyChanged427/);
  assert.match(source, /队首等待/);
  assert.match(source, /安全抢占/);
  assert.match(source, /当前任务不支持安全让出节点/);
  assert.match(source, /审计结果/);
  assert.match(source, /window\.reviewClean427=id=>window\.cleanDetail429/);
  assert.doesNotMatch(source, /window\.reviewClean427=async function/);
});


test('canonical main runtime exposes cleaning scope helpers with fresh module cache keys', () => {
  const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
  const index = fs.readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
  assert.match(main, /cleanSchedulingRequest, cleanScopeChoices, cleanScopeRequest, cleanScopeSupportsAnnotationAudit, cleanTaskView/);
  assert.match(
    main,
    /cleaning: \{applyCleanConfirmation, cleanExecutionChoices, cleanExecutionMode, cleanSchedulingRequest, cleanScopeChoices, cleanScopeRequest, cleanScopeSupportsAnnotationAudit, cleanTaskView, isActiveCleanTask\}/,
  );
  assert.match(main, /cleaning\.js\?v=422568/);
  assert.match(index, /styles\.css\?v=42\.24\.41/);
  assert.match(index, /app\.js\?v=42\.25\.261/);
  assert.match(index, /main\.mjs\?v=42\.25\.249/);
});
