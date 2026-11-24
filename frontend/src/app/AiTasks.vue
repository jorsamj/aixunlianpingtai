<script setup lang="ts">
import {onMounted,onBeforeUnmount,ref} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import type {AiTask,AiTaskPage} from '../types/ai-tasks';
import {aiTaskReaderApi} from '../api/ai-task-reader';
import {useReadScope} from '../composables/useReadScope';
import {request} from './http';
import {legacyUrl} from './navigation';
const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId);
const controller=new AbortController(),reads=useReadScope(controller),api=aiTaskReaderApi({projectId,get:request});
const status=ref(''),page=ref<AiTaskPage|null>(null),cursors=ref<string[]>(['']),index=ref(0);
// Product-facing labels follow the existing pilot page; unknown statuses stay raw.
const statuses:Record<string,string>={QUEUED:'排队中',WAITING_RESOURCE:'等待资源',RUNNING:'运行中',CANCEL_REQUESTED:'正在取消',AWAITING_CONFIRMATION:'等待确认',PARTIAL_SUCCESS:'部分成功',SUCCEEDED:'已完成',CANCELLED:'已取消',FAILED:'失败',BLOCKED_BY_ENVIRONMENT:'环境不可用',BLOCKED_BY_HARDWARE:'硬件不可用'};
const label=(value?:string)=>value?statuses[value]||value:'未提供';
const shown=(value:number|null|undefined)=>typeof value==='number'?String(value):'未知';
const created=(row:AiTask)=>row.created_at?row.created_at.replace('T',' ').slice(0,19):'未提供';
const progress=(row:AiTask)=>row.progress_percent!=null?`${row.progress_percent}%`:row.completed_count!=null?'已处理，进度未提供':'未提供';
const failures=(row:AiTask)=>shown(row.counts?.failed);
onBeforeUnmount(()=>controller.abort());
function load(){
 const cursor=cursors.value[index.value]||'';
 return reads.run('tasks',signal=>api.tasks(status.value,cursor,signal),value=>{page.value=value});
}
function search(){cursors.value=[''];index.value=0;page.value=null;void load()}
function next(){
 const cursor=page.value?.next_cursor;
 if(!cursor)return;
 cursors.value=cursors.value.slice(0,index.value+1);
 cursors.value.push(cursor);
 index.value+=1;
 page.value=null;
 void load();
}
function previous(){if(index.value<1)return;index.value-=1;page.value=null;void load()}
function openReview(row:AiTask){void router.push({name:'ai-review-native',params:{projectId,taskId:row.id}})}
onMounted(()=>void load());
</script>
<template><section class="ai-tasks" aria-label="AI 标注任务只读列表">
 <header><div><h2>AI 标注任务</h2><p>只读任务列表；创建、重试与完整导出继续使用原工作台。</p></div><a :href="legacyUrl(projectId,'自动标注及清洗')">原完整自动标注</a></header>
 <form @submit.prevent="search"><el-select v-model="status" aria-label="AI任务状态"><el-option label="全部状态" value=""/><el-option v-for="(name,code) in statuses" :key="code" :label="name" :value="code"/></el-select><el-button native-type="submit" type="primary" :disabled="reads.busy.tasks">查询</el-button><el-button :disabled="reads.busy.tasks" @click="load">刷新</el-button></form>
 <el-alert v-if="reads.errors.tasks" :title="reads.errors.tasks" type="error" :closable="false"/>
 <p v-if="reads.errors.tasks&&page" class="ai-tasks-note">下方为上次读取的快照，不能作为最新任务状态。</p>
 <el-alert v-if="page?.indexing" :title="`历史搜索索引准备中：已索引 ${shown(page.indexed)}，待处理 ${shown(page.remaining)}；当前空列表不代表没有任务。`" type="info" :closable="false"/>
 <el-alert v-else-if="page?.statistics_indexing" title="部分历史统计正在准备，失败数显示“未知”；稍后刷新。" type="info" :closable="false"/>
 <el-table v-loading="reads.busy.tasks" :data="page?.items||[]" row-key="id" empty-text="当前条件下没有 AI 标注任务" @row-click="openReview">
  <el-table-column label="任务" min-width="220"><template #default="{row}"><strong>{{row.name||row.id}}</strong><small class="ai-tasks-secondary">{{row.id}}</small></template></el-table-column>
  <el-table-column label="状态" min-width="150"><template #default="{row}"><el-tag>{{label(row.status)}}</el-tag><small class="ai-tasks-secondary">{{row.phase||'阶段未提供'}}</small></template></el-table-column>
  <el-table-column label="进度" min-width="150"><template #default="{row}">{{progress(row)}}<small class="ai-tasks-secondary">已处理 {{shown(row.completed_count)}} / 总数 {{shown(row.total_count)}}</small></template></el-table-column>
  <el-table-column label="失败数" width="110"><template #default="{row}">{{failures(row)}}</template></el-table-column>
  <el-table-column label="创建时间" min-width="180"><template #default="{row}">{{created(row)}}</template></el-table-column>
  <el-table-column label="操作" width="120"><template #default="{row}"><el-button link type="primary" @click.stop="openReview(row)">进入审核</el-button></template></el-table-column>
 </el-table>
 <footer v-if="page"><span>第 {{index+1}} 页 · 本页 {{page.items.length}} 条</span><el-button :disabled="index<1||reads.busy.tasks" @click="previous">上一页</el-button><el-button :disabled="!page.next_cursor||reads.busy.tasks" @click="next">下一页</el-button></footer>
</section></template>
<style scoped>
.ai-tasks{padding:24px}header,form,footer{display:flex;align-items:center;gap:12px;flex-wrap:wrap}header{justify-content:space-between}header h2{margin:0}header p{margin:6px 0 0;color:#777;font-size:13px}form{margin:20px 0}form .el-select{width:190px}footer{justify-content:flex-end;margin-top:16px}.ai-tasks-secondary{display:block;color:#777;font-size:12px;margin-top:4px;overflow-wrap:anywhere}.ai-tasks-note{font-size:13px;color:#955323}.ai-tasks :deep(.el-table__row){cursor:pointer}
</style>
