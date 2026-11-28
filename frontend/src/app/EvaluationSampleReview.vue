<script setup lang="ts">
import {onBeforeUnmount,onMounted,ref} from 'vue';
import {request} from './http';
import {readWorkspaceSession,useWorkspace,workspaceActorKey} from './main';
import {browseError} from '../api/model-browse';

const props=defineProps<{projectId:string;algorithmId:string;versionId:string;evaluationId:string;imageId:string;imageSha:string;filename:string}>();
const emit=defineEmits<{close:[]}>();
const controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
const actor=useWorkspace().actorKey;
const key='evaluation-review:'+JSON.stringify([actor,props.projectId,props.algorithmId,props.versionId,props.evaluationId,props.imageId]);
const url='/api/v12/projects/'+[props.projectId,'algorithms',props.algorithmId,'versions',props.versionId,'evaluation','review'].map(encodeURIComponent).join('/');
const identity={expected_evaluation_id:props.evaluationId,image_id:props.imageId};
type Feedback={id:string;project_id:string;algorithm_id:string;version_id:string;input_sha256:string;status:string;note:string;
  source:{source_channel:string;external_source:string;external_sample_id:string};result:{review_observation?:string;frozen_test_protected?:boolean;formal_gt_changed?:boolean}};
const choices={model_error:'模型错误',gt_error:'标注疑点',model_correct:'模型结果正确',hard_sample:'困难样本',unknown:'待进一步核对'};
const observation=ref<keyof typeof choices|''>(''),note=ref(''),error=ref(''),busy=ref(false),unknown=ref(false),ready=ref(false);
const receipt=ref<Feedback|null>(null);
function verify(value:Feedback){
  if(!value.id||value.project_id!==props.projectId||value.algorithm_id!==props.algorithmId||value.version_id!==props.versionId
    ||value.input_sha256!==props.imageSha||value.source?.source_channel!=='evaluation'
    ||value.source.external_source!==props.evaluationId||value.source.external_sample_id!==props.imageId
    ||(value.status==='confirmed'&&(value.result?.frozen_test_protected!==true||value.result.formal_gt_changed!==false)))
    throw new Error('复核回执与冻结样本身份不一致');
  return value;
}
function remember(value:boolean){
  if(value)sessionStorage.setItem(key,'pending');
  else sessionStorage.removeItem(key);
  unknown.value=value;
}
async function read(){
  if(busy.value)return;
  busy.value=true;ready.value=false;error.value='';
  try{
    unknown.value=sessionStorage.getItem(key)==='pending';
    const result=await request<{ok:boolean;feedback:Feedback|null}>(url+'?'+new URLSearchParams(identity),{signal:controller.signal});
    if(result.ok!==true)throw new Error('复核记录暂不可核验');
    receipt.value=result.feedback?verify(result.feedback):null;
    if(receipt.value){note.value=receipt.value.note;remember(false)}
    ready.value=true;
  }catch(cause){if(!controller.signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false}
}
async function save(){
  if(busy.value||!ready.value||unknown.value||!observation.value||receipt.value?.status==='confirmed')return;
  busy.value=true;error.value='';
  let sent=false;
  try{
    if(!actor||workspaceActorKey(await readWorkspaceSession(controller.signal))!==actor)throw new Error('会话已变化，请重新打开报告');
    remember(true);sent=true;
    const value=await request<{ok:boolean;feedback:Feedback;frozen_test_protected:boolean;automatic_execution:boolean}>(url,{
      method:'POST',signal:controller.signal,body:JSON.stringify({...identity,observation:observation.value,note:note.value}),
    });
    if(!value.ok||value.frozen_test_protected!==true||value.automatic_execution!==false)throw new Error('复核保护回执不完整');
    receipt.value=verify(value.feedback);
    remember(false);
    if(observation.value!=='unknown'&&receipt.value.result.review_observation!==observation.value)
      error.value='服务端已有不同复核结论，以下为持久记录。';
  }catch(cause){
    const status=(cause as {httpStatus?:number})?.httpStatus;
    if(!controller.signal.aborted){if(sent&&status&&status>=400&&status<500)remember(false);error.value=browseError(cause)}
  }finally{busy.value=false}
}
onMounted(()=>void read());
</script>

<template>
 <el-dialog :model-value="true" title="独立 Test 样本复核" width="min(570px,94vw)" :close-on-click-modal="false"
  :close-on-press-escape="!busy" :show-close="!busy" @close="emit('close')">
  <p>{{filename}} · {{imageId}}</p>
  <p>复核意见单独保存。冻结 Test、正式标注和训练数据保持原样。</p>
  <el-alert v-if="error" :title="error" type="error" :closable="false"/>
  <p v-if="unknown" role="status">提交结果待核验。请读取原复核记录。</p>
  <p v-if="receipt" role="status">回执 {{receipt.id}} ·
   {{ receipt.status==='confirmed' ? choices[receipt.result.review_observation as keyof typeof choices]||'已确认' : '意见已记录，待复核' }}
  </p>
  <template v-if="ready&&!unknown&&receipt?.status!=='confirmed'">
   <el-select v-model="observation" aria-label="复核结论" placeholder="选择复核结论" :disabled="busy" style="width:100%">
    <el-option v-for="(label,value) in choices" :key="value" :label="label" :value="value"/>
   </el-select>
   <el-input v-model="note" aria-label="复核说明" type="textarea" maxlength="1000" :disabled="busy" placeholder="补充说明" style="margin-top:12px"/>
  </template>
  <p v-else-if="receipt?.note">{{receipt.note}}</p>
  <template #footer>
   <el-button :loading="busy" @click="read">核对原回执</el-button>
   <el-button v-if="ready&&!unknown&&receipt?.status!=='confirmed'" type="primary" :disabled="busy||!observation" @click="save">确认提交复核</el-button>
  </template>
 </el-dialog>
</template>
