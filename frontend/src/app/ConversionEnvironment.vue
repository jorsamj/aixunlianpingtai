<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,shallowRef} from 'vue';
import {loadConversionResources,newConversionRequestId} from '../api/conversion-jobs';
import {detectLocalResources,readResourceCheck,saveResourceConfiguration,startResourceCheck} from '../api/conversion-environment';
import type {ResourceConfiguration} from '../api/conversion-environment';
import {useReadScope} from '../composables/useReadScope';
import type {CatalogOperation,PendingSlot,PreviewContext} from '../types/catalog';
import type {DeployResource} from '../types/conversion-job';
import ConversionResourceEditor from '../components/ConversionResourceEditor.vue';
import CatalogPreview from '../views/CatalogPreview.vue';
import {request} from './http';
import {legacyUrl} from './navigation';
import '../styles/theme.css';

const props=defineProps<{projectId:string}>();
const controller=new AbortController();
const reads=useReadScope(controller);
onBeforeUnmount(()=>controller.abort());
const legacyHref=computed(()=>legacyUrl(props.projectId,'部署资源'));
const tab=ref('resources');
const catalogOpened=ref(false);
const resources=shallowRef<DeployResource[]>([]);
const editing=ref(false);
const selected=shallowRef<DeployResource|null>(null);
const saving=ref(false);
const checking=ref('');
const notice=ref('');
const actionError=ref('');
const kinds:Record<string,string>={sophon:'算能 TPU-MLIR',ascend:'华为 CANN / ATC',rockchip:'瑞芯微 RKNN-Toolkit2',
  tensorrt:'NVIDIA TensorRT',ultralytics:'Ultralytics 导出',paddle:'PaddleDetection 导出'};
const modes:Record<string,string>={local:'本机',remote:'远程转换服务器',agent:'服务节点 Agent'};
const detectionStates:Record<string,string>={not_checked:'待检测',checking:'检测中',available:'检测通过',
  unavailable:'检测未通过',expired:'检测已过期',failed:'检测失败'};
const reasons:Record<string,string>={resource_configuration_changed:'资源配置已变更',local_environment_changed:'本机环境已变更',
  interrupted_detection:'上次检测已中断',review_due:'检测证据已过期'};
const detectionLabel=(row:DeployResource)=>detectionStates[row.detection?.state||'']||'待核验';
const runnable=(row:DeployResource)=>row.detection?.state==='available'&&row.status==='ready';
const locked=computed(()=>reads.busy.resources||saving.value||!!checking.value);
const failureText=(error:unknown)=>error instanceof Error?error.message:'请求失败';
const filterKind=ref(''),filterState=ref('');
const kindsPresent=computed(()=>[...new Set(resources.value.map(row=>row.kind||'').filter(Boolean))]);
const visibleResources=computed(()=>resources.value.filter(row=>
  (!filterKind.value||row.kind===filterKind.value)&&
  (!filterState.value||(filterState.value==='available'?runnable(row):(row.detection?.state||'not_checked')===filterState.value))));
const summary=computed(()=>{
  const list=resources.value;
  return {
    total:list.length,
    available:list.filter(row=>runnable(row)).length,
    failed:list.filter(row=>['unavailable','failed'].includes(row.detection?.state||'')).length,
    pending:list.filter(row=>['not_checked','checking','expired'].includes(row.detection?.state||'')).length,
  };
});

// Share the existing catalog handoff record because catalog revisions are global.
const pendingKey='cl_vue_catalog_pending_v1';
function readCatalogPending():CatalogOperation|null{
  try{
    const value=JSON.parse(sessionStorage.getItem(pendingKey)||'null');
    return value&&typeof value.operation_id==='string'&&['vendors','chips'].includes(value.entity)?value:null;
  }catch{return null}
}
const pending:PendingSlot={value:readCatalogPending(),save(value){
  this.value=value;
  try{if(value)sessionStorage.setItem(pendingKey,JSON.stringify(value));else sessionStorage.removeItem(pendingKey)}catch{/* The existing catalog session store is optional. */}
}};
const catalogContext:PreviewContext={
  signal:controller.signal,management:true,pending,createOperationId:newConversionRequestId,
  get:<T,>(url:string,options?:{signal?:AbortSignal})=>request<T>(url,options),
  post:<T,>(url:string,body:unknown)=>request<T>(url,{method:'POST',body:JSON.stringify(body),signal:controller.signal}),
  returnToManagement:()=>window.location.assign(legacyHref.value),
};

