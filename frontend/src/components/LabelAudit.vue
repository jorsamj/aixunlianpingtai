<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,reactive,ref,shallowRef} from 'vue';
import {getMaterialBatch,type MaterialBatchTask} from '../api/material-batches';
import {browseError} from '../api/model-browse';
import type {ProjectLabel} from '../api/label-management';
import {request} from '../app/http';
import {legacyUrl} from '../app/navigation';
import {readWorkspaceSession,useWorkspace,workspaceActorKey} from '../app/main';
import type {MaterialBox} from '../types/materials';
import MaterialPreview from './MaterialPreview.vue';

const props=defineProps<{projectId:string;labels:ProjectLabel[]}>();
const emit=defineEmits<{busy:[value:boolean]}>();
interface Group {label_code:string;issue_type:string;image_count:number;box_count:number}
interface Mapping {source_label:string;target_label:string}
interface AuditReport {
  summary:{scanned_images:number;affected_images:number;issue_count:number};
  groups:Group[];
  repair_defaults:Record<string,{target_label:string;merge_chain:string[]}>;
}
interface Sample {
  image_id:string;filename:string;width:number;height:number;content_url:string;thumbnail_url:string;
  historical_class_ids:number[];current_schema_identity:{class_id:number;label_code:string|null;status:string}[];
  provenance:Record<string,string>;boxes:MaterialBox[];
}
type Samples = {items:Sample[];next_cursor:string|null;candidate_count:number};
type RepairTask = MaterialBatchTask & {mapping_count?:number;still_requires_repair?:number;already_resolved?:number;mappings?:Mapping[]};
const batchBase=`/api/v62/projects/${encodeURIComponent(props.projectId)}/material-batches`;
const auditBase=`/api/v54/projects/${encodeURIComponent(props.projectId)}/labels/integrity/audits`;
const controller=new AbortController();
const task=shallowRef<RepairTask>(), auditId=ref(''), report=shallowRef<AuditReport>();
const records=shallowRef<RepairTask[]>([]), historyNext=ref(''), historyCursor=ref('');
const targetBySource=reactive<Record<string,string>>(Object.create(null));
const sampleSource=ref(''), samples=shallowRef<Samples>(), samplePending=ref(false), sampleError=ref('');
const error=ref(''), busy=ref(false), unknown=ref(false);
const actorKey=useWorkspace().actorKey;
const pendingKey='label-audit.pending:'+JSON.stringify([actorKey,props.projectId]);
try{unknown.value=sessionStorage.getItem(pendingKey)==='1'}catch{error.value='浏览器无法读取待核对的创建记录。'}
const confirmation=shallowRef<{audit:string;kind:'remap'|'projection';mappings:Mapping[];candidates:number}>();
const page=ref(1);
const auditOperation='AUDIT_LABEL_INTEGRITY';
const remapOperation='REMAP_ANNOTATION_LABELS';
const projectionOperation='REPAIR_ANNOTATION_PROJECTIONS';
const terminal=new Set(['SUCCEEDED','PARTIAL_SUCCESS','FAILED','CANCELLED','BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE']);
const statuses:Record<string,string>={QUEUED:'排队中',WAITING_RESOURCE:'等待资源',RUNNING:'处理中',CANCEL_REQUESTED:'正在取消',SUCCEEDED:'已完成',PARTIAL_SUCCESS:'部分成功',FAILED:'失败',CANCELLED:'已取消',BLOCKED_BY_ENVIRONMENT:'环境阻断',BLOCKED_BY_HARDWARE:'硬件阻断'};
const issueNames:Record<string,string>={
  ORPHAN_LABEL:'孤立标签',INCOMPLETE_MERGE:'历史合并未完成',INACTIVE_REFERENCE:'停用标签引用',
  DUPLICATE_ANNOTATION_CONFLICT:'同图不同正式标注',PROJECTION_PREVIEW_DRIFT:'缩略图标注投影不一致',
};
const repairable=new Set(['ORPHAN_LABEL','INCOMPLETE_MERGE','INACTIVE_REFERENCE']);
const active=computed(()=>!!task.value&&!terminal.has(task.value.status));
const groups=computed(()=>{
  const byLabel=new Map<string,{source:string;images:number;boxes:number;candidateUpperBound:number;issues:string[]}>();
  for(const row of report.value?.groups||[]){
    if(!row.label_code||!repairable.has(row.issue_type))continue;
    const group=byLabel.get(row.label_code)||{source:row.label_code,images:0,boxes:0,candidateUpperBound:0,issues:[]};
    group.images=Math.max(group.images,row.image_count);
    group.boxes=Math.max(group.boxes,row.box_count);
    group.candidateUpperBound+=row.image_count;
    group.issues.push(issueNames[row.issue_type]||row.issue_type);
    byLabel.set(row.label_code,group);
  }
  return [...byLabel.values()];
});
const visibleGroups=computed(()=>groups.value.slice((page.value-1)*30,page.value*30));
const mappings=computed(()=>groups.value.flatMap(({source})=>targetBySource[source]&&props.labels.some(label=>label.code===targetBySource[source])
  ?[{source_label:source,target_label:targetBySource[source]}]:[]));
