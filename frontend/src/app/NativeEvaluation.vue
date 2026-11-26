<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref} from 'vue';
import {trainingReaderApi,type EvaluationPage} from '../api/training-reader';
import {useReadScope} from '../composables/useReadScope';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
import NativeReportCharts from './NativeReportCharts.vue';
import EvaluationSamplePreview from './EvaluationSamplePreview.vue';
import EvaluationSampleReview from './EvaluationSampleReview.vue';
import {request} from './http';
const props=defineProps<{projectId:string;algorithmId:string;versionId:string;jobId:string;legacyHref:string}>();
const controller=new AbortController();onBeforeUnmount(()=>controller.abort());
const reads=useReadScope(controller),api=trainingReaderApi({projectId:props.projectId,get:request,memory:{}}),selection={jobId:props.jobId,algorithmId:props.algorithmId,versionId:props.versionId,returnPage:'assets' as const};
const tab=ref('classes'),summary=ref<EvaluationPage|null>(null),detail=ref<EvaluationPage|null>(null),offset=ref(0),classId=ref(''),issue=ref('fp'),sort=ref('severity'),versions=ref<{id:string;version_name?:string}[]>([]),versionPage=ref(1),versionTotal=ref(0),other=ref(''),comparison=ref<Record<string,unknown>|null>(null),comparisonOffset=ref(0),expanded=ref('');
const records=(v:unknown):Record<string,unknown>[]=>Array.isArray(v)?v.filter(x=>x&&typeof x==='object'):[];
const facts=(v:unknown):[string,unknown][]=>v&&typeof v==='object'?Object.entries(v).filter(([,x])=>x===null||['string','number','boolean'].includes(typeof x)):[];
const tableRows=(v:unknown)=>v&&typeof v==='object'?Object.entries(v).map(([metric,data])=>({metric,...(data as Record<string,unknown>)})):[];
const names:Record<string,string>={precision:'Precision',recall:'Recall',f1:'F1',map50:'mAP50',map50_95:'mAP50-95',true_positive:'TP',false_positive:'FP',false_negative:'FN',class_id:'类别 ID',label:'类别',ground_truth_count:'GT 数',prediction_count:'预测数'};
const originalEvaluation=computed(()=>summary.value?.evaluation_id
  ? props.legacyHref+'&'+new URLSearchParams({expected_evaluation_id:summary.value.evaluation_id})
  : props.legacyHref);
