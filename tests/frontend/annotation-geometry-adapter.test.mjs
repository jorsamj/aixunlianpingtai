import test from 'node:test';
import assert from 'node:assert/strict';
import {toAnno, fromAnno, annotationLabelIssue, withLegacyBoxIdentities} from '../../static/modules/annotation-geometry-adapter.js';

const size = {width: 640, height: 480};

test('idless historical live GT gets deterministic collision-free identities without replacing existing IDs or mutating evidence',()=>{
  const original=[{id:'legacy:image:1',label:'person'},{label:'person',x1:1,y1:2,x2:3,y2:4},{id:0,label:'person'}];
  const projected=withLegacyBoxIdentities(original,{imageId:'image'});
  assert.equal(projected[0],original[0]);assert.equal(projected[2],original[2]);assert.equal(projected[2].id,0);
  assert.equal(original[1].id,undefined);assert.equal(projected[1].id,'legacy:image:1:1');
  assert.deepEqual(withLegacyBoxIdentities(original,{imageId:'image'}),projected);
  assert.deepEqual(withLegacyBoxIdentities(projected,{imageId:'image'}),projected);
  assert.notEqual(withLegacyBoxIdentities(original,{imageId:'other'})[1].id,projected[1].id);
  assert.throws(()=>withLegacyBoxIdentities(original),/image id/);
});
const labels = [{class_id: 7, code: 'person'}, {class_id: 19, code: 'helmet'}];
const box = {id: 'legacy-box', class_id: 7, label: 'person', x1: 0.1, y1: 9.3, x2: 127.2, y2: 120.8,
  source: 'ai_candidate_reviewed', source_task_id: 'task-1', confidence: 0.83,
  arbitrary_metadata: {reviewer: 'human', nested: ['untouched']}};
const options = (original = box) => ({...size, labels, originalBoxesById: new Map([[String(original.id), original]])});

test('GT maps to the official ImageAnnotation rectangle shape and bounds', () => {
  const result = toAnno(box, size);
  assert.deepEqual(result, {id: box.id, bodies: [{id: `${box.id}:label`, annotation: box.id, purpose: 'tagging', value: 'person'}],
    target: {annotation: box.id, selector: {type: 'RECTANGLE', geometry: {x: box.x1, y: box.y1, w: box.x2-box.x1, h: box.y2-box.y1,
      bounds: {minX: box.x1, minY: box.y1, maxX: box.x2, maxY: box.y2}}}}});
  assert.equal(JSON.stringify(result).includes('source_content_sha256'), false);
});

test('untouched repeated round trips retain exact GT coordinates, identity and every metadata field', () => {
  let current = structuredClone(box);
  for (let i = 0; i < 1000; i++) current = fromAnno(toAnno(current, size), options(current));
  assert.deepEqual(current, box);
  assert.notEqual(current, box);
});

test('moving a rectangle merges only geometry into the original GT without mutating it', () => {
  const annotation = toAnno(box, size);
  annotation.target.selector.geometry = {x: 20, y: 30, w: 120, h: 60, bounds: {minX:20,minY:30,maxX:140,maxY:90}};
  assert.deepEqual(fromAnno(annotation, options()), {...box, x1:20,y1:30,x2:140,y2:90});
  assert.equal(box.x1, 0.1);
});

test('unknown legacy labels survive and require explicit correction, never the first class', () => {
  const unknown = {...box, class_id: 999, label: 'retired_code'};
  const next = fromAnno(toAnno(unknown, size), options(unknown));
  assert.deepEqual(next, unknown);
  assert.equal(annotationLabelIssue(next, labels).code, 'unknown_label');
  const corrected = toAnno(unknown, size);
  corrected.bodies[0].value = 'helmet';
  assert.deepEqual(fromAnno(corrected, options(unknown)), {...unknown, label:'helmet',class_id:19});
  assert.equal(annotationLabelIssue(fromAnno(corrected, options(unknown)), labels), null);
  assert.equal(annotationLabelIssue({...box,class_id:19},labels).code, 'class_code_mismatch');
});

test('new library rectangle keeps its new ID and requires an explicitly selected label', () => {
  const annotation = {...toAnno(box,size), id:'new-library-id', bodies:[]};
  annotation.target.annotation = annotation.id;
  const context = {...size, labels, originalBoxesById: new Map()};
  assert.throws(() => fromAnno(annotation,context), /label/i);
  assert.deepEqual(fromAnno(annotation,{...context,newLabel:labels[1]}), {
    id:'new-library-id',class_id:19,label:'helmet',x1:box.x1,y1:box.y1,x2:box.x1+(box.x2-box.x1),y2:box.y1+(box.y2-box.y1)});
});

test('conversion rejects invalid original pixels, rotated geometry and nonfinite bounds', () => {
  for (const invalid of [{x1:-1}, {x2:641}, {y2:481}, {x2:0.1}, {x1:NaN}, {y1:Infinity}, {x2:'10'}]) {
    assert.throws(() => toAnno({...box,...invalid},size), /geometry/i);
  }
  for (const invalid of [{w:0}, {x:-1}, {w:Infinity}, {rot:0.1}, {bounds:{minX:NaN,minY:0,maxX:1,maxY:1}}]) {
    const annotation = toAnno(box,size);
    Object.assign(annotation.target.selector.geometry,invalid);
    assert.throws(() => fromAnno(annotation,options()), /geometry/i);
  }
  assert.throws(() => toAnno(box,{width:0,height:480}), /dimensions/i);
  assert.throws(() => fromAnno(toAnno(box,size),size), /originalBoxesById/);
});

test('official editor stale derived bounds never override valid moved rectangle geometry', () => {
  const annotation = toAnno(box,size);
  Object.assign(annotation.target.selector.geometry,{x:20,y:30,w:120,h:60});
  // Official RectangleEditor 3.9.5 computes bounds from the previous reactive
  // rotatedCorners value. The geometry is authoritative, not this stale index.
  assert.deepEqual(fromAnno(annotation,options()),{...box,x1:20,y1:30,x2:140,y2:90});
  assert.deepEqual(toAnno(fromAnno(annotation,options()),size).target.selector.geometry.bounds,
    {minX:20,minY:30,maxX:140,maxY:90});
});

test('input is a single rectangle, not a version/SHA or full GT owner', () => {
  assert.throws(() => toAnno({boxes:[box],version:7,source_content_sha256:'abc'},size), /id/i);
  const annotation = toAnno(box,size);
  annotation.target.selector.type = 'POLYGON';
  assert.throws(() => fromAnno(annotation,options()), /rectangle/i);
});
