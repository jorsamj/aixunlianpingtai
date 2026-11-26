<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,reactive,ref,watch} from 'vue';
import {useRoute} from 'vue-router';
import {cleaningApi,type CleaningAudit,type CleaningResult,type CleaningRuntime,type CleaningTask} from '../api/cleaning';
import {materialsApi,materialMediaUrl} from '../api/materials';
import {browseError} from '../api/model-browse';
import {legacyUrl} from './navigation';
import {request} from './http';
import {readWorkspaceSession,useWorkspace,workspaceActorKey} from './main';
import {useMaterialDelete} from '../composables/useMaterialDelete';
import {getMaterialBatch,type MaterialBatchTask} from '../api/material-batches';
import {cleanScopeRequest,cleanTaskView} from '../../../static/modules/cleaning.js';

const route=useRoute(), projectId=String(route.params.projectId);
const actor=useWorkspace().actorKey;
const lifetime=new AbortController(), api=cleaningApi(projectId,lifetime.signal);
const materials=materialsApi({projectId,get:request,signal:lifetime.signal,memory:{}});
const rows=ref<CleaningTask[]>([]), selected=ref(String(route.query.task_id||'')), detail=ref<CleaningResult|null>(null);
const failure=ref<MaterialBatchTask>();
const removalReceipt=ref<MaterialBatchTask>();
const task=computed(()=>rows.value.find(row=>row.id===selected.value));
const form=ref(false), error=ref(''), notice=ref(''), busy=ref(false), refreshing=ref(false), checking=ref(false);
const uncertain=ref(false), confirmationUnknown=ref('');
const createKey='clean-create:'+JSON.stringify([actor,projectId]);
const keepKey=(id:string)=>'clean-confirm:'+JSON.stringify([actor,projectId,id]);
try{uncertain.value=sessionStorage.getItem(createKey)==='pending'}catch{uncertain.value=true}
const deleteSelection=ref<string[]>([]);
const linkedDelete=ref<{planId:string;ids:string[];confirmationPending?:boolean}>();
const linkInvalid=ref(false);
const deletion=useMaterialDelete({enabled:()=>!!actor,projectId:()=>projectId,actorKey:()=>actor,onSettled:()=>{}});
const linkKey=(id:string)=>'clean-delete:'+JSON.stringify([actor,projectId,id]);
function loadLink(){
  linkedDelete.value=undefined;
  linkInvalid.value=false;
  if(!task.value)return;
  try{
    if(task.value.status==='done')sessionStorage.removeItem(keepKey(task.value.id));
    confirmationUnknown.value=sessionStorage.getItem(keepKey(task.value.id))==='pending'?task.value.id:'';
    const raw=localStorage.getItem(linkKey(task.value.id));
    if(!raw)return;
    const value=JSON.parse(raw);
    if(typeof value.planId!=='string'||!value.planId||!Array.isArray(value.ids)||!value.ids.length
      ||value.ids.some((id:unknown)=>typeof id!=='string'||!id)||new Set(value.ids).size!==value.ids.length)
      throw new Error('删除任务恢复记录不完整，请在原清洗页核对');
    linkedDelete.value=value;
  }catch(cause){linkInvalid.value=true;reportError(cause)}
}
async function verifyActor(){
  if(!actor||workspaceActorKey(await readWorkspaceSession(lifetime.signal))!==actor)
    throw new Error('清洗会话已切换，请重新打开任务');
}
const runtime=ref<CleaningRuntime|null>(null);
let timer:ReturnType<typeof setTimeout>|undefined, checkGeneration=0, resultGeneration=0, auditGeneration=0, pickerGeneration=0;
const scope=ref<'all'|'selected'|'labels'>('all'), annotation=ref('all'), labelCodes=ref<string[]>([]);
const imageIds=ref<string[]>([]), pickerQuery=ref(''), appliedQuery=ref(''), pickerPage=ref(1), pickerTotal=ref(1);
const pickerRows=ref<{id:string;filename:string}[]>([]);
const labelChoices=ref<NonNullable<CleaningRuntime['label_counts']>>({});
const filtered=ref(false);
const execution=ref<'local'|'agent'>('local'), scheduling=ref<'auto'|'node'>('auto'), node=ref(''), queue=ref<'normal'|'front'|'preempt'>('normal');
const rules=reactive({exact_duplicate:true,near_duplicate:true,low:true,high:false,blur_check:true,brightness_check:false,corrupt_check:true});
const thresholds=reactive({min_width:320,min_height:240,max_width:10000,max_height:10000,near_duplicate_hamming:5,blur_min_laplacian:45,brightness_min:15,brightness_max:245});
const ruleLabels={exact_duplicate:'重复图',near_duplicate:'近似重复',low:'分辨率过低',high:'分辨率过高',blur_check:'疑似模糊',brightness_check:'过暗 / 过亮',corrupt_check:'图片损坏'};
const thresholdLabels={min_width:'最小宽度',min_height:'最小高度',max_width:'最大宽度',max_height:'最大高度',near_duplicate_hamming:'近似重复距离',blur_min_laplacian:'模糊阈值',brightness_min:'最低亮度',brightness_max:'最高亮度'};
const legacy=legacyUrl(projectId,'自动标注及清洗','','','material-clean');
const legacyTask=computed(()=>task.value&&detail.value?.task.id===task.value.id
  ?legacyUrl(projectId,'自动标注及清洗','','','material-clean-task')+'&task_id='+encodeURIComponent(task.value.id):'');