function load(){return reads.run('resources',loadConversionResources,value=>{resources.value=value})}
onMounted(load);
function switchTab(value:string|number){
  if(value==='catalog')catalogOpened.value=true;
  if(value==='resources')void load();
}
function startEditing(row:DeployResource|null){
  if(locked.value||reads.errors.resources||row?.builtin)return;
  actionError.value='';notice.value='';selected.value=row;editing.value=true;
}
function closeEditor(){
  if(saving.value)return;
  editing.value=false;selected.value=null;actionError.value='';
}
async function save(configuration:ResourceConfiguration){
  if(saving.value||!editing.value)return;
  const id=selected.value?.id||'';
  saving.value=true;actionError.value='';notice.value='';
  try{
    await saveResourceConfiguration(id,configuration,controller.signal);
    if(controller.signal.aborted)return;
    editing.value=false;selected.value=null;notice.value='资源已保存，可以读取状态或执行检测。';
    await load();
  }catch(error){
    if(controller.signal.aborted)return;
    const status=(error as {httpStatus?:number})?.httpStatus;
    if(status&&status>=400&&status<500){actionError.value=failureText(error);return}
    editing.value=false;selected.value=null;
    actionError.value=`未收到有效保存回执，请先核对已重新读取的资源列表再修改。${failureText(error)}`;
    await load();
  }finally{saving.value=false}
}
async function check(row:DeployResource,observeOnly:boolean){
  if(locked.value||editing.value)return;
  checking.value=row.id;actionError.value='';notice.value='';
  try{
    const result=await (observeOnly?readResourceCheck(row.id,controller.signal):startResourceCheck(row,controller.signal));
    if(controller.signal.aborted)return;
    resources.value=resources.value.map(item=>item.id===result.id?result:item);
    notice.value=`${row.name||row.id}：${detectionLabel(result)}${result.detection?.state==='checking'?'，稍后可读取检测结果。':'。'}`;
  }catch(error){
    if(!controller.signal.aborted)actionError.value=`${failureText(error)}${observeOnly?'':'。启动结果未确认，可先读取检测结果。'}`;
  }finally{checking.value=''}
}
async function detectLocal(){
  if(locked.value||editing.value)return;
  checking.value='local-batch';actionError.value='';notice.value='';
  try{
    const found=await detectLocalResources(controller.signal);
    notice.value=found.length?`本机检测通过 ${found.length} 项。`:'本次未核验到可用的本机工具。';
    await load();
  }catch(error){
    if(!controller.signal.aborted)actionError.value=`本机检测结果待核对。 ${failureText(error)}`;
  }finally{checking.value=''}
}
</script>

