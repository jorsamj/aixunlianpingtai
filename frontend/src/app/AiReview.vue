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
  &&!review.formalLocked&&!review.decision&&!review.decisionBusy&&!review.itemBusy&&!review.itemError&&['success','empty'].includes(review.item?.status||'')
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
const bulkStatusNames:Record<string,string>={QUEUED:'排队中',RUNNING:'后台执行中',CANCEL_REQUESTED:'正在取消',
  CANCELLED:'已取消',SUCCEEDED:'已完成',PARTIAL_SUCCESS:'部分成功',FAILED:'失败'};
const bulkStatusName=computed(()=>review.bulkExecution
  ?bulkStatusNames[review.bulkExecution.status]||review.bulkExecution.status
  :review.bulkCreatePending?'后台任务创建未确认'
  :review.bulkConflict?'预检冲突，已阻止执行'
  :review.bulkIntent?'已预检封存':review.bulkPendingUnknown?'上次预检未确认':'');
const bulkManualExcluded=computed(()=>review.frozenSelection
  ?Math.max(0,review.frozenSelection.count-review.selectedCount):0);
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
const selectionReasonLabels:Record<string,string>={
  committed:'已正式入库',unavailable:'当前不可操作',failed:'生成失败或未生成',
  rejected:'已拒绝',requires_review:'待人工消歧',
};
function toggleSelection(row:ReviewCandidate,event:Event){
  review.selectCandidate(row,(event.target as HTMLInputElement).checked);
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
      :disabled="review.pageBusy||review.formalLocked" :aria-pressed="review.filter===key" @click="review.setFilter(key)">
      {{ label }} <span v-if="review.page?.summary?.[key]!=null">{{ review.page.summary[key] }}</span>
     </button>
     <details><summary>更多筛选</summary>
      <button v-for="[key,label] in reviewFilters.slice(5)" :key="key" type="button"
       :disabled="review.pageBusy||review.formalLocked" :aria-pressed="review.filter===key" @click="review.setFilter(key)">
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
        <label v-if="review.task.status.toUpperCase()==='AWAITING_CONFIRMATION'" class="review-checkbox"
         :title="review.selectionReason(row)">
         <input type="checkbox" :aria-label="'选择 '+candidateName(row)" :checked="review.isSelected(row)"
          :disabled="!review.canSelect||!!review.selectionReason(row)" @change="toggleSelection(row,$event)">
         <span v-if="review.selectionReason(row)">{{ review.selectionReason(row) }}</span>
         <span v-else>选择</span>
        </label>
        <button class="review-image-link" :aria-current="review.item?.image_id===row.image_id ? 'true' : undefined"
         @click="readImage(row,$event)">{{ candidateName(row) }}</button>
        <span>{{ candidateStatus(row) }} · {{ row.boxes?.length ?? 0 }} 框</span>
       </div>
      </article>
     </div>
     <footer v-if="review.page && !review.page.task_error" class="review-pagination">
      <el-button :disabled="review.pageNumber===1 || review.pageBusy || review.selectionBusy || review.formalLocked" @click="review.previousPage()">上一页</el-button>
      <span>第 {{ review.pageNumber }} 页 · 每页 24 张</span>
      <el-button :disabled="!review.page.next_cursor || review.pageBusy || review.selectionBusy || review.formalLocked" @click="review.nextPage()">下一页</el-button>
     </footer>
     <section v-if="review.task.status.toUpperCase()==='AWAITING_CONFIRMATION'" class="review-selection"
      aria-label="候选选择">
      <div class="review-actions">
       <el-button :disabled="!review.canSelect||!review.page?.items.length" @click="review.selectPage()">选择本页</el-button>
       <el-button :disabled="!review.canSelect||!!review.frozenSelection||!review.page?.total"
        :loading="review.selectionBusy" @click="review.freezeSelection()">选择全部筛选结果</el-button>
       <el-button :disabled="!review.canPrepareFormal" @click="review.prepareFormal()">
        正式入库已选 {{ review.selectedCount }} 张
       </el-button>
       <el-button v-if="review.frozenSelection" :disabled="!review.canBulkFormal" @click="review.openBulkFormal()">
        后台正式入库 {{ review.selectedCount }} 张
       </el-button>
       <el-button :disabled="review.formalLocked||(!review.frozenSelection&&!review.selectedCount&&!review.selectionBusy)"
        @click="review.clearSelection()">清空选择</el-button>
      </div>
      <p aria-live="polite">
       <template v-if="review.frozenSelection">筛选 {{ review.frozenSelection.filtered_total }} 张 ·
        可操作 {{ review.frozenSelection.count }} 张 · </template>已选 {{ review.selectedCount }} 张
      </p>
      <p v-if="review.frozenSelection && Object.keys(review.frozenSelection.reasons).length">
       资格排除：<span v-for="(count,reason) in review.frozenSelection.reasons" :key="reason">
        {{ selectionReasonLabels[reason] ?? reason }} {{ count }} 张
       </span>
      </p>
      <p v-if="review.selectionNotice" role="status">{{ review.selectionNotice }}</p>
      <p v-if="review.formalUnavailable">{{ review.formalUnavailable }}</p>
      <div v-if="review.formalOperation" role="status">
       <span v-if="!review.formalOperation.receipt">正式入库结果待核验</span>
       <span v-else-if="review.formalOperation.receipt.status==='completed'">正式入库完成</span>
       <span v-else>原操作未写入正式 GT</span>
       <el-button :loading="review.formalBusy" @click="review.recoverFormal()">
        {{ review.formalOperation.receipt ? '重新读取候选与 GT' : '核验原入库请求' }}
       </el-button>
      </div>
      <p v-if="review.formalNotice" role="status">{{ review.formalNotice }}</p>
      <el-dialog :model-value="!!review.formalPlan" title="确认正式 GT 入库" width="min(480px, 92vw)"
       :close-on-click-modal="false" :close-on-press-escape="!review.formalBusy"
       :show-close="!review.formalBusy" @close="review.cancelFormal()">
       <template v-if="review.formalPlan">
        <p>项目 {{ projectId }} · 任务 {{ review.task?.name || taskId }}</p>
        <p>选中 {{ review.formalPlan.ids.length }} 张 · 有框 {{ review.formalPlan.boxed }} 张 ·
         零框 {{ review.formalPlan.ids.length - review.formalPlan.boxed }} 张</p>
        <p>确认后写入正式 GT，未选中的图片不受影响。</p>
        <p v-if="review.formalNotice" role="alert">{{ review.formalNotice }}</p>
       </template>
       <template #footer>
        <el-button :disabled="review.formalBusy" @click="review.cancelFormal()">取消</el-button>
        <el-button :loading="review.formalBusy" @click="review.confirmFormal()">确认写入正式 GT</el-button>
       </template>
      </el-dialog>
      <div v-if="review.bulkIntent || review.bulkExecution || review.bulkPendingUnknown || review.bulkCreatePending || review.bulkConflict || review.lastBulkResult" class="review-bulk" role="status">
       <p><b>{{ bulkStatusName }}</b>
        <template v-if="review.bulkExecution">
         · 已证明提交 GT
         {{ review.bulkExecution.committed_images_proven ? review.bulkExecution.committed_images : '未证明' }}
         / {{ review.bulkExecution.total_images }} 张
         · 完成批次 {{ review.bulkExecution.completed_batches }}/{{ review.bulkExecution.total_batches }}
         <template v-if="review.bulkExecution.candidate_adopted_images">
          · 候选已采用 {{ review.bulkExecution.candidate_adopted_images }} 张
         </template>
         <template v-if="review.bulkExecution.cancellation_requested && !review.bulkTerminal"> · 已请求取消</template>
        </template>
        <template v-else-if="review.bulkCreatePending"> · 后台任务创建结果未确认，原操作身份已保留，请查询或重试同一创建</template>
        <template v-else-if="review.bulkConflict"> · 原操作意图与本次选择不一致，已阻止执行</template>
        <template v-else-if="review.bulkIntent"> · 已封存 {{ review.bulkIntent.count }} 张，待创建后台任务</template>
        <template v-else-if="review.bulkPendingUnknown"> · 上次预检结果未确认，可重试同一操作</template>
       </p>
       <p v-if="review.bulkExecution?.blocked" role="alert">
        任务已阻断{{ review.bulkExecution.manual_review_required ? '，需要人工核验后恢复' : '' }}：
        {{ review.bulkExecution.blocked_reason || review.bulkExecution.last_error_message || review.bulkExecution.blocked_code }}
       </p>
       <p v-else-if="review.bulkExecution?.last_error_message" role="alert">{{ review.bulkExecution.last_error_message }}</p>
       <p v-if="review.lastBulkResult && !review.bulkExecution" role="status">上一笔：{{ bulkStatusNames[review.lastBulkResult.status] || review.lastBulkResult.status }} · 已证明提交 GT {{ review.lastBulkResult.committed_images_proven ? review.lastBulkResult.committed_images : '未证明' }} / {{ review.lastBulkResult.total_images }} 张</p>
       <p v-if="review.bulkNotice" role="status">{{ review.bulkNotice }}</p>
       <p v-if="review.bulkConflict" role="alert">服务端存在同一请求编号的原操作意图，但无法证明与本次选择一致，已阻止执行。</p>
       <div class="review-actions">
        <el-button :loading="review.bulkBusy" @click="review.refreshBulkFormal()">刷新进度</el-button>
        <el-button v-if="review.bulkExecution && !review.bulkTerminal && !review.bulkExecution.cancellation_requested"
         :loading="review.bulkBusy" @click="review.cancelBulkFormal()">取消后台任务</el-button>
        <el-button v-if="review.bulkExecution?.blocked" :loading="review.bulkBusy"
         @click="review.recoverBulkFormal()">核验并恢复</el-button>
        <el-button v-if="review.bulkCreatePending && review.bulkIntent" :loading="review.bulkBusy"
         @click="review.confirmBulkFormal()">重试创建后台任务</el-button>
        <el-button v-if="review.bulkCreatePending && !review.bulkIntent" :loading="review.bulkBusy"
         @click="review.preflightBulkFormal()">重试上次预检</el-button>
        <el-button v-if="review.bulkPendingUnknown" :loading="review.bulkBusy"
         @click="review.preflightBulkFormal()">重试上次预检</el-button>
        <el-button v-if="(review.bulkIntent || review.bulkConflict || review.bulkPendingUnknown) && !review.bulkRunning && !review.bulkCreatePending && !review.bulkBusy"
         @click="review.abandonBulkFormal()">{{ review.bulkIntent ? '放弃预检' : '放弃' }}</el-button>
        <el-button v-if="review.bulkIntent" @click="review.openBulkFormal()">查看预检</el-button>
       </div>
      </div>
      <el-dialog :model-value="review.bulkDialog" title="后台正式 GT 入库" width="min(560px, 92vw)"
       :close-on-click-modal="!review.bulkBusy" :close-on-press-escape="!review.bulkBusy"
       :show-close="!review.bulkBusy" @close="review.closeBulkFormal()">
       <template v-if="!review.bulkExecution">
        <p v-if="!review.bulkIntent">
         冻结筛选 {{ review.frozenSelection?.filtered_total }} 张 · 资格排除 {{ review.frozenSelection?.excluded }} 张 ·
         当前选择 {{ review.selectedCount }} 张 · 手动排除 {{ bulkManualExcluded }} 张
        </p>
        <p v-else>
         已封存：可入库 {{ review.bulkIntent.count }} 张 · 手动排除 {{ review.bulkIntent.excluded_count }} 张 ·
         原筛选 {{ review.bulkIntent.original_count }} 张
        </p>
        <p>预检只核验并封存范围，不写入正式 GT。确认后由后台 Worker 每 100 张一批提交，可随时取消。</p>
        <p v-if="review.bulkCreatePending" role="alert">创建后台任务的结果尚未确认。请先查询执行状态；需要重试时仍使用原操作身份，不要放弃或新建。</p>
        <p>放弃预检只清除浏览器本地记录，不会声称服务端已撤销；若后台任务已创建，必须查询或取消原任务。</p>
       </template>
       <template v-else>
        <p>{{ bulkStatusName }} · 任务 {{ review.bulkExecution.execution_task_id }}</p>
        <p>
         已证明提交 GT
         {{ review.bulkExecution.committed_images_proven ? review.bulkExecution.committed_images : '未证明' }}
         / {{ review.bulkExecution.total_images }} 张 · 完成批次
         {{ review.bulkExecution.completed_batches }}/{{ review.bulkExecution.total_batches }}
        </p>
        <p v-if="review.bulkExecution.candidate_adopted_images">
         候选已采用未提交 {{ review.bulkExecution.candidate_only_uncommitted_images }} 张
         <template v-if="review.bulkExecution.uncommitted_gt_changed_images">
          · 外部 GT 变更 {{ review.bulkExecution.uncommitted_gt_changed_images }} 张
         </template>
        </p>
        <p v-if="review.bulkExecution.blocked" role="alert">
         任务已阻断：{{ review.bulkExecution.blocked_reason || review.bulkExecution.blocked_code }}
        </p>
        <p v-else-if="review.bulkExecution.last_error_message" role="alert">{{ review.bulkExecution.last_error_message }}</p>
       </template>
       <p v-if="review.bulkError" role="alert">{{ review.bulkError }}</p>
       <p v-if="review.lastBulkResult && !review.bulkExecution" role="status">上一笔：{{ bulkStatusNames[review.lastBulkResult.status] || review.lastBulkResult.status }} · 已证明提交 GT {{ review.lastBulkResult.committed_images_proven ? review.lastBulkResult.committed_images : '未证明' }} / {{ review.lastBulkResult.total_images }} 张</p>
       <p v-if="review.bulkNotice" role="status">{{ review.bulkNotice }}</p>
       <template #footer>
        <el-button :disabled="review.bulkBusy" @click="review.closeBulkFormal()">关闭</el-button>
        <el-button v-if="!review.bulkIntent && review.bulkCreatePending" :loading="review.bulkBusy"
         @click="review.preflightBulkFormal()">重试上次预检</el-button>
        <el-button v-else-if="!review.bulkIntent" :loading="review.bulkBusy"
         @click="review.preflightBulkFormal()">预检并封存</el-button>
        <el-button v-if="(review.bulkIntent || review.bulkConflict) && !review.bulkExecution && !review.bulkCreatePending" :disabled="review.bulkBusy"
         @click="review.abandonBulkFormal()">放弃预检</el-button>
        <el-button v-if="review.bulkIntent && !review.bulkExecution && review.bulkCreatePending && !review.bulkConflict"
         type="primary" :loading="review.bulkBusy" @click="review.confirmBulkFormal()">重试创建后台任务</el-button>
        <el-button v-else-if="review.bulkIntent && !review.bulkExecution && !review.bulkConflict"
         type="primary" :loading="review.bulkBusy" @click="review.confirmBulkFormal()">确认创建后台任务</el-button>
      </template>
      </el-dialog>
      <small>此处的选择仅用于当前页面，原工作台需重新选择。</small>
     </section>
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
.review-checkbox{display:flex;align-items:center;gap:5px}
.review-checkbox input{margin:0;accent-color:#222}
.review-selection{margin-top:12px;padding-top:12px;border-top:1px solid #ddd}
.review-bulk{margin-top:10px;padding:8px 10px;border:1px solid #ddd;border-radius:6px;background:#fafafa}
.review-bulk p{margin:4px 0}
.review-selection p{margin:8px 0}
.review-selection p span+span::before{content:' · '}
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
