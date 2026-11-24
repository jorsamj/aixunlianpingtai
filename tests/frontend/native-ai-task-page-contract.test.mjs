import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {annotationTaskView} from '../../static/modules/annotation-task-view.js';

const page=await readFile(new URL('../../frontend/src/app/AiTasks.vue',import.meta.url),'utf8');
const api=await readFile(new URL('../../frontend/src/api/ai-task-actions.ts',import.meta.url),'utf8');

test('AI task page gates every write with the original status/permission projection',()=>{
  assert.match(page,/import \{annotationTaskView,type AnnotationTaskViewModel\} from '\.\.\/\.\.\/\.\.\/static\/modules\/annotation-task-view\.js';/);
  assert.match(page,/function view\(row:AiTask\):AnnotationTaskViewModel\{/);
  assert.match(page,/return annotationTaskView\(\{\.\.\.row,summary,failed_count:counts\.failed\?\?undefined\} as Record<string,unknown>\);/);
  for(const gate of ['detailView.canCancel','detailView.canRetry','detailView.canRecoverReview','detailView.canReview'])
    assert.ok(page.includes(gate),`missing real-status gate ${gate}`);
  assert.match(page,/v-if="view\(row\)\.canRetry"/);
  assert.match(page,/v-if="view\(row\)\.canReview"/);
});

test('AI task write buttons call only the existing v60 write endpoints',()=>{
  assert.match(page,/import \{cancelAiTask,fetchAiTaskDetail,fetchAiTaskFailures,recoverAiTaskReview,retryAiTask\} from '\.\.\/api\/ai-task-actions';/);
  assert.match(page,/const updated=await cancelAiTask\(projectId,current\.id,c\.signal\);/);
  assert.match(page,/const updated=await retryAiTask\(projectId,current\.id,c\.signal\);/);
  assert.match(page,/const updated=await retryAiTask\(projectId,current\.id,c\.signal,\[imageId\]\);/);
  assert.match(page,/await recoverAiTaskReview\(projectId,current\.id,c\.signal\);/);
  assert.match(api,/\$\{encodeURIComponent\(taskId\)\}\/cancel/);
  assert.match(api,/\$\{encodeURIComponent\(taskId\)\}\/retry/);
  assert.match(api,/\$\{encodeURIComponent\(taskId\)\}\/review-completed/);
});

test('AI task page keeps the legacy create entry instead of inventing creation',()=>{
  assert.match(page,/const createHref=legacyUrl\(projectId,'自动标注及清洗','','','material-ai'\);/);
  assert.match(page,/const legacyHref=legacyUrl\(projectId,'自动标注及清洗'\);/);
  assert.match(page,/创建任务（原工作台）/);
  assert.match(page,/<el-button tag="a" type="primary" :href="createHref">创建任务（原工作台）<\/el-button>/);
  assert.match(page,/原完整自动标注/);
});

test('AI task page provides progress, review return, material location and cancels its own reads',()=>{
  assert.match(page,/async function loadDetail\(\)/);
  assert.match(page,/if\(!alive\|\|!detailOpen\.value\|\|detail\.value\?\.id!==id\)return;/);
  assert.match(page,/scheduleDetailPoll\(id\)/);
  assert.match(page,/if\(!detailView\.value\?\.active\)return;/,'progress polling must stop for terminal tasks');
  assert.match(page,/function enterReview\(\)\{[\s\S]*router\.push\(\{name:'ai-review-native',params:\{projectId,taskId:id\}\}\)/);
  assert.match(page,/返回任务列表/);
  assert.match(page,/function locateMaterial\(imageId:string\)\{/);
  assert.match(page,/router\.push\(\{name:'materials',params:\{projectId\},query:\{detail:imageId\}\}\)/);
  assert.match(page,/const id=current\.id,c=new AbortController\(\);/);
  assert.match(page,/onBeforeUnmount\(\(\)=>\{alive=false;controller\.abort\(\);stopDetailPoll\(\);detailController\?\.abort\(\);failureController\?\.abort\(\);actionController\?\.abort\(\)\}\)/);
  assert.doesNotMatch(page,/\bfetch\(/,'native page must use the shared http owner');
  assert.doesNotMatch(page,/pinia|defineStore/,'no new global store is introduced');
});

test('AI task view projection derives cancel/retry/recover from real reader counts',()=>{
  const reader={id:'t',project_id:'p',status:'FAILED',statistics_known:true,
    counts:{total:8,success:5,empty:1,failed:2,accepted:0,rejected:0,unreviewed:8,boxes:0,gt_committed:0},
    total_count:8,completed_count:8,remaining_count:0,accepted:null};
  const summary={...(reader.counts)};
  const failedCounts={total:2,success:0,empty:0,failed:2,accepted:0,rejected:0,unreviewed:2,boxes:0,gt_committed:0};
  const failed=annotationTaskView({...reader,counts:failedCounts,summary:failedCounts,failed_count:2});
  assert.equal(failed.canRetry,true);
  assert.equal(failed.canCancel,false);
  assert.equal(failed.canRecoverReview,false,'no generated candidates means nothing to review');
  const recoveredSummary={total:2,success:1,empty:0,failed:1,accepted:0,rejected:0,unreviewed:2,boxes:0,gt_committed:0};
  const cancelled=annotationTaskView({...reader,status:'CANCELLED',total_count:2,completed_count:1,
    remaining_count:1,summary:recoveredSummary,failed_count:1});
  assert.equal(cancelled.canRetry,true);
  assert.equal(cancelled.canRecoverReview,true);
  const running=annotationTaskView({...reader,status:'RUNNING',summary});
  assert.equal(running.canCancel,true);
  assert.equal(running.canRetry,false);
  const awaiting=annotationTaskView({...reader,status:'AWAITING_CONFIRMATION',summary,failed_count:0});
  assert.equal(awaiting.canReview,true);
});