const reviewTarget=ref<{evaluationId:string;imageId:string;imageSha:string;filename:string}>();
function openReview(row:Record<string,unknown>){
  const id=detail.value?.evaluation_id;
  if(!id||!/^[a-f0-9]{64}$/.test(id)||!frozenUrl(row)||typeof row.image_id!=='string'||typeof row.image_content_sha256!=='string')return;
  reviewTarget.value={evaluationId:id,imageId:row.image_id,imageSha:row.image_content_sha256,filename:String(row.filename||row.image_id)};
}
function load(){
  detail.value=null;
  expanded.value='';
  return reads.run('detail',async signal=>{
    const head=summary.value||await api.evaluation(selection,'summary',0,signal);
    if(signal.aborted)return null;
    summary.value=head;
    if(head.state==='NOT_GENERATED'||head.state==='DEFERRED')return head;
    const value=await api.evaluation(selection,tab.value,offset.value,signal,{...(tab.value==='samples'?{issue:issue.value,sort:sort.value}:{}),...(classId.value?{class_id:classId.value}:{})});
    if(head.evaluation_id!==value.evaluation_id)throw new Error('冻结评测已变化，请重新读取报告。');
    return value;
  },value=>{detail.value=value});
}
function select(key:string){reads.cancel('detail');reads.cancel('versions');reads.cancel('comparison');tab.value=key;offset.value=0;detail.value=null;comparison.value=null;if(key==='compare')void loadVersions();else void load()}
function loadVersions(){return reads.run('versions',s=>api.versions(selection,versionPage.value,s),v=>{versions.value=v.items.filter(x=>x.id!==props.versionId);versionTotal.value=v.total})}
function compare(n=0){if(!other.value)return;comparisonOffset.value=n;comparison.value=null;return reads.run('comparison',s=>api.compare(selection,other.value,s,n),v=>comparison.value=v)}
function changeComparison(){reads.cancel('comparison');comparison.value=null;comparisonOffset.value=0}
function frozenUrl(row:Record<string,unknown>){
  const raw=row.preview_url, id=detail.value?.evaluation_id,digest=row.image_content_sha256;
  if(typeof raw!=='string'||!raw.startsWith('/api/')||!id||!row.image_id||typeof digest!=='string'||!/^[a-f0-9]{64}$/i.test(digest))return '';
  try{
    const url=new URL(raw,location.origin);
    const path=url.pathname.split('/').slice(1).map(decodeURIComponent);
    const expected=['api','v12','projects',props.projectId,'algorithms',props.algorithmId,'versions',props.versionId,'evaluation','images',row.filename];
    return url.origin===location.origin&&path.length===expected.length&&path.every((part,index)=>part===expected[index])
      && url.searchParams.get('expected_evaluation_id')===id&&url.searchParams.get('expected_image_id')===row.image_id&&url.searchParams.get('expected_sha256')===digest ? raw : '';
  }catch{return ''}
}
function retry(){if(tab.value==='compare'){if(other.value)void compare(comparisonOffset.value);else void loadVersions();return}summary.value=null;void load()}
function samples(id:unknown,kind:string){classId.value=String(id??'');issue.value=kind;select('samples')}
onMounted(()=>void load());
</script>
<template><EvaluationSampleReview v-if="reviewTarget" :key="reviewTarget.evaluationId+reviewTarget.imageId" v-bind="reviewTarget" :project-id="projectId" :algorithm-id="algorithmId" :version-id="versionId" @close="reviewTarget=undefined"/><section aria-label="独立评测"><nav class="actions"><el-button v-for="[key,label] in [['classes','类别指标'],['curves','PR 阈值曲线'],['confusion','混淆矩阵'],['samples','TP / FP / FN 样本'],['compare','版本对比']]" :key="key" :type="tab===key?'primary':'default'" @click="select(key)">{{label}}</el-button><a :href="originalEvaluation">叠加对照 / 继续训练 / 反馈补数 · LEGACY_BRIDGE</a></nav>
<p v-if="reads.errors.detail||reads.errors.versions||reads.errors.comparison" role="alert">{{reads.errors.detail||reads.errors.versions||reads.errors.comparison}} <el-button @click="retry">重试</el-button></p><el-skeleton v-if="reads.busy.detail||reads.busy.versions||reads.busy.comparison" :rows="4" animated/>
<section v-if="summary" class="evaluation-overview"><h3>独立 Test 记录</h3><ReadOnlyFacts :fields="[['评测状态',summary.evaluation?.status],['冻结评测 ID',summary.evaluation_id],['样本数',summary.evaluation?.image_count],['Snapshot',summary.evaluation?.snapshot_id],['数据集修订',summary.evaluation?.dataset_revision_id],['评测协议',summary.evaluation?.evaluation_protocol_id],['历史独立性',summary.evaluation?.historical_independence],...facts(summary.evaluation?.metrics),...facts(summary.evaluation?.benchmark_scope)]"/><p v-if="!summary.evaluation_id">此记录没有可核验的冻结评测身份。</p></section><section v-if="detail&&!reads.busy.detail"><p>状态 {{detail.state||'未提供'}} · 冻结评测 {{detail.evaluation_id||'未提供'}}</p><p v-if="detail.message">{{detail.message}}</p><ReadOnlyFacts :fields="facts(detail.evaluation)"/><div v-if="classId">类别筛选 {{classId}} <el-button @click="classId='';offset=0;load()">清除</el-button></div>
<el-table v-if="tab==='classes'" :data="records(detail.evaluation?.per_class)" empty-text="没有已记录类别指标"><el-table-column v-for="key in ['class_id','label','precision','recall','f1','map50','map50_95','ground_truth_count','prediction_count','true_positive']" :key="key" :prop="key" :label="names[key]||key" min-width="100"><template #default="{row}">{{row[key]??'未提供'}}</template></el-table-column><el-table-column label="诊断" min-width="180"><template #default="{row}"><el-button link @click="samples(row.class_id,'fp')">FP {{row.false_positive??'未提供'}}</el-button><el-button link @click="samples(row.class_id,'fn')">FN {{row.false_negative??'未提供'}}</el-button><el-button link @click="classId=String(row.class_id??'');select('curves')">曲线</el-button></template></el-table-column></el-table>
<template v-if="tab==='curves'||tab==='confusion'"><NativeReportCharts :evaluation="detail.evaluation||{}"/><p>PR 为已记录置信度阈值采样，不等同 AP 积分曲线。</p><details><summary>原协议字段</summary><pre>{{detail.evaluation?.confidence_curve_protocol||detail.evaluation?.confusion_matrix}}</pre></details></template>
<template v-if="tab==='samples'"><label>样本类型 <select v-model="issue" @change="offset=0;load()"><option value="tp">TP 正确识别</option><option value="fp">FP 误检</option><option value="fn">FN 漏检</option><option value="wrong_class">类别错误</option><option value="localization">定位偏差</option><option value="low_confidence">低置信度</option><option value="duplicate">重复检测</option></select></label><label>排序 <select v-model="sort" @change="offset=0;load()"><option value="severity">漏检、误检数量优先</option><option value="high_confidence_fp">误检置信度优先</option></select></label><p v-if="detail.filter_evidence_complete===false">当前筛选使用已保留的框级证据，历史样本证据可能不完整。</p><p v-if="issue==='low_confidence'&&detail.diagnostic_low_confidence_threshold!=null">置信度阈值 {{detail.diagnostic_low_confidence_threshold}}</p><div class="samples"><article v-for="(row,index) in records(detail.items)" :key="String(row.image_id||index)"><h3>{{row.filename||row.image_id||'冻结样本'}}</h3><EvaluationSamplePreview :key="frozenUrl(row)" :src="frozenUrl(row)" :sample="row" :expanded="expanded===row.image_id"/><el-button v-if="frozenUrl(row)" @click="expanded=expanded===row.image_id?'':String(row.image_id)">{{expanded===row.image_id?'收起框级诊断':'查看框级诊断'}}</el-button><ReadOnlyFacts :fields="facts(row)"/><p v-if="row.boxes_truncated||row.gt_boxes_truncated||row.pred_boxes_truncated">框证据已截断。</p><details v-if="detail.evaluation_id"><summary>冻结 GT / 预测框</summary><pre>{{ {gt:row.gt_boxes,predictions:row.pred_boxes} }}</pre></details><el-button v-if="frozenUrl(row)" link @click="openReview(row)">复核样本</el-button></article></div><p v-if="!records(detail.items).length">当前条件下没有已记录样本；不推断整体错误为零。</p></template>
<div class="actions"><el-button :disabled="offset===0" @click="offset=Math.max(0,offset-20);load()">上一页</el-button><span>偏移 {{detail.offset??offset}} · 总数 {{detail.total??'未提供'}}</span><el-button :disabled="!(detail.has_next??((detail.total??0)>offset+20))" @click="offset+=20;load()">下一页</el-button></div></section>
<section v-if="tab==='compare'"><h3>版本对比</h3><div class="actions"><select v-model="other" aria-label="对照版本" @change="changeComparison"><option value="">请选择已保存版本</option><option v-for="v in versions" :key="v.id" :value="v.id">{{v.version_name||v.id}}</option></select><el-button :disabled="!other" @click="compare(0)">读取对比</el-button><el-button :disabled="versionPage===1" @click="versionPage--;loadVersions()">上一页版本</el-button><span>第 {{versionPage}} 页</span><el-button :disabled="versionPage*20>=versionTotal" @click="versionPage++;loadVersions()">下一页版本</el-button></div><template v-if="comparison"><p>{{comparison.comparable===true?'原评测合同确认可比':comparison.comparable===false?'原评测合同判定不可比':'可比性尚未确认'}}</p><ReadOnlyFacts :fields="facts(comparison)"/><p>原因：{{comparison.reason_codes||'未提供'}}</p><template v-if="comparison.comparable===true"><h4>指标变化（原记录数值）</h4>
<el-table :data="tableRows(comparison.metrics)" empty-text="没有共同记录的指标">
  <el-table-column label="指标"><template #default="{row}">{{names[row.metric]||row.metric}}</template></el-table-column>
  <el-table-column v-for="[key,label] in [['before','来源版本'],['after','当前版本'],['delta','差值']]" :key="key" :label="label"><template #default="{row}">{{row[key]??'未提供'}}</template></el-table-column>
