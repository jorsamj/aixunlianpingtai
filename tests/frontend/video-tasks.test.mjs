import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

import {
  isActiveVideoTask,
  normalizeVideoTask,
  videoTaskFormValues,
} from '../../static/modules/video-tasks.js';


function finalVideoRowRenderer() {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const start = source.indexOf('function videoTaskRow424(t)');
  const end = source.indexOf('function patchVideoRows424()', start);
  assert.ok(start >= 0 && end > start, 'final v424 video row renderer must exist');
  const definition = source.slice(start, end);
  return new Function(
    'taskStatus424',
    'esc',
    'splitName424',
    'videoCore424',
    `${definition}; return videoTaskRow424;`,
  )(
    t => `<span>${t.statusText || t.status}</span>`,
    value => String(value ?? ''),
    value => String(value ?? ''),
    () => ({isActiveVideoTask}),
  );
}


test('video form supports interval fps and exact fixed count', () => {
  assert.deepEqual(videoTaskFormValues('interval_seconds', {intervalSeconds: 1.5, maxFrames: 100}), {
    mode: 'interval_seconds', interval_seconds: 1.5, max_frames: 100,
  });
  assert.deepEqual(videoTaskFormValues('fps', {extractFps: 2}), {
    mode: 'fps', extract_fps: 2,
  });
  assert.deepEqual(videoTaskFormValues('fixed_count', {fixedCount: 37}), {
    mode: 'fixed_count', fixed_count: 37,
  });
});


test('persistent uppercase statuses drive polling and result counts', () => {
  assert.equal(isActiveVideoTask({status: 'QUEUED'}), true);
  assert.equal(isActiveVideoTask({status: 'RUNNING'}), true);
  assert.equal(isActiveVideoTask({status: 'SUCCEEDED'}), false);
  const task = normalizeVideoTask({
    id: 'v1', status: 'SUCCEEDED', result: {extracted_frames: 8},
    video_name: 'demo.mp4', mode: 'fixed_count', fixed_count: 8,
  });
  assert.equal(task.extractedFrames, 8);
  assert.equal(task.samplingText, '固定抽取 8 帧');
  assert.equal(task.statusText, '已完成');
});


test('queued video row preserves durable resource queue position', () => {
  const task = normalizeVideoTask({
    id: 'vq1', status: 'QUEUED', progress: 0,
    video_name: 'queued.mp4', mode: 'fixed_count', fixed_count: 12,
    resource_queue_position: 3,
  });
  assert.equal(task.runtimeText, '资源队列第 3 位');
  const html = finalVideoRowRenderer()(task);
  assert.match(html, /资源队列第 3 位/);
});


test('waiting-resource video row preserves durable wait reason', () => {
  const task = normalizeVideoTask({
    id: 'vq2', status: 'QUEUED', stage: 'waiting_resource', progress: 0,
    video_name: 'waiting.mp4', mode: 'fixed_count', fixed_count: 12,
    resource_queue_position: 2,
    resource_wait_reason: 'GPU 资源占用中',
  });
  assert.equal(task.runtimeText, '资源队列第 2 位 · GPU 资源占用中');
  const html = finalVideoRowRenderer()(task);
  assert.match(html, /资源队列第 2 位/);
  assert.match(html, /GPU 资源占用中/);
});


test('final video page exposes fixed count and polls by row patching', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /option value="fixed_count"/);
  assert.match(source, /refreshVideo424Delta/);
  assert.doesNotMatch(source, /setTimeout\(\(\)=>\{if\(state\.page==='\u89c6频切帧'\)renderVideo424\(\)/);
});
