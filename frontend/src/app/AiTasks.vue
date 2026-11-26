<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import type {AiFailure,AiTask,AiTaskPage} from '../types/ai-tasks';
import {aiTaskReaderApi} from '../api/ai-task-reader';
import {cancelAiTask,fetchAiTaskDetail,fetchAiTaskFailures,recoverAiTaskReview,retryAiTask} from '../api/ai-task-actions';
import {browseError} from '../api/model-browse';
import {useReadScope} from '../composables/useReadScope';
import {request} from './http';
import {legacyUrl} from './navigation';
import {annotationTaskView,type AnnotationTaskViewModel} from '../../../static/modules/annotation-task-view.js';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';

const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId);
const controller=new AbortController(),reads=useReadScope(controller),api=aiTaskReaderApi({projectId,get:request});
const status=ref(''),page=ref<AiTaskPage|null>(null),cursors=ref<string[]>(['']),index=ref(0);
// Product-facing labels follow the existing pilot page; unknown statuses stay raw.
const statuses:Record<string,string>={QUEUED:'排队中',WAITING_RESOURCE:'等待资源',RUNNING:'运行中',CANCEL_REQUESTED:'正在取消',AWAITING_CONFIRMATION:'等待确认',PARTIAL_SUCCESS:'部分成功',SUCCEEDED:'已完成',CANCELLED:'已取消',FAILED:'失败',BLOCKED_BY_ENVIRONMENT:'环境不可用',BLOCKED_BY_HARDWARE:'硬件不可用'};
const label=(value?:string)=>value?statuses[value]||value:'未提供';
const tone=(value?:string)=>value==='SUCCEEDED'?'success'
  :value==='PARTIAL_SUCCESS'?'warning'
  :value==='FAILED'?'danger'
  :['BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE','AWAITING_CONFIRMATION'].includes(String(value||''))?'warning':'info';
const shown=(value:number|null|undefined)=>typeof value==='number'?String(value):'未知';
const created=(value?:string|null)=>value?value.replace('T',' ').slice(0,19):'未提供';
const progress=(row:AiTask)=>row.progress_percent!=null?`${row.progress_percent}%`:row.completed_count!=null?'已处理，进度未提供':'未提供';
// Same legacy status/permission projection the original wall uses. Reader
// counts are mapped back to its summary input instead of re-deriving buttons.
function view(row:AiTask):AnnotationTaskViewModel{
 const counts=row.statistics_known&&row.counts?row.counts:{};
 const summary=row.statistics_known?{total:counts.total,success:counts.success,empty:counts.empty,failed:counts.failed,accepted:counts.accepted,rejected:counts.rejected,unreviewed:counts.unreviewed,boxes:counts.boxes,gt_committed:counts.gt_committed}:{};
 return annotationTaskView({...row,summary,failed_count:counts.failed??undefined} as Record<string,unknown>);
}
function load(){
 const cursor=cursors.value[index.value]||'';
 return reads.run('tasks',signal=>api.tasks(status.value,cursor,signal),value=>{page.value=value});
}
function search(){cursors.value=[''];index.value=0;page.value=null;void load()}
function next(){
 const cursor=page.value?.next_cursor;
 if(!cursor)return;
 cursors.value=cursors.value.slice(0,index.value+1);
 cursors.value.push(cursor);
 index.value+=1;
 page.value=null;
 void load();
}
function previous(){if(index.value<1)return;index.value-=1;page.value=null;void load()}

