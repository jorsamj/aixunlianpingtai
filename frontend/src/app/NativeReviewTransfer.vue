<script setup lang="ts">
import {computed,onBeforeUnmount,ref,shallowRef,watch} from 'vue';
import {request} from './http';
import {readWorkspaceSession,workspaceActorKey} from './main';
import {browseError,modelBrowseApi} from '../api/model-browse';
import {transferReviewApi} from '../api/ai-review';
import type {ReviewAddress,TransferHistory,TransferPacket,TransferPreview,TransferRange,TransferReceipt} from '../api/ai-review';
import type {AlgorithmSummary} from '../types/model-browse';

const props=defineProps<{scope:ReviewAddress;actorKey:string;range?:TransferRange;reviewable:boolean}>();
const open=defineModel<boolean>('open',{required:true});
const emit=defineEmits<{settled:[];busy:[value:boolean]}>();
const scope={...props.scope},actor=props.actorKey;
const catalog=modelBrowseApi({projectId:scope.projectId,get:request});
const key='cl:review-transfer:'+JSON.stringify([actor,scope.projectId,scope.taskId]);
const categories=ref<{id:string;name:string;enabled:boolean}[]>([]);
const algorithms=ref<AlgorithmSummary[]>([]),algorithmPage=ref(1),algorithmTotal=ref(0);
const categoryIds=ref<string[]>([]),algorithmId=ref(''),confirmAbsent=ref(false),confirmed=ref(false);
const selectedAlgorithm=shallowRef<AlgorithmSummary>();
const preview=shallowRef<{result:TransferPreview;packet:TransferPacket}>();
const receipt=shallowRef<TransferReceipt>();
const record=shallowRef<{packet:TransferPacket;action:'submit'|'undo'}>();
const history=shallowRef<TransferHistory>(),historyId=ref(''),historyOpen=ref(false);
const offset=ref('0'),error=ref(''),targetError=ref(''),busy=ref(false),writing=ref(false),storageInvalid=ref(false);
const undoConfirmed=ref(false);
const operationStatus=computed(()=>receipt.value?.status??(record.value?'unknown':''));
const terminal=computed(()=>['completed','undone'].includes(operationStatus.value));
const pendingUndo=computed(()=>operationStatus.value==='undo_pending');
const settledPartial=computed(()=>receipt.value?.status==='partial'&&receipt.value.pending===0
  &&receipt.value.processed===receipt.value.total);
const receiptId=computed(()=>historyId.value||record.value?.packet.request_id||'');
const controller=new AbortController();
const coordinated=!!navigator.locks;
const statusText:Record<string,string>={
  pending:'等待续批',partial:'部分完成',completed:'转池完成',undo_pending:'撤销待续批',
  undone:'已撤销',unknown:'结果待核验',transferred:'已转池',failed:'未转池',
};
const storage=()=>coordinated?localStorage:sessionStorage;
async function exclusive(action:()=>Promise<void>){
  if(!navigator.locks)return action();
  return navigator.locks.request(key,{ifAvailable:true},async lock=>{
    if(controller.signal.aborted)return;
    if(!lock)throw new Error('同一审核任务正在另一标签页执行转池，请稍后核验');
    return action();
  });
}
async function verifyActor(){
  const session=await readWorkspaceSession(controller.signal);
  if(workspaceActorKey(session)!==actor)throw new Error('会话已切换，请返回原操作者核验该操作');
}