<template>
 <section aria-label="模型转换环境">
  <el-tabs v-model="tab" @tab-change="switchTab">
   <el-tab-pane name="resources" label="转换资源">
    <div class="page-toolbar"><p>转换资源</p><div class="environment-actions">
     <el-button :loading="reads.busy.resources" :disabled="saving||!!checking" @click="load">刷新状态</el-button>
     <el-button :loading="checking==='local-batch'" :disabled="locked||editing" @click="detectLocal">检测本机工具</el-button>
     <el-button type="primary" :disabled="locked||!!reads.errors.resources" @click="startEditing(null)">新增部署资源</el-button>
     <el-button tag="a" :href="legacyHref">原转换环境管理</el-button>
    </div></div>
    <p class="environment-note">资源列表显示现有配置和最近一次 SDK 检测。模型数值验证和硬件验证以具体转换记录为准。</p>
    <p class="environment-note">证据层级：SDK 检测通过 → 转换任务成功 → 张量与检测结果一致 → 硬件运行验证 → 具备交付资格，各阶段独立，前一级通过不代表后一级成立。</p>
    <el-alert v-if="reads.errors.resources" :title="reads.errors.resources" type="error" :closable="false"/>
    <el-alert v-if="actionError&&!editing" :title="actionError" type="error" :closable="false"/>
    <el-alert v-if="notice" :title="notice" type="info" :closable="false"/>
    <dl v-if="resources.length" class="environment-summary" aria-label="转换资源概览">
     <div><dt>资源</dt><dd>{{ summary.total }}</dd></div>
     <div><dt>检测通过</dt><dd>{{ summary.available }}</dd></div>
     <div><dt>检测未通过</dt><dd :class="{warn:summary.failed>0}">{{ summary.failed }}</dd></div>
     <div><dt>待检测 / 过期</dt><dd>{{ summary.pending }}</dd></div>
    </dl>
    <div v-if="resources.length" class="environment-filters">
     <el-select v-model="filterKind" aria-label="按厂商工具链筛选" placeholder="全部厂商工具链" clearable>
      <el-option label="全部厂商工具链" value=""/><el-option v-for="kind in kindsPresent" :key="kind" :label="kinds[kind]||kind" :value="kind"/>
     </el-select>
     <el-select v-model="filterState" aria-label="按检测状态筛选" placeholder="全部检测状态" clearable>
      <el-option label="全部检测状态" value=""/><el-option label="检测通过" value="available"/><el-option label="检测未通过" value="unavailable"/><el-option label="检测失败" value="failed"/><el-option label="待检测" value="not_checked"/><el-option label="检测已过期" value="expired"/>
     </el-select>
     <span>{{ visibleResources.length }} / {{ resources.length }} 项</span>
    </div>
    <el-skeleton v-if="reads.busy.resources&&!resources.length" :rows="6" animated/>
    <el-empty v-else-if="!resources.length&&!reads.errors.resources" description="暂无转换资源"/>
    <el-empty v-else-if="!visibleResources.length" description="当前筛选没有匹配的转换资源"/>
    <div v-else class="environment-grid">
     <article v-for="row in visibleResources" :key="row.id" class="environment-resource">
      <header><div><h2>{{ row.name||row.id }}</h2><p>{{ kinds[row.kind||'']||row.kind||'未知资源类型' }} · {{ modes[row.mode||'']||row.mode||'运行位置未记录' }}</p></div>
       <el-tag :type="runnable(row)?'success':row.detection?.state==='failed'?'danger':'info'" effect="plain">{{ detectionLabel(row) }}</el-tag></header>
      <h3>环境与工具链</h3>
      <dl>
       <dt>资源配置</dt><dd>{{ row.builtin?'内置':'已登记' }}</dd>
       <dt>SDK 安装证据</dt><dd>{{ row.version?`已上报版本 ${row.version}`:'未上报版本' }}</dd>
       <dt>工具上报目标</dt><dd>{{ row.targets?.join(' / ')||'未上报' }}</dd>
       <dt>工具上报芯片</dt><dd>{{ row.supported_chips?.join(' / ')||'未上报' }}</dd>
       <dt>工具上报精度</dt><dd>{{ row.supported_precisions?.join(' / ')||'未上报' }}</dd>
       <template v-if="row.agent_nodes?.length"><dt>服务节点 Agent</dt><dd>{{ row.agent_nodes.map(node=>node.display_name||node.node_id).filter(Boolean).join(' / ') }}</dd></template>
      </dl>
      <h3>检测证据</h3>
      <dl>
       <dt>实际可运行</dt><dd>{{ runnable(row)?'当前检测通过':'当前未证实' }}</dd>
       <dt>最近检测</dt><dd>{{ row.detection?.checked_at||row.last_checked_at||'未记录' }}</dd>
      </dl>
      <p v-if="row.detection?.reason">{{ reasons[row.detection.reason]||row.detection.reason }}</p>
      <p v-if="row.message">{{ row.message }}</p>
      <p v-if="row.detection?.error" role="status">{{ row.detection.error }}</p>
      <p v-if="row.solution">{{ row.solution }}</p>
      <footer class="environment-actions">
       <el-button v-if="!row.builtin" :disabled="locked||!!reads.errors.resources" @click="startEditing(row)">编辑</el-button>
       <el-button :disabled="locked||!!reads.errors.resources||row.detection?.state==='checking'" @click="check(row,false)">检测</el-button>
       <el-button :loading="checking===row.id" :disabled="locked" @click="check(row,true)">读取检测结果</el-button>
      </footer>
     </article>
    </div>
    <details class="environment-help"><summary>远程工具链接入说明</summary>
     <p>瑞芯微 RKNN-Toolkit2、算能 TPU-MLIR、华为 CANN / ATC 按厂商工具链执行。Windows 主机可执行 ONNX 导出。RKNN 可使用 Linux/WSL2、远程转换服务器或已安装相应工具的服务节点 Agent。</p>
     <p>删除资源入口保留在原转换环境管理。</p>
    </details>
   </el-tab-pane>
   <el-tab-pane name="catalog" label="厂商与芯片字典">
    <CatalogPreview v-if="catalogOpened" :context="catalogContext"/>
   </el-tab-pane>
  </el-tabs>
  <ConversionResourceEditor v-if="editing" :resource="selected" :kinds="kinds" :busy="saving" :error="actionError" @close="closeEditor" @save="save"/>
 </section>
</template>

<style scoped>
.environment-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:16px;margin:16px 0}
.environment-resource{min-width:0;padding:16px;border:1px solid var(--el-border-color);border-radius:8px;overflow-wrap:anywhere}
.environment-resource header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.environment-resource h2{font-size:1rem;margin:0}.environment-resource p{margin:8px 0}
.environment-resource dl{display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px 12px;margin:12px 0}
.environment-resource dd{margin:0}.environment-resource dt,.environment-note{color:var(--el-text-color-secondary)}
.environment-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.environment-actions :deep(.el-button + .el-button){margin-left:0}
.environment-help{margin:16px 0}.environment-help summary{cursor:pointer}
.environment-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:12px 0}
.environment-summary>div{padding:10px 12px;background:var(--el-bg-color);border:1px solid var(--el-border-color);border-radius:8px}
.environment-summary dt{font-size:12px;color:var(--el-text-color-secondary)}
.environment-summary dd{margin:4px 0 0;font-size:20px;font-weight:650;font-variant-numeric:tabular-nums}
.environment-summary dd.warn{color:var(--el-color-warning)}
.environment-filters{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:0 0 4px;font-size:12px;color:var(--el-text-color-secondary)}
.environment-filters .el-select{width:180px}
.environment-resource h3{margin:12px 0 4px;font-size:13px;color:var(--el-text-color-secondary);font-weight:600}
</style>
