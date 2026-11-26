<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {trainingReaderApi,type ReportSelection,type TrainingReport} from '../api/training-reader';
import {browseError} from '../api/model-browse';
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
const PANES=['overview','history','evaluation','samples','trace'] as const;
const pane=computed(()=>PANES.includes(query('tab') as typeof PANES[number])?query('tab'):'overview');
// Lineage is read on demand with one bounded version-detail call per opened report;
// it never scans the version history or infers relationships from names.
const traceDetail=ref<{version:{base_version_id?:string;parent_version_id?:string;training_lineage?:Record<string,unknown>;training_parameters?:Record<string,unknown>;snapshot_id?:string;dataset_revision_id?:string}}|null>(null);
const traceBusy=ref(false),traceError=ref('');
async function loadTrace(){
  const current=canonical.value;
  if(!current||traceDetail.value||traceBusy.value)return;
  traceBusy.value=true;traceError.value='';
  try{
    const value=await versions.detail(current.algorithmId,current.versionId,controller.signal);
    if(controller.signal.aborted)return;
    traceDetail.value={version:value.version};
  }catch(cause){if(!controller.signal.aborted)traceError.value=browseError(cause)}
  finally{traceBusy.value=false}
}
function selectPane(name:string){
  tab(name);
  if(name==='trace')void loadTrace();
}
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
    if(original.params.projectId===projectId&&(original.name==='algorithms'||original.name==='training-tasks'||original.name==='quality-centre'))return original.fullPath;
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
      <el-button v-for="[key,label] in [['overview','训练概况'],['history','训练过程'],['evaluation','独立评测'],['samples','样本诊断'],['trace','训练溯源']]" :key="key" :type="pane===key?'primary':'default'" :aria-pressed="pane===key" :disabled="key!=='overview'&&!canonical" @click="selectPane(key)">{{label}}</el-button>
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
      <section v-if="pane==='overview'" class="report-panel">
        <h3>冻结快照的样本分布</h3>
        <template v-if="report.fixed_zip_split">
          <h3>按 ZIP 来源固定划分</h3>
          <template v-if="report.fixed_zip_split.state==='VERIFIED'">
            <ReadOnlyFacts :fields="[['Train',report.fixed_zip_split.counts?.train],['Val',report.fixed_zip_split.counts?.validation],['Test',report.fixed_zip_split.counts?.test],['输入冻结摘要',report.fixed_zip_split.input_freeze_id]]"/>
            <details><summary>ZIP 来源规则</summary><ReadOnlyFacts :fields="Object.entries(report.fixed_zip_split.sources||{}).map(([job,source])=>[job,source.rule_digest])"/></details>
          </template>
          <p v-else>固定划分冻结证据不可用</p>
        </template>
        <ReadOnlyFacts v-if="Object.keys(report.sample_distribution||{}).length"
          :fields="Object.entries(report.sample_distribution||{}).map(([role,counts])=>[role,`正样本 ${counts.positive} · 已确认负样本 ${counts.confirmed_negative}`])"/>
        <p v-else>暂无可核验的分角色统计。</p>
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
      <section v-else-if="pane==='samples'" class="report-panel" aria-label="样本诊断">
        <h3>已记录的问题与异常</h3>
        <ReadOnlyFacts :fields="[['任务状态',report.result?.status],['完成原因',report.result?.completion_reason],['失败记录',report.result?.error],['早停原因',report.result?.early_stopping_reason],['质量门禁',report.result?.quality_gate_reason],['训练结果',report.result?.training_outcome],['质量状态',report.quality_status]]"/>
        <ul v-if="report.warnings?.length" class="report-warnings"><li v-for="(warning,index) in report.warnings" :key="index">{{warning}}</li></ul>
        <p v-if="Object.keys(report.credibility||{}).length" class="report-note">可信度诊断字段见“训练概况”中的可信度与质量诊断分区；本页只汇总可执行的问题线索。</p>
        <h3>进入样本与后续处理</h3>
        <p class="report-note">FP/FN、低置信度、类别退化与冻结图片证据在“独立评测”中按真实评测结果展示；困难样本、采纳与补数在“困难样本与继续训练”中处理。</p>
        <div class="report-actions">
          <el-button :disabled="!canonical" @click="selectPane('evaluation')">查看 TP / FP / FN 样本</el-button>
          <a v-if="canonical" :href="originalEvaluation">原高级评测与样本证据</a>
        </div>
        <p v-if="report.test_status==='not_generated'" class="report-note">该任务没有独立 Test 评测记录，因此没有 Test 侧的 FP/FN 证据；正式 Test 不会因困难样本被重新用于训练。</p>
      </section>
      <section v-else-if="pane==='trace'" class="report-panel" aria-label="训练溯源">
        <h3>身份与来源</h3>
        <ReadOnlyFacts :fields="[['记录来源',report.source],['任务',selection?.jobId],['算法',canonical?.algorithmId],['版本',canonical?.versionId],['训练快照',report.result?.snapshot_id],['数据集修订',report.result?.dataset_revision_id],['固定 ZIP 划分',report.fixed_zip_split?.state]]"/>
        <el-alert v-if="traceError" :title="traceError" type="error" :closable="false"/>
        <el-skeleton v-if="traceBusy&&!traceDetail" :rows="3" animated/>
        <template v-else-if="traceDetail">
          <h3>版本血缘</h3>
          <ReadOnlyFacts :fields="[['父版本 ID',traceDetail.version.parent_version_id],['基础版本 ID',traceDetail.version.base_version_id]]"/>
          <ReadOnlyFacts v-if="Object.keys(traceDetail.version.training_lineage||{}).length" :fields="Object.entries(traceDetail.version.training_lineage||{})"/>
          <p v-else class="report-note">未记录血缘字段；不根据版本名称推断父版本或母模型。</p>
          <div v-if="traceDetail.version.parent_version_id||traceDetail.version.base_version_id" class="report-actions">
            <router-link v-if="traceDetail.version.parent_version_id&&canonical" :to="{name:'version-report',params:{projectId,algorithmId:canonical.algorithmId,versionId:String(traceDetail.version.parent_version_id)},query:{back:query('back')||undefined}}">查看父版本报告</router-link>
            <router-link v-if="traceDetail.version.base_version_id&&canonical" :to="{name:'version-report',params:{projectId,algorithmId:canonical.algorithmId,versionId:String(traceDetail.version.base_version_id)},query:{back:query('back')||undefined}}">查看基础版本报告</router-link>
          </div>
        </template>
        <p v-else-if="!traceError" class="report-note">尚未读取版本血缘；打开本页按需读取一次，不扫描历史版本。</p>
        <h3>冻结数据与评测基准</h3>
        <ReadOnlyFacts :fields="[['Train/Val/Test 来源',report.fixed_zip_split?'按 ZIP 来源固定划分':(Object.keys(report.sample_distribution||{}).length?'按冻结快照样本角色':'未记录')],['输入冻结摘要',report.fixed_zip_split?.input_freeze_id],['独立 Test 评测状态',report.test_status]]"/>
        <h3>后续证据链</h3>
        <div class="report-actions">
          <router-link v-if="canonical" :to="{name:'version-report',params:{projectId,algorithmId:canonical.algorithmId,versionId:canonical.versionId},query:{tab:'evaluation',back:query('back')||undefined}}">独立评测</router-link>
          <router-link v-if="canonical" :to="{name:'version-conversions',params:{projectId,algorithmId:canonical.algorithmId,versionId:canonical.versionId}}">转换记录</router-link>
          <router-link v-if="canonical" :to="{name:'external-publish-native',params:{projectId},query:{algorithm:canonical.algorithmId,version:canonical.versionId}}">交付记录</router-link>
          <a v-if="canonical" :href="legacyUrl(projectId,'算法列表',canonical.algorithmId,canonical.versionId,'lineage')">原训练溯源</a>
        </div>
      </section>
    </template>
    <el-empty v-else-if="selection&&!selection.jobId" description="此版本没有已绑定的训练任务报告"/>
  </section>
</template>

<style scoped>
.native-report{min-width:0}.report-heading{display:flex;justify-content:space-between;align-items:end;gap:12px;flex-wrap:wrap}.report-heading h2{margin:0 0 4px;font-size:21px}.report-heading p{color:var(--workspace-muted);overflow-wrap:anywhere}
.report-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.report-actions :deep(.el-input){max-width:190px}.report-actions :deep(.el-button){margin-left:0}.report-tabs{margin:16px 0}
.report-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:12px}.report-panel{min-width:0;background:var(--workspace-surface);border-radius:var(--workspace-radius);padding:16px;margin-bottom:12px}.report-grid .report-panel{margin:0}.report-panel h3{margin-top:0;font-size:16px}.report-panel .report-actions{margin-top:12px}
.report-note{margin:8px 0;font-size:12px;color:var(--workspace-muted,#52525b)}
.report-warnings{margin:8px 0;padding-left:20px;font-size:13px;color:var(--el-color-warning);line-height:1.7}
.report-panel :deep(.readonly-facts){font-size:13px}
</style>
