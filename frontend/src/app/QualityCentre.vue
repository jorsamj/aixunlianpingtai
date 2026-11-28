<script setup lang="ts">
import {computed,onMounted,ref} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import QualityCheckChart from './QualityCheckChart.vue';
import SmartAudit from './SmartAudit.vue';
import TaskStatusTag from '../components/TaskStatusTag.vue';
import {trainingReaderApi,type TaskPage} from '../api/training-reader';
import {useReadScope} from '../composables/useReadScope';
import {request} from './http';
import {legacyUrl} from './navigation';

const {projectId}=defineProps<{projectId:string}>();
const route=useRoute(),router=useRouter();
const params={projectId};
const root=encodeURIComponent(projectId);
const reads=useReadScope(new AbortController());
const training=trainingReaderApi({projectId,get:request,memory:{}});
interface Material {id:string;filename?:string;name?:string;split?:string;quality_status?:string;annotation_state?:string}
interface MaterialPage {items:Material[];next_cursor?:string}
interface Snapshot {ok:boolean;project:{id:string};material_summary:{total:number;annotated:number;boxes:number};generated_at:string}
interface Quality {count:number;score:number;warnings?:string[];scores:Record<string,number>;split_counts:Record<string,number>;label_images:Record<string,number>}
const filters=[{id:'issue',label:'质量问题'},{id:'pending_decision',label:'待处理'},{id:'processed',label:'已处理'},{id:'',label:'全部'}];
const filter=ref('issue'),page=ref<MaterialPage>(),summary=ref<Snapshot>(),tasks=ref<TaskPage>(),quality=ref<Quality>();
const tab=ref(route.query.tab==='issues'||route.query.tab==='training'||route.query.tab==='audit'?route.query.tab:'overview');
const cursor=ref('');
// Explicit return path for every drill-down. Links only: no sample is moved
// between splits and no training candidate is created from a Test sample here.
const backPath=(name:'quality-centre',tabName:string)=>router.resolve({name,params,query:{tab:tabName}}).fullPath;
const issuesBack=backPath('quality-centre','issues');
const trainingBack=backPath('quality-centre','training');
function loadOverview(){
  return reads.run('summary',signal=>request<Snapshot>('/api/v53/bootstrap/snapshot?'+new URLSearchParams({preferred_project_id:projectId,core:'true'}),{signal}),value=>{
    if(value.ok!==true||value.project.id!==projectId)throw new Error('质量摘要项目不一致');
    summary.value=value;
  });
}
function loadIssues(next=''){
  quality.value=undefined;
  reads.cancel('check');
  const query=new URLSearchParams({limit:'30',reader_view:'true'});
  if(filter.value)query.set('quality_status',filter.value);
  if(next)query.set('cursor',next);
  return reads.run('issues',signal=>request<MaterialPage>('/api/v61/projects/'+root+'/materials?'+query,{signal}),value=>{
    if(!Array.isArray(value.items)||value.items.length>30||value.items.some(row=>!row.id))throw new Error('素材质量分页无效');
    page.value=value;cursor.value=next;
  });
}
function checkVisible(){
  const ids=page.value?.items.map(row=>row.id)||[];
  if(!ids.length||ids.length>30||reads.busy.issues)return;
  return reads.run('check',signal=>request<{ok:boolean;quality:Quality}>('/api/v44/projects/'+root+'/data-quality',{
    method:'POST',signal,body:JSON.stringify({image_ids:ids,max_samples:ids.length}),
  }),value=>{if(value.ok!==true||!value.quality)throw new Error('质量检查证据缺失');quality.value=value.quality});
}
interface TrainingTrend {ok:boolean;project_id:string;window_days:number;counts:Record<string,number>;total:number;prepare_total?:number}
const trend=ref<TrainingTrend|null>(null);
const trendLabels:Record<string,string>={QUEUED:'排队',WAITING_RESOURCE:'等待资源',PREPARING:'准备',RUNNING:'运行中',
  PAUSED:'已暂停',AWAITING_CONFIRMATION:'等待确认',CANCEL_REQUESTED:'正在取消',CANCELLED:'已取消',
  FAILED:'失败',SUCCEEDED:'已完成',PARTIAL_SUCCESS:'部分成功',BLOCKED_BY_ENVIRONMENT:'环境阻断',BLOCKED_BY_HARDWARE:'硬件阻断'};
