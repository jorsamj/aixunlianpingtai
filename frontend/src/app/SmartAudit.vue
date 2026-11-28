<script setup lang="ts">
import {computed,onBeforeUnmount,ref} from 'vue';
import {useReadScope} from '../composables/useReadScope';
import {request} from './http';
import {getMaterialBatch,manageMaterialBatch,type MaterialBatchTask} from '../api/material-batches';
import TaskStatusTag from '../components/TaskStatusTag.vue';

// Native projection of the existing smart-material-audit owner (platform_core/
// smart_material_audit). This page never analyses images itself: it only reads the
// original estimate/task/findings projections and posts the original review receipt.
const {projectId}=defineProps<{projectId:string}>();
const controller=new AbortController(),reads=useReadScope(controller);
onBeforeUnmount(()=>controller.abort());
const root=encodeURIComponent(projectId);
const base=`/api/v62/projects/${root}/smart-material-audit`;

interface AuditStatus {enabled?:boolean;max_images?:number;feature?:string;environment_validation?:string;read_only?:boolean;message?:string}
interface AuditEstimate {operation?:string;count?:number;total?:number;max_images?:number;selection_spec?:Record<string,unknown>;supported?:boolean;read_only?:boolean}
interface AuditTask extends MaterialBatchTask {attempt?:number;result_ready?:boolean;smart_audit_progress?:{stage?:string;prepared?:number;failed?:number;total?:number}|null}
interface FindingInput {filename?:string;content_sha256?:string;annotation_version?:number|null;frozen_split?:string|null}
interface Finding {
  issue_id:string;image_id:string;related_image_id?:string|null;issue_type:string;
  inputs?:Record<string,FindingInput>;
  current_identity?:Record<string,{content_sha256?:string|null;annotation_version?:number|null}>;
  review_token:string;stale?:boolean;review_valid?:boolean;requires_confirmation?:boolean;
  review?:{verdict?:string;note?:string;actor_id?:string;reviewed_at?:string}|null;
  evidence?:Record<string,unknown>;
}
interface FindingsPage {
  task_id:string;project_id:string;
  items:Finding[];total:number;offset:number;limit:number;generation:number;historical_generation?:boolean;
  review_counts?:Record<string,number>;counts?:Record<string,number>;
  checks?:Record<string,{status?:string;reason?:string;checked?:number}>;
  annotation_summary?:Record<string,number|string|null>;
}
// Same vocabulary as the original workbench; unknown issue types stay verbatim.
const issueNames:Record<string,string>={visual_similarity:'视觉相似',same_sha_reference:'同内容引用',
  cross_split_leakage:'冻结划分泄漏',suspected_annotation:'疑似错标',unverified:'未检查'};
const checkNames:Record<string,string>={visual_similarity:'视觉相似性',leakage:'冻结划分泄漏',
  mistakenness:'疑似错标',hardness:'困难度'};
const checkText:Record<string,string>={completed:'已检查',partial:'部分检查',not_checked:'未检查',computed:'已计算',skipped:'未执行',failed:'检查失败'};
const verdictNames:Record<string,string>={confirmed_issue:'确认存在问题',no_issue:'无需修改',corrected:'已修正',unknown:'暂无法确认',stale:'已失效',pending:'待复核'};
const PAGE=25;

const status=ref<AuditStatus|null>(null),estimate=ref<AuditEstimate|null>(null);
const task=ref<AuditTask|null>(null),page=ref<FindingsPage|null>(null),selected=ref<Finding|null>(null);
const issueType=ref(''),offset=ref(0),notice=ref(''),error=ref('');
const writeBusy=ref(''),createError=ref('');
const models=ref<{algorithm_id:string;version_id:string;label:string}[]>([]),modelCursor=ref<string|null>(null);
const model=ref('');
// Stable request identity: the original endpoint derives the durable task id from
// (project, request_id) and rejects the same id with different scope. The packet is
// kept in sessionStorage so a refresh retries the *same* request instead of a new one.
const requestScope=`smart-audit.request:${projectId}`;
const pending=ref<{request_id:string;selection_spec:Record<string,unknown>;options:Record<string,unknown>}|null>(null);
try{const saved=sessionStorage.getItem(requestScope);if(saved)pending.value=JSON.parse(saved)}catch{pending.value=null}

