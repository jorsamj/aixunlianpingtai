import test from 'node:test';
import assert from 'node:assert/strict';

import {createAnnotationWorkbench, queueWindow} from '../../static/modules/annotation-workbench.js';


test('stale annotation response cannot replace the newest image', async () => {
  const pending = new Map();
  const load = id => new Promise(resolve => pending.set(id, resolve));
  const applied = [];
  const workbench = createAnnotationWorkbench({load, save: async () => true, apply: value => applied.push(value)});
  const first = workbench.open('one');
  const second = workbench.open('two');
  pending.get('two')({image_id: 'two'});
  await second;
  pending.get('one')({image_id: 'one'});
  await first;
  assert.deepEqual(applied, [{image_id: 'two'}]);
});


test('dirty navigation waits for save and blocks when save fails', async () => {
  const events = [];
  const workbench = createAnnotationWorkbench({
    load: async id => ({image_id: id}),
    save: async () => { events.push('save'); return false; },
    apply: value => events.push(`open:${value.image_id}`),
  });
  await workbench.open('one');
  workbench.markDirty();
  const moved = await workbench.open('two');
  assert.equal(moved, false);
  assert.deepEqual(events, ['open:one', 'save']);
});


test('fifty-image queue renders a bounded window around the active image', () => {
  const ids = Array.from({length: 50}, (_, index) => `image-${index}`);
  const visible = queueWindow(ids, 'image-25', 9);
  assert.equal(visible.length, 9);
  assert.equal(visible.includes('image-25'), true);
  assert.equal(visible[0], 'image-21');
  assert.equal(visible.at(-1), 'image-29');
});


test('beforeLoad paints immediately while the authoritative annotation request is pending', async () => {
  let resolveLoad;
  const events = [];
  const workbench = createAnnotationWorkbench({
    beforeLoad: id => events.push(`shell:${id}`),
    load: id => new Promise(resolve => { resolveLoad = () => resolve({image_id: id}); }),
    save: async () => true,
    apply: value => events.push(`apply:${value.image_id}`),
  });
  const opening = workbench.open('one');
  assert.deepEqual(events, ['shell:one']);
  resolveLoad();
  await opening;
  assert.deepEqual(events, ['shell:one', 'apply:one']);
});

test('prefetched annotation opens from short-lived memory cache without a duplicate request', async () => {
  const loads = [];
  const applied = [];
  const workbench = createAnnotationWorkbench({
    load: async id => { loads.push(id); return {image_id: id}; },
    save: async () => true,
    apply: value => applied.push(value.image_id),
  });
  await workbench.open('one');
  await workbench.prefetch(['two', 'two']);
  assert.deepEqual(loads, ['one', 'two']);
  await workbench.open('two');
  assert.deepEqual(loads, ['one', 'two']);
  assert.deepEqual(applied, ['one', 'two']);
});

test('remember replaces cached annotation truth after a save', async () => {
  let loads = 0;
  const applied = [];
  const workbench = createAnnotationWorkbench({
    load: async id => { loads += 1; return {image_id: id, boxes: []}; },
    save: async () => true,
    apply: value => applied.push(value),
  });
  await workbench.open('one');
  workbench.remember('one', {image_id: 'one', boxes: [{label: 'person'}]});
  await workbench.open('one');
  assert.equal(loads, 1);
  assert.deepEqual(applied.at(-1).boxes, [{label: 'person'}]);
});
