<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,shallowRef} from 'vue';
import {ambiguityKey,createAmbiguityTask,getReviewLabels,readAmbiguityTask} from '../api/ai-review';
import type {AmbiguityPhase,AmbiguityPlanRequest,AmbiguityTask,ReviewAddress,ReviewLabel} from '../api/ai-review';
import {manageMaterialBatch} from '../api/material-batches';
import {browseError} from '../api/model-browse';
import {readWorkspaceSession,workspaceActorKey} from './main';

const props=defineProps<{scope:ReviewAddress;actorKey:string;formalBusy:boolean;formalError:string;
  range?:{id:string;revision:number;excluded:string[];count:number}}>();
const open=defineModel<boolean>('open',{required:true});
const emit=defineEmits<{busy:[value:boolean];settled:[];formal:[proof:{requestId:string;count:number}]}>();
const scope={...props.scope},actor=props.actorKey;
const controller=new AbortController(),signal=controller.signal,key=ambiguityKey(scope,actor);
const threshold=ref<number|undefined>(0.9),mode=ref<'manual'|'auto'>('manual'),label=ref('');
const labels=shallowRef<ReviewLabel[]>([]);
type Pending={id:string;plan:AmbiguityPlanRequest;planId?:string;phase:AmbiguityPhase};
const pending=shallowRef<Pending>(),task=shallowRef<AmbiguityTask>();
const busy=ref(false),canReplay=ref(false),error=ref(''),confirmed=ref(false),formalConsent=ref(false);
const isPlan=computed(()=>pending.value?.phase==='plan');
const statusLabels:Record<string,string>={QUEUED:'排队中',WAITING_RESOURCE:'等待资源',RUNNING:'执行中',
  SUCCEEDED:'已完成',PARTIAL_SUCCESS:'部分完成',FAILED:'失败',CANCEL_REQUESTED:'正在取消',CANCELLED:'已取消'};
const terminal=computed(()=>['SUCCEEDED','PARTIAL_SUCCESS','FAILED','CANCELLED','BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE'].includes(task.value?.status||''));
const canSave=computed(()=>isPlan.value&&task.value?.status==='SUCCEEDED'&&!!task.value.succeeded);
const canFormal=computed(()=>!isPlan.value&&pending.value?.plan.mode==='manual'&&
  ['SUCCEEDED','PARTIAL_SUCCESS'].includes(task.value?.status||'')&&!!task.value?.succeeded);

