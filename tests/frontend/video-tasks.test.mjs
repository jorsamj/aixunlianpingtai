import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

import {
  isActiveVideoTask,
  normalizeVideoTask,
  videoTaskFormValues,
} from '../../static/modules/video-tasks.js';


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


test('final video page exposes fixed count and polls by row patching', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /option value="fixed_count"/);
  assert.match(source, /refreshVideo424Delta/);
  assert.doesNotMatch(source, /setTimeout\(\(\)=>\{if\(state\.page==='\u89c6频切帧'\)renderVideo424\(\)/);
});