const projection=computed(()=>report.value?.groups.find(group=>group.issue_type==='PROJECTION_PREVIEW_DRIFT'));
const extraGroups=computed(()=>report.value?.groups.filter(group=>!repairable.has(group.issue_type))||[]);
const legacyLabels=legacyUrl(props.projectId,'标签管理');
const legacyIntegrity=legacyUrl(props.projectId,'数据集','','','material-integrity');
const isAuditTask=(value:MaterialBatchTask)=>value.operation===auditOperation||value.operation===projectionOperation
  ||(value.operation===remapOperation&&value.retire_sources_on_success===false);

function checkTask(value:RepairTask,id?:string,operation?:string){
  if(!value.task_id||value.project_id!==props.projectId||!isAuditTask(value)
      ||(id&&id!==value.task_id)||(operation&&operation!==value.operation))
    throw new Error('标签审计任务身份不一致，请读取任务记录。');
  return value;
}
function mappingIdentity(value:Mapping[]){
  return JSON.stringify(value.map(item=>[item.source_label,item.target_label]).sort());
}
async function run(work:()=>Promise<void>){
  if(busy.value)return;
  busy.value=true;error.value='';emit('busy',true);
  try{await work()}catch(cause){if(!controller.signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false;emit('busy',false)}
}
async function readHistory(cursor=''){
  const params=new URLSearchParams({limit:'50',cursor});
  const result=await request<{items:RepairTask[];next_cursor:string|null}>(`${batchBase}?${params}`,{signal:controller.signal,cache:'no-store'});
  records.value=result.items.filter(value=>value.project_id===props.projectId&&isAuditTask(value));
  historyCursor.value=cursor;historyNext.value=result.next_cursor||'';
}
async function showTask(value:RepairTask){
  task.value=value;
  if(value.operation!==auditOperation)return;
  if(auditId.value!==value.task_id){
    auditId.value=value.task_id;report.value=undefined;page.value=1;sampleSource.value='';
    for(const source of Object.keys(targetBySource))delete targetBySource[source];
  }
  if(value.status!=='SUCCEEDED'||report.value)return;
  const result=await request<AuditReport>(`${auditBase}/${encodeURIComponent(value.task_id)}/issues?limit=1`,{signal:controller.signal,cache:'no-store'});
  report.value=result;
  for(const [source,choice] of Object.entries(result.repair_defaults||{}))targetBySource[source]=choice.target_label;
}
const readTask=(id:string)=>run(async()=>showTask(checkTask(await getMaterialBatch(props.projectId,id,controller.signal),id)));
async function loadSamples(source:string,cursor=''){
  if(!auditId.value||!source||samplePending.value)return;
  const id=auditId.value;
  sampleSource.value=source;samplePending.value=true;sampleError.value='';samples.value=undefined;
  try{
    const params=new URLSearchParams({source_label:source,limit:'12',cursor});
    const result=await request<Samples>(`${auditBase}/${encodeURIComponent(id)}/samples?${params}`,{signal:controller.signal});
    if(auditId.value===id&&sampleSource.value===source)samples.value=result;
  }catch(cause){if(!controller.signal.aborted)sampleError.value=browseError(cause)}
  finally{samplePending.value=false}
}
function prepare(kind:'remap'|'projection'){
  if(!report.value||!auditId.value||busy.value||unknown.value||active.value)return;
  const selected=kind==='remap'?mappings.value:[];
  if(kind==='remap'&&!selected.length)return;
  const sources=new Set(selected.map(mapping=>mapping.source_label));
  confirmation.value={audit:auditId.value,kind,mappings:selected,
    candidates:kind==='projection'?projection.value?.image_count||0:groups.value.reduce((count,row)=>count+(sources.has(row.source)?row.candidateUpperBound:0),0)};
}
async function verifyActor(){
  if(!actorKey||workspaceActorKey(await readWorkspaceSession(controller.signal))!==actorKey)
    throw new Error('登录账号已变化，请刷新后重新核对。');
}
function pending(value:boolean){
  if(value)sessionStorage.setItem(pendingKey,'1');
  else sessionStorage.removeItem(pendingKey);
  unknown.value=value;
}
function start(kind:'audit'|'remap'|'projection'){
  const confirmed=confirmation.value;
  if(unknown.value||active.value||(kind!=='audit'&&(!confirmed||confirmed.audit!==auditId.value||confirmed.kind!==kind)))return;
  void run(async()=>{
    await verifyActor();
    const operation=kind==='audit'?auditOperation:kind==='projection'?projectionOperation:remapOperation;
    const url=kind==='audit'?auditBase:`${auditBase}/${encodeURIComponent(auditId.value)}/${kind==='projection'?'projection-repairs':'repairs'}`;
    let value:RepairTask;
    pending(true);
    try{
      value=checkTask(await request<RepairTask>(url,{method:'POST',
        ...(kind==='remap'?{body:JSON.stringify({mappings:confirmed?.mappings})}:{})}),undefined,operation);
      if(kind==='remap'&&mappingIdentity(value.mappings||[])!==mappingIdentity(confirmed?.mappings||[]))
        throw new Error('后台修复回执的标签映射与确认内容不一致，请核对任务记录。');
    }catch(cause){
      const status=(cause as {httpStatus?:number}).httpStatus;
      if([400,401,403,404,409,422].includes(status||0))pending(false);
      throw cause;
    }finally{confirmation.value=undefined}
    await showTask(value);
    pending(false);
    await readHistory();
  });
}
function startFreshAudit(){
  if(!unknown.value||busy.value||active.value)return;
  try{
    pending(false);
    report.value=undefined;auditId.value='';
    start('audit');
  }catch(cause){error.value=browseError(cause)}
}
function cancel(){
  const id=task.value?.task_id;
  if(!id||!active.value)return;
  void run(async()=>{
    await verifyActor();
    const value=checkTask(await request<RepairTask>(`${batchBase}/${encodeURIComponent(id)}/cancel`,{method:'POST'}),id);
    await showTask(value);
  });
}
function retry(){
  const current=task.value;
  if(!current||!terminal.has(current.status)||current.status==='SUCCEEDED'||unknown.value)return;
  void run(async()=>{
    await verifyActor();
    const value=checkTask(await request<RepairTask>(
      `${batchBase}/${encodeURIComponent(current.task_id)}/retry`,{method:'POST',signal:controller.signal}),
    current.task_id,current.operation);
    if(value.task_id===auditId.value){sampleSource.value='';report.value=undefined}
    await showTask(value);
    await readHistory();
  });
}
onMounted(()=>void run(async()=>{
  await readHistory();
  const newest=records.value[0];
  if(newest)await showTask(newest);
}));
onBeforeUnmount(()=>controller.abort());
</script>

<template>
 <section class="audit-panel" aria-label="标签审计与修复">
  <h2>标签完整性</h2>
  <div class="audit-actions">
   <el-button type="primary" :loading="busy" :disabled="unknown||active" @click="start('audit')">运行完整性审计</el-button>
   <el-button :disabled="busy" @click="run(()=>readHistory())">刷新任务记录</el-button>
   <el-button tag="a" :href="legacyLabels">智能质量建议与人工复核</el-button>
  </div>
  <el-alert v-if="error" :title="error" :closable="false" type="error"/>
  <el-alert v-if="unknown" title="创建结果待核对。请在任务记录查找后台任务，勿重复提交。" :closable="false" type="warning"/>
  <el-button v-if="unknown" :disabled="busy||active" @click="startFreshAudit">已人工核对，开始新的完整性审计</el-button>
  <div v-if="task" class="audit-task" aria-live="polite">
   <strong>{{ task.operation===auditOperation?'完整性审计':task.operation===projectionOperation?'缩略图修复':'历史标签修复' }} · {{ statuses[task.status] || task.status }}</strong>
   <code>{{ task.task_id }}</code>
   <p>已处理 {{ task.processed??'—' }} / {{ task.total??'—' }} · 成功 {{ task.succeeded??'—' }} · 失败 {{ task.failed??'—' }}</p>
   <p v-if="task.still_requires_repair!=null">提交时服务端核验 {{ task.still_requires_repair }} 张待修复 · {{ task.already_resolved??'—' }} 张已解决</p>
   <p v-for="(item,index) in task.error_examples||[]" :key="index">{{ item.error }}</p>
   <p v-if="task.operation!==auditOperation&&['PARTIAL_SUCCESS','FAILED','CANCELLED'].includes(task.status)">部分素材可能已经更新，下一次完整性审计将重新核对实际影响。</p>
   <div class="audit-actions">
    <el-button :disabled="busy" @click="readTask(task.task_id)">刷新状态</el-button>
    <el-button v-if="active" :disabled="busy||task.status==='CANCEL_REQUESTED'" @click="cancel">取消任务</el-button>
    <el-button v-if="terminal.has(task.status)&&task.status!=='SUCCEEDED'" :disabled="busy||unknown" @click="retry">重试原任务</el-button>
    <el-button v-if="task.log_available" tag="a" :href="`${batchBase}/${encodeURIComponent(task.task_id)}/log`" target="_blank" rel="noopener">任务日志</el-button>
   </div>
  </div>
  <details class="audit-records">
   <summary>审计与修复任务记录</summary>
   <p v-if="!records.length">本页没有标签审计或修复记录。</p>
   <ul><li v-for="item in records" :key="item.task_id">
    <el-button link :disabled="busy" @click="readTask(item.task_id)">{{ item.operation===auditOperation?'完整性审计':item.operation===projectionOperation?'缩略图修复':'历史标签修复' }}</el-button>
    <span>{{ statuses[item.status]||item.status }} · {{ item.created_at || item.task_id }}</span>
    <span v-if="item.mappings?.length"> · {{ item.mappings.map(mapping=>mapping.source_label+' → '+mapping.target_label).join('、') }}</span>
   </li></ul>
   <div class="audit-actions">
    <el-button v-if="historyCursor" :disabled="busy" @click="run(()=>readHistory())">返回最新</el-button>
    <el-button v-if="historyNext" :disabled="busy" @click="run(()=>readHistory(historyNext))">更早记录</el-button>
   </div>
  </details>
  <section v-if="report" aria-label="完整性审计结果">
   <p>已审计 {{ report.summary.scanned_images }} 张 · 异常素材 {{ report.summary.affected_images }} 张 · 问题记录 {{ report.summary.issue_count }} 条</p>
   <el-table :data="visibleGroups" row-key="source" empty-text="未发现需要映射的历史标签">
    <el-table-column label="历史标签" min-width="235"><template #default="{row}">
     <strong>{{row.source}}</strong>
     <div>{{row.images}} 张 · {{row.boxes}} 框 · {{row.issues.join('、')}}</div>
     <small v-if="report?.repair_defaults?.[row.source]">历史合并 {{report.repair_defaults[row.source]?.merge_chain.join(' → ')}}</small>
    </template></el-table-column>
    <el-table-column label="有效目标标签" min-width="195"><template #default="{row}">
     <el-select v-model="targetBySource[row.source]" :disabled="busy||unknown||active" :aria-label="`${row.source} 的目标标签`" clearable filterable>
      <el-option v-for="label in labels.filter(label=>label.code!==row.source)" :key="label.code" :label="`${label.display_name||label.code} · ${label.code}`" :value="label.code"/>
     </el-select>
    </template></el-table-column>
    <el-table-column label="样例" width="110"><template #default="{row}"><el-button link :disabled="samplePending" @click="loadSamples(row.source)">查看样例</el-button></template></el-table-column>
   </el-table>
   <el-pagination v-if="groups.length>30" v-model:current-page="page" :page-size="30" :total="groups.length" layout="prev,pager,next"/>
   <p v-for="group in extraGroups" :key="`${group.issue_type}:${group.label_code}`">{{ issueNames[group.issue_type]||group.issue_type }}<span v-if="group.label_code"> · {{group.label_code}}</span> · {{group.image_count}} 张 · {{group.box_count}} 框</p>
   <div class="audit-actions">
    <el-button v-if="mappings.length" :disabled="busy||unknown||active" @click="prepare('remap')">核对 {{mappings.length}} 个修复映射</el-button>
    <el-button v-if="projection" :disabled="busy||unknown||active" @click="prepare('projection')">修复历史缩略图</el-button>
    <el-button v-if="extraGroups.some(group=>group.issue_type==='DUPLICATE_ANNOTATION_CONFLICT')" tag="a" :href="legacyIntegrity">查看重复与异常素材</el-button>
   </div>
  </section>
  <el-dialog :model-value="!!confirmation" title="确认后台修复" :close-on-click-modal="false" width="min(650px,95vw)" @close="confirmation=undefined">
    <p>按审计记录估算最多 {{ confirmation?.candidates }} 张素材。服务端重新读取当前数据，按图片去重并排除已解决项。</p>
   <template v-if="confirmation?.kind==='remap'">
    <p>修复将重写仍使用历史标签的正式标注或审核范围。</p>
    <ul><li v-for="mapping in confirmation.mappings" :key="mapping.source_label">{{ mapping.source_label }} → {{ mapping.target_label }}</li></ul>
   </template>
   <p v-else>以正式标注校正缩略图和派生索引。发生并发变更时，服务端拒绝旧快照。</p>
   <template #footer><el-button :disabled="busy" @click="confirmation=undefined">取消</el-button><el-button type="primary" :loading="busy" :disabled="!confirmation" @click="confirmation&&start(confirmation.kind)">确认创建后台修复</el-button></template>
  </el-dialog>
  <el-dialog :model-value="!!sampleSource" :title="`历史样例 · ${sampleSource}`" width="min(920px,96vw)" @close="sampleSource=''">
   <p>样例供人工判断历史语义。当前同类别 ID 对应的标签只用于诊断身份错位。</p>
   <el-alert v-if="sampleError" :title="sampleError" type="error" :closable="false"/>
   <el-skeleton v-if="samplePending" :rows="4" animated/>
   <template v-if="samples">
    <p>本批 {{ samples.items.length }} 张 · 审计候选 {{ samples.candidate_count }} 张</p>
    <div class="audit-samples"><article v-for="sample in samples.items" :key="sample.image_id">
     <MaterialPreview :image="{...sample,id:sample.image_id}" :project-id="projectId" :boxes="sample.boxes"/>
     <strong>{{ sample.filename }}</strong>
     <div>历史类别 ID {{ sample.historical_class_ids.join('、') || '—' }}</div>
     <div v-for="entry in sample.current_schema_identity" :key="entry.class_id">{{ entry.class_id }} → {{ entry.label_code||'当前无对应标签' }} · {{ entry.status }}</div>
     <div v-for="(value,key) in sample.provenance" :key="key">{{ key }} · {{value}}</div>
    </article></div>
    <el-button v-if="samples.next_cursor" @click="loadSamples(sampleSource,samples.next_cursor)">下一批样例</el-button>
   </template>
  </el-dialog>
 </section>
</template>

<style scoped>
.audit-panel{background:#fff;border:1px solid #dedede;border-radius:8px;padding:20px}.audit-panel h2{font-size:17px;margin:0 0 14px}.audit-panel p,.audit-panel li{font-size:13px}.audit-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:8px 0 14px}.audit-task,.audit-records{border-top:1px solid #ddd;padding:12px 0;margin-top:12px}.audit-task code{margin-left:10px;overflow-wrap:anywhere}.audit-records summary{cursor:pointer}.audit-samples{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-bottom:14px}.audit-samples article{font-size:13px;border:1px solid #ddd;border-radius:6px;padding:8px;overflow-wrap:anywhere}
</style>
