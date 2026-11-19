<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {trainingReaderApi,type ReportSelection,type TrainingReport} from '../api/training-reader';
import {modelBrowseApi} from '../api/model-browse';
import {useReadScope} from '../composables/useReadScope';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
import NativeReportCharts from './NativeReportCharts.vue';
import NativeEvaluation from './NativeEvaluation.vue';
import {request} from './http';
import {legacyUrl} from './navigation';

const route=useRoute(),router=useRouter(),controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
const projectId=String(route.params.projectId);
const context={projectId,get:request,memory:{}};
const reads=useReadScope(controller),api=trainingReaderApi(context),versions=modelBrowseApi(context);
const report=ref<TrainingReport|null>(null),selection=ref<ReportSelection|null>(null);
const offset=ref(0),job=ref('');
const query=(key:string)=>typeof route.query[key]==='string'?route.query[key] as string:'';
const pane=computed(()=>['history','evaluation'].includes(query('tab'))?query('tab'):'overview');
const canonical=computed(()=>{
  const current=selection.value;
  const algorithmId=report.value?.algorithm_id||current?.algorithmId;
  const versionId=report.value?.version_id||current?.versionId;
  return algorithmId&&versionId?{algorithmId,versionId,jobId:current?.jobId||''}:null;
});
const back=computed(()=>{
  const source=query('back');
  if(source.startsWith('/projects/')){
    const original=router.resolve(source);
    if(original.params.projectId===projectId&&(original.name==='algorithms'||original.name==='training-tasks'))return original.fullPath;
  }
  return {name:route.name==='version-report'?'algorithms':'training-tasks',params:{projectId}};
});
function versionBridge(action:'report'|'evaluation',algorithmId:string,versionId:string){
  const source=typeof back.value==='string'?router.resolve(back.value):null;
  const url=legacyUrl(projectId,'算法列表',algorithmId,versionId,action);
  return source?.name==='algorithms'
    ?url+'&'+new URLSearchParams({return_to:source.fullPath})
    :url;
}
const originalEvaluation=computed(()=>canonical.value?versionBridge('evaluation',canonical.value.algorithmId,canonical.value.versionId):'');
const originalReport=computed(()=>canonical.value
  ?versionBridge('report',canonical.value.algorithmId,canonical.value.versionId)
  :legacyUrl(projectId,'训练任务','','','task-report')+'&'+new URLSearchParams({task_id:selection.value?.jobId||String(route.params.jobId||'')}));
const states:Record<string,string>={AVAILABLE:'报告已记录',PARTIAL:'仅有部分训练结果',NOT_GENERATED:'报告尚未生成',NOT_FOUND:'报告或任务记录不存在',ERROR:'报告读取异常',DEFERRED:'报告超出读取边界'};
const metricFields=[['Precision','precision'],['Recall','recall'],['mAP50','map50'],['mAP50-95','map50_95']] as const;

function tab(name:string){
  void router.replace({query:{...route.query,tab:name==='overview'?undefined:name}});
}
function page(start:number){
  const current=selection.value;
  if(!current?.jobId)return;
  void reads.run('report',signal=>api.report(current,signal,start),value=>{
    if(value.algorithm_id&&value.version_id){
      selection.value={...current,algorithmId:value.algorithm_id,versionId:value.version_id};
    }
    report.value=value;
    offset.value=value.history_offset??start;
  });
}
function load(){
  reads.cancel('report');
  report.value=null;
  selection.value=null;
  offset.value=0;
  if(route.name==='version-report'){
    const algorithmId=String(route.params.algorithmId),versionId=String(route.params.versionId);
    void reads.run('version',signal=>versions.detail(algorithmId,versionId,signal),value=>{
      selection.value={algorithmId,versionId,jobId:value.version.training_job_id||'',returnPage:'assets'};
      job.value=selection.value.jobId;
      if(job.value)page(0);
      else {
        const version=value.version;
        report.value={
          ok:true,project_id:projectId,job_id:'',algorithm_id:algorithmId,version_id:versionId,
          state:'PARTIAL',source:'已保存算法版本',message:'此版本没有已绑定的训练任务。执行终态、停止条件及历史曲线未提供。',
          val_metrics:version.val_metrics,test_metrics:version.test_metrics,
          result:{snapshot_id:version.training_lineage?.snapshot_id,dataset_revision_id:version.training_lineage?.dataset_revision_id},
        };
      }
    });
  }else{
    selection.value={jobId:String(route.params.jobId),returnPage:'tasks'};
    job.value=selection.value.jobId;
    page(0);
  }
}
function openTask(){
  if(job.value.trim())void router.push({name:'training-report',params:{projectId,jobId:job.value.trim()},query:{back:query('back')||undefined}});
}
watch(()=>route.path,load,{immediate:true});
</script>