// Detail/progress drawer: the v60 detail and failure reader are the only sources;
// no list row is optimistically promoted to a done/failed state.
const detailOpen=ref(false),detail=ref<AiTask|null>(null),detailBusy=ref(false),detailError=ref('');
const failures=ref<AiFailure[]>([]),failuresTotal=ref(0),failuresNext=ref<string|null>(null),failuresBusy=ref(false),failuresError=ref('');
const actionBusy=ref(''),actionError=ref(''),actionNotice=ref('');
let alive=true,detailTimer:number|undefined;
let detailController:AbortController|null=null,failureController:AbortController|null=null,actionController:AbortController|null=null;
const detailView=computed(()=>detail.value?view(detail.value):null);
const detailFacts=computed<[string,unknown][]>(()=>{
 const row=detail.value,model=detailView.value;
 if(!row||!model)return[];
 return [
  ['任务 ID',row.id],['状态',`${label(row.status)} (${row.status})`],['阶段',row.phase],['进度',`${model.completed} / ${model.total}（${model.percent.toFixed(1)}%）`],
  ['候选 / 失败 / 待审',`${model.generated} / ${model.failed} / ${shown(row.counts?.unreviewed)}`],
  ['模型',row.model_config_name||row.model_provider],['请求标签',(row.requested_labels||[]).join('、')||'未提供'],
  ['Worker',row.worker_id],['等待原因',row.resource_wait_reason],['创建',created(row.created_at)],['完成',created(row.finished_at)],['统计同步',created(row.statistics_synced_at)],
 ];
});
const createTarget={name:'ai-create',params:{projectId}};
const legacyHref=legacyUrl(projectId,'自动标注及清洗');
onBeforeUnmount(()=>{alive=false;controller.abort();stopDetailPoll();detailController?.abort();failureController?.abort();actionController?.abort()});
function openDetail(row:AiTask){
 detailOpen.value=true;detail.value=row;detailError.value='';actionError.value='';actionNotice.value='';
 failures.value=[];failuresTotal.value=0;failuresNext.value=null;failuresError.value='';
 void loadDetail();void loadFailures();
}
function closeDetail(){
 detailOpen.value=false;stopDetailPoll();
 detailController?.abort();detailController=null;
 failureController?.abort();failureController=null;
 detailBusy.value=false;failuresBusy.value=false;
 detail.value=null;failures.value=[];failuresNext.value=null;failuresError.value='';
}
function stopDetailPoll(){if(detailTimer!==undefined){window.clearTimeout(detailTimer);detailTimer=undefined}}
function scheduleDetailPoll(id:string){
 stopDetailPoll();
 if(!detailView.value?.active)return;
 detailTimer=window.setTimeout(()=>{
  detailTimer=undefined;
  if(!alive||!detailOpen.value||detail.value?.id!==id)return;
  void loadDetail();
 },2000);
}
async function loadDetail(){
 detailController?.abort();
 const current=detail.value;
 if(!current)return;
 const id=current.id,c=new AbortController();
 detailController=c;detailBusy.value=true;detailError.value='';
 try{
  const next=await fetchAiTaskDetail(projectId,id,c.signal);
  if(!alive||!detailOpen.value||detail.value?.id!==id)return;
  detail.value=next;
  scheduleDetailPoll(id);
 }catch(error){
  if(c.signal.aborted||!alive||!detailOpen.value||detail.value?.id!==id)return;
  detailError.value=browseError(error);
 }finally{if(detailController===c){detailController=null;detailBusy.value=false}}
}
async function loadFailures(cursor=''){
 failureController?.abort();
 const current=detail.value;
 if(!current)return;
 const id=current.id,c=new AbortController();
 failureController=c;failuresBusy.value=true;failuresError.value='';
 try{
  const result=await fetchAiTaskFailures(projectId,id,c.signal,cursor);
  if(!alive||!detailOpen.value||detail.value?.id!==id)return;
  failures.value=cursor?[...failures.value,...result.items]:result.items;
  failuresNext.value=result.next_cursor;
  failuresTotal.value=result.total;
 }catch(error){
  if(c.signal.aborted||!alive||!detailOpen.value||detail.value?.id!==id)return;
  failuresError.value=browseError(error);
 }finally{if(failureController===c){failureController=null;failuresBusy.value=false}}
}
function beginAction(){if(actionBusy.value)return null;actionController?.abort();actionController=new AbortController();actionError.value='';actionNotice.value='';return actionController}
async function refreshAfterAction(){
 await loadDetail();
 await load();
}
function actionFailure(kind:string,error:unknown){
 const status=(error as {httpStatus?:number}).httpStatus;
 // An explicit 4xx rejection can be corrected by the user; transport/5xx/unknown
 // receipts are surfaced without auto-resubmission.
 actionError.value=status!==undefined&&status<500
  ?`${kind}请求未受理：${browseError(error)}`
  :`${kind}结果待核验：未收到服务端确认回执；不会自动重复提交，请刷新任务状态后再核对。`;
}
async function runCancel(){
 const current=detail.value;
 if(!current||!view(current).canCancel)return;
 const c=beginAction();if(!c)return;
 actionBusy.value='cancel';
 try{
  const updated=await cancelAiTask(projectId,current.id,c.signal);
  if(!alive)return;
  if(detail.value?.id===updated.id)detail.value={...detail.value,...updated};
  actionNotice.value='取消请求已由服务端受理，正在等待任务进入取消终态。';
  await refreshAfterAction();
 }catch(error){if(!c.signal.aborted&&alive)actionFailure('取消',error)}
 finally{actionBusy.value=''}
}
async function runRetry(){
 const current=detail.value;
 if(!current||!view(current).canRetry)return;
 const c=beginAction();if(!c)return;
 actionBusy.value='retry';
 try{
  const updated=await retryAiTask(projectId,current.id,c.signal);
  if(!alive)return;
  if(detail.value?.id===updated.id)detail.value={...detail.value,...updated};
  actionNotice.value='继续生成请求已受理，任务状态以原 v60 任务 Owner 为准。';
  await refreshAfterAction();
 }catch(error){if(!c.signal.aborted&&alive)actionFailure('继续任务',error)}
 finally{actionBusy.value=''}
}
async function runRetryFailed(imageId:string){
 const current=detail.value;
 if(!current||!view(current).canRetry||actionBusy.value)return;
 const c=beginAction();if(!c)return;
 actionBusy.value='retry:'+imageId;
 try{
  const updated=await retryAiTask(projectId,current.id,c.signal,[imageId]);
  if(!alive)return;
  if(detail.value?.id===updated.id)detail.value={...detail.value,...updated};
  actionNotice.value='已提交该失败图片的合法重试；成功候选与其他草稿保持不变。';
  await refreshAfterAction();
 }catch(error){if(!c.signal.aborted&&alive)actionFailure('失败图片重试',error)}
 finally{actionBusy.value=''}
}
async function runRecoverReview(){
 const current=detail.value;
 if(!current||!view(current).canRecoverReview)return;
 const c=beginAction();if(!c)return;
 actionBusy.value='recover';
 try{
  await recoverAiTaskReview(projectId,current.id,c.signal);
  if(!alive)return;
  actionNotice.value='已恢复已保存的候选供人工审核；正式 GT 仍以原审核 Owner 为准。';
  enterReview();
 }catch(error){if(!c.signal.aborted&&alive)actionFailure('恢复审核',error)}
 finally{actionBusy.value=''}
}
function enterReview(){
 const id=detail.value?.id;
 if(!id)return;
 closeDetail();
 void router.push({name:'ai-review-native',params:{projectId,taskId:id}});
}
function locateMaterial(imageId:string){
 if(!imageId)return;
 closeDetail();
 void router.push({name:'materials',params:{projectId},query:{detail:imageId}});
}
onMounted(()=>void load());
</script>
<template><section class="ai-tasks" aria-label="AI 标注任务">
 <header><div><h2>AI 标注任务</h2></div><div class="ai-tasks-links"><el-button tag="router-link" type="primary" :to="createTarget">创建任务</el-button><el-button tag="router-link" :to="{name:'native-cleaning',params:{projectId}}">清洗任务</el-button><a :href="legacyHref">原完整自动标注</a></div></header>
 <el-alert v-if="typeof route.query.created==='string'" :title="`任务已创建：${route.query.created}`" type="success" :closable="false"/>
 <form @submit.prevent="search"><el-select v-model="status" aria-label="AI任务状态"><el-option label="全部状态" value=""/><el-option v-for="(name,code) in statuses" :key="code" :label="name" :value="code"/></el-select><el-button native-type="submit" type="primary" :disabled="reads.busy.tasks">查询</el-button><el-button :disabled="reads.busy.tasks" @click="load">刷新</el-button></form>
 <el-alert v-if="reads.errors.tasks" :title="reads.errors.tasks" type="error" :closable="false"/>
 <p v-if="reads.errors.tasks&&page" class="ai-tasks-note">下方为上次读取的快照，不能作为最新任务状态。</p>
 <el-alert v-if="page?.indexing" :title="`历史搜索索引准备中：已索引 ${shown(page.indexed)}，待处理 ${shown(page.remaining)}；当前空列表不代表没有任务。`" type="info" :closable="false"/>
 <el-alert v-else-if="page?.statistics_indexing" title="部分历史统计正在准备，失败数显示“未知”；稍后刷新。" type="info" :closable="false"/>
 <el-table v-loading="reads.busy.tasks" :data="page?.items||[]" row-key="id" empty-text="当前条件下没有 AI 标注任务" @row-click="openDetail">
  <el-table-column label="任务" min-width="220"><template #default="{row}"><strong>{{row.name||row.id}}</strong><small class="ai-tasks-secondary">{{row.id}}</small></template></el-table-column>
  <el-table-column label="状态" min-width="150"><template #default="{row}"><el-tag :type="tone(row.status)" effect="plain">{{label(row.status)}}</el-tag><small class="ai-tasks-secondary">{{row.phase||'阶段未提供'}}</small></template></el-table-column>
  <el-table-column label="进度" min-width="150"><template #default="{row}">{{progress(row)}}<small class="ai-tasks-secondary">已处理 {{shown(row.completed_count)}} / 总数 {{shown(row.total_count)}}</small></template></el-table-column>
  <el-table-column label="失败数" width="110"><template #default="{row}">{{shown(row.counts?.failed)}}</template></el-table-column>
  <el-table-column label="创建时间" min-width="180"><template #default="{row}">{{created(row.created_at)}}</template></el-table-column>
  <el-table-column label="操作" min-width="210"><template #default="{row}"><div class="ai-tasks-actions"><el-button link type="primary" @click.stop="openDetail(row)">查看进度</el-button><el-button v-if="view(row).canRetry" link @click.stop="openDetail(row)">继续任务</el-button><el-button v-if="view(row).canReview" link type="primary" @click.stop="router.push({name:'ai-review-native',params:{projectId,taskId:row.id}})">进入审核</el-button></div></template></el-table-column>
 </el-table>
 <footer v-if="page"><span>第 {{index+1}} 页 · 本页 {{page.items.length}} 条</span><el-button :disabled="index<1||reads.busy.tasks" @click="previous">上一页</el-button><el-button :disabled="!page.next_cursor||reads.busy.tasks" @click="next">下一页</el-button></footer>
 <el-dialog :model-value="detailOpen" title="AI 标注任务：进度与写操作" width="min(820px,100vw)" :append-to-body="false" :lock-scroll="false" @close="closeDetail">
  <el-skeleton v-if="detailBusy&&!detail" :rows="6" animated/>
  <el-alert v-else-if="detailError" :title="detailError" type="error" :closable="false"/>
  <template v-if="detail&&detailView">
   <div class="ai-detail-head"><el-tag :type="tone(detail.status)" effect="plain">{{detailView.statusText}}</el-tag><small>{{detail.name||detail.id}}</small></div>
   <el-progress :percentage="Math.max(0,Math.min(100,Math.round(detailView.percent)))"/>
   <p class="ai-detail-line">{{detailView.progressText}} · {{detailView.percent.toFixed(1)}}%<template v-if="detailView.runtimeText"> · {{detailView.runtimeText}}</template></p>
   <el-alert v-if="detailView.error" :title="detailView.error" type="warning" :closable="false"/>
   <ReadOnlyFacts :fields="detailFacts"/>
   <div class="ai-detail-actions">
    <el-button v-if="detailView.canCancel" type="danger" plain :loading="actionBusy==='cancel'" :disabled="!!actionBusy" @click="runCancel">取消任务</el-button>
    <el-button v-if="detailView.canRetry" type="primary" plain :loading="actionBusy==='retry'" :disabled="!!actionBusy" @click="runRetry">继续任务（合法重试）</el-button>
    <el-button v-if="detailView.canRecoverReview" :loading="actionBusy==='recover'" :disabled="!!actionBusy" @click="runRecoverReview">审核已完成（恢复审核）</el-button>
    <el-button v-if="detailView.canReview" type="primary" @click="enterReview">进入审核</el-button>
    <el-button :disabled="!!actionBusy" @click="loadDetail">刷新进度</el-button>
   </div>
   <p v-if="actionNotice" class="ai-action-notice" role="status">{{actionNotice}}</p>
   <el-alert v-if="actionError" :title="actionError" type="error" :closable="false"/>
   <h3 class="ai-failures-title">失败 / 未完成素材（{{failuresTotal}}）</h3>
   <el-alert v-if="failuresError" :title="failuresError" type="error" :closable="false"/>
   <el-table v-loading="failuresBusy" :data="failures" size="small" empty-text="没有可核验的失败素材（候选未生成或全部成功）">
    <el-table-column label="文件名" min-width="170"><template #default="{row}">{{row.filename||row.image_id}}</template></el-table-column>
    <el-table-column label="错误证据" min-width="220"><template #default="{row}">{{row.retry_suggestion||row.error||row.error_code||'未提供'}}</template></el-table-column>
    <el-table-column label="操作" width="200"><template #default="{row}"><el-button link type="primary" @click="locateMaterial(row.image_id)">在素材库定位</el-button><el-button v-if="detailView.canRetry" link :loading="actionBusy==='retry:'+row.image_id" :disabled="!!actionBusy" @click="runRetryFailed(row.image_id)">重试该图</el-button></template></el-table-column>
   </el-table>
   <el-button v-if="failuresNext" size="small" :disabled="failuresBusy" @click="loadFailures(failuresNext)">加载更多失败素材</el-button>
  </template>
  <template #footer><el-button @click="closeDetail">返回任务列表</el-button><el-button tag="a" :href="legacyHref">原工作台</el-button></template>
 </el-dialog>
