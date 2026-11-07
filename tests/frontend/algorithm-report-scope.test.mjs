import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

test('algorithm report distinguishes successful tasks, all tasks, measured durations and list windows', async () => {
  const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
  const fn=source.match(/window\.algorithmReport429=async function\(id\).*?;\r?\n/)[0];
  let body='';
  const context={window:{},api:async()=>({algorithm:{name:'scope'},summary:{training_count:1,successful_count:1,attempt_count:23,total_duration_seconds:40,avg_duration_seconds:13,duration_record_count:3,duration_unknown_count:20},trend:[],jobs_total:23,jobs_limit:20,jobs_truncated:true}),pid:()=> 'p',modal:(_title,html)=>{body=html;},esc:x=>String(x??''),algType429:x=>x??'',pct429:()=>'-',fmtTime424:x=>String(x),spark429:()=>'',dt429:x=>x,toast:error=>{throw error;}};
  vm.runInNewContext(fn,context);
  await context.window.algorithmReport429('a');
  assert.match(body,/成功训练次数/);
  assert.match(body,/训练任务数/);
  assert.match(body,/23 次/);
  assert.match(body,/所有训练任务累计耗时（含失败）/);
  assert.match(body,/所有训练任务平均耗时（含失败）/);
  assert.match(body,/3 条有耗时记录/);
  assert.match(body,/20 条耗时未知/);
  assert.match(body,/完整记录 23 条/);
  assert.match(body,/最近 20 条/);
  assert.doesNotMatch(body,/1 \/ 1 次/);
});