const resultTab=ref('image'), resultFilter=ref('all'), issueFilter=ref(''), resultPage=ref(1);
const audit=ref<CleaningAudit|null>(null), auditPage=ref(1),auditLoading=ref(false);
const auditCells=computed(()=>audit.value?.heatmap?.cells||[]);
const auditMaximum=computed(()=>Math.max(1,...auditCells.value));
const active=(row:CleaningTask)=>cleanTaskView(row).active;
const reviewable=(row:CleaningTask)=>['awaiting_confirmation','done'].includes(row.status);
const retriable=(row:CleaningTask)=>cleanTaskView(row).canRetry;
const reportError=(cause:unknown)=>{if(!lifetime.signal.aborted)error.value=browseError(cause)};

function selection(){
  const result=cleanScopeRequest(scope.value,imageIds.value,{labels:labelCodes.value,annotationState:annotation.value,
    filters:scope.value==='selected'&&filtered.value?{query:appliedQuery.value}:{},selectionMode:filtered.value?'filtered':'explicit'});
  // The canonical selection_spec carries SELECTED. The v47 adapter accepts only annotation states in clean_scope.
  return {...result,clean_scope:result.clean_scope==='selected'?'all':result.clean_scope};
}
async function preflight(){
  const generation=++checkGeneration;
  runtime.value=null;
  checking.value=false;
  if(!form.value)return;
  if(scope.value==='selected'&&!filtered.value&&!imageIds.value.length)return;
  checking.value=true;
  try{
    const hasLabels=scope.value!=='labels'||labelCodes.value.length>0;
    const result=await api.preflight(hasLabels?selection():{selection_mode:'all',clean_scope:'all'});
    if(generation===checkGeneration){
      if(result.label_counts)labelChoices.value=result.label_counts;
      if(!hasLabels)return;
      runtime.value=result;
      if(!result.agent_available)execution.value='local';
      if(!result.eligible_nodes?.some(row=>row.node_id===node.value))node.value=result.eligible_nodes?.[0]?.node_id||'';
    }
  }catch(cause){if(generation===checkGeneration)reportError(cause)}
  finally{if(generation===checkGeneration)checking.value=false}
}
async function loadPicker(page=1){
  const generation=++pickerGeneration;
  try{
    const result=await materials.list({query:appliedQuery.value,label:'',annotation_state:annotation.value==='all'?'':annotation.value,
      quality_status:'',storage_source_id:'',source_batch_id:'',created_from:'',created_to:''},page,lifetime.signal);
    if(generation===pickerGeneration){
      pickerRows.value=result.items;
      pickerPage.value=result.page;
      pickerTotal.value=result.total_pages;
    }
  }catch(cause){if(generation===pickerGeneration)reportError(cause)}
}
function searchPicker(){
  filtered.value=false;
  appliedQuery.value=pickerQuery.value.trim();
  void loadPicker();
}
function toggleImage(id:string){
  filtered.value=false;
  imageIds.value=imageIds.value.includes(id)?imageIds.value.filter(value=>value!==id):[...imageIds.value,id];
}
function selectPage(){
  filtered.value=false;
  imageIds.value=[...new Set([...imageIds.value,...pickerRows.value.map(row=>row.id)])];
}
async function loadResult(row:CleaningTask,page=resultPage.value){
  const generation=++resultGeneration;
  const firstRead=detail.value?.task.id!==row.id;
  try{
    const value=await api.result(row.id,page,resultFilter.value,issueFilter.value,firstRead);
    if(generation!==resultGeneration||selected.value!==row.id)return;
    if(value.task.id!==row.id)throw new Error('清洗结果身份不一致');
    if(firstRead)deleteSelection.value=value.result.suggested_ids||[];
    resultPage.value=value.result.page;
    detail.value=value;
  }catch(cause){if(generation===resultGeneration)reportError(cause)}
}
async function loadAudit(page:number){
  if(!task.value)return;
  const id=task.value.id, generation=++auditGeneration;
  auditLoading.value=true;
  try{
    const value=await api.audit(id,page);
    if(generation===auditGeneration&&selected.value===id){audit.value=value;auditPage.value=page}
  }catch(cause){if(generation===auditGeneration)reportError(cause)}
  finally{if(generation===auditGeneration)auditLoading.value=false}
}
function selectTask(row:CleaningTask){
  ++resultGeneration;
  ++auditGeneration;
  selected.value=row.id;
  detail.value=null;
  failure.value=undefined;
  removalReceipt.value=undefined;
  deleteSelection.value=[];
  audit.value=null;
  auditLoading.value=false;
  resultTab.value='image';
  resultFilter.value='all';
  issueFilter.value='';
  resultPage.value=1;
  loadLink();
  if(reviewable(row))void loadResult(row);
}
async function readFailure(){
  const id=task.value?.id;
  if(!id)return;
  try{
    const value=await getMaterialBatch(projectId,id,lifetime.signal);
    if(value.project_id!==projectId||value.task_id!==id||value.operation!=='CLEAN')throw new Error('清洗诊断任务身份不一致');
    if(selected.value===id)failure.value=value;
  }catch(cause){reportError(cause)}
}
async function refresh(){
  if(refreshing.value)return;
  refreshing.value=true;
  clearTimeout(timer);
  try{
    rows.value=(await api.list()).items;
    const refreshKnown=task.value?.id;
    if(refreshKnown&&linkedDelete.value===undefined)loadLink();
    if(task.value&&reviewable(task.value)&&(detail.value?.task.status!==task.value.status||detail.value?.task.id!==task.value.id))await loadResult(task.value);
    if(task.value?.status==='done'&&confirmationUnknown.value===task.value.id){
      sessionStorage.removeItem(keepKey(task.value.id));confirmationUnknown.value='';
    }
  }catch(cause){reportError(cause)}
  finally{
    refreshing.value=false;
    if(!lifetime.signal.aborted&&rows.value.some(active))timer=setTimeout(()=>void refresh(),2500);
  }
}
async function submit(){
  if(busy.value||uncertain.value||!runtime.value?.selected_count)return;
  busy.value=true;
  error.value='';
  notice.value='';
  try{
    await verifyActor();
    const isAgent=execution.value==='agent';
    const assigned=isAgent&&scheduling.value==='node';
    const target=runtime.value.eligible_nodes?.find(row=>row.node_id===node.value);
    if(isAgent&&(!runtime.value.agent_available||(assigned&&!target)))
      throw Object.assign(new Error('当前无可用清洗节点，请重新核对范围'),{httpStatus:409});
    if(assigned&&queue.value==='preempt'&&target?.idle===false&&!target.preemptible)
      throw Object.assign(new Error('该节点当前任务不支持安全抢占'),{httpStatus:409});
    const {low,high,...checks}=rules;
    const scopeLabel={all:'全部图片',selected:'选定图片',labels:'选定标签'};
    sessionStorage.setItem(createKey,'pending');
    const row=await api.create({
      ...selection(),...checks,...thresholds,
      min_width:low?thresholds.min_width:0,min_height:low?thresholds.min_height:0,
      max_width:high?thresholds.max_width:999999,max_height:high?thresholds.max_height:999999,
      execution_mode:execution.value,scheduling_mode:isAgent?scheduling.value:'auto',
      target_node_id:assigned?node.value:'',queue_policy:assigned&&!(queue.value==='preempt'&&target?.idle)?queue.value:'normal',
      task_name:'自动清洗-'+scopeLabel[scope.value]+'-'+new Date().toLocaleDateString(),
    });
    if(!row.id)throw new Error('创建回执缺少任务身份');
    sessionStorage.removeItem(createKey);
    form.value=false;
    if(!rows.value.some(item=>item.id===row.id))rows.value=[row,...rows.value];
    selectTask(row);
    await refresh();
  }catch(cause){
    const status=(cause as {httpStatus?:number})?.httpStatus;
    uncertain.value=!(status&&status>=400&&status<500);
    if(!uncertain.value)sessionStorage.removeItem(createKey);
    reportError(cause);
    if(uncertain.value)await refresh();
  }finally{busy.value=false}
}
async function action(kind:'stop'|'retry'|'keep'){
  const row=task.value;
  if(busy.value||!row)return;
  if(kind==='keep'&&(row.status!=='awaiting_confirmation'||detail.value?.task.id!==row.id||confirmationUnknown.value===row.id
    ||linkedDelete.value||deletion.state.dialog))return;
  if(kind==='keep'&&!window.confirm('确认保留本次全部素材，并将有效清洗范围标记为已处理？'))return;
  if(kind==='stop'&&!window.confirm('确认停止当前清洗任务？'))return;
  busy.value=true;
  error.value='';
  notice.value='';
  try{
    await verifyActor();
    if(kind==='stop')await api.stop(row.id);
    if(kind==='retry'){
      const result=await api.retry(row.id);
      selected.value=result.task_id||row.id;
    }
    if(kind==='keep'){
      sessionStorage.setItem(keepKey(row.id),'pending');
      const result=await api.confirm(row.id,[]);
      if(!result.ok||!Array.isArray(result.processed_ids))throw new Error('清洗确认回执无效');
      confirmationUnknown.value=row.id;
      notice.value='已确认清洗，'+result.processed_ids.length+' 张素材进入已处理。';
    }
  }catch(cause){
    const status=(cause as {httpStatus?:number})?.httpStatus;
    if(kind==='keep'){
      if(status&&status>=400&&status<500)sessionStorage.removeItem(keepKey(row.id));
      else confirmationUnknown.value=row.id;
    }
    reportError(cause);
  }finally{await refresh();busy.value=false}
}
async function prepareDeletion(){
  if(busy.value||linkInvalid.value||!deleteSelection.value.length||linkedDelete.value||task.value?.status!=='awaiting_confirmation')return;
  await deletion.prepareMany(deleteSelection.value);
}
async function submitDeletion(){
  const row=task.value,preview=deletion.state.estimate?.deletion_preview;
  if(!row||row.status!=='awaiting_confirmation'||!preview||busy.value||linkedDelete.value)return;
  busy.value=true;error.value='';
  try{
    await verifyActor();
    const link={planId:preview.plan_id,ids:[...deletion.state.targetIds]};
    const validation=await api.confirm(row.id,link.ids,link.planId,true);
    if(!validation.ok||validation.deletion_plan_id!==link.planId)throw new Error('清洗与删除预检身份不一致');
    localStorage.setItem(linkKey(row.id),JSON.stringify(link));
    linkedDelete.value=link;
    await deletion.confirm();
    if(!deletion.state.task&&!deletion.state.pendingPlanId&&!deletion.state.unknown){
      localStorage.removeItem(linkKey(row.id));linkedDelete.value=undefined;
    }
  }catch(cause){reportError(cause)}
  finally{busy.value=false}
}
async function acknowledgeRemaining(){
  const row=task.value,link=linkedDelete.value;
  if(busy.value||!row||!link||link.confirmationPending||row.status!=='awaiting_confirmation')return;
  busy.value=true;error.value='';
  try{
    await verifyActor();
    await readRemovalReceipt(link);
    const pending={...link,confirmationPending:true};
    localStorage.setItem(linkKey(row.id),JSON.stringify(pending));linkedDelete.value=pending;
    const result=await api.confirm(row.id,link.ids,link.planId);
    if(!result.ok||result.deletion_plan_id!==link.planId||!Array.isArray(result.processed_ids))throw new Error('清洗确认回执无效');
    notice.value='已确认其余 '+result.processed_ids.length+' 张。已排除 '+link.ids.length+' 张，按原删除任务回执核算。';
  }catch(cause){
    const status=(cause as {httpStatus?:number})?.httpStatus;
    if(status&&status>=400&&status<500&&linkedDelete.value?.confirmationPending){
      localStorage.setItem(linkKey(row.id),JSON.stringify(link));linkedDelete.value=link;
    }
    reportError(cause);
  }finally{await refresh();busy.value=false}
}
async function readRemovalReceipt(link=linkedDelete.value){
  if(!link)return;
  const receipt=await getMaterialBatch(projectId,link.planId,lifetime.signal);
  if(receipt.task_id!==link.planId||receipt.project_id!==projectId||receipt.operation!=='DELETE_INDEX'||receipt.total!==link.ids.length)
    throw Object.assign(new Error('删除任务身份或冻结数量不一致，请核验原计划'),{httpStatus:409});
  if(linkedDelete.value?.planId===link.planId)removalReceipt.value=receipt;
}
function resolveCreate(){
  if(!window.confirm('请先核对清洗任务列表。确认后才能开始创建另一项任务。'))return;
  try{sessionStorage.removeItem(createKey);uncertain.value=false}
  catch(cause){reportError(cause)}
}
watch([form,scope,annotation,labelCodes,imageIds,filtered],()=>void preflight());
watch([scope,annotation],()=>{if(scope.value==='selected')void loadPicker()});
watch([resultFilter,issueFilter],()=>{if(task.value&&detail.value?.task.id===task.value.id)void loadResult(task.value,1)});
watch(resultTab,value=>{if(value==='annotation'&&!audit.value)void loadAudit(1)});
onMounted(()=>{void refresh();void deletion.recover()});
onBeforeUnmount(()=>{lifetime.abort();clearTimeout(timer)});
</script>

