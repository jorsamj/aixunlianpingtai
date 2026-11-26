<script setup lang="ts">
import {computed,onBeforeUnmount,ref} from 'vue';
import {useRoute} from 'vue-router';
import {useReadScope} from '../composables/useReadScope';
import {request} from './http';
import {legacyUrl} from './navigation';

const {projectId}=defineProps<{projectId:string}>();
const route=useRoute();
const controller=new AbortController(),reads=useReadScope(controller);
onBeforeUnmount(()=>controller.abort());
const legacy=computed(()=>legacyUrl(projectId,'服务节点'));

interface GpuRow {id?:string;name?:string;available?:boolean;memory_total_mb?:number;error?:string}
interface DeviceReport {
  ok?:boolean;error?:string;python_executable?:string;torch_version?:string;ultralytics_version?:string;
  cuda_version?:string;cuda_available?:boolean;cpu_name?:string;gpus?:GpuRow[];recommended?:string;
  options?:{id?:string;label?:string;type?:string;available?:boolean;meaning?:string}[];
}
interface MotherAsset {
  asset_id?:string;file_name?:string;display_name?:string;sha256?:string;size_bytes?:number;source?:string;
  format?:string;validation_status?:string;validation_error?:string;trainable?:boolean;created_at?:string;
  registered_at?:string;origin?:string;
}
interface AssetPage {items?:MotherAsset[];verification_environment?:Record<string,unknown>}
interface NodeInventoryRow {node_id?:string;display_name?:string;online?:boolean;install_available?:boolean;status?:string;scanned_at?:string;truncated?:boolean;models?:{name?:string;path?:string;size_bytes?:number;status?:string;trainable?:boolean}[]}
interface InstallRow {task_id?:string;status?:string;stage?:string;asset_id?:string;node_id?:string;created_at?:string;receipt?:Record<string,unknown>}

const devices=ref<DeviceReport|null>(null),assets=ref<AssetPage|null>(null),inventory=ref<NodeInventoryRow[]>([]),installations=ref<InstallRow[]>([]);
const actionError=ref(''),notice=ref(''),verifying=ref(''),uploading=ref(false);

const assetsLoaded=ref(false),installationsLoaded=ref(false),inventoryLoaded=ref(false);
const validationLabel=(status?:string)=>({PASSED:'校验通过',CHECKING:'校验中',FAILED:'校验失败',INTERRUPTED:'校验中断',PENDING:'待校验'}[String(status||'')]||status||'未提供');
const validationTone=(status?:string)=>status==='PASSED'?'success':status==='FAILED'?'danger':status==='CHECKING'?'warning':'info';
const sizeText=(value?:number)=>typeof value==='number'&&Number.isFinite(value)&&value>=0?`${(value/1048576).toFixed(1)} MB`:'未提供';
const cudaLabel=computed(()=>{
  const row=devices.value;
  if(!row)return '未读取';
  if(row.cuda_available===true)return `CUDA 可用${row.cuda_version?` · ${row.cuda_version}`:''}`;
  if(row.cuda_available===false)return `CUDA 不可用${row.cuda_version?` · ${row.cuda_version}`:''}`;
  return 'CUDA 状态未提供';
});

