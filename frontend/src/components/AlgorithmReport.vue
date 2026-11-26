<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref} from 'vue';
import {request} from '../app/http';
import {browseError} from '../api/model-browse';

const props=defineProps<{projectId:string;algorithmId:string;legacyHref:string;back:string}>();
const emit=defineEmits<{close:[]}>();
const controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
type Quality={version_id:string;version_name:string;finished_at:string;val_map50:number|null;test_map50:number|null;
  test_status:string;test_snapshot_id:string;evaluation_id?:string;benchmark_scope_id?:string;
  evaluation_protocol_id?:string;comparability_key?:string|null;comparability_reason?:string|null};
type Report={ok:boolean;report_type:string;algorithm:{id:string;name:string;current_version_id:string;version_count:number};
  summary:{attempt_count:number;successful_count:number;duration_record_count:number;duration_unknown_count:number;total_duration_seconds:number};
  version_quality:Quality[];version_quality_total:number;version_quality_truncated:boolean;
  jobs:{job_id:string;version:string;status:string;finished_at:string}[];jobs_total:number;
  latest_created_version?:{id:string;version_name?:string;created_at?:string}|null};
const report=ref<Report>(),busy=ref(false),error=ref('');
const versions=computed(()=>report.value?.version_quality??[]);
const reasonLabels:Record<string,string>={evaluation_missing:'评测未成功',benchmark_evidence_missing:'基准证据缺失',
  benchmark_input_binding_missing:'输入绑定未验证',benchmark_historical_independence_unverified:'历史独立性未验证',
  evaluation_protocol_missing:'评测协议缺失'};
