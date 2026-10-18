import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {metricCredibilityHtml} from '../../static/modules/reports.js';

test('report and evaluation share one server-truth presentation, not client-side mAP inference', () => {
  const html = metricCredibilityHtml({
    schema_version: 1,
    status: 'review_required',
    validation_map50: 0.97,
    independent_test_map50: 0.72,
    val_minus_test_map50: 0.25,
    test_image_count: 100,
    reason_codes: ['validation_test_map50_gap_at_least_10pp', 'capture_source_partly_unknown'],
  });
  assert.match(html, /需人工复核/);
  assert.match(html, /Val mAP50/);
  assert.match(html, /97\.0%/);
  assert.match(html, /72\.0%/);
  assert.match(html, /\+25\.0 pp/);
  assert.match(html, /来源未知/);
  assert.match(html, /不是事件告警准确率/);
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const main = readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
  assert.match(app, /metricCredibilityHtml\(rep\.metric_credibility\|\|version\?\.metric_credibility\)/);
  assert.match(app, /metricCredibilityHtml\(v\?\.metric_credibility\)/);
  assert.match(main, /reports: \{reportPresentation, metricChart, trainingCharts, formatPercentagePointDelta, metricCredibilityHtml\}/);
});

test('older reports remain explicitly unverified, no inferred or fake numeric evidence', () => {
  assert.match(metricCredibilityHtml(null), /历史证据缺失/);
  assert.doesNotMatch(metricCredibilityHtml(null), /97\.0%|0\.0%/);
  const noTest = metricCredibilityHtml({
    schema_version: 1,
    status: 'review_required',
    validation_map50: 0.97,
    independent_test_map50: null,
    val_minus_test_map50: null,
    test_image_count: null,
    reason_codes: ['independent_test_unavailable'],
  });
  assert.match(noTest, /独立 Test 未完成/);
  assert.match(noTest, /未记录/);
  assert.doesNotMatch(noTest, /Test mAP50<\/span><b>0\.0%/);
});

test('server-owned unknown diagnostic codes must be escaped, not injected into report HTML', () => {
  const html = metricCredibilityHtml({
    schema_version: 1,
    status: '<img src=x onerror=alert(1)>',
    reason_codes: ['<script>alert(1)</script>'],
    test_image_count: 0,
  });
  assert.doesNotMatch(html, /<script>|<img/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /data-metric-credibility="&lt;img/);
});
