<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref} from 'vue';
import {useRouter} from 'vue-router';
import {useReadScope} from '../composables/useReadScope';
import {getReviewTask,type ReviewTask} from '../api/ai-review';
import {adoptReviewed,confirmIteration,freezeFeedbackCandidates,isDigest,loadMiningMaterials,readFeedbackCandidates,readIteration,readReviewed,readTrainingSource,startMining} from '../api/training-iteration';
import type {FeedbackSample,IterationView,MiningSample,ReviewedSample} from '../api/training-iteration';
import {readWorkspaceSession,useWorkspace,workspaceActorKey} from './main';

const props=defineProps<{projectId:string;algorithmId:string;versionId:string;evaluationId:string}>();
const address={projectId:props.projectId,algorithmId:props.algorithmId,versionId:props.versionId};
const router=useRouter(),actor=useWorkspace().actorKey;
const controller=new AbortController(),reads=useReadScope(controller);
const view=ref<IterationView>(),eligible=ref<MiningSample[]>([]),selected=ref<string[]>([]);
const task=ref<ReviewTask>(),taskId=ref(''),taskInput=ref(''),reviewed=ref<ReviewedSample[]>([]),more=ref(false),offset=ref(0);
const miningChoices=ref<ReviewedSample[]>([]),feedback=ref<FeedbackSample[]>([]),feedbackChoices=ref<FeedbackSample[]>([]);
const truncated=ref(false),writing=ref(false),error=ref(''),notice=ref(''),consent=ref(false);
const scope='mining-request:'+JSON.stringify([actor,...Object.values(address),props.evaluationId]);
interface MiningRequest {image_ids:string[];source:'existing';request_key:string;expected_model_sha256:string;expected_source_hashes:Record<string,string>}
const pending=ref<MiningRequest>();
const current=computed(()=>view.value?.current_version_id===props.versionId);
const actionCode=computed(()=>view.value?.decision.decision==='needs_data'?'supplement_data'
  :view.value?.decision.decision==='continue_training'?'continue_training':undefined);
const actionNames={supplement_data:'补充数据',continue_training:'继续训练'};
const canSupplement=computed(()=>current.value&&view.value?.action?.action==='supplement_data'&&view.value.action.status==='confirmed');
const canOpenTraining=computed(()=>current.value&&(view.value?.action?.action==='continue_training'||!!view.value?.candidate_set));
const states:Record<string,string>={QUEUED:'排队中',RUNNING:'运行中',AWAITING_CONFIRMATION:'待人工审核',
  SUCCEEDED:'已完成',FAILED:'失败',CANCEL_REQUESTED:'正在取消',CANCELLED:'已取消'};
