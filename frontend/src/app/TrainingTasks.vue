<script setup lang="ts">
import {ref,watch,onBeforeUnmount} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {request} from './http';
import {legacyUrl} from './navigation';
import {trainingReaderApi,type TrainingTask,type TaskPage} from '../api/training-reader';
import {useReadScope} from '../composables/useReadScope';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
import {withRequestDeadline} from '../../../static/modules/api.js';
const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId),controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
const reads=useReadScope(controller),api=trainingReaderApi({projectId,get:request,memory:{}});
const page = ref<TaskPage | null>(null);
const task = ref<TrainingTask | null>(null);
const log = ref('');
const query = ref('');
const status = ref('');
const kind = ref('');
const previousCursors = new Map<string, string>();
const param = (name: string) => typeof route.query[name] === 'string' ? String(route.query[name]) : '';
const listParams = () => ({query: param('query'), status: param('status'), kind: param('kind'), cursor: param('cursor')});

function navigate(values: Record<string, string>) {
  void router.push({
    name:'training-tasks', params:{projectId},
    query:Object.fromEntries(Object.entries(values).filter(([, value]) => value)),
  });
}
function search() {
  previousCursors.clear();
  navigate({query:query.value,status:status.value,kind:kind.value});
}
function open(id:string) {
  navigate({...listParams(), previous:param('previous'), task:id});
}
function close() {
  if (param('task')) open('');
}
function reportLink(row:TrainingTask) {
  return {name:'training-report',params:{projectId,jobId:row.report_job_id||row.task_id},query:{back:route.fullPath}};
}
function bridge(action = '', id = '') {
  const base = legacyUrl(projectId,'训练任务','','',action);
  if (!id) return base;
  return base + '&' + new URLSearchParams({...listParams(),previous:param('previous'),task_id:id});
}
function loadList() {
  return reads.run('tasks',signal=>api.tasks(listParams(),signal),value=>{page.value=value});
}
function loadDetail() {
  const id = param('task');
  reads.cancel('detail');
  reads.cancel('log');
  task.value = null;
  log.value = '';
  if (!id) return;
  void reads.run('detail',signal=>api.task(id,signal),value=>{
    task.value = value;
    if (value.kind === 'TRAINING') loadLog(value.task_id);
  });
}
function loadLog(id:string) {
  void reads.run('log', signal => withRequestDeadline(async requestSignal => {
    const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(id)}/log`, {
      signal:requestSignal,credentials:'same-origin',headers:{Accept:'text/plain'},
    });
    if (!response.ok) throw new Error(`日志读取失败（HTTP ${response.status}）`);
    return (await response.text()).slice(-120000);
  },{signal}),value=>{log.value=value});
}
function refresh() {
  void loadList();
  loadDetail();
}
watch(()=>[param('query'),param('status'),param('kind'),param('cursor')].join('\0'),()=>{
  ({query:query.value,status:status.value,kind:kind.value}=listParams());
  page.value = null;
  void loadList();
},{immediate:true});
watch(()=>param('task'),loadDetail,{immediate:true});
function prev() {
  const cursor = previousCursors.get(param('cursor')) || param('previous');
  navigate({...listParams(),cursor,previous:previousCursors.get(cursor)||''});
}
function next() {
  const nextCursor = page.value?.next_cursor;
  if (!nextCursor) return;
  const previous = param('cursor');
  previousCursors.set(nextCursor,previous);
  navigate({...listParams(),cursor:nextCursor,previous});
}
const labels:Record<string,string> = {
  QUEUED:'排队中', WAITING_RESOURCE:'等待资源', RUNNING:'运行中', PAUSED:'已暂停',
  AWAITING_CONFIRMATION:'等待确认', CANCEL_REQUESTED:'已请求取消', CANCELLED:'已取消',
  FAILED:'失败', SUCCEEDED:'成功', PARTIAL_SUCCESS:'部分成功',
  BLOCKED_BY_ENVIRONMENT:'环境阻断', BLOCKED_BY_HARDWARE:'硬件阻断',
};
const kinds:Record<string,string> = {TRAINING:'训练',TRAINING_PREPARE:'训练准备'};
function canStop(row:TrainingTask) {
  return row.kind==='TRAINING' && ['QUEUED','WAITING_RESOURCE','RUNNING','PAUSED'].includes(row.status) &&
    !['cancelling','stopping','starting','pausing','resuming','cleaning_training_process','process_cleanup_blocked'].includes(row.phase||'');
}
</script>
<template><section class="training-tasks"><header><div><span>任务列表</span></div><div><a :href="bridge('')">原完整训练任务页</a>　<router-link :to="{name:'training-create',params:{projectId}}">新建训练</router-link></div></header>
<form @submit.prevent="search"><el-input v-model="query" placeholder="搜索任务 ID 或阶段"/><el-select v-model="status" placeholder="状态"><el-option label="全部状态" value=""/><el-option v-for="v in page?.filter_options.status||[]" :key="v" :label="labels[v]||v" :value="v"/></el-select><el-select v-model="kind" placeholder="类型"><el-option label="全部类型" value=""/><el-option v-for="v in page?.filter_options.kind||[]" :key="v" :label="kinds[v]||v" :value="v"/></el-select><el-button native-type="submit" type="primary">查询</el-button><el-button @click="refresh">刷新</el-button></form>
<el-alert v-if="reads.errors.tasks" :title="reads.errors.tasks" type="error" :closable="false"/><el-table v-loading="reads.busy.tasks" :data="page?.items||[]" row-key="task_id" empty-text="暂无任务"><el-table-column prop="task_id" label="任务 ID" min-width="200"/><el-table-column label="类型"><template #default="{row}">{{ kinds[row.kind]||row.kind }}</template></el-table-column><el-table-column label="状态"><template #default="{row}">{{labels[row.status]||row.status}}</template></el-table-column><el-table-column label="进度 / 阶段" min-width="150"><template #default="{row}">{{row.progress_percent==null?'未提供':row.progress_percent+'%'}} · {{row.phase||'—'}}</template></el-table-column><el-table-column prop="created_at" label="创建时间" min-width="170"/><el-table-column label="操作" min-width="145"><template #default="{row}"><el-button link type="primary" @click="open(row.task_id)">详情</el-button> <router-link v-if="row.kind==='TRAINING'" :to="reportLink(row)">训练报告</router-link></template></el-table-column></el-table><footer><span>本页 {{page?.items.length||0}} 条</span><el-button :disabled="!param('cursor')" @click="prev">上一页</el-button><el-button :disabled="!page?.next_cursor" @click="next">下一页</el-button></footer>
<el-drawer :model-value="!!param('task')" title="任务详情" size="min(680px,100vw)" @close="close"><el-skeleton v-if="reads.busy.detail" :rows="8" animated/><el-alert v-else-if="reads.errors.detail" :title="reads.errors.detail" type="error" :closable="false"/><div v-else-if="task"><el-button @click="loadDetail">刷新详情</el-button>　<router-link v-if="task.kind==='TRAINING'" :to="reportLink(task)">训练报告</router-link><h3>身份与状态</h3><ReadOnlyFacts :fields="[['任务 ID',task.task_id],['类型',task.kind],['状态',`${labels[task.status]||task.status} (${task.status})`],['持久状态',task.persisted_status],['进度（%）',task.progress_percent],['阶段',task.phase],['算法',task.algorithm_name||task.algorithm_id],['版本',task.version_id]]"/><p v-if="task.related_task_id">关联任务：<el-button link type="primary" @click="open(task.related_task_id!)">{{task.related_task_id}}</el-button></p><h3>执行与资源</h3><ReadOnlyFacts :fields="[['创建',task.created_at],['开始',task.started_at],['结束',task.finished_at],['Worker',task.worker_id],['资源',task.resource_key],['等待原因',task.resource_wait_reason],...Object.entries(task.execution||{})]"/><h3>配置</h3><ReadOnlyFacts :fields="Object.entries(task.configuration||{})"/><h4>请求的执行配置</h4><ReadOnlyFacts :fields="Object.entries(task.requested_execution||{})"/><h3>失败信息</h3><ReadOnlyFacts :fields="[['原因',task.error]]"/><template v-if="task.kind==='TRAINING'"><h3>训练日志</h3><el-button @click="loadLog(task.task_id)">刷新日志</el-button><p v-if="reads.errors.log">{{reads.errors.log}}</p><pre>{{log||'暂无日志'}}</pre></template><p><a v-if="task.kind==='TRAINING'" :href="bridge('task-detail',task.task_id)">原工作台 · 操作与恢复</a>　<a v-if="canStop(task)" :href="bridge('task-stop',task.task_id)">原工作台 · 停止任务</a></p></div></el-drawer></section></template>
<style scoped>.training-tasks{padding:24px}header,form,footer{display:flex;align-items:center;gap:12px;flex-wrap:wrap}header{justify-content:space-between}form{margin:20px 0}form .el-input{max-width:300px}form .el-select{width:160px}footer{justify-content:flex-end;margin-top:16px}pre{white-space:pre-wrap;overflow:auto;max-height:300px;background:#f5f7fa;padding:12px}</style>