function persist(value:NonNullable<typeof record.value>){
  storage().setItem(key,JSON.stringify(value));
  record.value=value;
}
function stringIds(value:unknown,max:number):value is string[]{
  return Array.isArray(value)&&value.length<=max&&value.every(id=>typeof id==='string'&&id.length>0)
    &&new Set(value).size===value.length;
}
function readJournal(){
  const raw=storage().getItem(key);
  if(!raw){record.value=undefined;receipt.value=undefined;return}
  const value=JSON.parse(raw),p=value?.packet;
  if(!p||!['submit','undo'].includes(value.action)||typeof p.request_id!=='string'||!/^[\da-f-]{32,36}$/i.test(p.request_id)
    ||!Number.isSafeInteger(p.review_revision)||p.review_revision<0||!stringIds(p.image_ids,200)
    ||!stringIds(p.excluded_image_ids,50000)||!stringIds(p.category_ids,100)||!p.category_ids.length
    ||typeof p.algorithm_id!=='string'||typeof p.confirm_absent!=='boolean'
    ||(p.confirm_absent&&!p.algorithm_id)
    ||(p.selection_id?(typeof p.selection_id!=='string'||!!p.image_ids.length):(!p.image_ids.length||!!p.excluded_image_ids.length)))
    throw new Error('本地转池记录无法读取，请在原审核工作台核对操作');
  if(record.value?.packet.request_id!==p.request_id)receipt.value=undefined;
  record.value=value;
}
function syncJournal(){
  try{readJournal();storageInvalid.value=false}
  catch(cause){storageInvalid.value=true;error.value=browseError(cause)}
}
async function loadTargets(page=1){
  targetError.value='';
  const signal=controller.signal;
  try{
    const [pool,options]=await Promise.all([
      categories.value.length?null:request<{items:typeof categories.value}>(
        `/api/v61/projects/${encodeURIComponent(scope.projectId)}/negative-pool/categories`,{signal}),
      catalog.algorithms({page},signal),
    ]);
    if(signal.aborted)return;
    if(pool)categories.value=pool.items.filter(item=>item.enabled);
    algorithms.value=options.items;algorithmPage.value=options.page;algorithmTotal.value=options.total;
  }catch(cause){if(!signal.aborted)targetError.value=browseError(cause)}
}
async function fetchReceipt(at='0'){
  const id=receiptId.value;
  if(!id)return;
  const p=historyId.value?undefined:record.value?.packet;
  const value=await transferReviewApi.receipt(scope,id,at,controller.signal);
  if(value.request_id!==id||!value.target||(p&&(value.target.algorithm_id!==p.algorithm_id
    ||value.target.confirm_absent!==p.confirm_absent
    ||JSON.stringify(value.target.category_ids)!==JSON.stringify(p.category_ids)))
    ||!Number.isSafeInteger(value.processed)||!Number.isSafeInteger(value.total)||value.total<1
    ||value.processed<0||value.processed>value.total||!Array.isArray(value.items)||value.items.length>100
    ||(value.next_cursor!==null&&(!/^\d+$/.test(value.next_cursor)||Number(value.next_cursor)<=Number(at))))
    throw new Error('转池回执身份或范围不一致');
  if(controller.signal.aborted)return;
  receipt.value=value;offset.value=at;
  return value;
}
function isMissing(cause:unknown){return (cause as {httpStatus?:number}|null)?.httpStatus===404}
async function check(at='0'){
  if(busy.value)return;
  error.value='';busy.value=true;
  try{await fetchReceipt(at)}
  catch(cause){if(!controller.signal.aborted)error.value=isMissing(cause)
    ?'当前没有持久回执，请保留原操作并核验。':browseError(cause)}
  finally{busy.value=false}
}
async function readHistory(cursor=''){
  if(busy.value)return;
  historyOpen.value=true;busy.value=true;error.value='';
  try{
    const result=await transferReviewApi.history(scope,cursor,controller.signal);
    history.value=cursor&&history.value?{...result,items:[...history.value.items,...result.items]}:result;
  }catch(cause){if(!controller.signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false}
}
async function inspectHistory(id:string){
  if(busy.value)return;
  historyId.value=id;receipt.value=undefined;undoConfirmed.value=false;
  if(id||record.value)await check();
}
async function undoHistory(){
  if(!historyId.value||busy.value||!undoConfirmed.value||!props.reviewable)return;
  const id=historyId.value;
  error.value='';busy.value=true;writing.value=true;emit('busy',true);
  try{
    await exclusive(async()=>{
      await verifyActor();
      const current=await fetchReceipt();
      if(current?.request_id!==id||current.target.confirm_absent||!['completed','partial','undo_pending'].includes(current.status))return;
      await transferReviewApi.undo(scope,id,controller.signal);
      await fetchReceipt();
    });
  }catch(cause){if(!controller.signal.aborted){receipt.value=undefined;error.value=browseError(cause)}}
  finally{if(!controller.signal.aborted)emit('settled');writing.value=false;busy.value=false;emit('busy',false)}
}
async function prepare(){
  if(busy.value||!props.range||!props.reviewable||!categoryIds.value.length||storageInvalid.value
    ||(confirmAbsent.value&&!algorithmId.value))return;
  error.value='';busy.value=true;confirmed.value=false;
  const id=Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
  const packet:TransferPacket={...props.range,request_id:id,category_ids:[...categoryIds.value],
    algorithm_id:algorithmId.value,confirm_absent:confirmAbsent.value};
  try{
    await verifyActor();
    const result=await transferReviewApi.preview(scope,packet,controller.signal);
    if(result.review_revision!==packet.review_revision)throw new Error('审核范围已变化，请刷新后重新预检');
    preview.value={result,packet};
  }catch(cause){if(!controller.signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false}
}
async function run(action:'submit'|'undo'){
  if(busy.value||storageInvalid.value)return;
  const prepared=preview.value;
  error.value='';busy.value=true;writing.value=true;emit('busy',true);
  let attempted=false;
  try{
    await exclusive(async()=>{
      await verifyActor();
      readJournal();
      if(prepared&&record.value)throw new Error('已有待处理的转池记录，请先核验原操作');
      const packet=record.value?.packet??prepared?.packet;
      if(!packet)return;
      let current:TransferReceipt|undefined;
      if(record.value){
        if(action==='submit'&&record.value.action==='undo')return;
        try{current=await fetchReceipt()}
        catch(cause){
          if(!isMissing(cause)||record.value.action!=='submit'||action!=='submit')throw cause;
          receipt.value=undefined;
        }
        if(action==='submit'&&current&&!['pending','partial'].includes(current.status))return;
        if(action==='undo'&&(!undoConfirmed.value||!props.reviewable||packet.confirm_absent
          ||!current||!['completed','partial','pending','undo_pending'].includes(current.status)))return;
      }else if(action!=='submit'||!prepared||!confirmed.value||!props.reviewable||!prepared.result.eligible)return;
      persist({packet,action});
      preview.value=undefined;
      let processed=current?.processed??0;
      // Each server call advances at most 200 items. A failed response needs an explicit receipt check before continuation.
      for(let batch=0;batch<251;batch++){
        attempted=true;
        const result=action==='submit'
          ?await transferReviewApi.submit(scope,packet,controller.signal)
          :await transferReviewApi.undo(scope,packet.request_id,controller.signal);
        if('request_id' in result&&result.request_id!==packet.request_id)throw new Error('转池响应身份不一致');
        const next=await fetchReceipt();
        if(!next||next.status!=='pending'||action==='undo'||next.processed<=processed)break;
        processed=next.processed;
      }
    });
  }catch(cause){
    if(!controller.signal.aborted){
      if(attempted){receipt.value=undefined;error.value='执行结果待核验。'+browseError(cause)}
      else error.value=browseError(cause);
    }
  }finally{
    if(!controller.signal.aborted&&attempted)emit('settled');
    writing.value=false;busy.value=false;emit('busy',false);
  }
}
async function finish(){
  if(busy.value)return;
  const id=record.value?.packet.request_id;
  if(!id)return;
  busy.value=true;error.value='';
  try{
    await exclusive(async()=>{
      readJournal();
      if(record.value?.packet.request_id!==id)return;
      const current=await fetchReceipt();
      if(!current||!(['completed','undone'].includes(current.status)
        ||(current.status==='partial'&&current.pending===0&&current.processed===current.total)))return;
      storage().removeItem(key);
      record.value=undefined;receipt.value=undefined;undoConfirmed.value=false;
    });
    if(!record.value)open.value=false;
  }catch(cause){if(!controller.signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false}
}
watch(open,visible=>{
  if(!visible)return;
  error.value='';preview.value=undefined;confirmed.value=false;undoConfirmed.value=false;
  historyId.value='';historyOpen.value=false;history.value=undefined;syncJournal();
  if(record.value)void check();
  else if(props.range&&!storageInvalid.value)void loadTargets();
});
onBeforeUnmount(()=>controller.abort());
</script>

<template>
 <el-dialog v-model="open" title="转入负样本池" width="min(720px, 94vw)" destroy-on-close
  :close-on-click-modal="false" :close-on-press-escape="!writing" :show-close="!writing">
  <el-alert v-if="error" type="error" :closable="false" :title="error" show-icon />
  <div class="transfer-actions">
   <el-button link :disabled="busy" @click="historyOpen?historyOpen=false:readHistory()">转池操作历史</el-button>
   <el-button v-if="historyId" link :disabled="busy" @click="inspectHistory('')">返回当前操作</el-button>
  </div>
  <div v-if="historyOpen" class="transfer-panel" aria-label="转池操作历史">
   <p v-if="history && !history.items.length">此页没有当前操作者的操作。</p>
   <div v-for="item in history?.items" :key="item.request_id" class="transfer-actions">
    <el-button link :disabled="busy" @click="inspectHistory(item.request_id)">{{ item.request_id }}</el-button>
    <span>{{ statusText[item.status] || item.status }} · {{ item.created_at || '时间未记录' }}</span>
   </div>
   <el-button v-if="history?.next_cursor" :disabled="busy" @click="readHistory(history.next_cursor)">加载更多操作</el-button>
  </div>
  <section v-if="receiptId" class="transfer-panel">
   <p role="status">{{ statusText[operationStatus] || operationStatus || '结果待核验' }} · 操作 {{ receiptId }}</p>
   <template v-if="receipt">
    <p>已记录 {{ receipt.processed }} / {{ receipt.total }} 张</p>
    <p v-if="receipt.failed!==undefined">已转池 {{ receipt.transferred }} · 失败 {{ receipt.failed }}（身份冲突 {{ receipt.permanent_conflicts }}） · 待处理 {{ receipt.pending }}</p>
    <p v-if="receipt.target.confirm_absent">此操作可能已写入正式负样本证据，请通过正式冲突处理核验。</p>
    <el-table :data="receipt.items" max-height="260" empty-text="还没有逐图回执">
     <el-table-column label="素材" min-width="160"><template #default="{row}">{{ (row.filename || row.image_id).split(/[\\/]/).at(-1) }}</template></el-table-column>
     <el-table-column label="结果" width="115"><template #default="{row}">{{ row.permanent_conflict ? '身份冲突' : statusText[row.status] || row.status }}</template></el-table-column>
     <el-table-column label="原因" min-width="220"><template #default="{row}">{{ row.error ? browseError(new Error(row.error)) : '—' }}</template></el-table-column>
    </el-table>
    <div class="transfer-actions">
     <el-button :disabled="busy || offset==='0'" @click="check(String(Math.max(0,Number(offset)-100)))">上一页</el-button>
     <el-button :disabled="busy || !receipt.next_cursor" @click="check(receipt.next_cursor || '0')">下一页</el-button>
    </div>
   </template>
   <div class="transfer-actions">
    <el-button :loading="busy && !writing" :disabled="writing" @click="check()">核验原回执</el-button>
    <el-button v-if="!historyId && !terminal && !pendingUndo && record?.action==='submit'
      && (!settledPartial || receipt?.failed!==receipt?.permanent_conflicts)" :loading="writing" :disabled="busy"
     @click="run('submit')">{{ operationStatus==='partial' ? '重试原操作的失败项' : '按原操作核验并续批' }}</el-button>
    <el-button v-if="!historyId && terminal" :disabled="busy" @click="finish()">关闭并清除本地记录</el-button>
    <el-button v-if="!historyId && settledPartial" :disabled="busy" @click="finish()">结束本次部分完成，保留服务端回执</el-button>
   </div>
   <div v-if="receipt && operationStatus!=='undone' && reviewable && !receipt.target.confirm_absent
       && (!historyId || ['completed','partial','undo_pending'].includes(operationStatus))" class="transfer-actions">
    <el-checkbox v-model="undoConfirmed" :disabled="busy">确认按原回执核验撤销资格</el-checkbox>
    <el-button :loading="writing" :disabled="busy || !undoConfirmed" @click="historyId?undoHistory():run('undo')">{{ pendingUndo ? '继续撤销' : '撤销转池' }}</el-button>
   </div>
  </section>
  <section v-else-if="preview" class="transfer-panel">
   <p>范围 {{ preview.result.total }} 张 · 可转池 {{ preview.result.eligible }} 张 · 冲突 {{ preview.result.conflicts }} 张</p>
   <p>有框 {{ preview.result.with_boxes }} 张 · 零框 {{ preview.result.zero }} 张 · 候选框 {{ preview.result.discarded_boxes }} 个</p>
   <p>审核修订 {{ preview.result.review_revision }} · 目标 {{ selectedAlgorithm?.name || '公共负样本池' }} ·
    {{ categories.filter(category=>preview?.packet.category_ids.includes(category.id)).map(category=>category.name).join('、') }}</p>
   <p>已有正式 GT 的素材会被保护。{{ preview.packet.confirm_absent ? '通过校验后将登记正式负样本证据。' : '本次只变更候选与负样本池归属。' }}</p>
   <ul v-if="preview.result.ineligible_reasons"><li v-for="(count,reason) in preview.result.ineligible_reasons" :key="reason">{{ reason }}（{{ count }}）</li></ul>
   <el-checkbox v-model="confirmed">确认转池范围及候选框弃用{{ preview.packet.confirm_absent ? '，并确认原算法目标不存在' : '' }}</el-checkbox>
   <div class="transfer-actions">
    <el-button :disabled="busy" @click="preview=undefined">返回修改</el-button>
    <el-button type="primary" :loading="writing" :disabled="busy || !confirmed || !preview.result.eligible" @click="run('submit')">确认转池</el-button>
   </div>
  </section>
  <section v-else-if="range && !storageInvalid" class="transfer-panel">
   <el-alert v-if="targetError" type="error" :closable="false" :title="targetError" />
   <el-form label-position="top">
    <el-form-item label="负样本分类">
     <el-select v-model="categoryIds" multiple filterable :multiple-limit="100" placeholder="选择分类" style="width:100%">
      <el-option v-for="category in categories" :key="category.id" :label="category.name" :value="category.id" />
     </el-select>
    </el-form-item>
    <el-form-item label="目标算法（可选）">
     <el-select v-model="algorithmId" clearable placeholder="不指定算法" style="width:100%"
      @change="selectedAlgorithm=algorithms.find(row=>row.id===algorithmId);if(!algorithmId)confirmAbsent=false">
      <el-option v-if="selectedAlgorithm && !algorithms.some(row=>row.id===selectedAlgorithm?.id)" :label="selectedAlgorithm.name" :value="selectedAlgorithm.id" />
      <el-option v-for="algorithm in algorithms" :key="algorithm.id" :label="algorithm.name" :value="algorithm.id" />
     </el-select>
     <div class="transfer-actions">
      <el-button :disabled="algorithmPage<=1 || busy" @click="loadTargets(algorithmPage-1)">上一页算法</el-button>
      <el-button :disabled="algorithmPage*20>=algorithmTotal || busy" @click="loadTargets(algorithmPage+1)">下一页算法</el-button>
     </div>
    </el-form-item>
    <el-checkbox v-model="confirmAbsent" :disabled="!algorithmId">确认目标不存在（产生正式负样本证据，转池回执无法撤销）</el-checkbox>
   </el-form>
   <el-button type="primary" :loading="busy" :disabled="!categoryIds.length" @click="prepare">预检转池</el-button>
  </section>
  <p v-else-if="!storageInvalid">当前标签页没有待核验的转池记录。</p>
 </el-dialog>
</template>

<style scoped>
.transfer-panel{display:grid;gap:12px}.transfer-panel p,.transfer-panel ul{margin:0}
.transfer-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.transfer-actions :deep(.el-button){margin-left:0}
</style>
