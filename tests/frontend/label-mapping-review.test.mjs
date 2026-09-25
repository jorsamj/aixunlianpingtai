import test from 'node:test';
import assert from 'node:assert/strict';

import {
  bulkSetLabelMapping,
  buildManualLabelMapping,
  createLabelMappingReview,
  filterCanonicalLabels,
  labelMappingReviewPage,
  labelMappingReviewSummary,
  reconcileLabelMappingReview,
  setLabelMapping,
  setLabelMappingReviewPage,
  setLabelMappingReviewSearch,
  setLabelMappingSelected,
} from '../../static/modules/label-mapping-review.js';

function classes(count) {
  return Array.from({length: count}, (_, index) => ({
    class_id: String(index),
    name: 'external_' + String(index).padStart(5, '0'),
    image_count: 2,
    box_count: 3,
  }));
}

test('10k external labels render in bounded 50-row pages', () => {
  const review = createLabelMappingReview(classes(10000));
  let page = labelMappingReviewPage(review);
  assert.equal(page.rows.length, 50);
  assert.equal(page.total, 10000);
  assert.equal(page.pageCount, 200);
  setLabelMappingReviewPage(review, 200);
  page = labelMappingReviewPage(review);
  assert.equal(page.rows.length, 50);
  assert.equal(page.rows[0].classId, '9950');
});

test('search changes only the view and preserves mappings outside the current page', () => {
  const review = createLabelMappingReview(classes(300));
  setLabelMapping(review, '299', 'smoke');
  setLabelMappingReviewSearch(review, 'external_00299');
  const page = labelMappingReviewPage(review);
  assert.equal(page.rows.length, 1);
  assert.equal(page.rows[0].classId, '299');
  assert.equal(page.rows[0].code, 'smoke');
  setLabelMappingReviewSearch(review, '');
  assert.equal(labelMappingReviewSummary(review).mapped, 1);
});

test('bulk mapping applies only to explicitly checked external labels', () => {
  const review = createLabelMappingReview(classes(5));
  setLabelMappingSelected(review, '1', true);
  setLabelMappingSelected(review, '3', true);
  bulkSetLabelMapping(review, 'smoke');
  assert.deepEqual(review.mapping, {'1': 'smoke', '3': 'smoke'});
  assert.equal(labelMappingReviewSummary(review).selected, 0);
});

test('confirmation remains blocked until every external label is manually mapped', () => {
  const review = createLabelMappingReview(classes(2));
  setLabelMapping(review, '0', 'helmet');
  assert.throws(() => buildManualLabelMapping(review), /1 个外部标签未映射/);
  setLabelMapping(review, '1', 'helmet');
  assert.deepEqual(buildManualLabelMapping(review), {'0': 'helmet', '1': 'helmet'});
});

test('reconcile preserves user decisions but never creates decisions for new external labels', () => {
  let review = createLabelMappingReview(classes(2));
  setLabelMapping(review, '0', 'helmet');
  review = reconcileLabelMappingReview(review, classes(3));
  assert.equal(review.mapping['0'], 'helmet');
  assert.equal(review.mapping['2'], undefined);
  assert.equal(labelMappingReviewSummary(review).unmapped, 2);
});

test('canonical label search is factual filtering and keeps already selected codes visible', () => {
  const labels = [
    {code: 'helmet', display_name: '安全头盔', status: 'active'},
    {code: 'smoke', display_name: '烟雾', aliases: ['抽烟'], status: 'active'},
    {code: 'old', display_name: '旧类', status: 'inactive'},
  ];
  assert.deepEqual(filterCanonicalLabels(labels, '烟').map(row => row.code), ['smoke']);
  assert.deepEqual(filterCanonicalLabels(labels, 'nomatch', ['helmet']).map(row => row.code), ['helmet']);
  assert.equal(filterCanonicalLabels(labels, '').some(row => row.code === 'old'), false);
});