const params={projectId:props.projectId};
const taskLink=computed(()=>({name:'ai-review-native',params:{...params,taskId:taskId.value}}));
function load(){
  return reads.run('iteration',signal=>readIteration(address,signal),value=>{
    if(value.evaluation_id!==props.evaluationId)throw new Error('冻结评测已变化，请重新打开报告');
    view.value=value;
  });
}
async function write(action:()=>Promise<void>){
  if(writing.value)return;
  writing.value=true;error.value='';notice.value='';
  try{
    if(!actor||workspaceActorKey(await readWorkspaceSession(controller.signal))!==actor)throw new Error('会话已变化，请重新打开报告');
    await action();
  }catch(cause){if(!controller.signal.aborted)error.value=(cause as Error).message}
  finally{writing.value=false}
}
function confirmDecision(){
  const decision=view.value?.decision.decision_id,code=actionCode.value;
  if(!current.value||!isDigest(decision)||!code||!window.confirm('确认'+actionNames[code]+'建议？本次确认只保存决策。'))return;
  return write(async()=>{await confirmIteration(address,code,decision,controller.signal);await load()});
}
function loadEligible(){
  return reads.run('eligible',signal=>loadMiningMaterials(address,signal),result=>{
    if(result.display_items?.length!==result.items.length||result.items.length>100||
      result.display_items.some((row,index)=>row.image_id!==result.items[index]||!isDigest(row.content_sha256)))
      throw new Error('挖掘范围缺少可信素材身份');
    eligible.value=result.display_items;selected.value=[];
  });
}
function createMining(){
  if(!pending.value&&(!selected.value.length||!isDigest(view.value?.model_sha256)))return;
  if(!window.confirm(pending.value?'按原素材摘要重试原请求？':'创建所选素材的困难样本挖掘任务？'))return;
  return write(async()=>{
    let packet=pending.value;
    if(!packet){
      const chosen=new Set(selected.value);
      const rows=eligible.value.filter(row=>chosen.has(row.image_id));
      if(!rows.length||rows.length!==chosen.size)throw new Error('所选素材已变化');
      packet={image_ids:rows.map(row=>row.image_id),source:'existing',
        request_key:Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join(''),
        expected_model_sha256:view.value!.model_sha256,
        expected_source_hashes:Object.fromEntries(rows.map(row=>[row.image_id,row.content_sha256]))};
      sessionStorage.setItem(scope,JSON.stringify(packet));pending.value=packet;
    }
    const receipt=await startMining(address,{...packet},controller.signal);
    const id=receipt.id||receipt.task_id;
    if(!id||!/^hm[a-f0-9]{14}$/.test(id))throw new Error('挖掘任务回执身份缺失');
    sessionStorage.setItem(scope+':task',id);sessionStorage.removeItem(scope);pending.value=undefined;
    taskInput.value=id;
    await findTask();
  });
}
function findTask(){
  const id=taskInput.value.trim();
  if(!/^hm[a-f0-9]{14}$/.test(id))return;
  if(taskId.value!==id){taskId.value='';task.value=undefined;miningChoices.value=[];reviewed.value=[];consent.value=false}
  return reads.run('task',signal=>getReviewTask({projectId:props.projectId,taskId:id},signal),value=>{task.value=value;taskId.value=id});
}
function previewReviewed(start=0){
  if(!taskId.value)return;
  return reads.run('reviewed',signal=>readReviewed(address,taskId.value,start,signal),value=>{
    if(value.ok!==true||value.items.length>24)throw new Error('审核候选范围无法核验');
    reviewed.value=value.items;more.value=value.has_more;offset.value=start;consent.value=false;
  });
}
function loadFeedback(){
  return reads.run('feedback',signal=>readFeedbackCandidates(address,signal),value=>{
    if(value.action_id!==view.value?.action?.action_id||value.items.length>500)throw new Error('补数候选与已确认决策不一致');
    feedback.value=value.items;truncated.value=value.truncated;feedbackChoices.value=[];consent.value=false;
  });
}
function selectReviewed(rows:ReviewedSample[]){
  const byId=new Map(miningChoices.value.map(row=>[row.image_id,row]));
  for(const row of reviewed.value)byId.delete(row.image_id);
  for(const row of rows)if(row.eligible&&isDigest(row.candidate_digest))byId.set(row.image_id,row);
  miningChoices.value=[...byId.values()];consent.value=false;
}
function freeze(fromMining:boolean){
  if(!consent.value||!canSupplement.value||view.value?.candidate_set)return;
  return write(async()=>{
    try{
      if(fromMining){
        const rows=miningChoices.value;
        if(!rows.length||rows.length>50||rows.some(row=>!isDigest(row.candidate_digest)))return;
        await adoptReviewed(address,taskId.value,rows.map(row=>({image_id:row.image_id,candidate_digest:row.candidate_digest!})),controller.signal);
      }else{
        const rows=feedbackChoices.value;
        if(!rows.length||rows.some(row=>!row.eligible||!isDigest(row.candidate_digest)))return;
        await freezeFeedbackCandidates(address,rows.map(row=>({feedback_id:row.feedback_id,candidate_digest:row.candidate_digest})),controller.signal);
      }
    }finally{
      consent.value=false;
      await load();
    }
    if(view.value?.candidate_set)notice.value='已读取原版本的冻结补数回执。';
  });
}
function openTraining(){
  const value=view.value,action=value?.action;
  if(!value||!action||!canOpenTraining.value)return;
  const source={...address,actionId:action.action_id,evaluationId:value.evaluation_id,candidateSetId:value.candidate_set?.candidate_set_id||''};
  try{
    readTrainingSource(value,source);
    void router.push({name:'training-create',params,query:{algorithm:props.algorithmId,source_version:props.versionId,
      evaluation:source.evaluationId,action:source.actionId,supplement:source.candidateSetId||undefined}});
  }catch(cause){error.value=(cause as Error).message}
}
onMounted(()=>{
  try{
    const saved=sessionStorage.getItem(scope);
    if(saved)pending.value=JSON.parse(saved);
    taskInput.value=sessionStorage.getItem(scope+':task')||'';
  }catch{error.value='原困难样本记录无法读取'}
  void load();
  if(taskInput.value)void findTask();
});
onUnmounted(()=>controller.abort());
</script>

