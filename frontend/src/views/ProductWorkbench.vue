<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref} from 'vue';
import type {ProductWorkbenchContext} from '../types/product-workbench';
import type {AiTaskPage} from '../types/ai-tasks';
import {aiTasksApi} from '../api/ai-tasks';
import {trainingReaderApi,type TaskPage,type TrainingTask} from '../api/training-reader';
import {useReadScope} from '../composables/useReadScope';
import PageHeader from '../components/PageHeader.vue';

const props=defineProps<{context:ProductWorkbenchContext}>();
const scope=props.context,projectId=scope.projectId,reads=useReadScope(scope);
const trainingApi=trainingReaderApi(scope),aiApi=aiTasksApi(scope);
const training=ref<TaskPage|null>(null),ai=ref<AiTaskPage|null>(null);
const trainingReadAt=ref(''),aiReadAt=ref(''),opening=ref(''),navigationError=ref('');
const trainingRows=computed(()=>training.value?.items.slice(0,5)||[]);
const aiRows=computed(()=>ai.value?.items.slice(0,5)||[]);
const available=computed(()=>Boolean(projectId)&&!props.context.scopeError&&!scope.signal.aborted&&props.context===scope&&props.context.projectId===projectId);
let alive=true;
onBeforeUnmount(()=>{alive=false});
function current(){return alive&&!scope.signal.aborted&&available.value}
function progress(value:number|undefined){return typeof value==='number'&&Number.isFinite(value)?`${value}%`:'未提供'}
function loadTraining(){
  if(!current())return;
  return reads.run('training',signal=>trainingApi.tasks({},signal,5),value=>{
    if(current()){training.value=value;trainingReadAt.value=new Date().toLocaleTimeString()}
  });
}
function loadAi(){
  if(!current())return;
  return reads.run('ai',signal=>aiApi.list('','','',signal,5),value=>{
    if(current()){ai.value=value;aiReadAt.value=new Date().toLocaleTimeString()}
  });
}
async function navigate(id:string,action:()=>unknown){
  if(!current()||opening.value)return;
  opening.value=id;navigationError.value='';
  try{await action()}
  catch(_){if(current())navigationError.value='暂时无法打开该入口，请重试。'}
  finally{if(alive)opening.value=''}
}
function report(row:TrainingTask){
  if(!row.report_job_id||!scope.openReport)return;
  void navigate(`report:${row.task_id}`,()=>scope.openReport?.({jobId:row.report_job_id!,algorithmId:row.algorithm_id,versionId:row.version_id,returnPage:'workbench'}));
}
onMounted(()=>{void loadTraining();void loadAi()});
</script>