<template>
  <section class="native-report" aria-label="训练报告">
    <header class="report-heading">
      <div>
        <router-link :to="back">返回来源</router-link>
        <h2>{{pane==='evaluation'?'独立评测':'训练报告'}}</h2>
        <p>项目 {{projectId}} · 任务 {{selection?.jobId||'未关联'}} · 算法 {{canonical?.algorithmId||'未关联'}} · 版本 {{canonical?.versionId||'未关联'}}</p>
      </div>
      <form class="report-actions" @submit.prevent="openTask">
        <el-input v-model="job" aria-label="切换训练任务 ID" placeholder="训练任务 ID"/>
        <el-button native-type="submit" :disabled="!job.trim()">打开报告</el-button>
        <el-button @click="load">重新读取</el-button>
      </form>
    </header>
    <nav class="report-actions report-tabs" aria-label="报告内容">
      <el-button v-for="[key,label] in [['overview','结果概况'],['history','训练过程'],['evaluation','独立评测']]" :key="key" :type="pane===key?'primary':'default'" :aria-pressed="pane===key" :disabled="key==='evaluation'&&!canonical" @click="tab(key)">{{label}}</el-button>
      <a v-if="selection" :href="originalReport">完整旧报告 · LEGACY_BRIDGE</a>
      <a v-if="canonical" :href="legacyUrl(projectId,'算法列表',canonical.algorithmId,canonical.versionId,'lineage')">训练溯源 · 原工作台</a>
    </nav>
    <el-alert v-if="reads.errors.version||reads.errors.report" :title="reads.errors.version||reads.errors.report" type="error" :closable="false"/>
    <el-skeleton v-if="reads.busy.version||(reads.busy.report&&!report&&pane!=='evaluation')" :rows="6" animated/>
    <NativeEvaluation v-if="pane==='evaluation'&&canonical" :key="canonical.algorithmId+'/'+canonical.versionId" :project-id="projectId" v-bind="canonical" :legacy-href="originalEvaluation"/>
    <template v-else-if="report">
      <section v-if="pane==='overview'" class="report-panel">
        <h3>{{states[report.state]||report.state}}</h3>
        <p v-if="report.message">{{report.message}}</p>
        <ReadOnlyFacts :fields="[['记录来源',report.source],['任务状态',report.result?.status],['完成原因',report.result?.completion_reason],['失败记录',report.result?.error],['早停原因',report.result?.early_stopping_reason],['质量门禁',report.result?.quality_gate_reason],['训练结果',report.result?.training_outcome],['最终 Epoch',report.result?.completed_epochs??report.result?.current_epoch],['请求 Epoch',report.result?.requested_epochs],['最佳 Epoch',report.result?.best_epoch],['训练耗时（秒）',report.result?.elapsed_seconds],['开始时间',report.result?.started_at],['完成时间',report.result?.finished_at],['训练快照',report.result?.snapshot_id],['数据集修订',report.result?.dataset_revision_id]]"/>
      </section>
      <div v-if="pane==='overview'" class="report-grid">
        <section class="report-panel"><h3>Val 指标</h3><ReadOnlyFacts :fields="metricFields.map(([label,key])=>[label,report?.val_metrics?.[key]])"/></section>
        <section class="report-panel"><h3>独立 Test 指标</h3><ReadOnlyFacts :fields="[['正式评测状态',report.test_status],...metricFields.map(([label,key]):[string,unknown]=>[label,report?.test_metrics?.[key]])]"/></section>
        <section class="report-panel"><h3>训练参数</h3><h4>请求配置</h4><ReadOnlyFacts :fields="Object.keys(report.configuration||{}).length?Object.entries(report.configuration||{}):[['参数记录',null]]"/><h4>实际执行参数</h4><ReadOnlyFacts :fields="Object.keys(report.actual_parameters||{}).length?Object.entries(report.actual_parameters||{}):[['参数记录',null]]"/><template v-if="Object.keys(report.historical_parameters||{}).length"><h4>历史参数（来源未标注）</h4><ReadOnlyFacts :fields="Object.entries(report.historical_parameters||{})"/></template></section>
        <section class="report-panel"><h3>可信度与质量诊断</h3><ReadOnlyFacts :fields="[['质量状态',report.quality_status],...Object.entries(report.credibility||{})]"/><ul v-if="report.warnings?.length"><li v-for="(warning,index) in report.warnings" :key="index">{{warning}}</li></ul></section>
        <section v-if="Object.keys(report.best_metrics||{}).length" class="report-panel"><h3>已记录最佳结果</h3><ReadOnlyFacts :fields="metricFields.map(([label,key])=>[label,report?.best_metrics?.[key]])"/></section>
      </div>
      <section v-else-if="pane==='history'" class="report-panel">
        <h3>已记录训练过程</h3>
        <el-empty v-if="!report.history?.length" description="当前页没有已记录的 Epoch"/>
        <NativeReportCharts v-else :history="report.history"/>
        <el-table v-if="report.history?.length" :data="report.history" max-height="360" empty-text="当前页没有已记录的 Epoch">
          <el-table-column v-for="[key,label] in [['epoch','Epoch'],['precision','Precision'],['recall','Recall'],['map50','mAP50'],['map50_95','mAP50-95'],['box_loss','Train box loss'],['val_box_loss','Val box loss'],['duration_seconds','耗时（秒）']]" :key="key" :label="label" min-width="105"><template #default="{row}">{{row[key]??'未提供'}}</template></el-table-column>
        </el-table>
        <div class="report-actions"><el-button :disabled="offset===0||reads.busy.report" @click="page(Math.max(0,offset-100))">上一页 Epoch</el-button><span>偏移 {{offset}} / {{report.history_total??'未提供'}}</span><el-button :disabled="!report.history_has_next||reads.busy.report" @click="page(offset+100)">下一页 Epoch</el-button></div>
      </section>
    </template>
    <el-empty v-else-if="selection&&!selection.jobId" description="此版本没有已绑定的训练任务报告"/>
  </section>
</template>

<style scoped>
.native-report{padding:24px;min-width:0}.report-heading{display:flex;justify-content:space-between;align-items:end;gap:16px;flex-wrap:wrap}.report-heading h2{margin:10px 0 4px}.report-heading p{color:#60646b;overflow-wrap:anywhere}
.report-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.report-actions :deep(.el-input){max-width:190px}.report-actions :deep(.el-button){margin-left:0}.report-tabs{margin:16px 0}
.report-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:14px}.report-panel{min-width:0;border:1px solid #dedfe2;border-radius:8px;padding:16px;margin-bottom:14px}.report-grid .report-panel{margin:0}.report-panel h3{margin-top:0}.report-panel .report-actions{margin-top:16px}
</style>