// Environment probing spawns the training interpreter, so it only runs on an
// explicit user action; the page never auto-detects on open.
function loadDevices(){
  return reads.run('devices',signal=>request<DeviceReport>('/api/v62/training-devices',{signal}),value=>{
    if(!Array.isArray(value.gpus)&&value.ok!==false)throw new Error('训练环境响应缺少设备证据');
    devices.value=value;
  });
}
function loadAssets(){
  return reads.run('assets',signal=>request<AssetPage>('/api/v63/base-models/assets',{signal}),value=>{
    if(!Array.isArray(value.items))throw new Error('母模型资产响应格式无效');
    assets.value=value;assetsLoaded.value=true;
  });
}
function loadInventory(){
  return reads.run('inventory',signal=>request<{items:NodeInventoryRow[]}>('/api/v63/base-models/node-inventory',{signal}),value=>{
    if(!Array.isArray(value.items))throw new Error('节点母模型清单格式无效');
    inventory.value=value.items;inventoryLoaded.value=true;
  });
}
function loadInstallations(){
  return reads.run('installations',signal=>request<{items:InstallRow[]}>('/api/v63/base-models/installations',{signal}),value=>{
    if(!Array.isArray(value.items))throw new Error('安装任务响应格式无效');
    installations.value=value.items;installationsLoaded.value=true;
  });
}
async function verifyAsset(row:MotherAsset){
  const id=row.asset_id;
  if(!id||verifying.value)return;
  if(!window.confirm(`对母模型 ${row.file_name||id} 执行安全校验？校验在受保护沙箱中运行，不会加载到本页面。`))return;
  verifying.value=id;actionError.value='';notice.value='';
  try{
    const result=await request<{ok?:boolean;task_id?:string;status?:string}>(`/api/v63/base-models/assets/${encodeURIComponent(id)}/verify`,{method:'POST',body:JSON.stringify({}),signal:controller.signal});
    if(result?.ok===false)throw new Error('校验请求未被受理');
    notice.value=`已提交母模型安全校验${result?.status?`（${result.status}）`:''}；完成后刷新资产列表查看结论。`;
    await loadAssets();
  }catch(error){if(!controller.signal.aborted)actionError.value=(error as Error).message}
  finally{verifying.value=''}
}
async function uploadAsset(event:Event){
  const input=event.target as HTMLInputElement;
  const file=input.files?.[0];
  if(!file||uploading.value)return;
  if(!/\.pt$/i.test(file.name)){actionError.value='仅支持 .pt 母模型权重。';input.value='';return}
  uploading.value=true;actionError.value='';notice.value='';
  try{
    const body=new FormData();
    body.append('file',file);
    const result=await request<{ok?:boolean;asset_id?:string;reused?:boolean}>(`/api/v63/base-models/upload`,{method:'POST',body,signal:controller.signal});
    if(result?.ok===false||!result?.asset_id)throw new Error('上传回执缺少母模型资产编号');
    notice.value=`已登记母模型 ${result.asset_id}${result.reused?'（同内容已存在，复用原资产）':''}；仍需安全校验后才可用于训练。`;
    await loadAssets();
  }catch(error){if(!controller.signal.aborted)actionError.value=(error as Error).message}
  finally{uploading.value=false;input.value=''}
}
function loadAll(){
  void loadAssets();void loadInventory();void loadInstallations();
}
loadAll();
</script>