</section></template>
<style scoped>
.ai-tasks{padding:24px}header,form,footer{display:flex;align-items:center;gap:12px;flex-wrap:wrap}header{justify-content:space-between}header h2{margin:0}header p{margin:6px 0 0;color:#777;font-size:13px;max-width:820px}.ai-tasks-links{display:flex;align-items:center;gap:12px}form{margin:20px 0}form .el-select{width:190px}footer{justify-content:flex-end;margin-top:16px}.ai-tasks-secondary{display:block;color:#777;font-size:12px;margin-top:4px;overflow-wrap:anywhere}.ai-tasks-note{font-size:13px;color:#955323}.ai-tasks-actions{display:flex;flex-direction:column;align-items:flex-start;gap:2px}.ai-tasks-actions :deep(.el-button){margin:0}.ai-tasks :deep(.el-table__row){cursor:pointer}.ai-detail-head{display:flex;align-items:center;gap:10px;margin-bottom:10px}.ai-detail-head small{color:#777;overflow-wrap:anywhere}.ai-detail-line{font-size:13px;color:#475569}.ai-detail-actions{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}.ai-detail-actions :deep(.el-button){margin:0}.ai-action-notice{font-size:13px;color:#166534}.ai-failures-title{margin:18px 0 8px;font-size:15px}
</style>