const trendParts=computed(()=>trend.value?Object.entries(trend.value.counts).filter(([,count])=>count>0)
  .sort((left,right)=>right[1]-left[1]).map(([status,count])=>({status,label:trendLabels[status]||status,count})):[]);
// Same bounded aggregation as the overview; never scans history or report files.
function loadTrend(){
  return reads.run('trend',signal=>request<TrainingTrend>(`/api/v62/projects/${encodeURIComponent(projectId)}/tasks/summary?days=7`,{signal}),value=>{
    if(value.ok!==true||value.project_id!==projectId)throw new Error('训练趋势响应身份不一致');
    trend.value=value;
  });
}
function loadTraining(){
  return reads.run('training',signal=>training.tasks({},signal),value=>{tasks.value=value});
}
function switchTab(value:string|number){
  void router.replace({query:{...route.query,tab:value==='overview'?undefined:String(value)}});
  if(value==='issues'&&!page.value)void loadIssues();
  if(value==='training'&&!tasks.value)void loadTraining();
}
onMounted(()=>{void loadOverview();switchTab(tab.value)});
</script>

<template>
  <section class="quality-centre">
    <header>
      <h2>质量中心</h2>
      <div class="actions">
        <router-link :to="{name:'labels',params}">标签审计</router-link>
        <router-link :to="{name:'native-cleaning',params}">清洗与治理</router-link>
        <a :href="legacyUrl(projectId,'质量中心')">场景实测与高级评测</a>
      </div>
    </header>
    <el-tabs v-model="tab" @tab-change="switchTab">
      <el-tab-pane name="overview" label="质量概览">
        <div class="tools"><el-button :loading="reads.busy.summary" @click="loadOverview">刷新概况</el-button></div>
        <el-alert v-if="reads.errors.summary" :title="reads.errors.summary" type="error" :closable="false"/>
        <dl v-if="summary" class="measures">
          <div><dt>素材</dt><dd>{{summary.material_summary.total.toLocaleString()}}</dd></div>
          <div><dt>已标注</dt><dd>{{summary.material_summary.annotated.toLocaleString()}}</dd></div>
          <div><dt>标注框</dt><dd>{{summary.material_summary.boxes.toLocaleString()}}</dd></div>
        </dl>
      </el-tab-pane>
      <el-tab-pane name="issues" label="素材与标注">
        <div class="tools">
          <el-select v-model="filter" aria-label="质量筛选" @change="loadIssues()">
            <el-option v-for="item in filters" :key="item.id" :label="item.label" :value="item.id"/>
          </el-select>
          <el-button :loading="reads.busy.issues" @click="loadIssues(cursor)">刷新</el-button>
          <el-button :loading="reads.busy.check" :disabled="!page?.items.length||reads.busy.issues" @click="checkVisible">检查本页素材</el-button>
          <span class="scope-note">仅检查当前页最多 30 张，不是全库审计</span>
        </div>
        <el-alert v-if="reads.errors.issues||reads.errors.check" :title="reads.errors.issues||reads.errors.check" type="error" :closable="false"/>
        <el-table :data="page?.items||[]" v-loading="reads.busy.issues" row-key="id" empty-text="此范围暂无素材">
          <el-table-column label="素材" min-width="230"><template #default="{row}">{{row.filename||row.name||row.id}}</template></el-table-column>
          <el-table-column prop="split" label="用途" min-width="100"/>
          <el-table-column prop="annotation_state" label="标注状态" min-width="120"/>
          <el-table-column label="操作" min-width="180"><template #default="{row}">
            <router-link :to="{name:'formal-annotation',params,query:{image:row.id,quality_status:filter||undefined,back:issuesBack}}">人工标注</router-link>
            <router-link :to="{name:'materials',params,query:{detail:row.id,...(filter?{quality_status:filter}:{})}}">素材详情</router-link>
          </template></el-table-column>
        </el-table>
        <div class="tools">
          <el-button :disabled="!cursor||reads.busy.issues" @click="loadIssues()">回到首批</el-button>
          <el-button :disabled="!page?.next_cursor||reads.busy.issues" @click="loadIssues(page?.next_cursor)">下一批</el-button>
        </div>
        <section v-if="quality">
          <h3>本页检查结果 · {{quality.count}} 张</h3>
          <p class="scope-note">本次只检查当前页素材，结论不适用于全库。</p>
          <QualityCheckChart :scores="quality.scores"/>
          <ul v-if="quality.warnings?.length"><li v-for="warning in quality.warnings" :key="warning">{{warning}}</li></ul>
          <el-table :data="Object.entries(quality.label_images).map(([label,count])=>({label,count}))" max-height="280" empty-text="本次没有标签记录">
            <el-table-column prop="label" label="标签"/><el-table-column prop="count" label="覆盖素材"/>
          </el-table>
        </section>
      </el-tab-pane>
      <el-tab-pane name="training" label="训练与评测">
        <div class="tools"><el-button :loading="reads.busy.training" @click="loadTraining">刷新近期训练</el-button><el-button :loading="reads.busy.trend" @click="loadTrend">读取近 7 天状态</el-button>
          <router-link :to="{name:'training-tasks',params,query:{kind:'TRAINING'}}">全部训练任务</router-link></div>
        <el-alert v-if="reads.errors.training" :title="reads.errors.training" type="error" :closable="false"/><p v-if="trend" class="scope-note">近 7 天训练任务 {{ trend.total }} 条（另有准备任务 {{ trend.prepare_total??0 }} 条）<template v-if="trendParts.length">：<template v-for="part in trendParts" :key="part.status">{{ part.label }} {{ part.count }} · </template></template><template v-else>：窗口内没有任务</template></p><p v-if="reads.errors.trend" class="scope-note">近 7 天状态未读取：{{ reads.errors.trend }}</p>
        <el-table :data="tasks?.items||[]" v-loading="reads.busy.training" row-key="task_id" empty-text="暂无训练任务">
          <el-table-column label="算法" min-width="190"><template #default="{row}">{{row.algorithm_name||row.algorithm_id||row.task_id}}</template></el-table-column>
          <el-table-column label="状态" min-width="110"><template #default="{row}"><TaskStatusTag :status="row.status"/></template></el-table-column>
          <el-table-column label="质量证据" min-width="150"><template #default="{row}">
            <router-link v-if="row.report_job_id" :to="{name:'training-report',params:{...params,jobId:row.report_job_id},query:{algorithm:row.algorithm_id,version:row.version_id,back:trainingBack}}">训练报告与评测</router-link>
            <span v-else>暂无报告</span>
          </template></el-table-column>
          <el-table-column label="样本诊断" min-width="200"><template #default="{row}">
            <template v-if="row.algorithm_id&&row.version_id">
              <router-link :to="{name:'version-report',params:{...params,algorithmId:row.algorithm_id,versionId:row.version_id},query:{tab:'evaluation',view:'samples',issue:'fp',back:trainingBack}}">FP 误检</router-link>
              <router-link :to="{name:'version-report',params:{...params,algorithmId:row.algorithm_id,versionId:row.version_id},query:{tab:'evaluation',view:'samples',issue:'fn',back:trainingBack}}">FN 漏检</router-link>
              <router-link :to="{name:'version-report',params:{...params,algorithmId:row.algorithm_id,versionId:row.version_id},query:{tab:'evaluation',view:'iteration',back:trainingBack}}">困难样本与继续训练</router-link>
            </template>
            <span v-else>未关联算法版本</span>
          </template></el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane name="audit" label="智能审计">
        <SmartAudit :project-id="projectId"/>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<style scoped>
.quality-centre {display:grid;gap:14px;min-width:0}
.quality-centre header,.actions,.tools {display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.quality-centre header {justify-content:space-between}
.quality-centre h2,.quality-centre h3 {margin:0}
.tools {margin-block:12px}
.tools .el-select {width:170px}
.measures {display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:14px;padding-block:12px}
.measures>div {padding:12px 14px;border:1px solid var(--el-border-color-light);border-radius:6px}
.measures dd {margin:5px 0 0;font-size:1.45rem;font-weight:650}
.scope-note {font-size:12px;color:var(--el-text-color-secondary);margin:0}
</style>
