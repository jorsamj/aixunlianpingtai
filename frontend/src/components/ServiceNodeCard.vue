<script setup lang="ts">
import {computed} from 'vue';
import type {ServiceNode} from '../types/service-nodes';
import ResourceMeter from './ResourceMeter.vue';
const props=defineProps<{node:ServiceNode}>();
const state=(value?:string)=>({ONLINE:'在线',OFFLINE:'离线',DISABLED:'已停用',NEVER_CONNECTED:'未收到心跳'}[value||'']||value||'未核验');
function bytes(value?:number){if(typeof value!=='number'||!Number.isFinite(value)||value<0)return '未上报';const units=['B','KB','MB','GB','TB'];let i=0;while(value>=1024&&i<4){value/=1024;i++}return `${value.toFixed(i?1:0)} ${units[i]}`}
const groups=[['allowed_capabilities','管理员允许的能力'],['reported_capabilities','Agent 实际上报能力'],['effective_capabilities','当前有效能力']] as const;
// Heartbeat age is the only connectivity evidence in this snapshot; a stale
// heartbeat is shown as a fact, never as a schedulability decision.
const heartbeat=computed(()=>{
  const age=props.node.heartbeat_age_seconds;
  if(typeof age!=='number'||!Number.isFinite(age)||age<0)return {text:props.node.last_heartbeat_at||'未上报',stale:false};
  if(age<60)return {text:`${Math.round(age)} 秒前`,stale:false};
  if(age<3600)return {text:`${Math.round(age/60)} 分钟前`,stale:age>=300};
  if(age<86400)return {text:`${Math.round(age/3600)} 小时前`,stale:true};
  return {text:`${Math.round(age/86400)} 天前`,stale:true};
});
const gpus=computed(()=>props.node.resources?.gpu?.gpus||[]);
const busyGpus=computed(()=>gpus.value.filter(gpu=>(gpu.utilization_percent||0)>0||(gpu.memory_used_bytes||0)>0).length);
const workers=computed(()=>props.node.workers||[]);
const onlineWorkers=computed(()=>workers.value.filter(worker=>worker.online===true).length);
const durableTasks=computed(()=>props.node.durable_tasks||[]);
const reportedTasks=computed(()=>props.node.reported_active_tasks||[]);
// Central durable tasks and Agent-reported tasks describe different sources. A
// shared task identity is deduplicated; anything without identity is counted
// separately instead of being silently added or merged.
const reportedOnlyTasks=computed(()=>{
  const known=new Set(durableTasks.value.map(task=>String(task.task_id||'').trim()).filter(Boolean));
  return reportedTasks.value.filter(task=>{
    const id=String(task.task_id||'').trim();
    return !id||!known.has(id);
  });
});
const runningTasks=computed(()=>durableTasks.value.length+reportedOnlyTasks.value.length);
const taskSourceText=computed(()=>durableTasks.value.length||reportedTasks.value.length
  ?`中央 ${durableTasks.value.length} · Agent 独有 ${reportedOnlyTasks.value.length}`:'');
const cuda=computed(()=>props.node.runtime?.cuda_available===true?'CUDA 已上报可用'
  :props.node.runtime?.cuda_available===false?'CUDA 已上报不可用'
  :props.node.runtime?.cuda_version?`CUDA ${props.node.runtime.cuda_version}（可用性未核验）`:'运行环境未上报');
