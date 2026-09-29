import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import '../../static/browser-runtime.js';

import {
  createCanonicalTrainingTaskId,
  isCanonicalTrainingTaskId,
} from '../../static/modules/training-submit.js';

const appSource = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const submitSource = fs.readFileSync(new URL('../../static/modules/training-submit.js', import.meta.url), 'utf8');

test('training modal shows algorithm name and planned task id', () => {
  assert.match(appSource, /<label>算法名称<\/label>/);
  assert.match(appSource, /id="tr429TaskId"/);
  assert.match(appSource, /TrainingSubmitRuntime\?\.createTaskId\?\.\(\)/);
  assert.doesNotMatch(appSource, /Math\.random\(\)\.toString\(16\)/);
});

test('training submit sends the planned task id through the canonical submit owner', () => {
  assert.match(submitSource, /getElementById\('tr429TaskId'\)/);
  assert.match(submitSource, /payload\.task_id = plannedTaskId/);
});

const canonicalTaskId = /^train_[0-9a-f]{16,32}$/;

test('canonical training task id uses randomUUID when available', () => {
  const taskId = createCanonicalTrainingTaskId({
    cryptoSource: {
      randomUUID: () => 'ABCDEF01-2345-6789-ABCD-EF0123456789',
      getRandomValues: () => { throw new Error('must not use getRandomValues'); },
    },
    random: () => { throw new Error('must not use fallback random'); },
  });

  assert.match(taskId, canonicalTaskId);
  assert.equal(isCanonicalTrainingTaskId(taskId), true);
});

test('canonical training task id uses getRandomValues without randomUUID', () => {
  const taskId = createCanonicalTrainingTaskId({
    cryptoSource: {
      getRandomValues(bytes) {
        bytes.forEach((_, index) => { bytes[index] = index + 1; });
        return bytes;
      },
    },
    random: () => { throw new Error('must not use fallback random'); },
  });

  assert.match(taskId, canonicalTaskId);
  assert.equal(isCanonicalTrainingTaskId(taskId), true);
});

test('canonical training task id fallback concatenates enough random hex', () => {
  const values = [0.1, 0.2, 0.3, 0.4];
  const taskId = createCanonicalTrainingTaskId({
    cryptoSource: null,
    random: () => values.shift() ?? 0.5,
  });

  assert.match(taskId, canonicalTaskId);
  assert.equal(isCanonicalTrainingTaskId(taskId), true);
});
