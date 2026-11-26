<script setup lang="ts">
import {computed,onMounted,ref} from 'vue';
import {useRoute} from 'vue-router';
import {aiTaskReaderApi} from '../api/ai-task-reader';
import {trainingReaderApi,type TaskPage} from '../api/training-reader';
import {useReadScope} from '../composables/useReadScope';
import TaskStatusTag from '../components/TaskStatusTag.vue';
import type {AiTaskPage} from '../types/ai-tasks';
import {request} from './http';
import {legacyUrl} from './navigation';

interface CoreSnapshot {
  ok:boolean;
  project:{id:string};
  algorithms_total:number;
  datasets:unknown[];
  material_summary:{total:number;annotated:number;boxes:number};
  generated_at:string;
}

const route=useRoute(),projectId=String(route.params.projectId);
const params={projectId};
const reads=useReadScope(new AbortController());
const trainingApi=trainingReaderApi({projectId,get:request,memory:{}});
const aiApi=aiTaskReaderApi({projectId,get:request});
const core=ref<CoreSnapshot|null>(null);
const training=ref<TaskPage|null>(null);
const ai=ref<AiTaskPage|null>(null);
const failed=ref<TaskPage|null>(null);
const metrics=computed(()=>{
  const snapshot=core.value;
  if(!snapshot)return [];
  const {total,annotated,boxes}=snapshot.material_summary;
  return [
    {label:'算法总数',value:snapshot.algorithms_total},
    {label:'数据集',value:snapshot.datasets.length},
    {label:'素材',value:total},
    {label:'已标注',value:annotated},
    {label:'标注框',value:boxes},
    {label:'标注率',value:total?`${(annotated/total*100).toFixed(1)}%`:'0.0%'},
  ];
});
const progress=(value:number|null|undefined)=>value==null?'未提供':`${value}%`;
const time=(value:string|null|undefined)=>value?.replace('T',' ').slice(0,19)||'未提供';
const trainingLink=(task:string)=>({name:'training-tasks',params,query:{task}});
const failedLink=computed(()=>({name:'training-tasks',params,query:{status:'FAILED'}}));

function loadCore(){
  return reads.run('core',signal=>request<CoreSnapshot>(
    '/api/v53/bootstrap/snapshot?'+new URLSearchParams({preferred_project_id:projectId,core:'true'}),{signal},
  ),snapshot=>{
    if(snapshot.ok!==true||snapshot.project?.id!==projectId)
      throw new Error('项目概况响应身份不一致。');
    core.value=snapshot;
  });
}

function loadTraining(){
  return reads.run('training',signal=>trainingApi.tasks({},signal,5),page=>{training.value=page;});
}

function loadAi(){
  return reads.run('ai',signal=>aiApi.tasks('','',signal,5),page=>{ai.value=page;});
}

function loadFailed(){
  return reads.run('failed',signal=>trainingApi.tasks({status:'FAILED'},signal,5),page=>{failed.value=page;});
}

onMounted(()=>{void loadCore();void loadTraining();void loadAi();void loadFailed();});
</script>

