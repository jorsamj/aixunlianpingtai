import test from 'node:test';
import assert from 'node:assert/strict';

import {PollRegistry, installPollRegistry} from '../../static/modules/poll-registry.js';

test('registry keeps polling owned by the destination page and clears the rest', () => {
  const registry = new PollRegistry();
  const cleared = [];
  registry.adopt('training', ['训练任务', '检测台'], 11, id => cleared.push(id));
  registry.adopt('sources', '素材接入', 22, id => cleared.push(id));

  registry.leave('训练任务');

  assert.deepEqual(cleared, [22]);
  assert.deepEqual(registry.snapshot().map(row => row.key), ['training']);
});

test('adopting a replacement timer clears the older timer for the same key', () => {
  const registry = new PollRegistry();
  const cleared = [];
  registry.adopt('sources', '素材接入', 10, id => cleared.push(id));
  registry.adopt('sources', '素材接入', 20, id => cleared.push(id));

  assert.deepEqual(cleared, [10]);
  assert.equal(registry.snapshot()[0].active, true);
});

test('legacy page timers are adopted and references are cleared when navigating away', () => {
  const state = {
    jobPollTimer: 1,
    source422Timer: 2,
    auto422Timer: 3,
  };
  const cleared = [];
  const originalClearInterval = globalThis.clearInterval;
  globalThis.clearInterval = id => cleared.push(id);
  globalThis.window = {
    __videoFramePollTimer: 4,
    __prelabelPollTimer: 5,
  };

  const runtime = installPollRegistry({getState: () => state});
  runtime.beforeNavigate('数据集');

  assert.deepEqual(cleared.sort((a, b) => a - b), [1, 2, 3, 4, 5]);
  assert.equal(state.jobPollTimer, null);
  assert.equal(state.source422Timer, null);
  assert.equal(state.auto422Timer, null);
  assert.equal(globalThis.window.__videoFramePollTimer, null);
  assert.equal(globalThis.window.__prelabelPollTimer, null);
  assert.deepEqual(runtime.snapshot(), []);

  runtime.destroy();
  globalThis.clearInterval = originalClearInterval;
  delete globalThis.window;
});
