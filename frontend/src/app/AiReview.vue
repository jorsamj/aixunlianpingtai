<script setup lang="ts">
import {computed,defineAsyncComponent,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue';
import {onBeforeRouteLeave,onBeforeRouteUpdate} from 'vue-router';
import {readWorkspaceSession,useWorkspace,workspaceActorKey} from './main';
import {legacyUrl} from './navigation';
import {login} from './http';
import {reviewFilters} from '../api/ai-review';
import type {ReviewCandidate} from '../api/ai-review';
import {canAdopt,hasUnresolvedAmbiguity} from '../stores/ai-review-decision';
import {useAiReviewStore} from '../stores/ai-review';
import MaterialPreview from '../components/MaterialPreview.vue';

const props=defineProps<{projectId:string;taskId:string}>();
const workspace=useWorkspace(),review=useAiReviewStore();
const NativeAiCandidateEditor=defineAsyncComponent(()=>import('./NativeAiCandidateEditor.vue'));
const editor=ref<{canLeave():boolean;suspend(value:boolean):void;hasUnresolved():boolean}>();
const editing=ref<string>();
const editScope=computed(()=>({projectId:props.projectId,taskId:props.taskId}));
const checkedScope=ref<string[]>([]);
watch([()=>review.item?.image_id,()=>review.item?.draft_revision,()=>review.item?.accepted],()=>{checkedScope.value=[]});
const scopeOptions=computed(()=>review.item?.review_scope_policy==='per_image_required'
  ?[...new Set(review.item.missing_review_scope??[])].filter(code=>typeof code==='string'&&code.trim()===code&&code)
  :[]);
const adoptAvailable=computed(()=>!!review.item&&canAdopt(review.item,checkedScope.value));
const canEdit=computed(()=>review.task?.status.toUpperCase()==='AWAITING_CONFIRMATION'
  &&!review.decision&&!review.decisionBusy&&!review.itemBusy&&!review.itemError&&['success','empty'].includes(review.item?.status||'')
  &&review.item?.review_state==='active'&&!review.item.gt_committed);
const canLeave=()=>editor.value?.canLeave()??true;
onBeforeRouteLeave(canLeave);
onBeforeRouteUpdate((to,from)=>to.path===from.path||canLeave());
function beforeUnload(event:BeforeUnloadEvent){
  if(editor.value?.hasUnresolved()){event.preventDefault();event.returnValue=''}
}
function beforeLogout(event:Event){if(!canLeave())event.preventDefault()}
function closeEditor(){
  editor.value?.suspend(true);editing.value=undefined;review.checkDraftOutstanding();
}
function decide(accepted:boolean){
  if(!editing.value)void review.decide(accepted,checkedScope.value);
}
const layout=ref<'grid'|'list'>('grid'),original=ref(false);
const inspectorTitle=ref<HTMLElement>(),focusReturn=ref<HTMLButtonElement>();
const legacy=computed(()=>legacyUrl(props.projectId,'自动标注及清洗'));
const sessionError=ref('');
let sessionRead:AbortController|undefined;

function open(){
  sessionError.value='';
  if(!document.hidden&&workspace.actorKey)void review.open({
    projectId:props.projectId,taskId:props.taskId,actorKey:workspace.actorKey,
  });
}
watch([()=>props.projectId,()=>props.taskId,()=>workspace.actorKey],()=>{
  sessionRead?.abort();
  closeEditor();
  review.reset();
  open();
},{immediate:true,flush:'sync'});
async function verifySession(){
  sessionRead?.abort();
  if(editing.value)editor.value?.suspend(true);
  else review.reset();
  if(document.hidden)return;
  const controller=sessionRead=new AbortController();
  sessionError.value='';
  try{
    const session=await readWorkspaceSession(controller.signal);
    if(controller.signal.aborted)return;
    if(!session.authenticated){login();return}
    if(workspaceActorKey(session)!==workspace.actorKey){closeEditor();review.reset();location.reload();return}
    if(editing.value)editor.value?.suspend(false);
    else open();
  }catch(cause){
    if(!controller.signal.aborted)sessionError.value=(cause as Error).message;
  }
}
function release(){
  sessionRead?.abort();
  closeEditor();
  review.reset();
}
function restore(event:PageTransitionEvent){if(event.persisted)void verifySession()}
onMounted(()=>{
  document.addEventListener('visibilitychange',verifySession);
  window.addEventListener('beforeunload',beforeUnload);
  window.addEventListener('workspace-before-logout',beforeLogout);
  window.addEventListener('pagehide',release);
  window.addEventListener('pageshow',restore);
});
onBeforeUnmount(()=>{
  document.removeEventListener('visibilitychange',verifySession);
  window.removeEventListener('beforeunload',beforeUnload);
  window.removeEventListener('workspace-before-logout',beforeLogout);
  window.removeEventListener('pagehide',release);
  window.removeEventListener('pageshow',restore);
  release();
});

const statusNames:Record<string,string>={AWAITING_CONFIRMATION:'待人工审核',QUEUED:'排队中',RUNNING:'处理中',
  CANCEL_REQUESTED:'已请求取消',CANCELLED:'已取消',SUCCEEDED:'已完成',PARTIAL_SUCCESS:'部分成功',FAILED:'失败',BLOCKED:'已阻断'};
const taskStatus=computed(()=>{
  const status=review.task?.status||'';
  return statusNames[status.toUpperCase()]||status;
});
const candidateName=(row:ReviewCandidate)=>(row.filename||row.image_id).split(/[\\/]/).at(-1)||row.image_id;
function candidateStatus(row:ReviewCandidate){
  if(row.gt_committed)return '已正式入库';
  if(row.review_state==='transferred')return '已转池';
  if(row.review_state==='pending_transfer')return '转池待恢复';
  if(row.review_state==='blocked')return '已阻断';
  if(row.status==='failed')return '失败';
  if(row.accepted===false)return '已拒绝候选';
  if(row.accepted===true)return '已采用候选';
  if(hasUnresolvedAmbiguity(row))return '待消歧';
  if(!['success','empty'].includes(row.status))return '未生成候选';
  return '待人工审核';
}
function media(row:ReviewCandidate){
  const content_url='/api/v61/projects/'+encodeURIComponent(props.projectId)+'/materials/'+encodeURIComponent(row.image_id)+'/content';
  return {id:row.image_id,filename:candidateName(row),width:row.width,height:row.height,content_url,
    thumbnail_url:content_url+'/thumbnail?edge=384'};
}
function readImage(row:ReviewCandidate,event:MouseEvent){
  focusReturn.value=event.currentTarget as HTMLButtonElement;
  original.value=false;
  void review.inspect(row);
  void nextTick(()=>inspectorTitle.value?.focus());
}
function closeImage(){
  review.closeImage();
  focusReturn.value?.focus();
}
const displayedBoxes=computed(()=>original.value?review.item?.original_boxes:review.item?.boxes);
const diagnosticFacts=computed(()=>{
  const evidence=review.diagnostics?.diagnostics;
  const counts=evidence?.counts;
  return [
    ['模型',evidence?.model_name||evidence?.model],['适配器',evidence?.provider||evidence?.adapter],
    ['诊断状态',evidence?.status],['耗时（ms）',evidence?.latency_ms],['输出协议',evidence?.contract?.output_protocol],
    ['坐标空间',evidence?.contract?.coordinate_space],['坐标顺序',evidence?.contract?.coordinate_order],
    ['原始候选',counts?.raw],['非法框',counts?.invalid],['阈值淘汰',counts?.threshold_filtered],
    ['NMS 淘汰',counts?.nms_filtered],['最终候选',counts?.final],
  ].filter(([,value])=>value!=null&&value!=='');
});
</script>

<template>
 <section class="review-workspace" aria-label="原生 AI 候选审核">
  <header class="review-heading">
   <div><h2>{{ review.task?.name || '候选审核' }}</h2>
    <p>任务 {{ taskId }} <template v-if="taskStatus"> · {{ taskStatus }}</template></p>
   </div>
   <el-button tag="a" :href="legacy">返回原工作台</el-button>
  </header>
  <div v-if="sessionError" role="alert" class="review-notice">
   {{ sessionError }} <el-button @click="verifySession()">重试会话核验</el-button>
  </div>
  <NativeAiCandidateEditor v-if="editing" ref="editor" :key="editing" :image-id="editing"
   :scope="editScope" :actor-key="workspace.actorKey" @close="closeEditor" @saved="review.refreshAfterDraft" />
  <div v-else-if="review.taskError" role="alert" class="review-notice">
   {{ review.taskError }} <el-button @click="open()">重试</el-button>
  </div>
  <p v-else-if="!review.task && !sessionError" role="status" class="review-notice">正在核验任务…</p>
  <template v-else-if="review.task">
   <p v-if="review.task.error || review.task.generation_interruption_code" class="review-notice" role="status">
    {{ review.task.error || review.task.generation_interruption_code }}
   </p>
   <div class="review-columns">
    <nav aria-label="候选筛选" class="review-filters">
     <h3>审核范围</h3>
     <button v-for="[key,label] in reviewFilters.slice(0,5)" :key="key" type="button"
      :disabled="review.pageBusy" :aria-pressed="review.filter===key" @click="review.setFilter(key)">
      {{ label }} <span v-if="review.page?.summary?.[key]!=null">{{ review.page.summary[key] }}</span>
     </button>
     <details><summary>更多筛选</summary>
      <button v-for="[key,label] in reviewFilters.slice(5)" :key="key" type="button"
       :disabled="review.pageBusy" :aria-pressed="review.filter===key" @click="review.setFilter(key)">
       {{ label }} <span v-if="review.page?.summary?.[key]!=null">{{ review.page.summary[key] }}</span>
      </button>
     </details>
    </nav>
    <section class="review-results" aria-label="候选结果" :aria-busy="review.pageBusy">
     <div class="review-toolbar">
      <h3>候选图片 <small v-if="review.page && !review.page.task_error">{{ review.page.total }} 张</small></h3>
      <div role="group" aria-label="显示方式">
       <button :aria-pressed="layout==='grid'" @click="layout='grid'">网格</button>
       <button :aria-pressed="layout==='list'" @click="layout='list'">列表</button>
      </div>
     </div>
     <p v-if="review.pageBusy" role="status">正在读取候选…</p>
     <div v-else-if="review.pageError" role="alert">{{ review.pageError }} <el-button @click="review.reloadPage()">重试</el-button></div>
     <div v-else-if="review.page?.task_error" role="status">{{ review.page.task_error.message }}
      <el-button @click="open">重新读取任务</el-button>
     </div>
     <p v-else-if="!review.page?.items.length" role="status">当前筛选没有候选图片。</p>
     <div v-else class="review-cards" :class="layout">
      <article v-for="row in review.page.items" :key="row.image_id" class="review-candidate">
       <MaterialPreview :image="media(row)" :project-id="projectId" :boxes="row.boxes?.slice(0,32)" />
       <div class="review-candidate-caption">
        <button class="review-image-link" :aria-current="review.item?.image_id===row.image_id ? 'true' : undefined"
         @click="readImage(row,$event)">{{ candidateName(row) }}</button>
        <span>{{ candidateStatus(row) }} · {{ row.boxes?.length ?? 0 }} 框</span>
       </div>
      </article>
     </div>
     <footer v-if="review.page && !review.page.task_error" class="review-pagination">
      <el-button :disabled="review.pageNumber===1 || review.pageBusy" @click="review.previousPage()">上一页</el-button>
      <span>第 {{ review.pageNumber }} 页 · 每页 24 张</span>
      <el-button :disabled="!review.page.next_cursor || review.pageBusy" @click="review.nextPage()">下一页</el-button>
     </footer>
    </section>
    <aside class="review-inspector" :class="{open:review.item}" aria-label="当前图片检查" @keydown.esc="closeImage">
     <div class="review-toolbar">
      <h3 ref="inspectorTitle" tabindex="-1">当前图片检查</h3>
      <el-button v-if="review.item" text @click="closeImage">关闭检查</el-button>
     </div>
     <p v-if="!review.item">选择候选图片查看候选框和诊断。</p>
     <template v-else>
      <h4>{{ candidateName(review.item) }} · {{ review.decision?.status==='pending' ? '审核结果待核验' : candidateStatus(review.item) }}</h4>
      <div class="review-actions" role="group" aria-label="单图审核">
       <el-button v-if="canEdit" @click="editing=review.item.image_id">编辑候选</el-button>
       <el-button :disabled="!review.decisionEligible || !adoptAvailable || review.item.accepted===true"
        @click="decide(true)">采用候选</el-button>
       <el-button :disabled="!review.decisionEligible || review.item.accepted===false"
        @click="decide(false)">拒绝候选</el-button>
      </div>
      <fieldset v-if="scopeOptions.length && review.decisionEligible" class="review-scope">
       <legend>本次已审核类别</legend>
       <label v-for="code in scopeOptions" :key="code">
        <input v-model="checkedScope" type="checkbox" :value="code"> {{ code }}
       </label>
      </fieldset>
      <p v-else-if="review.decisionEligible && review.item.review_scope_policy==='per_image_required'" role="status">
       缺少冻结审核范围，请在原工作台核对。
      </p>
      <p v-if="review.draftOutstanding" role="status">请先在候选编辑器核验原草稿保存。</p>
      <p v-if="review.decisionStorageError" role="alert">{{ review.decisionStorageError }}</p>
      <div v-if="review.decision?.status==='pending'" class="review-notice">
       <el-button :loading="review.decisionBusy" @click="review.recoverDecision()">核验原操作</el-button>
      </div>
      <el-button v-else-if="review.decision" :loading="review.decisionBusy"
       @click="review.retryDecisionRefresh()">重读候选和统计</el-button>
      <p v-if="review.decisionNotice" role="status">{{ review.decisionNotice }}</p>
      <p v-if="review.decisionOutsidePage" role="status">当前图片已不在本页筛选结果中。</p>
      <div v-if="review.item.original_boxes" class="review-toolbar" role="group" aria-label="候选框版本">
       <button :aria-pressed="!original" @click="original=false">当前候选框</button>
       <button :aria-pressed="original" @click="original=true">原始候选框</button>
      </div>
      <MaterialPreview :key="review.item.image_id" :image="media(review.item)" :project-id="projectId" :boxes="displayedBoxes" full />
      <p v-if="review.itemBusy" role="status">正在读取图片详情…</p>
      <div v-if="review.itemError" role="alert">{{ review.itemError }} <el-button @click="review.inspect(review.item)">重试详情</el-button></div>
      <dl v-if="review.item.status==='failed' || review.item.error">
       <dt>失败详情</dt><dd>{{ review.item.error || review.item.error_code || '未记录' }}</dd>
       <template v-if="review.item.error_stage"><dt>失败阶段</dt><dd>{{ review.item.error_stage }}</dd></template>
       <template v-if="review.item.http_status"><dt>HTTP 状态</dt><dd>{{ review.item.http_status }}</dd></template>
       <template v-if="review.item.attempt_count != null"><dt>请求次数</dt><dd>{{ review.item.attempt_count }}</dd></template>
       <template v-if="review.item.retry_suggestion"><dt>重试建议</dt><dd>{{ review.item.retry_suggestion }}</dd></template>
      </dl>
      <p v-if="review.item.draft_revision">草稿版本 {{ review.item.draft_revision }}</p>
      <p v-if="review.item.review_scope?.length">审核范围 {{ review.item.review_scope.join('、') }}</p>
      <ul v-if="review.item.review_conflicts?.length" aria-label="候选冲突">
       <li v-for="(conflict,index) in review.item.review_conflicts.slice(0,12)" :key="index">
        {{ conflict.labels?.join(' / ') }} · IoU {{ conflict.iou?.toFixed(2) }}
       </li>
      </ul>
      <ul v-if="displayedBoxes?.length" class="review-boxes" aria-label="候选框">
       <li v-for="(box,index) in displayedBoxes" :key="index">
        {{ box.label || '候选框' }} <span v-if="box.confidence!=null">· 置信度 {{ box.confidence }}</span>
       </li>
      </ul>
      <el-button :loading="review.diagnosticsBusy" @click="review.readDiagnostics()">{{ review.diagnosticsError ? '重试诊断' : '读取诊断' }}</el-button>
      <p v-if="review.diagnosticsError" role="alert">{{ review.diagnosticsError }}</p>
      <template v-if="review.diagnostics">
       <dl v-if="diagnosticFacts.length" aria-label="诊断结果">
        <template v-for="[name,value] in diagnosticFacts" :key="name"><dt>{{ name }}</dt><dd>{{ value }}</dd></template>
       </dl>
       <p v-else role="status">{{ review.diagnostics.status==='DIAGNOSTICS_EXPIRED'?'诊断记录已过期。':'没有可用的诊断记录。' }}</p>
      </template>
     </template>
    </aside>
   </div>
  </template>
 </section>
</template>

<style scoped>
.review-workspace{color:#222;overflow-wrap:anywhere}
.review-heading,.review-toolbar,.review-pagination{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px}
.review-heading{margin-bottom:12px}.review-heading h2,.review-toolbar h3{margin:0}
.review-heading p,.review-candidate-caption span,.review-pagination,small{color:#555;font-size:.85rem}
.review-notice,.review-filters,.review-results,.review-inspector{background:#fff;border:1px solid #ddd;border-radius:8px;padding:12px;min-width:0}
.review-columns{display:grid;grid-template-columns:184px minmax(0,1fr) 320px;align-items:start;gap:12px}
.review-filters{display:flex;flex-direction:column;gap:4px}.review-filters h3{margin:0 0 8px}
button:not(.el-button){border:1px solid #ddd;background:#fff;color:#222;border-radius:5px;padding:6px 9px;font:inherit;cursor:pointer}
button[aria-pressed=true],button[aria-current=true]{background:#e9e9e9;border-color:#555}
.review-filters button{text-align:left}.review-filters span{float:right;margin-inline-start:8px}
.review-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,150px),1fr));gap:10px;margin-block:12px}
.review-cards.list{grid-template-columns:1fr}.list .review-candidate{display:grid;grid-template-columns:96px minmax(0,1fr);align-items:center}
.review-candidate{border:1px solid #ddd;border-radius:7px;min-width:0;padding:6px}
.review-candidate-caption{display:grid;gap:3px;padding:5px}.review-image-link{text-align:left;overflow-wrap:anywhere}
.review-inspector{position:sticky;top:12px;max-height:calc(100dvh - 24px);overflow:auto}.review-inspector h4{margin-block:10px}
.review-inspector dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:5px 10px}.review-inspector dd{margin:0}
.review-actions,.review-scope{display:flex;flex-wrap:wrap;gap:8px}
.review-actions :deep(.el-button){margin:0}
.review-scope{margin:8px 0;padding:6px 10px;border:1px solid #ddd;min-width:0}
.review-boxes{max-height:9rem;overflow:auto}.review-pagination{margin-top:12px}
.review-workspace :deep(.material-media){background:#ededed}
.review-workspace :deep(.box-layer rect){stroke:#444}
.review-workspace :deep(.box-layer text){fill:#444}
.review-candidate :deep(.media-scroll){max-height:none}
.review-filters details button{display:block;width:100%;margin-top:4px}
.review-filters summary{cursor:pointer;padding:5px}
@media(min-width:901px) and (max-width:1400px){
 .review-columns{grid-template-columns:184px minmax(0,1fr)}
 .review-inspector{display:none}
 .review-inspector.open{display:block;position:fixed;top:0;right:0;bottom:0;width:350px;max-height:100dvh;z-index:10}
}
@media(max-width:900px){
 .review-columns{grid-template-columns:minmax(0,1fr)}
 .review-filters{flex-direction:row;flex-wrap:wrap;align-items:center}
 .review-filters h3{flex-basis:100%}
 .review-inspector{display:none}
 .review-inspector.open{display:block;position:fixed;top:0;right:0;bottom:0;width:min(100%,380px);max-height:100dvh;border-radius:0;z-index:10;box-shadow:0 0 0 1px #ddd}
}
</style>