<template>
 <section class="iteration">
  <header><h3>困难样本与下一轮训练</h3><el-button :loading="reads.busy.iteration" :disabled="writing" @click="load">核对原决策与补数记录</el-button></header>
  <el-alert v-if="error||reads.errors.iteration" :title="error||reads.errors.iteration" type="error" :closable="false"/>
  <p v-if="notice" role="status">{{notice}}</p>
  <p v-if="view&&!current">当前报告为历史版本。</p>
  <p v-if="view">来源模型 SHA256 {{view.model_sha256||'未提供'}}</p>
  <div v-if="actionCode&&view" class="iteration-actions">
   <span>评测建议 {{actionNames[actionCode]}} · {{view.decision.weak_labels?.join('、')||'无额外标签'}}</span>
   <el-button v-if="current&&!view.action" :disabled="writing" @click="confirmDecision">确认{{actionNames[actionCode]}}建议</el-button>
   <el-button v-if="canOpenTraining" type="primary" :disabled="writing" @click="openTraining">{{view.candidate_set?'使用已冻结补数进入训练':'带来源继续训练'}}</el-button>
  </div>
  <p v-if="view?.candidate_set">原补数回执 {{view.candidate_set.candidate_set_id}} · {{view.candidate_set.material_ids.length}} 张</p>
  <section v-if="view" class="iteration-panel">
   <h4>挖掘非 Test 素材</h4>
   <p>冻结 Test 的问题样本可在评测中复核。挖掘范围由原服务按素材和内容摘要排除历史 Test。</p>
   <div class="iteration-actions">
    <el-button :loading="reads.busy.eligible" :disabled="writing||!!pending" @click="loadEligible">读取可挖掘素材</el-button>
    <el-button :loading="writing" :disabled="!pending&&!selected.length" @click="createMining">{{pending?'重试原挖掘请求':'挖掘所选素材'}}</el-button>
    <span v-if="pending">原请求待核验 · {{pending.image_ids.length}} 张</span>
    <el-checkbox v-if="eligible.length" :model-value="selected.length===eligible.length" :disabled="!!pending||writing"
     @change="(checked:unknown)=>selected=checked?eligible.map(row=>row.image_id):[]">选中当前批次</el-checkbox>
   </div>
   <el-alert v-if="reads.errors.eligible" :title="reads.errors.eligible" type="warning" :closable="false"/>
   <el-checkbox-group v-if="eligible.length" v-model="selected" class="iteration-list" :disabled="!!pending||writing">
    <el-checkbox v-for="row in eligible" :key="row.image_id" :value="row.image_id">{{row.filename||row.image_id}}</el-checkbox>
   </el-checkbox-group>
   <form class="iteration-actions" @submit.prevent="findTask">
    <el-input v-model="taskInput" aria-label="困难样本任务 ID" placeholder="困难样本任务 ID" :disabled="writing"/>
    <el-button native-type="submit" :loading="reads.busy.task">核验任务</el-button>
    <router-link v-if="taskId&&task?.status==='AWAITING_CONFIRMATION'" :to="taskLink">人工审核候选</router-link>
    <span v-if="task">{{states[task.status]||task.status}}<template v-if="task.phase"> · {{task.phase}}</template></span>
   </form>
   <el-alert v-if="reads.errors.task||reads.errors.reviewed" :title="reads.errors.task||reads.errors.reviewed" type="warning" :closable="false"/>
   <el-button v-if="task?.status==='SUCCEEDED'" :loading="reads.busy.reviewed" @click="previewReviewed(0)">读取已审核候选</el-button>
   <template v-if="reviewed.length||offset">
    <el-checkbox-group class="iteration-list" :model-value="miningChoices.map(row=>row.image_id)"
     @change="(keys:string[])=>selectReviewed(reviewed.filter(row=>keys.includes(row.image_id)))">
     <el-checkbox v-for="row in reviewed" :key="row.image_id" :value="row.image_id" :disabled="!row.eligible||writing||!!view.candidate_set">
      {{row.image_id}} · {{row.eligible?'正式 GT 已审核':row.reason}}
     </el-checkbox>
    </el-checkbox-group>
    <el-button :disabled="!offset||reads.busy.reviewed" @click="previewReviewed(Math.max(0,offset-24))">上一批</el-button>
    <el-button :disabled="!more||reads.busy.reviewed" @click="previewReviewed(offset+24)">下一批</el-button>
   </template>
  </section>
  <section v-if="canSupplement&&!view?.candidate_set" class="iteration-panel">
   <h4>确认补充范围</h4>
   <el-button :loading="reads.busy.feedback" @click="loadFeedback">读取已确认反馈</el-button>
   <el-alert v-if="reads.errors.feedback" :title="reads.errors.feedback" type="warning" :closable="false"/>
   <p v-if="truncated">本次展示前 500 条已确认反馈。</p>
   <el-table v-if="feedback.length" :data="feedback" row-key="feedback_id" max-height="280"
    @selection-change="(rows:FeedbackSample[])=>{feedbackChoices=rows;consent=false}">
    <el-table-column type="selection" :selectable="(row:FeedbackSample)=>row.eligible&&!writing"/>
    <el-table-column prop="material_id" label="素材" min-width="130"/>
    <el-table-column label="准入原因" min-width="180"><template #default="{row}">{{row.eligible?'正式 GT 已核验':row.reason_codes.join('、')}}</template></el-table-column>
    <el-table-column label="正式标注" min-width="100"><template #default="{row}">
      <router-link v-if="row.material_id&&!row.eligible&&row.reason_codes.includes('ANNOTATION_REQUIRED')" :to="{name:'formal-annotation',params,query:{image:row.material_id}}">打开标注</router-link>
    </template></el-table-column>
   </el-table>
   <el-checkbox v-if="miningChoices.length||feedbackChoices.length" v-model="consent" :disabled="writing">已核对范围，确认冻结所选补数候选</el-checkbox>
   <div class="iteration-actions">
    <el-button type="primary" :loading="writing" :disabled="!consent||!miningChoices.length||miningChoices.length>50||!!feedbackChoices.length" @click="freeze(true)">采纳已审核挖掘样本（{{miningChoices.length}}/50）</el-button>
    <el-button :loading="writing" :disabled="!consent||!feedbackChoices.length||!!miningChoices.length" @click="freeze(false)">冻结选中反馈（{{feedbackChoices.length}}）</el-button>
   </div>
  </section>
 </section>
</template>

<style scoped>
.iteration,.iteration-panel{display:grid;gap:10px;min-width:0}
.iteration header,.iteration-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.iteration header{justify-content:space-between}
.iteration h3,.iteration h4,.iteration p{margin:0;overflow-wrap:anywhere}
.iteration-panel{border:1px solid var(--el-border-color-light);padding:14px;border-radius:8px}
.iteration-list{display:grid;max-height:260px;overflow:auto}
.iteration-actions .el-input{width:min(100%,250px)}
</style>