async function run(action:()=>Promise<void>){
  if(busy.value)return;
  busy.value=true;error.value='';emit('busy',true);
  try{
    if(workspaceActorKey(await readWorkspaceSession(signal))!==actor)throw new Error('会话已切换，请重新打开审核');
    await action();
  }catch(cause){if(!signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false;emit('busy',false)}
}
function remember(record:Pending){
  sessionStorage.setItem(key,JSON.stringify(record));pending.value=record;
}
function accept(record:AmbiguityTask,phase:AmbiguityPhase){
  if(!record.task_id||record.project_id!==scope.projectId
    ||record.operation!==(phase==='plan'?'PLAN_AI_AMBIGUITY':'SAVE_AI_AMBIGUITY_DRAFTS'))
    throw new Error('消歧任务回执身份不一致');
  const previous=task.value?.succeeded||0;
  task.value=record;
  if(phase==='save'&&(record.succeeded||0)>previous)emit('settled');
}
async function submit(record:Pending){
  canReplay.value=false;
  const body=record.phase==='plan'?record.plan:{plan_task_id:record.planId!};
  accept(await createAmbiguityTask(scope,record.id,record.phase,body,signal),record.phase);
}
function prepare(){
  const range=props.range,iou=threshold.value;
  if(!range||iou===undefined||iou<0.5||iou>1||(mode.value==='manual'&&!labels.value.some(item=>item.code===label.value)))return;
  const id=Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
  const record:Pending={id,phase:'plan',plan:{selection_id:range.id,review_revision:range.revision,
    excluded_image_ids:[...range.excluded],mode:mode.value,label:label.value,threshold:iou}};
  void run(async()=>{remember(record);await submit(record)});
}
function save(){
  if(!canSave.value||!pending.value||!task.value||!confirmed.value)return;
  const record:Pending={...pending.value,phase:'save',planId:task.value.task_id};
  void run(async()=>{remember(record);task.value=undefined;await submit(record)});
}
function refresh(){
  const record=pending.value;
  if(!record)return;
  void run(async()=>{
    canReplay.value=false;
    try{accept(await readAmbiguityTask(scope,record.id,record.phase,signal),record.phase)}
    catch(cause){
      if((cause as {httpStatus?:number}).httpStatus===404&&!task.value){canReplay.value=true;return}
      throw cause;
    }
  });
}
function replay(){
  const record=pending.value;
  if(record&&canReplay.value)void run(()=>submit(record));
}
function manage(action:'cancel'|'retry'){
  const id=task.value?.task_id,phase=pending.value?.phase;
  if(id&&phase)void run(async()=>{accept(await manageMaterialBatch(scope.projectId,id,action,signal),phase)});
}
function clear(){
  try{
    sessionStorage.removeItem(key);pending.value=undefined;task.value=undefined;
    canReplay.value=false;confirmed.value=false;formalConsent.value=false;
  }catch(cause){error.value=browseError(cause)}
}
function freeze(){
  if(canFormal.value&&pending.value&&task.value?.succeeded&&formalConsent.value)
    emit('formal',{requestId:pending.value.id,count:task.value.succeeded});
}
onMounted(async()=>{
  try{
    const stored=sessionStorage.getItem(key);
    if(stored){pending.value=JSON.parse(stored) as Pending;refresh()}
    labels.value=await getReviewLabels(scope.projectId,signal);
  }catch(cause){if(!signal.aborted)error.value=browseError(cause)}
});
onBeforeUnmount(()=>controller.abort());
</script>

<template>
 <el-dialog v-model="open" title="IoU 批量消歧" width="min(680px,94vw)"
  :close-on-click-modal="false" :show-close="!busy&&!formalBusy" :close-on-press-escape="!busy&&!formalBusy">
  <el-alert v-if="error||formalError" type="error" :title="error||formalError" :closable="false" />
  <el-form v-if="!pending&&range" label-position="top" :disabled="busy">
   <p>已冻结 {{range.count}} 张候选。</p>
   <el-form-item label="保留策略"><el-radio-group v-model="mode">
    <el-radio value="manual">保留指定标签</el-radio><el-radio value="auto">优先可信置信度</el-radio>
   </el-radio-group></el-form-item>
   <el-form-item v-if="mode==='manual'" label="正式标签">
    <el-select v-model="label" filterable><el-option v-for="item in labels" :key="item.code" :label="item.display_name || item.code" :value="item.code" /></el-select>
   </el-form-item>
   <el-form-item label="IoU 阈值（大于或等于）">
    <el-input-number v-model="threshold" :min="0.5" :max="1" :step="0.01" :precision="2" />
   </el-form-item>
  </el-form>
  <template v-if="pending">
   <p v-if="task" role="status">{{isPlan?'消歧预检':'保存草稿'}} · {{statusLabels[task.status]||task.status}} · {{task.processed ?? 0}} / {{task.total ?? '待核验'}} 张 · {{isPlan?'可处理':'已保存'}} {{task.succeeded ?? 0}} 张 · {{isPlan?'跳过':'失败'}} {{task.failed ?? 0}} 张</p>
   <p v-else role="status">{{canReplay?'尚未查到任务，可按原请求继续提交。':'任务结果待核验。'}}</p>
   <p v-if="isPlan && task?.result">移除 {{task.result.removed ?? 0}} 个重叠框 · {{task.result.fallback_groups ?? 0}} 组按原候选顺序保留</p>
   <ul v-if="task?.result?.skipped_reasons"><li v-for="(count,reason) in task.result.skipped_reasons" :key="reason">{{reason}}（{{count}}）</li></ul>
   <ul v-else-if="task?.error_examples?.length"><li v-for="(item,index) in task.error_examples" :key="index">{{item.error}}</li></ul>
   <el-table v-if="task?.result?.examples?.length" :data="task.result.examples" max-height="200" aria-label="消歧样例">
    <el-table-column prop="id" label="素材"/><el-table-column prop="before" label="原框" width="68"/>
    <el-table-column prop="after" label="保留框" width="80"/><el-table-column label="保留标签">
     <template #default="{row}">{{row.labels.join('、')}}</template>
    </el-table-column>
   </el-table>
   <el-checkbox v-if="canSave" v-model="confirmed">确认按选定策略保存候选草稿</el-checkbox>
   <el-checkbox v-if="canFormal" v-model="formalConsent">已核对人工指定标签和保留范围</el-checkbox>
   <p v-else-if="!isPlan&&terminal&&pending.plan.mode==='auto'">自动策略只保存草稿，请人工复核后入库。</p>
  </template>
  <template #footer>
   <el-button :disabled="busy||formalBusy" @click="open=false">关闭</el-button>
   <el-button v-if="!pending&&range" type="primary" :disabled="busy||(mode==='manual'&&!label)" @click="prepare">预检消歧</el-button>
   <el-button v-if="pending" :loading="busy" @click="refresh">刷新任务</el-button>
   <el-button v-if="canReplay" :disabled="busy" @click="replay">按原请求提交</el-button>
   <el-button v-if="task&&!terminal&&task.status!=='CANCEL_REQUESTED'" :disabled="busy" @click="manage('cancel')">取消任务</el-button>
   <el-button v-if="!isPlan&&terminal&&(task?.status==='CANCELLED'||task?.status==='FAILED')" :disabled="busy" @click="manage('retry')">继续未处理项</el-button>
   <el-button v-if="terminal||canReplay" :disabled="busy||formalBusy" @click="clear">完成核对</el-button>
   <el-button v-if="canSave" type="primary" :disabled="!confirmed||busy" @click="save">保存草稿</el-button>
   <el-button v-if="canFormal" type="primary" :loading="formalBusy" :disabled="!formalConsent||busy" @click="freeze">预检 C2-B 正式入库</el-button>
  </template>
 </el-dialog>
</template>