</el-table>
<h4>参数差异</h4>
<el-table :data="tableRows(comparison.parameter_differences)" empty-text="没有已记录的参数差异">
  <el-table-column prop="metric" label="参数"/><el-table-column prop="before" label="来源版本"/><el-table-column prop="after" label="当前版本"/>
</el-table>
<h4>逐类对比</h4>
<el-table :data="records(comparison.classes)" max-height="400" empty-text="没有可比类别">
  <el-table-column prop="label" label="类别"/><el-table-column label="可比性"><template #default="{row}">{{row.comparable===true?'可比':row.comparable===false?'不可比':'未确认'}}</template></el-table-column>
  <el-table-column label="已记录差值" min-width="220"><template #default="{row}"><ReadOnlyFacts :fields="tableRows(row.metrics).map((metric):[string,unknown]=>[names[metric.metric]||metric.metric,(metric as Record<string,unknown>).delta])"/></template></el-table-column>
</el-table></template><p v-else>未确认可比时不展示版本优劣结论。</p><div class="actions"><el-button :disabled="comparisonOffset===0" @click="compare(Math.max(0,comparisonOffset-20))">上一页对比</el-button><span>偏移 {{comparison.offset??comparisonOffset}} · 类别总数 {{comparison.total??'未提供'}}</span><el-button :disabled="!comparison.has_next" @click="compare(comparisonOffset+20)">下一页对比</el-button></div></template></section></section></template>
<style scoped>.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:12px 0}.actions :deep(.el-button){margin:0}.samples{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}.samples article{border:1px solid #ddd;padding:12px;min-width:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:300px;overflow:auto}</style>