</script>
<template><article class="node-card" :aria-label="node.display_name||node.node_id">
 <header><div><h2>{{ node.display_name||'未命名节点' }}</h2><small>{{ node.node_id }}</small></div><el-tag :type="node.status==='ONLINE'?(heartbeat.stale?'warning':'success'):'info'" effect="plain">{{ state(node.status) }}</el-tag></header>
 <p class="node-summary">
  <span :class="{stale:heartbeat.stale}">心跳 {{ heartbeat.text }}</span>
  <span>{{ cuda }}</span>
  <span>GPU {{ gpus.length }} 张{{ busyGpus?` · 占用 ${busyGpus}`:'' }}</span>
  <span>Worker {{ onlineWorkers }}/{{ workers.length }}</span>
  <span>执行中 {{ runningTasks }} 项<template v-if="taskSourceText">（{{ taskSourceText }}）</template></span>
  <span>调度准入：需独立证据</span>
 </p>
 <dl class="node-meta"><div><dt>连接类型</dt><dd>{{ node.connection_mode==='local'?'本地 Agent':node.connection_mode==='agent'?'远程 Agent':'未上报' }}</dd></div><div><dt>操作系统 / CPU 架构</dt><dd>{{ node.os_name||'系统未上报' }} / {{ node.architecture||'架构未上报' }}</dd></div><div><dt>最近心跳</dt><dd>{{ node.last_heartbeat_at||'未上报' }}</dd></div><div><dt>Agent 版本</dt><dd>{{ node.agent_version||'未上报' }}<small v-if="node.build_id"> / {{ node.build_id }}</small></dd></div></dl>
 <section class="node-capabilities"><div v-for="[key,label] in groups" :key="key" :aria-label="label"><span>{{ label }}</span><div><el-tag v-for="cap in node[key]||[]" :key="cap" type="info" effect="plain">{{ cap }}</el-tag><small v-if="!node[key]?.length">{{ key==='effective_capabilities'?'暂无有效能力':key==='allowed_capabilities'?'未授权能力':'未上报能力' }}</small></div></div><div aria-label="当前可调度能力"><span>当前可调度能力</span><div><small>未提供独立调度准入证据</small></div></div></section>
 <div class="node-meters"><ResourceMeter label="CPU 使用率" :value="node.resources?.cpu?.usage_percent" :detail="`${node.resources?.cpu?.physical_cores??'未上报'} 物理核 / ${node.resources?.cpu?.logical_cores??'未上报'} 逻辑核`"/><ResourceMeter label="内存使用率" :value="node.resources?.memory?.usage_percent" :detail="`${bytes(node.resources?.memory?.used_bytes)} / ${bytes(node.resources?.memory?.total_bytes)}，可用 ${bytes(node.resources?.memory?.available_bytes)}`"/></div>
 <section class="node-gpus" aria-label="已上报 GPU 信息"><h3>已上报 GPU</h3><p v-if="!node.resources?.gpu?.gpus?.length">未上报 GPU 设备信息</p><p v-if="node.resources?.gpu?.error">{{ node.resources.gpu.error }}</p><div v-for="(gpu,index) in node.resources?.gpu?.gpus||[]" :key="gpu.id||index" class="node-device"><strong>{{ gpu.name||'设备名称未上报' }}</strong><small>{{ gpu.id||`上报序号 ${gpu.index??index}` }}</small><ResourceMeter label="GPU 使用率" :value="gpu.utilization_percent" :detail="`显存 ${bytes(gpu.memory_used_bytes)} / ${bytes(gpu.memory_total_bytes)}，空闲 ${bytes(gpu.memory_free_bytes)}`"/></div></section>
 <p class="node-footnote">设备与能力来自已有心跳快照，在线不代表训练准入；NPU 等未有统一上报证据的设备仍未核验。</p>
 <details class="node-task-detail"><summary>任务占用与 Worker · {{ node.durable_tasks?.length??'未知' }} 项持久任务</summary><p v-if="!node.durable_tasks?.length">当前快照未列出执行中持久任务。</p><p v-for="task in node.durable_tasks||[]" :key="task.task_id">{{ task.kind }} · {{ task.task_id }} · {{ task.stage||task.status||'阶段未上报' }} · {{ typeof task.progress==='number'?task.progress+'%':'进度未上报' }}</p><p v-for="worker in node.workers||[]" :key="worker.worker_id">Worker {{ worker.worker_id }} · {{ worker.online===true?'在线':worker.online===false?'离线':'未核验' }} · {{ worker.roles?.join(' / ') }}</p><p v-for="(task,index) in node.reported_active_tasks||[]" :key="index">Agent 上报占用：{{ task.task_id }} · {{ task.kind }} · {{ task.status||task.stage }}</p><p>磁盘空闲 {{ bytes(node.resources?.disk?.free_bytes) }} / {{ bytes(node.resources?.disk?.total_bytes) }}</p><p>PyTorch {{ node.runtime?.torch_version||'未上报' }} · CUDA {{ node.runtime?.cuda_version||'未上报' }} · CUDA 可用 {{ node.runtime?.cuda_available===true?'已上报为是':node.runtime?.cuda_available===false?'已上报为否':'未核验' }}</p></details>
 <el-alert v-if="node.last_error" :title="node.last_error" type="warning" :closable="false"/>
</article></template>
<style scoped>
.node-summary{display:flex;flex-wrap:wrap;gap:4px 12px;margin:0 0 10px;font-size:12px;color:var(--workspace-muted,#52525b)}
.node-summary span{white-space:nowrap}
.node-summary .stale{color:var(--el-color-warning)}
</style>
