import test from 'node:test';
import assert from 'node:assert/strict';

import {applyAnnotationResult} from '../../static/modules/annotation.js';
import {applyCleanConfirmation} from '../../static/modules/cleaning.js';
import {activeLabelOptions} from '../../static/modules/labels.js';
import {filterByAnyLabel, replaceMaterial} from '../../static/modules/materials.js';
import {uploadBatchFromResponse} from '../../static/modules/upload.js';

test('saved annotation replaces only the matching material', () => {
  const before = [
    {id: 'one', labels: [], box_count: 0},
    {id: 'two', labels: ['old'], box_count: 1}
  ];
  const after = replaceMaterial(before, {id: 'one', labels: ['person'], box_count: 2});

  assert.deepEqual(after, [
    {id: 'one', labels: ['person'], box_count: 2},
    {id: 'two', labels: ['old'], box_count: 1}
  ]);
  assert.notEqual(after, before);
  assert.equal(after[1], before[1]);
});

test('multi-label filtering uses OR semantics', () => {
  const rows = [
    {id: 'one', labels: ['person']},
    {id: 'two', labels: ['vehicle']},
    {id: 'three', labels: ['animal']}
  ];
  assert.deepEqual(filterByAnyLabel(rows, ['person', 'vehicle']).map(row => row.id), ['one', 'two']);
  assert.deepEqual(filterByAnyLabel(rows, []).map(row => row.id), ['one', 'two', 'three']);
});

test('label options come only from active label-library records', () => {
  const options = activeLabelOptions([
    {code: 'person', display_name_zh: '人员', status: 'active'},
    {code: 'legacy', display_name_zh: '旧标签', status: 'disabled'},
    {code: '', display_name_zh: '无编码', status: 'active'}
  ]);
  assert.deepEqual(options, [{code: 'person', displayName: '人员'}]);
});

test('annotation response updates gallery state without a reload', () => {
  const result = applyAnnotationResult(
    [{id: 'one', annotated: false, labels: [], box_count: 0}],
    {image: {id: 'one', annotated: true, labels: ['person'], box_count: 1}},
    [{class_id: 0, label: 'person', x1: 1, y1: 2, x2: 10, y2: 20}]
  );
  assert.equal(result[0].annotated, true);
  assert.equal(result[0].box_count, 1);
  assert.deepEqual(result[0].annotation_preview, [
    {class_id: 0, label: 'person', x1: 1, y1: 2, x2: 10, y2: 20}
  ]);
});

test('upload response exposes one decision batch for single or multiple files', () => {
  assert.deepEqual(uploadBatchFromResponse({batch_id: 'b1', uploaded_image_ids: ['one']}), {
    batchId: 'b1', imageIds: ['one'], images: []
  });
  assert.deepEqual(uploadBatchFromResponse({batch_id: 'b2', uploaded: [{id: 'one'}, {id: 'two'}]}), {
    batchId: 'b2', imageIds: ['one', 'two'], images: [{id: 'one'}, {id: 'two'}]
  });
});

test('clean confirmation removes only backend-confirmed deletions and marks the rest ready', () => {
  const after = applyCleanConfirmation(
    [{id: 'one'}, {id: 'two'}, {id: 'three'}],
    {deleted_images: ['two'], processed_ids: ['one']}
  );
  assert.deepEqual(after, [
    {id: 'one', processing_status: 'processed', clean_skipped: false},
    {id: 'three'}
  ]);
});
