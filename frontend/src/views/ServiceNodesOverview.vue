<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref} from 'vue';
import type {PreviewContext} from '../types/catalog';
import type {ServiceNode,ServiceNodeList} from '../types/service-nodes';
import PageHeader from '../components/PageHeader.vue';
import ServiceNodeCard from '../components/ServiceNodeCard.vue';
const props=defineProps<{context:PreviewContext}>();
const nodes=ref<ServiceNode[]>([]),query=ref(''),status=ref(''),capability=ref(''),error=ref(''),busy=ref(false),loaded=ref(false),updated=ref('');
let controller:AbortController|undefined,alive=true;
const capabilities=computed(()=>[...new Set(nodes.value.flatMap(node=>[...(node.allowed_capabilities||[]),...(node.reported_capabilities||[]),...(node.effective_capabilities||[])]))].sort());
const filtered=computed(()=>nodes.value.filter(node=>(!query.value||`${node.node_id} ${node.display_name||''}`.toLocaleLowerCase().includes(query.value.toLocaleLowerCase()))&&(!status.value||node.status===status.value)&&(!capability.value||[...(node.allowed_capabilities||[]),...(node.reported_capabilities||[]),...(node.effective_capabilities||[])].includes(capability.value))));
// Aggregates are derived from the same bounded snapshot; no extra request and no
// schedulability claim beyond the reported evidence.
const summary=computed(()=>{
 const list=nodes.value;
 const stale=list.filter(node=>node.status==='ONLINE'&&typeof node.heartbeat_age_seconds==='number'&&node.heartbeat_age_seconds>=300).length;
 // Two task sources are reported separately: a cross-source global identity and
 // late-report ownership are not proven, so they are never summed into one total.
 const centralTasks=list.reduce((sum,node)=>sum+(node.durable_tasks||[]).length,0);
 const reportedTasks=list.reduce((sum,node)=>sum+(node.reported_active_tasks||[]).length,0);
 return {
  total:list.length,
  online:list.filter(node=>node.status==='ONLINE').length,
  stale,
  gpu:list.reduce((sum,node)=>sum+(node.resources?.gpu?.gpus?.length||0),0),
  cuda:list.filter(node=>node.runtime?.cuda_available===true).length,
  centralTasks,
  reportedTasks,
 };
});
async function load(){
 if(busy.value||!alive)return;controller=new AbortController();const current=controller;busy.value=true;error.value='';
 try{const response=await props.context.get<ServiceNodeList>('/api/v63/service-nodes',{signal:current.signal});if(!alive||current.signal.aborted)return;if(!Array.isArray(response.items)||response.items.some(node=>typeof node?.node_id!=='string'))throw new Error('节点响应格式无效');nodes.value=response.items;loaded.value=true;updated.value=new Date().toLocaleTimeString('zh-CN',{hour12:false})}
 catch(e){if(alive&&!current.signal.aborted){error.value=e instanceof Error?e.message:'读取失败';if([401,403].includes((e as {httpStatus?:number}).httpStatus||0))nodes.value=[]}}
 finally{if(alive&&controller===current)busy.value=false}
}
function dispose(){alive=false;controller?.abort();props.context.signal.removeEventListener('abort',dispose)}
onMounted(()=>{props.context.signal.addEventListener('abort',dispose,{once:true});void load()});onUnmounted(dispose);
</script>
<template><section class="catalog-preview node-overview" aria-label="服务节点只读总览">
 <PageHeader title="服务节点与算力" eyebrow="计算资源 / 服务节点" description="查看节点心跳、资源与已上报能力。" badge="只读总览" @back="context.returnToManagement"/>
 <div v-if="context.openResource||context.openConfiguration" class="preview-actions resource-entries"><el-button v-if="context.openResource" @click="context.openResource('training')">训练资源与环境</el-button><el-button v-if="context.openResource" @click="context.openResource('conversion')">转换资源与环境</el-button><el-button v-if="context.openResource" @click="context.openResource('models')">AI 模型服务</el-button><el-button v-if="context.openResource" @click="context.openResource('nodes')">完整节点管理</el-button><el-button v-if="context.openConfiguration" @click="context.openConfiguration()">配置中心</el-button></div>
 <div class="node-toolbar"><router-link class="node-env-link" :to="{name:'training-environments-native',params:{projectId:context.projectId}}">训练环境与母模型</router-link><el-input v-model="query" aria-label="搜索节点" placeholder="搜索节点名称或 ID" clearable/><el-select v-model="status" aria-label="节点状态" placeholder="全部状态"><el-option label="全部状态" value=""/><el-option label="在线" value="ONLINE"/><el-option label="离线" value="OFFLINE"/><el-option label="已停用" value="DISABLED"/><el-option label="未收到心跳" value="NEVER_CONNECTED"/></el-select><el-select v-model="capability" aria-label="节点能力" placeholder="全部能力"><el-option label="全部能力" value=""/><el-option v-for="item in capabilities" :key="item" :label="item" :value="item"/></el-select><el-button :disabled="busy" @click="load">{{ busy?'读取中…':'刷新节点' }}</el-button></div>
 <div class="node-query-summary"><span>当前筛选 {{ filtered.length }} / {{ loaded?nodes.length:'—' }} 个节点</span><span>{{ updated?'快照读取于 '+updated:'尚未读取快照' }} · 手动刷新</span></div>
 <dl v-if="loaded&&nodes.length" class="node-fleet-summary" aria-label="算力概览">
  <div><dt>节点</dt><dd>{{ summary.total }}</dd></div>
  <div><dt>在线</dt><dd>{{ summary.online }}</dd></div>
  <div><dt>心跳超 5 分钟</dt><dd :class="{warn:summary.stale>0}">{{ summary.stale }}</dd></div>
  <div><dt>已上报 GPU</dt><dd>{{ summary.gpu }}</dd></div>
  <div><dt>CUDA 已上报可用</dt><dd>{{ summary.cuda }}</dd></div>
  <div><dt>中央持久任务</dt><dd>{{ summary.centralTasks }}</dd></div><div><dt>Agent 上报任务</dt><dd>{{ summary.reportedTasks }}</dd></div>
 </dl>
 <p v-if="loaded&&nodes.length" class="node-fleet-note">在线与心跳只说明连接证据；中央持久任务与 Agent 上报任务来自不同来源，未合并为精确执行总数；可调度、环境就绪与 GPU 可训练资格需各自的服务端证据，本页不推断。</p>
 <el-alert v-if="error" :title="error" type="error" :closable="false"/>
 <el-skeleton v-if="busy&&!loaded" :rows="8" animated/>
 <el-empty v-else-if="!error&&!filtered.length" :description="nodes.length?'没有匹配的服务节点':'暂无已登记的服务节点'"/>
 <div class="node-card-grid" :aria-busy="busy"><ServiceNodeCard v-for="node in filtered" :key="node.node_id" :node="node"/></div>
</section></template>
<style scoped>
.node-fleet-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:0 0 8px}
.node-fleet-summary>div{padding:10px 12px;background:var(--workspace-surface,#fff);border:1px solid var(--workspace-line,#e4e4e7);border-radius:8px}
.node-fleet-summary dt{font-size:12px;color:var(--workspace-subtle,#686872)}
.node-fleet-summary dd{margin:4px 0 0;font-size:20px;font-weight:650;font-variant-numeric:tabular-nums}
.node-fleet-summary dd.warn{color:var(--el-color-warning)}
.node-fleet-note{margin:0 0 12px;font-size:12px;color:var(--workspace-muted,#52525b)}
</style>