const modelLabel=computed(()=>{
  const chosen=models.value.find(row=>`${row.algorithm_id}:${row.version_id}`===model.value);
  return chosen?.label||'';
});
const reviewCounts=computed(()=>Object.entries(page.value?.review_counts||{})
  .filter(([,count])=>Number(count)>0)
  .map(([key,count])=>`${verdictNames[key]||key} ${count}`).join(' / '));
const checkRows=computed(()=>Object.entries(page.value?.checks||{})
  .map(([key,value])=>({key,label:checkNames[key]||key,state:checkText[String(value.status||'')]||String(value.status||'未提供'),reason:value.reason||''})));

function loadStatus(){
  return reads.run('status',signal=>request<AuditStatus>(`${base}/status`,{signal}),value=>{status.value=value});
}
function previewScope(){
  estimate.value=null;createError.value='';notice.value='';
  return reads.run('estimate',signal=>request<AuditEstimate>(`${base}/estimate`,{method:'POST',signal,
    // The server owns the scope limit; the browser never enumerates the library.
    body:JSON.stringify({selection_spec:{scope:'FILTERED',filters:{}}})}),value=>{
    if(value.operation!=='SMART_AUDIT'||typeof value.count!=='number'||!value.selection_spec)
      throw new Error('分析范围预检响应不完整');
    estimate.value=value;
  });
}
function remember(packet:typeof pending.value){
  pending.value=packet;
  try{packet?sessionStorage.setItem(requestScope,JSON.stringify(packet)):sessionStorage.removeItem(requestScope)}catch{/* storage is advisory */}
}
// One write at a time, and the local lock is always released: every write goes
// through this wrapper so a failure, an abort or an unknown result cannot leave
// the page permanently busy. `after` runs only on success, after the lock is
// free, which is what lets the review refresh the candidate page.
function writeOnce<T>(busy:string,key:string,read:(signal:AbortSignal)=>Promise<T>,apply:(value:T)=>void,after?:()=>void){
  if(writeBusy.value)return Promise.resolve();
  writeBusy.value=busy;
  let applied=false;
  return reads.run(key,read,value=>{apply(value);applied=true})
    .finally(()=>{writeBusy.value='';if(applied&&after)after()});
}
function createAudit(){
  const current=estimate.value;
  if(!current?.selection_spec||writeBusy.value)return;
  if(!window.confirm(`对当前范围 ${current.count??0} 张素材创建只读智能分析任务？`))return;
  const packet=pending.value??{request_id:crypto.randomUUID(),
    selection_spec:current.selection_spec,
    options:{...(model.value?{algorithm_id:model.value.split(':')[0],version_id:model.value.split(':')[1]}:{})}};
  remember(packet);
  createError.value='';notice.value='';
  void writeOnce('create','create',signal=>request<AuditTask>(base,{method:'POST',signal,body:JSON.stringify(packet)}),value=>{
    const id=String(value.id||'');
    if(value.project_id!==projectId||value.operation!=='SMART_AUDIT'||!/^smart_[a-f0-9]{32}$/.test(id))
      throw new Error('分析任务回执身份不完整');
    task.value=value;remember(null);notice.value='已受理只读智能分析任务；结果以服务端任务与候选记录为准。';
  });
}
function openTask(row:AuditTask|{id:string}){
  selected.value=null;page.value=null;offset.value=0;issueType.value='';
  return reads.run('task',signal=>getMaterialBatch(projectId,row.id,signal),value=>{
    if(value.id!==row.id||value.operation!=='SMART_AUDIT')throw new Error('分析任务身份不一致');
    task.value=value as AuditTask;
  });
}
function loadFindings(next=offset.value){
  const current=task.value;
  if(!current||writeBusy.value)return;
  return reads.run('findings',async signal=>{
    const item=await getMaterialBatch(projectId,current.id,signal);
    const value=await request<FindingsPage>(`${base}/${encodeURIComponent(current.id)}/findings?`+new URLSearchParams({
      offset:String(next),limit:String(PAGE),...(issueType.value?{issue_type:issueType.value}:{}),
    }),{signal});
    return {value,attempt:(item as AuditTask).attempt??0,resultReady:!!(item as AuditTask).result_ready};
  },result=>{
    const value=result.value;
    if(value.task_id!==current.id||value.project_id!==projectId)throw new Error('分析候选范围与任务不一致');
    if(value.items.length>PAGE)throw new Error('分析候选分页超出边界');
    task.value={...current,attempt:result.attempt,result_ready:result.resultReady};
    page.value=value;offset.value=value.offset;
    if(selected.value&&!value.items.some(row=>row.issue_id===selected.value?.issue_id)){selected.value=null}
  });
}
function openFinding(row:Finding){
  const current=task.value;
  if(!current)return;
  return reads.run('finding',signal=>request<Finding>(
    `${base}/${encodeURIComponent(current.id)}/findings/${encodeURIComponent(row.issue_id)}?generation=${current.attempt??0}`,{signal}),
  value=>{
    if(value.issue_id!==row.issue_id)throw new Error('分析候选身份不一致');
    selected.value=value;
  });
}
function review(verdict:'confirmed_issue'|'no_issue'|'unknown'|'corrected'){
  const current=task.value,item=selected.value;
  if(!current||!item||writeBusy.value)return;
  if(!window.confirm(`记录人工复核结论「${verdictNames[verdict]}」？本操作只保存复核回执，不改写正式标注。`))return;
  error.value='';notice.value='';
  void writeOnce('review','review',signal=>request<Finding>(
    `${base}/${encodeURIComponent(current.id)}/findings/${encodeURIComponent(item.issue_id)}/review`,
    {method:'POST',signal,body:JSON.stringify({verdict,expected_generation:current.attempt??0,
      expected_review_token:item.review_token,note:note.value.slice(0,1000)})}),value=>{
    selected.value=value;notice.value='复核回执已记录；正式 GT 只在原标注入口保存。';note.value='';
  },()=>{void loadFindings()});
}
const note=ref('');
function loadModels(cursor=''){
  return reads.run('models',signal=>request<{items:{algorithm_id:string;version_id:string;label:string}[];next_cursor:string|null;enabled?:boolean}>(
    `${base}/models?`+new URLSearchParams({limit:'25',...(cursor?{cursor}:{})}),{signal}),value=>{
    if(!Array.isArray(value.items)||value.items.length>25)throw new Error('可选模型分页无效');
    models.value=cursor?[...models.value,...value.items]:value.items;
    modelCursor.value=value.next_cursor||null;
  });
}
function cancelTask(){
  const current=task.value;
  if(!current||writeBusy.value)return;
  if(!window.confirm('请求取消该只读智能分析任务？'))return;
  error.value='';notice.value='';
  void writeOnce('cancel','cancel',signal=>manageMaterialBatch(projectId,current.id,'cancel',signal),value=>{
    if(value.id!==current.id)throw new Error('取消回执与当前任务不一致');
    task.value=value as AuditTask;notice.value='取消请求已受理，最终状态以服务端任务记录为准。';
  });
}
function retryTask(){
  const current=task.value;
  if(!current||writeBusy.value)return;
  if(!window.confirm('按原范围重试该只读智能分析任务？'))return;
  error.value='';notice.value='';
  void writeOnce('retry','retry',signal=>request<AuditTask>(`${base}/${encodeURIComponent(current.id)}/retry`,{method:'POST',signal}),value=>{
    if(value.id!==current.id)throw new Error('重试回执与当前任务不一致');
    task.value=value;notice.value='已按原任务身份重试；历史结果不会冒充本次结果。';
  });
}
function thumbnail(id:string){return `/api/v61/projects/${root}/materials/${encodeURIComponent(id)}/content/thumbnail?edge=128`}
function imageContent(id:string){return `/api/v61/projects/${root}/materials/${encodeURIComponent(id)}/content`}
const params={projectId};
const canCreate=computed(()=>status.value?.enabled===true&&!!estimate.value&&!writeBusy.value);
const canRetry=computed(()=>['FAILED','CANCELLED','PARTIAL_SUCCESS','BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE'].includes(String(task.value?.status||'')));
const canCancel=computed(()=>['QUEUED','WAITING_RESOURCE','RUNNING','CANCEL_REQUESTED'].includes(String(task.value?.status||'')));
loadStatus();
</script>

