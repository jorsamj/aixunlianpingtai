<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref} from 'vue';
import {request} from '../app/http';
import {browseError} from '../api/model-browse';

const props=defineProps<{projectId:string;algorithmId:string;legacyHref:string;back:string}>();
const emit=defineEmits<{close:[]}>();
const controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
type Quality={version_id:string;version_name:string;finished_at:string;val_map50:number|null;test_map50:number|null;test_status:string;test_snapshot_id:string};
type Report={ok:boolean;report_type:string;algorithm:{id:string;name:string;current_version_id:string;version_count:number};
  summary:{attempt_count:number;successful_count:number;duration_record_count:number;duration_unknown_count:number;total_duration_seconds:number};
  version_quality:Quality[];version_quality_total:number;version_quality_truncated:boolean;
  jobs:{job_id:string;version:string;status:string;finished_at:string}[];jobs_total:number;
  latest_created_version?:{id:string;version_name?:string}|null};
const report=ref<Report>(),busy=ref(false),error=ref('');
const versions=computed(()=>report.value?.version_quality??[]);
const highestTest=computed(()=>versions.value.reduce<Quality|undefined>((best,row)=>
  row.test_status==='succeeded'&&typeof row.test_map50==='number'&&Number.isFinite(row.test_map50)
  &&(!best||row.test_map50>(best.test_map50??-1))?row:best,undefined));
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
   <p>当前版本 {{report.algorithm.current_version_id||'无'}} · 最近创建 {{report.latest_created_version?.version_name||report.latest_created_version?.id||'未提供'}} · 近 {{versions.length}} 条中最高 Test mAP50 {{highestTest?.version_name||'未提供'}}</p>
   <p>训练 {{report.summary.attempt_count}} 次 · 成功 {{report.summary.successful_count}} 次 ·
    时长有记录 {{report.summary.duration_record_count}} 次 · 无记录 {{report.summary.duration_unknown_count}} 次</p>
   <h4>版本指标</h4>
   <el-table :data="versions" row-key="version_id" max-height="310" empty-text="暂无版本质量数据">
    <el-table-column label="版本" min-width="165"><template #default="{row}">{{row.version_name||row.version_id}}
     <el-tag v-if="row.version_id===report.algorithm.current_version_id" size="small">当前</el-tag>
    </template></el-table-column>
    <el-table-column label="Val mAP50" width="112"><template #default="{row}">{{metric(row.val_map50)}}</template></el-table-column>
    <el-table-column label="独立 Test mAP50" min-width="135"><template #default="{row}">{{metric(row.test_map50)}}</template></el-table-column>
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