const reasonLabel=(value?:string|null)=>value?reasonLabels[value]||value:'未知原因';
// Only versions whose evaluation passes the existing compare_evaluations key can
// be ranked against each other; every benchmark/protocol group is reported on its
// own so no cross-benchmark ordering is ever implied.
const comparableGroups=computed(()=>{
  const groups=new Map<string,{key:string;scopeId:string;protocol:string;rows:Quality[];best?:Quality}>();
  for(const row of versions.value){
    if(!row.comparability_key||typeof row.test_map50!=='number'||!Number.isFinite(row.test_map50))continue;
    const group=groups.get(row.comparability_key)??{key:row.comparability_key,scopeId:row.benchmark_scope_id||'',protocol:row.evaluation_protocol_id||'',rows:[]};
    group.rows.push(row);
    if(!group.best||row.test_map50>(group.best.test_map50??-1))group.best=row;
    groups.set(row.comparability_key,group);
  }
  return [...groups.values()].sort((left,right)=>right.rows.length-left.rows.length);
});
const excludedReasons=computed(()=>{
  const counts=new Map<string,number>();
  for(const row of versions.value){
    if(row.test_status!=='succeeded'||row.comparability_key||typeof row.test_map50!=='number')continue;
    const key=row.comparability_reason||'unknown';
    counts.set(key,(counts.get(key)??0)+1);
  }
  return [...counts.entries()].map(([reason,count])=>({reason,label:reasonLabel(reason),count}));
});
const windowNote=computed(()=>{
  const current=report.value;
  if(!current)return '';
  return current.version_quality_truncated
    ? `仅统计最近 ${versions.value.length} / ${current.version_quality_total} 个版本，不是全历史最佳`
    : `已覆盖全部 ${versions.value.length} 个版本`;
});
const shortScope=(value?:string)=>value?value.slice(0,12):'基准未提供';
const metric=(value:number|null)=>typeof value==='number'&&Number.isFinite(value)?(value*100).toFixed(1)+'%':'未提供';
const destination=(id:string)=>({name:'version-report',params:{projectId:props.projectId,algorithmId:props.algorithmId,versionId:id},query:{tab:'evaluation',back:props.back}});
async function load(){
  if(busy.value)return;
  busy.value=true;error.value='';
  try{
    const result=await request<Report>(`/api/v49/projects/${encodeURIComponent(props.projectId)}/algorithms/${encodeURIComponent(props.algorithmId)}/report?lightweight=true`,{signal:controller.signal});
    if(result.ok!==true||result.report_type!=='algorithm'||result.algorithm?.id!==props.algorithmId
      ||!Array.isArray(result.version_quality)||!Array.isArray(result.jobs))
      throw new Error('算法报告响应身份不一致');
    report.value=result;
  }catch(cause){if(!controller.signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false}
}
onMounted(()=>void load());
</script>

<template>
 <el-dialog :model-value="true" title="算法报告" width="min(1050px,95vw)" @close="emit('close')">
  <el-alert v-if="error" :title="error" type="error" :closable="false"/>
  <el-skeleton v-if="busy" :rows="5" animated/>
  <section v-if="report">
   <h3>{{report.algorithm.name}}</h3>
   <p>当前版本 {{report.algorithm.current_version_id||'无'}} · 最新创建 {{report.latest_created_version?.version_name||report.latest_created_version?.id||'未提供'}}（两项身份独立，可同时成立）</p>
   <div v-if="comparableGroups.length" class="comparability-groups">
    <p v-for="group in comparableGroups" :key="group.key">
     <strong>{{ group.rows.length>1?'同口径最佳':'唯一合格版本' }}</strong> · 基准 {{shortScope(group.scopeId)}} · 协议 {{group.protocol||'未提供'}}：
     {{group.best?.version_name||group.best?.version_id}} {{metric(group.best?.test_map50??null)}}
     <small>{{ group.rows.length>1?`该口径内 ${group.rows.length} 个版本比较`:'该口径内只有 1 个合格版本，未进行多版本优劣比较' }}</small>
    </p>
   </div>
   <el-alert v-else title="暂无可比评测证据：没有版本同时满足同基准、同协议与输入绑定已验证的 Test 结果，因此不提供最佳版本排名。" type="info" :closable="false"/>
   <p v-for="reason in excludedReasons" :key="reason.reason" class="comparability-excluded">
     {{reason.count}} 个成功 Test 结果不可比：{{reason.label}}，不参与比较。
   </p>
   <p class="comparability-window">{{windowNote}}；不同基准或协议之间不排名。</p>
   <p>训练 {{report.summary.attempt_count}} 次 · 成功 {{report.summary.successful_count}} 次 ·
    时长有记录 {{report.summary.duration_record_count}} 次 · 无记录 {{report.summary.duration_unknown_count}} 次</p>
   <h4>版本指标</h4>
   <el-table :data="versions" row-key="version_id" max-height="310" empty-text="暂无版本质量数据">
    <el-table-column label="版本" min-width="165"><template #default="{row}">{{row.version_name||row.version_id}}
     <el-tag v-if="row.version_id===report.algorithm.current_version_id" size="small">当前</el-tag>
     <el-tag v-if="report.latest_created_version?.id===row.version_id" size="small" effect="plain">最新创建</el-tag>
    </template></el-table-column>
    <el-table-column label="Val mAP50" width="112"><template #default="{row}">{{metric(row.val_map50)}}</template></el-table-column>
    <el-table-column label="独立 Test mAP50" min-width="135"><template #default="{row}">{{metric(row.test_map50)}}</template></el-table-column>
    <el-table-column label="可比性" min-width="165"><template #default="{row}">
      <el-tag v-if="row.comparability_key" type="success" effect="plain" size="small">同口径可比</el-tag>
      <el-tag v-else type="info" effect="plain" size="small">{{row.test_status==='succeeded'?reasonLabel(row.comparability_reason):'无成功 Test'}}</el-tag>
      <small v-if="row.comparability_key">{{shortScope(row.benchmark_scope_id)}} · {{row.evaluation_protocol_id||'协议未提供'}}</small>
    </template></el-table-column>
    <el-table-column prop="test_snapshot_id" label="Test 快照" min-width="130" show-overflow-tooltip/>
    <el-table-column label="操作" width="125"><template #default="{row}"><router-link v-if="row.version_id&&row.test_snapshot_id" :to="destination(row.version_id)">查看独立评测</router-link></template></el-table-column>
   </el-table>
   <p v-if="report.version_quality_truncated">展示最近 {{versions.length}} / {{report.version_quality_total}} 个版本。</p>
   <h4>近期训练</h4>
   <el-table :data="report.jobs" row-key="job_id" max-height="240" empty-text="暂无训练记录">
    <el-table-column prop="version" label="版本" min-width="120"/>
    <el-table-column prop="status" label="状态" min-width="115"/>
    <el-table-column prop="finished_at" label="时间" min-width="170"/>
    <el-table-column label="报告" width="115"><template #default="{row}"><router-link v-if="row.job_id" :to="{name:'training-report',params:{projectId,jobId:row.job_id},query:{back}}">训练报告</router-link></template></el-table-column>
   </el-table>
  </section>
  <template #footer><el-button :loading="busy" @click="load">刷新</el-button><el-button tag="a" :href="legacyHref">完整历史与标签统计</el-button></template>
 </el-dialog>
</template>

<style scoped>
.comparability-groups p { margin: 0 0 4px; }
.comparability-groups small, .comparability-window { color: var(--workspace-subtle, #686872); font-size: 12px; }
.comparability-excluded { margin: 4px 0; font-size: 12px; color: var(--el-color-warning); }
.comparability-window { margin: 4px 0 12px; }
</style>