<template>
 <section class="smart-audit" aria-label="智能审计">
  <header class="audit-head">
   <div><h3>智能审计（只读分析）</h3><p class="audit-note">分析在后台任务中执行，结论只作人工复核线索；不改写正式标注、不删除素材、不参与训练准入。</p></div>
   <div class="audit-actions">
    <el-button :loading="reads.busy.status" @click="loadStatus">读取分析配置</el-button>
    <el-button :loading="reads.busy.estimate" :disabled="status?.enabled!==true" @click="previewScope">预览分析范围</el-button>
    <el-button type="primary" :loading="reads.busy.create" :disabled="!canCreate" @click="createAudit">{{pending?'重试原分析请求':'创建只读分析'}}</el-button>
   </div>
  </header>
  <el-alert v-if="reads.errors.status" :title="reads.errors.status" type="error" :closable="false"/>
  <el-alert v-if="status&&status.enabled!==true" :title="status.message||'智能分析未启用，原清洗、审核、标注和训练不受影响'" type="info" :closable="false"/>
  <p v-if="status?.enabled===true" class="audit-note">分析上限 {{status.max_images??'未提供'}} 张 · 特征 {{status.feature||'未提供'}} · 运行环境校验 {{status.environment_validation||'未提供'}}（实际环境由任务执行核验）</p>
  <el-alert v-if="reads.errors.estimate" :title="reads.errors.estimate" type="warning" :closable="false"/>
  <p v-if="estimate" class="audit-note">本次范围 {{estimate.count??0}} 张（服务端上限 {{estimate.max_images??'未提供'}}）。分析范围由服务端按当前素材修订冻结。</p>
  <el-alert v-if="reads.errors.create||createError" :title="reads.errors.create||createError" type="error" :closable="false"/>
  <el-alert v-if="error||reads.errors.cancel||reads.errors.retry" :title="error||reads.errors.cancel||reads.errors.retry" type="error" :closable="false"/>
  <p v-if="notice" role="status" class="audit-note">{{notice}}</p>

  <section class="audit-panel">
   <header class="audit-actions">
    <strong>可选模型证据</strong>
    <el-select v-model="model" aria-label="分析模型" clearable placeholder="不使用模型证据" style="width:min(100%,320px)">
     <el-option label="不使用模型证据" value=""/>
     <el-option v-for="row in models" :key="row.algorithm_id+':'+row.version_id" :label="row.label" :value="row.algorithm_id+':'+row.version_id"/>
    </el-select>
    <el-button size="small" :loading="reads.busy.models" @click="loadModels()">读取可信评测版本</el-button>
    <el-button size="small" :disabled="!modelCursor||reads.busy.models" @click="loadModels(modelCursor||'')">更多模型</el-button>
   </header>
   <p class="audit-note">不选择可信评测版本时，错标与冻结划分泄漏保持“未检查”，不会默认为正常。{{model?`当前选择：${modelLabel}`:''}}</p>
   <el-alert v-if="reads.errors.models" :title="reads.errors.models" type="warning" :closable="false"/>
  </section>

  <section v-if="task" class="audit-panel">
   <header class="audit-actions">
    <strong>分析任务 {{task.id}}</strong>
    <TaskStatusTag :status="String(task.status||'')"/>
    <span class="audit-note">代际 {{task.attempt??'未提供'}} · 结果{{task.result_ready?'已生成':'未生成'}}</span>
    <el-button size="small" :loading="reads.busy.task" @click="openTask(task)">刷新任务</el-button>
    <el-button size="small" :disabled="!canCancel||!!writeBusy" :loading="writeBusy==='cancel'" @click="cancelTask">取消分析</el-button>
    <el-button size="small" :disabled="!canRetry||!!writeBusy" :loading="writeBusy==='retry'" @click="retryTask">按原范围重试</el-button>
   </header>
   <p v-if="task.smart_audit_progress" class="audit-note">准备 {{task.smart_audit_progress.prepared??0}} / {{task.smart_audit_progress.total??'未提供'}} · 失败 {{task.smart_audit_progress.failed??0}}<template v-if="task.smart_audit_progress.stage"> · 阶段 {{task.smart_audit_progress.stage}}</template></p>
   <p v-if="task.error_examples?.length" class="audit-note">失败样例：{{task.error_examples.map(row=>row.error).join('；')}}</p>
   <div class="audit-actions">
    <el-select v-model="issueType" aria-label="候选类型" clearable placeholder="全部候选" style="width:170px" @change="loadFindings(0)">
     <el-option label="全部候选" value=""/>
     <el-option v-for="(name,key) in issueNames" :key="key" :label="name" :value="key"/>
    </el-select>
    <el-button size="small" :loading="reads.busy.findings" @click="loadFindings(offset)">读取候选</el-button>
    <span class="audit-note" v-if="page">候选 {{page.total}} 条 · 第 {{Math.floor(page.offset/page.limit)+1}} 页<template v-if="reviewCounts"> · 复核 {{reviewCounts}}</template></span>
   </div>
   <el-alert v-if="reads.errors.findings||reads.errors.task" :title="reads.errors.findings||reads.errors.task" type="warning" :closable="false"/>
   <p v-if="page?.historical_generation" class="audit-note">当前展示历史代际结果，不是本次分析结论。</p>
   <div v-if="checkRows.length" class="audit-checks">
    <span v-for="row in checkRows" :key="row.key">{{row.label}}：{{row.state}}<template v-if="row.reason">（{{row.reason}}）</template></span>
   </div>
   <p v-if="page?.annotation_summary" class="audit-note">错标候选 {{page.annotation_summary.suspected_images??'未检查'}} 张 · 可能漏标 {{page.annotation_summary.possible_missing_boxes??'未检查'}} 框 · 可能多标 {{page.annotation_summary.possible_spurious_boxes??'未检查'}} 框 · 未检查素材 {{page.annotation_summary.annotation_not_checked_images??'未提供'}} 张</p>
   <div class="audit-columns">
    <aside class="audit-list">
     <p v-if="!page" class="audit-note">尚未读取候选结果。</p>
     <p v-else-if="!page.items.length" class="audit-note">当前筛选没有候选；未检查项仍为未检查，不代表全库无问题。</p>
     <button v-for="row in page?.items||[]" :key="row.issue_id" type="button" :aria-current="selected?.issue_id===row.issue_id"
      :class="['audit-row',{active:selected?.issue_id===row.issue_id}]" @click="openFinding(row)">
      <img v-if="row.image_id" :src="thumbnail(row.image_id)" :alt="row.inputs?.[row.image_id]?.filename||row.image_id" loading="lazy">
      <span><b>{{issueNames[row.issue_type]||row.issue_type}}</b><small>{{row.image_id}}<template v-if="row.related_image_id"> ↔ {{row.related_image_id}}</template></small>
      <small>{{row.stale?'证据已变化，需复核':row.review_valid?'已人工复核':'待人工复核'}}</small></span>
     </button>
     <div class="audit-actions">
      <el-button size="small" :disabled="offset===0||reads.busy.findings" @click="loadFindings(Math.max(0,offset-PAGE))">上一页</el-button>
      <el-button size="small" :disabled="!page||offset+PAGE>=page.total||reads.busy.findings" @click="loadFindings(offset+PAGE)">下一页</el-button>
     </div>
    </aside>
    <main class="audit-detail">
     <p v-if="!selected" class="audit-note">请选择一条分析候选。建议仅供人工复核，不影响正式清洗或评测指标。</p>
     <template v-else>
      <h4>{{issueNames[selected.issue_type]||selected.issue_type}}</h4>
      <p class="audit-note">{{selected.stale?'原图或正式标注证据已改变，请重新检查。':'复核身份与当前图片内容、标注版本绑定。'}}</p>
      <div class="audit-images">
       <figure v-for="image in [selected.image_id,selected.related_image_id].filter(Boolean) as string[]" :key="image">
        <img :src="imageContent(image)" :alt="image"><figcaption>{{selected.inputs?.[image]?.filename||image}}</figcaption>
       </figure>
      </div>
      <p class="audit-note">标注版本（分析时）{{selected.inputs?.[selected.image_id]?.annotation_version??'未提供'}} → 当前 {{selected.current_identity?.[selected.image_id]?.annotation_version??'未提供'}}</p>
      <details><summary>分析证据</summary><pre>{{selected.evidence}}</pre></details>
      <div class="audit-actions">
       <router-link :to="{name:'formal-annotation',params,query:{image:selected.image_id,back:`/projects/${projectId}/quality?tab=audit`}}">打开标注并保存修正</router-link>
       <router-link :to="{name:'materials',params,query:{detail:selected.image_id}}">素材详情</router-link>
      </div>
      <h4>人工复核</h4>
      <p class="audit-note">复核只记录结论回执，不修改正式标注；“已修正”需要先在原标注入口保存新的正式 GT 版本。</p>
      <el-input v-model="note" type="textarea" :rows="2" maxlength="1000" aria-label="复核备注" placeholder="复核备注（可选）"/>
      <div class="audit-actions">
       <el-button size="small" :loading="writeBusy==='review'" :disabled="!!writeBusy" @click="review('confirmed_issue')">确认存在问题</el-button>
       <el-button size="small" :loading="writeBusy==='review'" :disabled="!!writeBusy" @click="review('no_issue')">无需修改</el-button>
       <el-button size="small" :loading="writeBusy==='review'" :disabled="!!writeBusy" @click="review('unknown')">暂无法确认</el-button>
       <el-button size="small" :loading="writeBusy==='review'" :disabled="!!writeBusy" @click="review('corrected')">已保存修正</el-button>
      </div>
      <p v-if="selected.review" class="audit-note">最近复核：{{verdictNames[selected.review.verdict||'']||selected.review.verdict||'未提供'}} · {{selected.review.actor_id||'未记录人员'}} · {{selected.review.reviewed_at||''}}{{selected.review_valid?'':'（已失效，需重新核验）'}}<template v-if="selected.review.note"> · {{selected.review.note}}</template></p>
      <el-alert v-if="reads.errors.finding||reads.errors.review" :title="reads.errors.finding||reads.errors.review" type="warning" :closable="false"/>
     </template>
    </main>
   </div>
  </section>
 </section>
