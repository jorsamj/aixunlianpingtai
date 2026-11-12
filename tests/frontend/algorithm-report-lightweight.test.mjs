import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {algorithmReportHtml} from '../../static/modules/reports.js';

const css=readFileSync(new URL('../../static/algorithm-report-modal.css',import.meta.url),'utf8');
const app=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const main=readFileSync(new URL('../../static/main.mjs',import.meta.url),'utf8');

const report={
  algorithm:{name:'人员检测',version_count:3,industry:'视频分析'},
  summary:{current_version:'v3',successful_count:3,attempt_count:4,total_duration_seconds:7200,duration_record_count:4,
    latest_accuracy:0.82,label_counts:{},label_counts_scope:'not_computed_fast'},
  best_map50:0.85,best_version:'v2',latest_vs_previous:{map50_delta:0.02},
  current_quality:{test_status:'succeeded',test_map50:0.74,test_snapshot_id:'a'.repeat(64)},
  version_quality:[
    {version_id:'v1',version_name:'v1',val_map50:0.71},
    {version_id:'v2',version_name:'v2',val_map50:0.80},
    {version_id:'v3',version_name:'v3',val_map50:0.82,is_current:true},
  ],
};
test('algorithm overview is compact, factual, and excludes all history rows on first paint',()=>{
  const html=algorithmReportHtml(report);
  assert.match(html,/82\.0%/);
  assert.match(html,/74\.0%/);
  assert.match(html,/85\.0%/);
  assert.match(html,/\+2\.0 pp/);
  assert.match(html,/仅 Validation 指标/);
  assert.match(html,/不等于业务验收/);
  assert.doesNotMatch(html,/最新正确率|正确率 ·/);
  assert.match(html,/data-algorithm-report-pane="versions" hidden/);
  assert.match(html,/data-algorithm-report-pane="data" hidden/);
  assert.match(html,/data-algorithm-report-pane="jobs" hidden/);
  assert.doesNotMatch(html,/data-algorithm-report-job=/);
});
test('missing and malformed metrics are never inferred as zero or fake percentages',()=>{
  const html=algorithmReportHtml({algorithm:{name:'<img src=x onerror=alert(1)>'},
    summary:{latest_accuracy:97},current_quality:{test_status:'not_recorded'},
    latest_vs_previous:{map50_delta:null}});
  assert.doesNotMatch(html,/<img|9700\.0%|0\.0%/);
  assert.match(html,/&lt;img src=x/);
  assert.match(html,/未记录/);
  assert.match(html,/未完成/);
});
test('lightweight URL and bounded async ownership are used for the algorithm report',()=>{
  assert.match(app,/report\?lightweight=true/);
  assert.match(app,/captureOwner\?\.\(\)/);
  assert.match(app,/owner\.isCurrent\(\)/);
  assert.match(app,/presenter\.algorithmReportHtml\(report\)/);
  assert.match(main,/algorithmReportHtml, mountAlgorithmReport/);
});
test('modal always owns a limited scrollport even when cards resize',()=>{
  assert.match(css,/\.modal:not\(\.hidden\)>\.modal-card>\.modal-body\{/);
  assert.match(css,/min-height:0/);
  assert.match(css,/overflow-y:auto/);
  assert.match(css,/overscroll-behavior:contain/);
  assert.match(css,/height:86dvh/);
  assert.match(css,/scrollbar-gutter:stable/);
  assert.match(css,/\.alg-report-tabs \[role=tab\]\{[^}]*flex:none/);
});
