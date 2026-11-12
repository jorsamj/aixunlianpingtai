import test from 'node:test';
import assert from 'node:assert/strict';
import {readAiReviewRoute, aiReviewUrl, aiReviewListUrl, installAiReviewRoute} from '../../static/modules/ai-review-route.js';

test('AI review route identifies only a bounded task id and preserves the original page URL', () => {
  assert.equal(readAiReviewRoute('#ai-review/train_123'), 'train_123');
  assert.equal(readAiReviewRoute('#ai-review/%2Fprivate'), null);
  assert.equal(readAiReviewRoute('#ai-review/%ZZ'), null);
  assert.equal(readAiReviewRoute('#ai-review/' + 'x'.repeat(129)), null);
  assert.equal(readAiReviewRoute('#other/123'), null);
  const href = 'https://example.org/?scope=annotation#somewhere';
  assert.equal(aiReviewUrl(href, 'task-123'), '/?scope=annotation#ai-review/task-123');
  assert.equal(aiReviewListUrl('https://example.org/?scope=annotation#ai-review/task-123'), '/?scope=annotation');
  assert.throws(() => aiReviewUrl(href, '../other'), /无效/);
});

test('route ownership respects unfinished review and never bypasses navigation rejection', () => {
  const original = globalThis.window;
  const listeners = new Map();
  let href = 'https://example.org/', blocked = true, closed = 0;
  const history = {
    pushState(_state, _title, path) {href = new URL(path, href).href},
    replaceState(_state, _title, path) {href = new URL(path, href).href},
  };
  globalThis.window = {
    location: {get href() {return href}, get hash() {return new URL(href).hash}},
    history,
    addEventListener(name, listener) {listeners.set(name, listener)},
  };
  try {
    const review = {id:'candidate_7',closed:false};
    const runtime = installAiReviewRoute({getReview:()=>review,close:()=>{closed++;return !blocked}});
    runtime.open(review.id);
    assert.equal(new URL(href).hash, '#ai-review/candidate_7');
    assert.equal(runtime.beforeNavigate('数据集'), false);
    assert.equal(closed, 1);
    assert.equal(new URL(href).hash, '#ai-review/candidate_7');
    blocked = false;
    assert.equal(runtime.beforeNavigate('数据集'), true);
    runtime.leave();
    assert.equal(new URL(href).hash, '');
    assert.ok(listeners.has('popstate'));
    assert.ok(listeners.has('hashchange'));
  } finally {
    if (original === undefined) delete globalThis.window;
    else globalThis.window = original;
  }
});
