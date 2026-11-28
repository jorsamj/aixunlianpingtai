<script setup lang="ts">
import {computed,onBeforeUnmount,ref,shallowRef,watch} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {previewLabelUnify,createLabelUnify,type ProjectLabel,type LabelImpact} from '../api/label-management';
import {getMaterialBatch,type MaterialBatchTask} from '../api/material-batches';
import {request} from '../app/http';
import {browseError} from '../api/model-browse';
const props=defineProps<{projectId:string;labels:ProjectLabel[]}>();
const emit=defineEmits<{settled:[];pending:[value:boolean]}>();
const route=useRoute(),router=useRouter();
const sources=ref<number[]>([]),target=shallowRef(''),search=shallowRef('');
const preview=shallowRef<LabelImpact|null>(null),task=shallowRef<MaterialBatchTask|null>(null),error=shallowRef('');
const busy=shallowRef(false),previewBusy=shallowRef(false),notice=shallowRef('');
const labels:Record<string,string>={QUEUED:'排队中',WAITING_RESOURCE:'等待资源',RUNNING:'处理中',CANCEL_REQUESTED:'正在取消',SUCCEEDED:'已完成',PARTIAL_SUCCESS:'部分成功',FAILED:'失败',CANCELLED:'已取消',BLOCKED_BY_ENVIRONMENT:'环境阻断',BLOCKED_BY_HARDWARE:'硬件阻断'};
const terminal=new Set(['SUCCEEDED','PARTIAL_SUCCESS','FAILED','CANCELLED','BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE']);
const active=computed(()=>!!task.value&&!terminal.has(task.value.status));
const pending=computed(()=>route.query.unify_pending==='1');
const visibleSources=computed(()=>props.labels.filter(row=>(row.affected_images??0)>0&&`${row.code} ${row.display_name||''}`.toLowerCase().includes(search.value.trim().toLowerCase())));
const targets=computed(()=>props.labels.filter(row=>!sources.value.includes(row.class_id)));
const canStart=computed(()=>!busy.value&&!previewBusy.value&&!pending.value&&!active.value&&(!route.query.unify_task||!!task.value)&&!!target.value&&!!preview.value&&sources.value.length>0&&sources.value.length<=50);
let previewController:AbortController|undefined,taskController:AbortController|undefined,timer:ReturnType<typeof setTimeout>|undefined,alive=true,settledId='';

