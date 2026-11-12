import test from 'node:test';
import assert from 'node:assert/strict';
import {algorithmReportHtml, algorithmReportView} from '../../static/modules/reports.js';

test('algorithm report keeps successful counts, all attempts and duration evidence without eager job DOM', () => {
  const payload={algorithm:{name:'Scope'},summary:{training_count:1,successful_count:1,attempt_count:23,total_duration_seconds:40,
    avg_duration_seconds:13,duration_record_count:3,duration_unknown_count:20},
    version_quality:[],jobs_total:23,jobs_limit:20,jobs_truncated:true,
    jobs:[{job_id:'failed-fixture',status:'failed',map50:0.2}]};
  const overview=algorithmReportHtml(payload);
  assert.match(overview,/成功训练<\/dt><dd>1 次/);
  assert.match(overview,/训练尝试总数<\/dt><dd>23 次/);
  assert.match(overview,/平均耗时（含失败）<\/dt><dd>13\.0 秒/);
  assert.match(overview,/耗时记录覆盖<\/dt><dd>3 \/ 23/);
  assert.match(overview,/耗时未知<\/dt><dd>20 条/);
  assert.doesNotMatch(overview,/failed-fixture/,'job rows are deferred until the jobs tab opens');
  const jobs=algorithmReportView('jobs',payload);
  assert.match(jobs,/最近 1 \/ 23 条任务/);
  assert.match(jobs,/failed-fixture/);
  assert.match(jobs,/最近 20 条/);
  assert.match(jobs,/完整记录请在训练任务页面检索/);
});

test('algorithm report never invents missing duration evidence',()=>{
  const html=algorithmReportHtml({summary:{attempt_count:5,duration_record_count:0}});
  assert.match(html,/累计训练时长<\/dt><dd>未记录/);
  assert.match(html,/平均耗时（含失败）<\/dt><dd>未记录/);
  assert.match(html,/耗时未知<\/dt><dd>未记录/);
});