<template><section class="catalog-preview product-workbench" aria-label="项目工作台">
  <PageHeader title="工作台" eyebrow="项目 / 工作台" description="查看近期任务，进入素材、算法与模型管理。" badge="当前项目" @back="navigate('legacy',()=>context.legacyWorkbench())"/>
  <div class="workbench-project"><span>当前项目</span><strong>{{ context.projectId||'未选择项目' }}</strong><small>近期任务各读取最多 5 条，状态以最近一次读取为准。</small></div>
  <el-alert v-if="context.scopeError||!context.projectId" :title="context.scopeError||'请先选择项目。'" type="warning" :closable="false"/>
  <el-alert v-if="navigationError" :title="navigationError" type="error" :closable="false"/>
  <section class="workbench-shortcuts" aria-label="业务入口"><h2>开始工作</h2><div class="shortcut-grid">
    <article v-for="entry in context.entries" :key="entry.id" class="shortcut-card" :data-workbench-entry="entry.id"><h3>{{ entry.title }}</h3><p>{{ entry.description }}</p><el-button :disabled="!available||Boolean(opening)" :loading="opening===entry.id" :aria-label="'打开'+entry.title" @click="navigate(entry.id,()=>context.open(entry.id))">打开{{ entry.title }}</el-button></article>
  </div><p v-if="!context.entries.length" class="workbench-muted">当前没有可用业务入口。</p></section>
  <div class="recent-grid">
    <section class="recent-panel" aria-label="近期训练任务" data-workbench-tasks="training"><header class="recent-heading"><div><h2>近期训练任务</h2><small>{{ trainingReadAt?'读取于 '+trainingReadAt:'尚未读取' }} · 最多 5 条</small></div><el-button :loading="reads.busy.training" :disabled="!available" @click="loadTraining">刷新训练任务</el-button></header>
      <el-alert v-if="reads.errors.training" :title="reads.errors.training" type="error" :closable="false"/><p v-if="reads.errors.training&&training" class="stale-notice">下方为上次读取结果，尚未确认最新状态。</p>
      <el-skeleton v-if="!training&&reads.busy.training" :rows="5" animated/>
      <p v-else-if="!training" class="workbench-muted">{{ reads.errors.training?'训练任务读取失败，可单独刷新重试。':'训练任务尚未读取。' }}</p>
      <p v-else-if="!trainingRows.length" class="workbench-muted">本次读取没有训练任务。</p>
      <div v-if="trainingRows.length" class="recent-list"><article v-for="row in trainingRows" :key="row.task_id" class="recent-task"><div class="task-heading"><strong>{{ row.task_id }}</strong><el-tag type="info" effect="plain">{{ row.status||'状态未提供' }}</el-tag></div><dl><div><dt>算法</dt><dd>{{ row.algorithm_name||row.algorithm_id||'未提供' }}<small v-if="row.algorithm_name&&row.algorithm_id">{{ row.algorithm_id }}</small></dd></div><div><dt>版本</dt><dd>{{ row.version_id||'未提供' }}</dd></div><div><dt>阶段 / 进度</dt><dd>{{ row.phase||'未提供' }} / {{ progress(row.progress_percent) }}</dd></div><div><dt>创建时间</dt><dd>{{ row.created_at||'未提供' }}</dd></div></dl><p v-if="row.resource_wait_reason||row.error" class="task-note">{{ row.resource_wait_reason||row.error }}</p><div v-if="context.openTasks||(row.report_job_id&&context.openReport)" class="task-actions"><el-button v-if="context.openTasks" link :disabled="!available||Boolean(opening)" @click="navigate('task:'+row.task_id,()=>context.openTasks?.(row.task_id))">查看任务</el-button><el-button v-if="row.report_job_id&&context.openReport" link :disabled="!available||Boolean(opening)" @click="report(row)">阅读报告</el-button></div></article></div>
    </section>
    <section class="recent-panel" aria-label="近期AI标注任务" data-workbench-tasks="ai"><header class="recent-heading"><div><h2>近期 AI 标注任务</h2><small>{{ aiReadAt?'读取于 '+aiReadAt:'尚未读取' }} · 最多 5 条</small></div><el-button :loading="reads.busy.ai" :disabled="!available" @click="loadAi">刷新 AI 任务</el-button></header>
      <el-alert v-if="reads.errors.ai" :title="reads.errors.ai" type="error" :closable="false"/><p v-if="reads.errors.ai&&ai" class="stale-notice">下方为上次读取结果，尚未确认最新状态。</p>
      <el-skeleton v-if="!ai&&reads.busy.ai" :rows="5" animated/>
      <p v-else-if="!ai" class="workbench-muted">{{ reads.errors.ai?'AI 任务读取失败，可单独刷新重试。':'AI 任务尚未读取。' }}</p>
      <p v-else-if="!aiRows.length" class="workbench-muted">{{ ai.indexing||ai.statistics_indexing?'任务索引正在准备，可稍后手动刷新。':'本次读取没有 AI 标注任务。' }}</p>
      <div v-if="aiRows.length" class="recent-list"><article v-for="row in aiRows" :key="row.id" class="recent-task"><div class="task-heading"><strong>{{ row.name||row.id }}</strong><el-tag type="info" effect="plain">{{ row.status||'状态未提供' }}</el-tag></div><small v-if="row.name" class="task-id">{{ row.id }}</small><dl><div><dt>模型服务</dt><dd>{{ row.model_config_name||'未提供' }}</dd></div><div><dt>服务类型</dt><dd>{{ row.model_provider||'未提供' }}</dd></div><div><dt>阶段 / 进度</dt><dd>{{ row.phase||'未提供' }} / {{ progress(row.progress_percent) }}</dd></div><div><dt>创建时间</dt><dd>{{ row.created_at||'未提供' }}</dd></div></dl><p v-if="row.resource_wait_reason||row.error" class="task-note">{{ row.resource_wait_reason||row.error }}</p></article></div>
    </section>
  </div>
