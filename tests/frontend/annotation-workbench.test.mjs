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