function stop(){if(timer!==undefined){clearTimeout(timer);timer=undefined}}
function identity(value:MaterialBatchTask,id?:string){
 if(!value.task_id||value.project_id!==props.projectId||value.operation!=='REMAP_ANNOTATION_LABELS'||value.retire_sources_on_success!==true||(id&&value.task_id!==id))throw new Error('标签统一任务身份不一致');
 const expectedSources=typeof route.query.unify_sources==='string'?route.query.unify_sources:'',expectedTarget=route.query.unify_target;
 if(pending.value&&!expectedSources)throw new Error('缺少原请求范围，请在原任务记录中人工核对。');
 if(expectedSources&&(JSON.stringify([...(value.source_labels||[])].sort())!==expectedSources||value.target_label!==expectedTarget))throw new Error('任务来源及目标标签与原请求不一致');
 return value;
}
async function readTask(id:string){
 stop();taskController?.abort();const current=new AbortController();taskController=current;error.value='';
 try{
  const value=identity(await getMaterialBatch(props.projectId,id,current.signal),id);
  if(!alive||current.signal.aborted)return;
  task.value=value;
  if(terminal.has(value.status)){
   if(settledId!==id){settledId=id;sources.value=[];target.value='';preview.value=null;emit('settled')}
  }else timer=setTimeout(()=>void readTask(id),2000);
 }catch(cause){if(alive&&!current.signal.aborted)error.value=browseError(cause)}
}
watch(()=>sources.value.join(','),async(_value,_old,onCleanup)=>{
 previewController?.abort();preview.value=null;error.value='';
 if(!targets.value.some(row=>row.code===target.value))target.value='';
 if(!sources.value.length||sources.value.length>50){previewBusy.value=false;return}
 const c=new AbortController();previewController=c;onCleanup(()=>c.abort());previewBusy.value=true;
 const ids=[...sources.value];
 try{
  const result=await previewLabelUnify(props.projectId,ids,c.signal);
  if(c.signal.aborted)return;
  const expected=props.labels.filter(row=>ids.includes(row.class_id)).map(row=>row.code).sort();
  if(!result.ok||JSON.stringify([...result.source_labels].sort())!==JSON.stringify(expected)||![result.positive_images,result.scope_images,result.boxes,result.affected_images].every(value=>Number.isSafeInteger(value)&&value>=0))throw new Error('标签影响范围响应无效');
  preview.value=result;
 }catch(cause){if(!c.signal.aborted)error.value=browseError(cause)}finally{if(previewController===c)previewBusy.value=false}
});
watch(pending,value=>emit('pending',value),{immediate:true});
async function start(){
 if(!canStart.value)return;
 const ids=[...sources.value],code=target.value;
 busy.value=true;error.value='';notice.value='';
 try{
  // The URL retains an unresolved create; refresh never replays this POST.
  const codes=props.labels.filter(row=>ids.includes(row.class_id)).map(row=>row.code).sort();
  const failure=await router.replace({query:{...route.query,unify_pending:'1',unify_task:undefined,unify_sources:JSON.stringify(codes),unify_target:code}});
  if(failure)throw new Error('无法保留待核请求，本次未提交。');
  try{
   const value=identity(await createLabelUnify(props.projectId,ids,code));
   if(!alive)return;
   task.value=value;
   await router.replace({query:{...route.query,unify_pending:undefined,unify_task:value.task_id}});
   void readTask(value.task_id);
  }catch(cause){
   const status=(cause as {httpStatus?:number}).httpStatus;
   if(status&&[400,401,403,404,409,422].includes(status))await router.replace({query:{...route.query,unify_pending:undefined}});
   throw cause;
  }
 }catch(cause){if(alive)error.value=browseError(cause)}finally{busy.value=false}
}
const recoveryId=shallowRef('');
async function recover(){
 const id=recoveryId.value.trim();if(!id||busy.value)return;
 stop();taskController?.abort();const current=new AbortController();taskController=current;
 busy.value=true;error.value='';
 try{const value=identity(await getMaterialBatch(props.projectId,id,current.signal),id);if(!alive||current.signal.aborted)return;task.value=value;await router.replace({query:{...route.query,unify_pending:undefined,unify_task:id}});void readTask(id)}
 catch(cause){if(!current.signal.aborted)error.value=browseError(cause)}finally{busy.value=false}
}
async function cancel(){
 const id=task.value?.task_id;if(!id||busy.value)return;
 busy.value=true;notice.value='';
 try{stop();taskController?.abort();identity(await request<MaterialBatchTask>(`/api/v62/projects/${encodeURIComponent(props.projectId)}/material-batches/${encodeURIComponent(id)}/cancel`,{method:'POST'}),id);notice.value='已请求取消，正在核对任务状态。'}
 catch(cause){notice.value='取消结果待核对，请读取任务状态。';error.value=browseError(cause)}
 finally{busy.value=false;void readTask(id)}
}
const initialId=typeof route.query.unify_task==='string'?route.query.unify_task:'';
if(initialId)void readTask(initialId);
onBeforeUnmount(()=>{alive=false;stop();previewController?.abort();taskController?.abort()});
</script>
<template><section class="label-unify" aria-label="批量统一标签">
 <header><h2>统一历史标签</h2><p>正式标注及已确认无目标范围一起迁移；完成后停用来源标签，历史训练版本保持不变。</p></header>
 <el-alert v-if="error" :title="error" type="error" :closable="false"/>
 <section v-if="pending" class="label-recovery"><el-alert title="创建结果待核对，请勿重复提交。请在原任务记录核对任务 ID 后读取。" type="warning" :closable="false"/><el-input v-model="recoveryId" aria-label="标签统一任务 ID" placeholder="任务 ID"/><el-button :loading="busy" :disabled="!recoveryId.trim()" @click="recover">读取已有任务</el-button></section>
 <div class="unify-columns"><section><h3>来源标签 · {{ sources.length }} / 50</h3><el-input v-model="search" aria-label="搜索来源标签" placeholder="搜索编码或名称" clearable/><el-checkbox-group v-model="sources" :disabled="busy||pending||active" :max="50" class="unify-sources"><el-checkbox v-for="row in visibleSources" :key="row.class_id" :value="row.class_id"><strong>{{ row.display_name||row.code }}</strong><span>{{ row.code }} · {{ row.affected_images }} 张素材</span></el-checkbox></el-checkbox-group><el-empty v-if="!visibleSources.length" description="暂无匹配的历史引用标签" :image-size="56"/></section>
 <section><h3>目标标签</h3><el-select v-model="target" :disabled="busy||pending||active" aria-label="统一目标标签" filterable placeholder="选择目标标签"><el-option v-for="row in targets" :key="row.class_id" :label="`${row.display_name||row.code} · ${row.code}`" :value="row.code"/></el-select>
 <dl class="impact" v-loading="previewBusy"><div v-for="[name,key] in [['正样本图片','positive_images'],['无目标范围','scope_images'],['标注框','boxes'],['受影响素材','affected_images']] as const" :key="key"><dt>{{name}}</dt><dd>{{preview?.[key]??'—'}}</dd></div></dl>
 <el-button type="primary" :disabled="!canStart" :loading="busy" @click="start">开始后台统一</el-button></section></div>
 <section v-if="task" class="unify-task" aria-live="polite"><header><h3>{{ labels[task.status]||task.status }}</h3><code>{{task.task_id}}</code></header><p>已处理 {{task.processed??'未知'}} / {{task.total??'未知'}} · 成功 {{task.succeeded??'未知'}} · 失败 {{task.failed??'未知'}}</p><p v-if="notice">{{notice}}</p><p v-for="(item,index) in task.error_examples||[]" :key="index">{{item.error}}</p><div class="task-actions"><el-button :disabled="busy" @click="readTask(task.task_id)">刷新状态</el-button><el-button v-if="active" :disabled="busy||task.status==='CANCEL_REQUESTED'" @click="cancel">取消任务</el-button><el-button v-if="task.log_available" tag="a" target="_blank" rel="noopener" :href="`/api/v62/projects/${encodeURIComponent(projectId)}/material-batches/${encodeURIComponent(task.task_id)}/log`">完整任务日志</el-button></div>
 <p v-if="task.changed_images!=null">已改写 {{task.changed_images}} 张素材 / {{task.changed_boxes??'未知'}} 个框。</p><p v-if="task.status==='PARTIAL_SUCCESS'||task.status==='FAILED'||task.status==='CANCELLED'">可能已有部分正式标注及素材投影更新，请在标签审计中复核；来源标签不能据此认定已经清零。</p></section>