</section></template>

<style scoped>
.product-workbench{min-width:0;color:#202124}.workbench-project{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 14px;padding:14px 0 20px}.workbench-project>span,.workbench-project small,.workbench-muted{color:#646970;font-size:13px;line-height:1.7}.workbench-project strong{overflow-wrap:anywhere}.workbench-project small{margin-left:auto}.workbench-shortcuts{margin:8px 0 26px}.workbench-shortcuts h2,.recent-heading h2{font-size:17px;line-height:1.5;margin:0 0 12px}.shortcut-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.shortcut-card{display:flex;flex-direction:column;align-items:flex-start;min-width:0;background:#fff;border:1px solid #e4e7eb;border-radius:9px;padding:17px}.shortcut-card h3{font-size:15px;line-height:1.6;margin:0;overflow-wrap:anywhere}.shortcut-card p{flex:1;margin:8px 0 14px;font-size:13px;line-height:1.8;color:#646970;overflow-wrap:anywhere}.shortcut-card :deep(.el-button){max-width:100%;height:auto;min-height:32px;white-space:normal;line-height:1.6}.recent-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;align-items:start}.recent-panel{min-width:0;background:#fff;border:1px solid #e4e7eb;border-radius:9px;padding:18px}.recent-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:16px}.recent-heading h2{margin:0 0 4px}.recent-heading small,.task-id{font-size:12px;line-height:1.7;color:#646970}.recent-heading :deep(.el-button){flex-shrink:0}.recent-task{padding:16px 0;border-top:1px solid #edf0f2;min-width:0}.task-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.task-heading strong{font-size:14px;line-height:1.7;overflow-wrap:anywhere;min-width:0}.task-heading :deep(.el-tag){max-width:55%;height:auto;min-height:24px;white-space:normal;overflow-wrap:anywhere;flex-shrink:0}.task-id{display:block;overflow-wrap:anywhere;margin-top:4px}.recent-task dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 18px;margin:12px 0 0}.recent-task dl>div{min-width:0}.recent-task dt{font-size:12px;line-height:1.7;color:#646970}.recent-task dd{font-size:13px;line-height:1.7;margin:2px 0 0;overflow-wrap:anywhere}.recent-task dd small{display:block;color:#646970;font-size:12px}.task-note,.stale-notice{font-size:12px;line-height:1.8;overflow-wrap:anywhere;color:#72552c;margin:10px 0 0}.task-actions{display:flex;flex-wrap:wrap;gap:12px;margin-top:10px}.task-actions :deep(.el-button){margin:0}.workbench-muted{margin:16px 0}.product-workbench>:deep(.el-alert){margin-bottom:12px}
@media(min-width:1600px){.shortcut-grid{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-width:1100px){.recent-grid{grid-template-columns:minmax(0,1fr)}.shortcut-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.workbench-project small{margin-left:0;flex-basis:100%}}
@media(max-width:650px){.shortcut-grid{grid-template-columns:minmax(0,1fr)}.recent-panel{padding:14px}.recent-heading{flex-wrap:wrap}.recent-task dl{gap:10px}.task-heading{flex-wrap:wrap}.task-heading :deep(.el-tag){max-width:100%}}
@media(max-width:400px){.recent-task dl{grid-template-columns:minmax(0,1fr)}}
</style>