<template>
 <section class="training-environments" aria-label="训练环境与母模型">
  <header class="env-head">
   <div><h2>训练环境与母模型</h2><small>项目 {{projectId}}</small></div>
   <div class="env-actions">
    <el-button :loading="reads.busy.devices" @click="loadDevices">读取训练环境</el-button>
    <el-button :loading="reads.busy.assets" @click="loadAssets">刷新母模型资产</el-button>
    <el-button tag="a" :href="legacy">原节点与资源配置</el-button>
   </div>
  </header>
  <el-alert v-if="actionError" :title="actionError" type="error" :closable="false"/>
  <el-alert v-if="notice" :title="notice" type="info" :closable="false"/>

  <section class="env-card" aria-label="训练运行环境">
   <header class="env-card-head"><h3>训练运行环境</h3><span class="env-note">环境探测只在点击“读取训练环境”时执行，不在进入页面时自动探测。</span></header>
   <el-alert v-if="reads.errors.devices" :title="reads.errors.devices" type="error" :closable="false"/>
   <el-skeleton v-if="reads.busy.devices&&!devices" :rows="4" animated/>
   <p v-else-if="!devices" class="env-note">尚未读取。训练环境需要显式读取，避免进入页面即执行解释器探测。</p>
   <template v-else>
    <dl class="env-facts">
     <div><dt>解释器</dt><dd>{{devices.python_executable||'未提供'}}</dd></div>
     <div><dt>PyTorch</dt><dd>{{devices.torch_version||'未提供'}}</dd></div>
     <div><dt>Ultralytics</dt><dd>{{devices.ultralytics_version||'未提供'}}</dd></div>
     <div><dt>CUDA</dt><dd>{{cudaLabel}}</dd></div>
     <div><dt>CPU</dt><dd>{{devices.cpu_name||'未提供'}}</dd></div>
     <div><dt>调度建议</dt><dd>{{devices.recommended||'未提供'}}</dd></div>
    </dl>
    <el-alert v-if="devices.error" :title="devices.error" type="warning" :closable="false"/>
    <el-table v-if="devices.gpus?.length" :data="devices.gpus" row-key="id" size="small" max-height="260">
     <el-table-column label="GPU" min-width="200"><template #default="{row}">{{row.id||'未提供'}} · {{row.name||'名称未提供'}}</template></el-table-column>
     <el-table-column label="可用" width="90"><template #default="{row}"><el-tag :type="row.available?'success':'info'" effect="plain" size="small">{{row.available?'可用':'不可用'}}</el-tag></template></el-table-column>
     <el-table-column label="显存" width="110"><template #default="{row}">{{row.memory_total_mb?row.memory_total_mb+' MB':'未提供'}}</template></el-table-column>
     <el-table-column label="错误" min-width="160"><template #default="{row}">{{row.error||'—'}}</template></el-table-column>
    </el-table>
    <p v-else class="env-note">本次探测没有上报 GPU；CPU 训练资格与可调度性仍由调度与资源证据决定。</p>
   </template>
  </section>

  <section class="env-card" aria-label="母模型资产">
   <header class="env-card-head">
    <h3>母模型资产</h3>
    <div class="env-actions">
     <label class="env-upload">上传 .pt 母模型<input type="file" accept=".pt" :disabled="uploading" @change="uploadAsset"></label>
     <el-button size="small" :loading="reads.busy.assets" @click="loadAssets">刷新</el-button>
    </div>
   </header>
   <p class="env-note">上传只做显式登记与内容摘要，不触发下载或推理；校验通过且未变化的权重才可被训练引用。</p>
   <el-alert v-if="reads.errors.assets" :title="reads.errors.assets" type="error" :closable="false"/>
   <el-table :data="assets?.items||[]" row-key="asset_id" size="small" :empty-text="assetsLoaded?'暂无已登记母模型':'尚未读取母模型资产'">
    <el-table-column label="母模型" min-width="200"><template #default="{row}"><strong>{{row.file_name||row.display_name||row.asset_id}}</strong><small>{{row.asset_id}}</small></template></el-table-column>
    <el-table-column label="格式 / 大小" width="130"><template #default="{row}">{{row.format||'.pt'}} · {{sizeText(row.size_bytes)}}</template></el-table-column>
    <el-table-column label="来源" min-width="130"><template #default="{row}">{{row.source||row.origin||'未提供'}}</template></el-table-column>
    <el-table-column label="校验状态" min-width="130"><template #default="{row}"><el-tag :type="validationTone(row.validation_status)" effect="plain" size="small">{{validationLabel(row.validation_status)}}</el-tag><small v-if="row.validation_error">{{row.validation_error}}</small></template></el-table-column>
    <el-table-column label="训练可用" width="100"><template #default="{row}">{{row.trainable===true?'可用':row.trainable===false?'不可用':'未核验'}}</template></el-table-column>
    <el-table-column label="SHA256" min-width="150"><template #default="{row}"><code :title="row.sha256">{{row.sha256?String(row.sha256).slice(0,16)+'…':'未提供'}}</code></template></el-table-column>
    <el-table-column label="操作" width="120"><template #default="{row}"><el-button link :loading="verifying===row.asset_id" :disabled="!!verifying" @click="verifyAsset(row)">安全校验</el-button></template></el-table-column>
   </el-table>
   <p v-if="assets?.verification_environment" class="env-note">校验环境：{{JSON.stringify(assets.verification_environment)}}</p>
  </section>

  <section class="env-card" aria-label="节点母模型清单">
   <header class="env-card-head"><h3>节点已发现母模型</h3><el-button size="small" :loading="reads.busy.inventory" @click="loadInventory">刷新</el-button></header>
   <p class="env-note">来自 Agent 心跳的有界路径清单，只代表“已发现”，不代表已校验或可训练。</p>
   <el-alert v-if="reads.errors.inventory" :title="reads.errors.inventory" type="error" :closable="false"/>
   <el-table :data="inventory" row-key="node_id" size="small" :empty-text="inventoryLoaded?'没有 Agent 上报母模型路径':'尚未读取节点清单'">
    <el-table-column label="节点" min-width="170"><template #default="{row}">{{row.display_name||row.node_id}}<small>{{row.node_id}}</small></template></el-table-column>
    <el-table-column label="在线" width="80"><template #default="{row}">{{row.online?'在线':'离线'}}</template></el-table-column>
    <el-table-column label="清单状态" min-width="130"><template #default="{row}">{{row.status||'未上报'}}<small v-if="row.scanned_at">扫描 {{row.scanned_at}}</small></template></el-table-column>
    <el-table-column label="已发现权重" min-width="220"><template #default="{row}"><template v-if="row.models?.length"><p v-for="model in row.models" :key="model.path">{{model.name}} · {{sizeText(model.size_bytes)}} · 未校验</p></template><span v-else>未发现</span></template></el-table-column>
   </el-table>
  </section>

  <section class="env-card" aria-label="母模型安装任务">
   <header class="env-card-head"><h3>母模型安装任务</h3><el-button size="small" :loading="reads.busy.installations" @click="loadInstallations">刷新</el-button></header>
   <el-alert v-if="reads.errors.installations" :title="reads.errors.installations" type="error" :closable="false"/>
   <el-table :data="installations" row-key="task_id" size="small" :empty-text="installationsLoaded?'暂无母模型安装任务':'尚未读取安装任务'">
    <el-table-column prop="task_id" label="任务" min-width="180"/>
    <el-table-column label="资产 / 节点" min-width="200"><template #default="{row}">{{row.asset_id||'未提供'}} · {{row.node_id||'未提供'}}</template></el-table-column>
    <el-table-column label="状态" width="130"><template #default="{row}">{{row.status||'未提供'}}<small v-if="row.stage">{{row.stage}}</small></template></el-table-column>
    <el-table-column prop="created_at" label="创建时间" min-width="160"/>
   </el-table>
   <p class="env-note">安装到节点需要已校验资产与具备安装能力的在线 Agent，属独立安全流程；本页只读展示任务状态。</p>
  </section>
 </section>