</section></template>
<style scoped>
.label-unify{background:#fff;border:1px solid #dedede;border-radius:8px;padding:20px}.label-unify h2{font-size:17px;margin:0}.label-unify h3{font-size:14px}.label-unify header p{font-size:13px;color:#666;line-height:1.7}.unify-columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(280px,1fr);gap:28px}.unify-sources{display:grid;max-height:300px;overflow:auto;margin-top:12px}.unify-sources :deep(.el-checkbox){height:auto;margin:0;padding:10px 4px;border-bottom:1px solid #eee}.unify-sources :deep(.el-checkbox__label){display:grid;gap:5px;white-space:normal;overflow-wrap:anywhere}.unify-sources span{color:#737373;font-size:12px}.impact{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:24px 0}.impact dt{font-size:12px;color:#737373}.impact dd{margin:6px 0 0;font-size:23px;font-variant-numeric:tabular-nums}.unify-task{border-top:1px solid #ddd;margin-top:24px;padding-top:16px}.unify-task header,.task-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.unify-task code{font-size:12px;overflow-wrap:anywhere}.unify-task p{font-size:13px}.task-actions{margin-bottom:12px}.label-recovery{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}.label-recovery .el-alert{width:100%}.label-recovery .el-input{max-width:320px}@media(max-width:1000px){.unify-columns{grid-template-columns:1fr;gap:16px}.unify-sources{max-height:220px}}
</style>
