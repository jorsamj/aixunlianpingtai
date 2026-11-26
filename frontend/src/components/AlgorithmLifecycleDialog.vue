<script setup lang="ts">
import {computed,onUnmounted,ref} from 'vue';
import {browseError} from '../api/model-browse';
import {deletedVersion,submitLifecycle,verifyLifecycle,type LifecycleTarget,type VersionOperation} from '../api/algorithm-lifecycle';

const props=defineProps<{projectId:string;target:LifecycleTarget;recovering:boolean;saveIntent(value:LifecycleTarget|null):void}>();
const emit=defineEmits<{close:[];completed:[target:LifecycleTarget,message:string,receipt:VersionOperation]}>();
const scope=new AbortController();
onUnmounted(()=>scope.abort());
const busy=ref(false),unknown=ref(props.recovering),error=ref('');
const title=computed(()=>props.target.action==='rollback'?'删除当前版本并回退':'删除版本');

async function run(){
 if(busy.value)return;
 const target=props.target,checking=unknown.value;
 busy.value=true;
 error.value='';
 let sent=false;
 try{
  if(!checking){props.saveIntent(target);sent=true}
  const receipt=checking
   ?await verifyLifecycle(props.projectId,target,scope.signal)
   :await submitLifecycle(props.projectId,target);
  if(scope.signal.aborted)return;
  props.saveIntent(null);
  const message=`${title.value}已确认。操作 ID ${receipt.operation_id}。`;
  emit('completed',target,message,receipt);
 }catch(cause){
  if(scope.signal.aborted)return;
  const status=(cause as {httpStatus?:number}).httpStatus;
  unknown.value=checking||(sent&&(!status||![400,401,403,404,409,422].includes(status)));
  if(sent&&!unknown.value){
   try{props.saveIntent(null)}catch{unknown.value=true}
  }
  error.value=browseError(cause);
 }finally{busy.value=false}
}
</script>

<template>
 <el-dialog :model-value="true" :title="title" width="min(560px,94vw)"
  :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" @close="emit('close')">
  <p>算法 {{ target.algorithmName }}（{{ target.algorithmId }}）</p>
  <p>将删除版本 {{ target.action==='rollback'?deletedVersion(target):target.versionName+'（'+target.versionId+'）' }}</p>
  <p v-if="target.action==='rollback'">回到版本 {{ target.versionName }}（{{ target.versionId }}）</p>
  <p>服务端会检查训练、转换、部署测试和待审核在线回流引用。线上部署实例需要另行核对。</p>
  <el-alert v-if="error" :title="error" type="error" :closable="false"/>
  <p v-if="unknown" role="status">操作结果尚未确认。请核对服务端记录，避免重复提交。</p>
  <template #footer>
   <el-button :disabled="busy" @click="emit('close')">{{ unknown?'关闭':'取消' }}</el-button>
   <el-button :type="unknown?'primary':'danger'" :loading="busy" @click="run">
    {{ unknown?'核对操作结果':'确认'+title }}
   </el-button>
  </template>
 </el-dialog>
</template>