<template>
  <div class="overview">
    <section class="overview-panel" aria-labelledby="overview-heading">
      <header class="overview-heading">
        <div>
          <h2 id="overview-heading">算法生产总览</h2>
          <small v-if="core">快照时间 {{ time(core.generated_at) }}</small>
        </div>
        <div class="overview-actions">
          <router-link :to="{name:'material-upload',params}">素材接入</router-link>
          <router-link :to="{name:'algorithms',params}">算法库</router-link>
          <a :href="legacyUrl(projectId,'总览')">原总览</a>
          <el-button :loading="reads.busy.core" @click="loadCore">刷新概况</el-button>
        </div>
      </header>
      <el-alert v-if="reads.errors.core" :title="reads.errors.core" type="error" :closable="false"/>
      <el-skeleton v-if="!core&&reads.busy.core" :rows="2" animated/>
      <dl v-if="core" class="overview-metrics">
        <div v-for="metric in metrics" :key="metric.label">
          <dt>{{ metric.label }}</dt>
          <dd>{{ typeof metric.value==='number'?metric.value.toLocaleString():metric.value }}</dd>
        </div>
      </dl>
    </section>

    <div class="overview-recent">
      <section class="overview-panel" aria-labelledby="training-heading">
        <header class="overview-heading">
          <h2 id="training-heading">最近训练</h2>
          <div class="overview-actions">
            <router-link :to="{name:'training-tasks',params}">全部训练任务</router-link>
            <el-button :loading="reads.busy.training" @click="loadTraining">刷新</el-button>
          </div>
        </header>
        <el-alert v-if="reads.errors.training" :title="reads.errors.training" type="error" :closable="false"/>
        <el-skeleton v-if="!training&&reads.busy.training" :rows="4" animated/>
        <el-table v-if="training" :data="training.items" empty-text="暂无训练任务">
          <el-table-column label="任务" min-width="170">
            <template #default="{row}">
              <router-link :to="trainingLink(row.task_id)">{{ row.algorithm_name||row.task_id }}</router-link>
              <small v-if="row.algorithm_name" class="overview-id">{{ row.task_id }}</small>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="95">
            <template #default="{row}"><TaskStatusTag :status="row.status"/></template>
          </el-table-column>
          <el-table-column label="进度" min-width="80">
            <template #default="{row}">{{ progress(row.progress_percent) }}</template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="160">
            <template #default="{row}">{{ time(row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </section>

      <section class="overview-panel" aria-labelledby="failed-heading">
        <header class="overview-heading">
          <h2 id="failed-heading">待处理失败任务</h2>
          <div class="overview-actions">
            <router-link :to="failedLink">查看全部失败任务</router-link>
            <el-button :loading="reads.busy.failed" @click="loadFailed">刷新</el-button>
          </div>
        </header>
        <p class="overview-hint">最近 5 条失败记录，不代表全部范围；失败原因与恢复资格以任务详情为准。</p>
        <el-alert v-if="reads.errors.failed" :title="reads.errors.failed" type="error" :closable="false"/>
        <el-skeleton v-if="!failed&&reads.busy.failed" :rows="3" animated/>
        <el-table v-if="failed" :data="failed.items" empty-text="暂无失败任务">
          <el-table-column label="任务" min-width="160">
            <template #default="{row}">
              <router-link :to="trainingLink(row.task_id)">{{ row.algorithm_name||row.task_id }}</router-link>
              <small v-if="row.algorithm_name" class="overview-id">{{ row.task_id }}</small>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="90">
            <template #default="{row}"><TaskStatusTag :status="row.status"/></template>
          </el-table-column>
          <el-table-column label="原因" min-width="170">
            <template #default="{row}">{{ row.error||'未提供' }}</template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="150">
            <template #default="{row}">{{ time(row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </section>

      <section class="overview-panel" aria-labelledby="ai-heading">
        <header class="overview-heading">
          <h2 id="ai-heading">最近 AI 标注</h2>
          <div class="overview-actions">
            <router-link :to="{name:'ai-tasks',params}">全部 AI 标注任务</router-link>
            <el-button :loading="reads.busy.ai" @click="loadAi">刷新</el-button>
          </div>
        </header>
        <el-alert v-if="reads.errors.ai" :title="reads.errors.ai" type="error" :closable="false"/>
        <el-skeleton v-if="!ai&&reads.busy.ai" :rows="4" animated/>
        <el-table v-if="ai" :data="ai.items" :empty-text="ai.indexing||ai.statistics_indexing?'任务索引正在准备':'暂无 AI 标注任务'">
          <el-table-column label="任务" min-width="170">
            <template #default="{row}">{{ row.name||row.id }}</template>
          </el-table-column>
          <el-table-column label="状态" min-width="95">
            <template #default="{row}"><TaskStatusTag :status="row.status"/></template>
          </el-table-column>
          <el-table-column label="进度" min-width="80">
            <template #default="{row}">{{ progress(row.progress_percent) }}</template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="160">
            <template #default="{row}">{{ time(row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </section>
    </div>
  </div>
</template>

<style scoped>
.overview,.overview-recent{display:grid;gap:16px}
.overview-recent{grid-template-columns:repeat(auto-fit,minmax(min(100%,490px),1fr));align-items:start}
.overview-panel{min-width:0;padding:16px;background:var(--el-bg-color);border:1px solid var(--el-border-color);border-radius:8px}
.overview-heading,.overview-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.overview-heading{justify-content:space-between;margin-bottom:12px}
.overview-heading h2{margin:0;font-size:16px}
.overview-heading small,.overview-id{color:var(--el-text-color-secondary)}
.overview-id{display:block;overflow-wrap:anywhere}
.overview-metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:12px;margin:0}
.overview-metrics>div{padding:12px;background:var(--el-fill-color-lighter);border-radius:6px}
.overview-metrics dt{font-size:13px;color:var(--el-text-color-secondary)}
.overview-metrics dd{margin:6px 0 0;font-size:23px;font-weight:600;font-variant-numeric:tabular-nums}
.overview-hint{margin:0 0 10px;font-size:12px;color:var(--el-text-color-secondary)}
</style>
