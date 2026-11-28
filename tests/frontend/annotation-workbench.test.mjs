import test from 'node:test';
import assert from 'node:assert/strict';

import {
  annotationReviewView,
  annotationSavePayload,
  createAnnotationWorkbench,
  queueWindow,
} from '../../static/modules/annotation-workbench.js';


test('review labels remain unchecked until the user explicitly selects them', () => {
  assert.deepEqual(
    annotationReviewView(
      {annotation_scope: ['helmet']},
      ['helmet', 'vest', 'person'],
    ),
    {
      reviewed: ['helmet'],
      required: ['helmet', 'vest', 'person'],
      pending: ['vest', 'person'],
    },
  );
  assert.deepEqual(
    annotationSavePayload({
      annotation: {version: 7},
      image: {content_sha256: 'a'.repeat(64)},
      boxes: [{label: 'helmet'}],
    }).reviewed_label_codes,
    [],
  );
});


test('legacy wildcard scope remains read-compatible without creating new checks', () => {
  assert.deepEqual(
    annotationReviewView({annotation_scope: ['*']}, ['helmet', 'person']),
    {reviewed: ['*'], required: ['helmet', 'person'], pending: []},
  );
});


test('save and confirm sends only explicitly checked review labels with CAS identities', () => {
  const payload = annotationSavePayload({
    annotation: {version: 7},
    image: {content_sha256: 'a'.repeat(64)},
    boxes: [{label: 'helmet'}],
    reviewedLabelCodes: ['vest', 'vest'],
  });
  assert.equal(payload.expected_version, 7);
  assert.equal(payload.source_content_sha256, 'a'.repeat(64));
  assert.deepEqual(payload.reviewed_label_codes, ['vest']);
});

test('empty ordinary save is pending and drops negative review proof', () => {
  const payload = annotationSavePayload({annotation: {version: 4, annotation_state: 'confirmed_empty'},
    image: {content_sha256: 'sha'}, boxes: [], reviewedLabelCodes: ['vest']});
  assert.equal(payload.annotation_state, 'unannotated');
  assert.deepEqual(payload.reviewed_label_codes, []);
  assert.equal(payload.expected_version, 4);
  assert.equal(payload.source_content_sha256, 'sha');
});

test('empty negative save requires explicit confirmation and uses only current checked labels', () => {
  const payload = annotationSavePayload({annotation: {version: 4, annotation_scope: ['helmet']},
    boxes: [], confirmEmpty: true, reviewedLabelCodes: ['vest', 'vest']});
  assert.equal(payload.annotation_state, 'confirmed_empty');
  assert.deepEqual(payload.reviewed_label_codes, ['vest']);
});


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


test('closing the workbench can cancel pending apply without throwing away the short-lived cache', async () => {
  let loads = 0;
  const applied = [];
  const workbench = createAnnotationWorkbench({
    load: async id => { loads += 1; return {image_id: id}; },
    save: async () => true,
    apply: value => applied.push(value.image_id),
  });

  await workbench.open('one');
  workbench.cancel();
  await workbench.open('one');

  assert.equal(loads, 1);
  assert.deepEqual(applied, ['one', 'one']);
});


test('original annotation load preserves the trusted source URL when detail omits it and rejects another image',async()=>{
 const {readFileSync}=await import('node:fs');const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
 const start=source.indexOf('      load:async id=>{',source.indexOf('  function ensureWorkbench(){')),end=source.indexOf('\n      save:',start);
 assert.ok(start>0&&end>start);
 const expression=source.slice(start,end).trim().replace(/^load:/,'').replace(/,$/,'');
 const image={id:'img',url:'/api/v61/projects/p/materials/img/content',filename:'indexed.jpg',width:640},annotation={boxes:[]};
 let response={image:{id:'img',filename:'authoritative.jpg',width:640},annotation};
 const load=new Function('imageById','state','LABEL_SCHEMA_CACHE_TTL_MS','apiRequestAnnotation420',`return (${expression})`)(()=>image,{labels:[{code:'smoke'}],label414LoadedAt:Date.now()},60000,async()=>response);
 const result=await load('img');assert.equal(result.image.url,image.url);assert.equal(result.image.filename,'authoritative.jpg');assert.equal(result.annotation,annotation);
 response={image:{id:'img',url:'/api/v61/projects/p/materials/img/content?revision=9'},annotation};assert.equal((await load('img')).image.url,response.image.url);
 response={image:{id:'other'},annotation};await assert.rejects(()=>load('img'),/图片身份/);
});