<template>
  <main class="cleaning">
    <header class="cleaning-head"><h2>自动清洗</h2><div>
      <el-button @click="refresh" :loading="refreshing">刷新任务</el-button>
      <el-button type="primary" @click="form=true">创建自动清洗任务</el-button>
      <el-button tag="a" :href="legacy">原清洗创建</el-button>
    </div></header>
    <el-alert v-if="error" :title="error" type="error" @close="error=''" />
    <el-alert v-if="notice" :title="notice" type="success" @close="notice=''" />
    <el-alert v-if="uncertain" title="上次创建结果待确认。请刷新并核对已有任务。" type="warning" :closable="false">
      <el-button :disabled="refreshing" @click="resolveCreate">已核对任务列表</el-button>
    </el-alert>
    <el-table :data="rows" empty-text="暂无清洗任务">
      <el-table-column prop="name" label="任务" />
      <el-table-column label="状态"><template #default="{row}">{{row.status_text||row.status}}</template></el-table-column>
      <el-table-column label="进度"><template #default="{row}">{{row.processed_images}} / {{row.total_images}}</template></el-table-column>
      <el-table-column prop="flagged_images" label="需复核" />
      <el-table-column prop="created_at" label="创建时间" />
      <el-table-column label="操作"><template #default="{row}"><el-button text :disabled="busy || deletion.state.dialog" @click="selectTask(row)">详情</el-button></template></el-table-column>
    </el-table>
    <section v-if="task" class="cleaning-section">
      <h3>{{task.name}}</h3>
      <p>{{task.status_text||task.status}} · {{task.processed_images}} / {{task.total_images}} <span v-if="task.stage">· {{task.stage}}</span></p>
      <p v-if="task.resource_wait_reason||task.current_item||task.worker_id">{{task.resource_wait_reason}} {{task.current_item}} {{task.worker_id}}</p>
      <p v-if="cleanTaskView(task).runtimeText">{{cleanTaskView(task).runtimeText}}</p>
      <el-progress :percentage="Math.min(100,Math.max(0,task.progress||0))" />
      <el-button v-if="active(task)&&task.status_text!=='正在停止'" :disabled="busy" @click="action('stop')">停止</el-button>
      <el-button v-if="retriable(task)" :disabled="busy" @click="action('retry')">重试失败项</el-button>
      <el-button v-if="retriable(task)" :disabled="busy" @click="readFailure">查看失败详情</el-button>
      <section v-if="failure?.task_id===task.id">
        <ul v-if="failure.error_examples?.length"><li v-for="(item,index) in failure.error_examples" :key="index">{{item.error}}</li></ul>
        <el-button v-if="failure.log_available" tag="a" :href="'/api/v62/projects/'+encodeURIComponent(projectId)+'/material-batches/'+encodeURIComponent(task.id)+'/log'" target="_blank" rel="noopener">任务日志</el-button>
      </section>
      <template v-if="detail?.task.id===task.id">
        <el-tabs v-model="resultTab">
          <el-tab-pane label="图片质量" name="image">
            <p>扫描 {{detail.result.scanned}} 张 · 建议剔除 {{detail.result.suggested}} 张 · 扫描失败 {{detail.result.failed}} 张</p>
            <div class="cleaning-controls">
              <el-select v-model="resultFilter" aria-label="复核范围"><el-option label="全部复核项" value="all"/><el-option label="建议剔除" value="suggested"/><el-option label="扫描失败" value="failed"/></el-select>
              <el-select v-model="issueFilter" aria-label="问题类型"><el-option label="全部问题" value=""/><el-option v-for="[key,label] in detail.result.issue_options" :key="key" :label="label" :value="key"/></el-select>
            </div>
            <el-table :data="detail.result.items" empty-text="暂无需复核图片">
              <el-table-column v-if="task.status==='awaiting_confirmation'" label="选为剔除" width="95">
                <template #default="{row}"><el-checkbox
                  :model-value="deleteSelection.includes(row.image_id)" :disabled="busy || !!linkedDelete || linkInvalid"
                  :aria-label="'选择 '+(row.name||row.filename||row.image_id)"
                  @change="(value:unknown)=>{deleteSelection=value===true?[...new Set([...deleteSelection,row.image_id])]:deleteSelection.filter(id=>id!==row.image_id)}" /></template>
              </el-table-column>
              <el-table-column label="图片"><template #default="{row}"><a v-if="materialMediaUrl(row.url,projectId,row.image_id,'content')" :href="materialMediaUrl(row.url,projectId,row.image_id,'content')" target="_blank" rel="noopener">{{row.name||row.filename||row.image_id}}</a><span v-else>{{row.name||row.filename||row.image_id}}</span></template></el-table-column>
              <el-table-column label="问题"><template #default="{row}">{{row.issues?.map((issue: {name?:string;code?:string})=>issue.name||issue.code).join('、')||row.item_error}}</template></el-table-column>
              <el-table-column label="建议剔除"><template #default="{row}">{{row.suggest_delete?'是':'否'}}</template></el-table-column>
            </el-table>
            <el-pagination v-if="detail.result.total>detail.result.page_size" :current-page="resultPage" :page-size="detail.result.page_size" :total="detail.result.total" layout="prev, pager, next"
              @current-change="(page:number)=>task&&loadResult(task,page)" />
          </el-tab-pane>
          <el-tab-pane label="标注质量" name="annotation">
            <template v-if="audit?.enabled">
              <p>正式已标注 {{audit.audited_images||0}} 张 · 需复核 {{audit.review_images||0}} 张 · 警告 {{audit.warning_count||0}} 条</p>
              <div class="cleaning-options">
                <div v-if="Object.keys(audit.issue_counts||{}).length"><h4>问题分布</h4><p v-for="(count,key) in audit.issue_counts" :key="key">{{key}} · {{count}}</p></div>
                <div v-if="Object.keys(audit.provenance_counts||{}).length"><h4>标注来源</h4><p v-for="(count,key) in audit.provenance_counts" :key="key">{{key}} · {{count}}</p></div>
                <div v-if="audit.class_balance?.length"><h4>类别分布</h4><p v-for="entry in audit.class_balance" :key="entry.label">{{entry.label}} · {{entry.count||0}}</p></div>
                <div v-if="auditCells.length"><h4>框中心分布</h4><div class="cleaning-heatmap"><span v-for="(count,index) in auditCells" :key="index" :title="'格 '+(index+1)+' · '+count+' 个框'" :style="{background:'rgba(0,0,0,'+(count/auditMaximum/3)+')'}">{{count}}</span></div></div>
              </div>
              <el-table :data="auditPage===1?(audit.items||[]).slice(0,20):audit.items||[]" empty-text="暂无标注质量警告">
                <el-table-column prop="image_id" label="图片" />
                <el-table-column label="问题"><template #default="{row}">{{row.issues?.map((issue: {name?:string;code?:string})=>issue.name||issue.code).join('、')}}</template></el-table-column>
              </el-table>
              <el-pagination v-if="(audit.review_images||0)>20" :current-page="auditPage" :page-size="20" :total="audit.review_images||0" layout="prev, pager, next" @current-change="loadAudit" />
            </template>
            <p v-else-if="auditLoading" role="status">正在读取标注审计。</p>
            <p v-else-if="audit">本次结果没有标注质量审计。</p>
            <el-button v-else @click="loadAudit(1)">读取标注审计</el-button>
          </el-tab-pane>
        </el-tabs>
        <template v-if="task.status==='awaiting_confirmation'">
          <el-button :disabled="busy || !!linkedDelete || linkInvalid || confirmationUnknown===task.id" @click="action('keep')">保留全部并确认</el-button>
          <el-button type="danger" plain :disabled="busy || !!linkedDelete || linkInvalid || !deleteSelection.length || confirmationUnknown===task.id"
            @click="prepareDeletion">预检删除已选 {{deleteSelection.length}} 张</el-button>
          <span v-if="deletion.state.error" role="alert">{{deletion.state.error}}</span>
        </template>
        <template v-if="linkedDelete">
          <p>删除任务 {{linkedDelete.planId}} · {{deletion.state.task?.task_id===linkedDelete.planId ? deletion.statusLabel.value : '待核对'}}</p>
          <p v-if="deletion.state.task?.task_id===linkedDelete.planId">{{deletion.state.notice}}</p>
          <p v-if="removalReceipt?.task_id===linkedDelete.planId" role="status">
            删除状态 {{removalReceipt.status}} · 已删除 {{removalReceipt.logical_removed ?? '待核对'}} · 失败 {{removalReceipt.failed ?? '待核对'}}
          </p>
          <el-button :disabled="busy" @click="readRemovalReceipt().catch(reportError)">核验删除回执</el-button>
          <el-button v-if="deletion.state.pendingPlanId===linkedDelete.planId" :disabled="busy" @click="deletion.openTask()">查看删除任务</el-button>
          <el-button v-if="task.status==='awaiting_confirmation'" :disabled="busy || linkedDelete.confirmationPending"
            @click="acknowledgeRemaining">核对删除任务并确认其余素材</el-button>
          <p v-if="linkedDelete.confirmationPending && task.status!=='done'">确认结果待核对，请刷新任务。</p>
        </template>
        <el-button v-if="legacyTask" tag="a" :href="legacyTask">原清洗任务</el-button>
        <p v-if="confirmationUnknown===task.id">确认结果待核对，请刷新任务。</p>
      </template>
    </section>

    <el-dialog :model-value="deletion.state.dialog" title="清洗素材删除" width="min(560px, 94vw)"
      :close-on-click-modal="false" :show-close="!busy && !deletion.state.busy" @close="deletion.close()">
      <template v-if="deletion.state.estimate?.deletion_preview">
        <p>本次拟删除 {{deletion.state.estimate.count}} 张素材的索引，保留原图字节。</p>
        <p>正式 GT {{deletion.state.estimate.deletion_preview.gt_count ?? '未核验'}} 张 ·
          历史引用 {{deletion.state.estimate.deletion_preview.historical_reference_count ?? '未核验'}} 张 ·
          活动引用 {{deletion.state.estimate.deletion_preview.active_reference_count ?? '未核验'}} 张 ·
          当前 Test {{deletion.state.estimate.deletion_preview.current_test_count ?? '未核验'}} 张</p>
      </template>
      <p v-if="deletion.state.task">删除任务 {{deletion.state.task.task_id}} · {{deletion.statusLabel.value}}</p>
      <p v-if="deletion.state.notice" role="status">{{deletion.state.notice}}</p>
      <p v-if="deletion.state.error" role="alert">{{deletion.state.error}}</p>
      <template #footer>
        <el-button :disabled="busy || deletion.state.busy" @click="deletion.close()">关闭</el-button>
        <el-button v-if="deletion.terminal.value && deletion.state.unknown" :loading="deletion.state.busy" @click="deletion.verifyResults()">核对逐图结果</el-button>
        <el-button v-if="deletion.state.estimate && !deletion.state.pendingPlanId && !deletion.state.task && !linkedDelete"
          type="danger" :loading="busy || deletion.state.busy" @click="submitDeletion">确认删除</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="form" title="创建自动清洗任务" width="min(850px, 95vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy">
      <p>先确认扫描范围。图片删除需要单独确认。</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <fieldset :disabled="busy">
        <legend>主要范围</legend>
        <el-radio-group v-model="scope"><el-radio value="all">全部图片</el-radio><el-radio value="selected">选定图片</el-radio><el-radio value="labels">选定标签</el-radio></el-radio-group>
        <div v-if="scope==='selected'">
          <div class="cleaning-controls"><el-input v-model="pickerQuery" aria-label="图片名称" placeholder="搜索图片名称" @keyup.enter="searchPicker" /><el-button @click="searchPicker">查询</el-button></div>
          <el-button @click="selectPage">全选当前页</el-button><el-button @click="filtered=true">全选当前筛选结果</el-button><el-button @click="imageIds=[];filtered=false">取消选择</el-button>
          <p>{{filtered?'按当前筛选结果冻结范围':'跨页已选 '+imageIds.length+' 张'}}</p>
          <div class="cleaning-options"><el-checkbox v-for="row in pickerRows" :key="row.id" :model-value="!filtered&&imageIds.includes(row.id)" @change="toggleImage(row.id)">{{row.filename||row.id}}</el-checkbox></div>
          <el-pagination :current-page="pickerPage" :page-count="pickerTotal" layout="prev, pager, next" @current-change="loadPicker" />
        </div>
        <el-select v-if="scope==='labels'" v-model="labelCodes" multiple aria-label="标签" placeholder="选择标签，任一命中">
          <el-option v-for="(count,code) in runtime?.label_counts||labelChoices" :key="code" :label="code+' · '+count.images+' 张'" :value="code"/>
        </el-select>
        <div class="cleaning-controls"><label for="clean-annotation-state">标注状态</label><el-select id="clean-annotation-state" v-model="annotation">
          <el-option label="全部状态" value="all"/><el-option label="已标注" value="annotated"/><el-option label="未标注" value="unannotated"/><el-option label="已确认无目标" value="confirmed_empty"/>
        </el-select><strong v-if="runtime">最终匹配 {{runtime.selected_count}} 张</strong><span v-else-if="checking">正在核对范围</span></div>
      </fieldset>
      <fieldset :disabled="busy">
        <legend>执行位置</legend>
        <el-radio-group v-model="execution"><el-radio value="local">中央 Worker</el-radio><el-radio value="agent" :disabled="!runtime?.agent_available">远程清洗节点</el-radio></el-radio-group>
        <p v-if="runtime&&!runtime.agent_available&&runtime.reason">{{runtime.reason}}</p>
        <div v-if="execution==='agent'" class="cleaning-controls">
          <el-select v-model="scheduling" aria-label="调度方式"><el-option label="自动调度" value="auto"/><el-option label="指定节点" value="node"/></el-select>
          <el-select v-if="scheduling==='node'" v-model="node" aria-label="指定节点"><el-option v-for="entry in runtime?.eligible_nodes||[]" :key="entry.node_id" :value="entry.node_id" :label="entry.display_name||entry.name||entry.node_id"/></el-select>
          <el-select v-if="scheduling==='node'" v-model="queue" aria-label="队列策略"><el-option label="正常排队" value="normal"/><el-option label="队首" value="front"/><el-option label="抢占" value="preempt"/></el-select>
        </div>
      </fieldset>
      <fieldset :disabled="busy">
        <legend>清洗规则</legend>
        <el-checkbox v-for="(label,key) in ruleLabels" :key="key" v-model="rules[key]">{{label}}</el-checkbox>
        <details><summary>高级阈值</summary><div class="cleaning-options"><label v-for="(label,key) in thresholdLabels" :key="key">{{label}} <el-input-number v-model="thresholds[key]" /></label></div></details>
      </fieldset>
      <template #footer><el-button :disabled="busy" @click="form=false">取消</el-button><el-button type="primary" :disabled="checking||!runtime?.selected_count||uncertain" :loading="busy" @click="submit">开始清洗</el-button></template>
    </el-dialog>
  </main>
</template>

<style scoped>
.cleaning{display:grid;gap:16px}.cleaning-head,.cleaning-controls{display:flex;align-items:center;flex-wrap:wrap;gap:12px}.cleaning-head{justify-content:space-between}.cleaning-controls>*{max-width:260px}.cleaning-section{border:1px solid #ddd;border-radius:8px;padding:16px}.cleaning-section .el-progress{margin:12px 0}.cleaning-options{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:4px 14px}.cleaning fieldset{border:1px solid #ddd;border-radius:6px;padding:10px 14px;margin:10px 0;min-width:0}.cleaning-heatmap{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:3px;max-width:250px;text-align:center}.cleaning-heatmap span{padding:4px}
</style>