</template>

<style scoped>
.training-environments{display:grid;gap:16px;min-width:0}
.env-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap}
.env-head h2{margin:0 0 4px;font-size:20px}
.env-head small{color:var(--workspace-muted,#52525b)}
.env-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.env-actions :deep(.el-button+.el-button){margin-left:0}
.env-card{background:var(--workspace-surface,#fff);border:1px solid var(--workspace-line,#e4e4e7);border-radius:var(--workspace-radius,8px);padding:16px;min-width:0}
.env-card-head{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
.env-card-head h3{margin:0;font-size:16px}
.env-note{margin:0 0 10px;font-size:12px;color:var(--workspace-muted,#52525b);overflow-wrap:anywhere}
.env-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin:0 0 12px}
.env-facts>div{padding:8px 10px;background:var(--workspace-page,#f7f8fa);border-radius:6px;min-width:0}
.env-facts dt{font-size:12px;color:var(--workspace-subtle,#686872)}
.env-facts dd{margin:4px 0 0;font-size:13px;overflow-wrap:anywhere}
.env-card small{display:block;color:var(--workspace-subtle,#686872);font-size:11px;overflow-wrap:anywhere}
.env-card code{font-size:11px;overflow-wrap:anywhere}
.env-card p{margin:0 0 4px;overflow-wrap:anywhere}
.env-upload{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--workspace-muted,#52525b)}
</style>