</template>

<style scoped>
.smart-audit{display:grid;gap:12px;min-width:0}
.audit-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}
.audit-head h3{margin:0 0 4px;font-size:16px}
.audit-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0}
.audit-actions :deep(.el-button+.el-button){margin-left:0}
.audit-note{margin:4px 0;font-size:12px;color:var(--workspace-muted,#52525b);overflow-wrap:anywhere}
.audit-panel{border:1px solid var(--workspace-line,#e4e4e7);border-radius:var(--workspace-radius,8px);padding:14px;min-width:0}
.audit-checks{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--workspace-muted,#52525b);margin:6px 0}
.audit-columns{display:grid;grid-template-columns:minmax(220px,300px) minmax(0,1fr);gap:14px;margin-top:8px}
.audit-list{display:grid;gap:6px;align-content:start;min-width:0;max-height:520px;overflow:auto}
.audit-row{display:flex;gap:8px;align-items:center;width:100%;padding:6px;border:1px solid transparent;border-radius:6px;background:transparent;color:inherit;text-align:left;cursor:pointer}
.audit-row.active{border-color:var(--el-color-primary);background:var(--workspace-hover,#f4f4f5)}
.audit-row img{width:64px;height:44px;object-fit:contain;background:var(--workspace-page,#f7f8fa);flex:none}
.audit-row span{display:grid;min-width:0}
.audit-row small{color:var(--workspace-subtle,#686872);font-size:11px;overflow-wrap:anywhere}
.audit-detail{min-width:0}
.audit-detail h4{margin:10px 0 4px;font-size:14px}
.audit-images{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0}
.audit-images figure{margin:0;min-width:0;max-width:280px}
.audit-images img{max-width:100%;background:var(--workspace-page,#f7f8fa);border:1px solid var(--workspace-line,#e4e4e7);border-radius:6px}
.audit-images figcaption{font-size:11px;color:var(--workspace-subtle,#686872);overflow-wrap:anywhere}
.audit-detail pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto;font-size:12px}
</style>
