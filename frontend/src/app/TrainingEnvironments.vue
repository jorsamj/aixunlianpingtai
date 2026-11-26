<script setup lang="ts">
import {computed,onBeforeUnmount,ref} from 'vue';
import {useReadScope} from '../composables/useReadScope';
import {request} from './http';
import {legacyUrl} from './navigation';

const {projectId}=defineProps<{projectId:string}>();
const controller=new AbortController(),reads=useReadScope(controller);
onBeforeUnmount(()=>controller.abort());
const legacy=computed(()=>legacyUrl(projectId,'服务节点'));

interface GpuRow {id?:string;name?:string;available?:boolean;memory_total_mb?:number;error?:string}
interface DeviceReport {
  ok?:boolean;error?:string;python_executable?:string;torch_version?:string;ultralytics_version?:string;
  cuda_version?:string;cuda_available?:boolean;cpu_name?:string;gpus?:GpuRow[];recommended?:string;
}
interface MotherAsset {
  asset_id?:string;file_name?:string;name?:string;sha256?:string;size_bytes?:number;source?:string;
  format?:string;validation_status?:string;validation_error?:string;trainable?:boolean;
  created_at?:string;verified_at?:string;
}
interface AssetPage {items?:MotherAsset[];verification_environment?:Record<string,unknown>}
interface NodeWeight {name?:string;path?:string;size_bytes?:number;status?:string;trainable?:boolean}
interface NodeInventoryRow {
  node_id?:string;display_name?:string;online?:boolean;install_available?:boolean;status?:string;
  scanned_at?:string;truncated?:boolean;items?:NodeWeight[];
}
interface InstallRow {
  task_id?:string;asset_id?:string;node_id?:string;status?:string;progress?:number;stage?:string;
  error?:string;created_at?:string;finished_at?:string;installed?:boolean;verified_sha256?:string|null;
}

const devices=ref<DeviceReport|null>(null),assets=ref<AssetPage|null>(null);
const inventory=ref<NodeInventoryRow[]>([]),installations=ref<InstallRow[]>([]);
const actionError=ref(''),notice=ref(''),verifying=ref(''),uploading=ref(false);
const assetsLoaded=ref(false),installationsLoaded=ref(false),inventoryLoaded=ref(false);
const installCursors=ref<string[]>(['']),installNext=ref('');

// Real mother-model validation states from the asset owner; nothing is guessed.
const validationStates:Record<string,{label:string;tone:'success'|'warning'|'danger'|'info'}> = {
  UNVERIFIED:{label:'待校验',tone:'info'},
  CHECKING:{label:'校验中',tone:'warning'},
  VERIFIED:{label:'校验通过',tone:'success'},
  INVALID:{label:'不兼容权重',tone:'danger'},
  INCOMPATIBLE:{label:'任务类型不兼容',tone:'danger'},
  SANDBOX_UNAVAILABLE:{label:'校验环境不可用',tone:'warning'},
  FAILED:{label:'校验失败',tone:'danger'},
  INTERRUPTED:{label:'校验中断',tone:'warning'},
};
const validationState=(status?:string)=>validationStates[String(status||'')]??{label:status||'未提供',tone:'info' as const};
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
function loadInstallations(cursor=''){
  return reads.run('installations',signal=>request<{items:InstallRow[];next_cursor?:string|null}>(
    `/api/v63/base-models/installations${cursor?`?cursor=${encodeURIComponent(cursor)}`:''}`,{signal}),value=>{
    if(!Array.isArray(value.items))throw new Error('安装任务响应格式无效');
    installations.value=value.items;
    installCursors.value=[...installCursors.value.slice(0,installCursors.value.indexOf(cursor)+1)];
    installNext.value=value.next_cursor||'';
    installationsLoaded.value=true;
  });
}
function nextInstallations(){
  if(!installNext.value)return;
  installCursors.value=[...installCursors.value,installNext.value];
  void loadInstallations(installNext.value);
}
function previousInstallations(){
  if(installCursors.value.length<2)return;
  const cursors=[...installCursors.value];
  cursors.pop();
  void loadInstallations(cursors.at(-1)||'');
}
async function verifyAsset(row:MotherAsset){
  const id=row.asset_id;
  if(!id||verifying.value)return;
  if(!window.confirm(`对母模型 ${row.file_name||row.name||id} 执行安全校验？校验在受保护沙箱中运行，不会加载到本页面。`))return;
  verifying.value=id;actionError.value='';notice.value='';
  try{
    const result=await request<{accepted?:boolean;asset_id?:string;validation_status?:string;deduplicated?:boolean}>(
      `/api/v63/base-models/assets/${encodeURIComponent(id)}/verify`,{method:'POST',body:JSON.stringify({}),signal:controller.signal});
    // The real contract answers accepted/asset_id/validation_status; anything else
    // is treated as unknown and resolved by re-reading the asset state instead of
    // submitting a second verification.
    if(result?.accepted!==true||result.asset_id!==id||!validationStates[String(result.validation_status||'')]){
      await loadAssets();
      actionError.value='校验受理回执不完整，已改为读取原资产状态；未重复提交。';
      return;
    }
    notice.value=`已受理母模型安全校验（${validationState(result.validation_status).label}）${result.deduplicated?'，同资产校验正在进行':''}；完成后刷新资产列表查看结论。`;
    await loadAssets();
  }catch(error){
    if(!controller.signal.aborted){
      actionError.value=`校验请求结果未知：${(error as Error).message}。已改为读取原资产状态，未重复提交。`;
      await loadAssets().catch(()=>{});
    }
  }finally{verifying.value=''}
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
    const result=await request<{ok?:boolean;asset_id?:string;sha256?:string;reused?:boolean;validation_status?:string;size_bytes?:number}>(
      `/api/v63/base-models/upload`,{method:'POST',body,signal:controller.signal});
    const valid=result?.ok===true&&/^pt_[0-9a-f]{24}$/.test(String(result.asset_id||''))
      &&/^[a-f0-9]{64}$/.test(String(result.sha256||''))&&typeof result.reused==='boolean'
      &&!!validationStates[String(result.validation_status||'')];
    if(!valid){actionError.value='上传回执不完整，请刷新资产列表核对，未重复上传。';await loadAssets().catch(()=>{});return}
    const state=validationState(result.validation_status);
    notice.value=`已登记母模型 ${result.asset_id}（${state.label}）${result.reused?'，同内容已存在并复用原资产':''}。`
      +(result.validation_status==='VERIFIED'?'官方摘要固定的权重可直接被训练引用。':'该权重尚未通过安全校验，训练引用前必须先完成校验。');
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
   <p class="env-note">上传只做显式登记与内容摘要，不触发下载或推理；只有校验通过且内容未变化的权重才可被训练引用，单个节点具备该权重也不等于全部节点可训练。</p>
   <el-alert v-if="reads.errors.assets" :title="reads.errors.assets" type="error" :closable="false"/>
   <el-table :data="assets?.items||[]" row-key="asset_id" size="small" :empty-text="assetsLoaded?'暂无已登记母模型':'尚未读取母模型资产'">
    <el-table-column label="母模型" min-width="200"><template #default="{row}"><strong>{{row.file_name||row.name||row.asset_id}}</strong><small>{{row.asset_id}}</small></template></el-table-column>
    <el-table-column label="格式 / 大小" width="130"><template #default="{row}">{{row.format||'.pt'}} · {{sizeText(row.size_bytes)}}</template></el-table-column>
    <el-table-column label="来源" min-width="120"><template #default="{row}">{{row.source||'未提供'}}</template></el-table-column>
    <el-table-column label="校验状态" min-width="140"><template #default="{row}"><el-tag :type="validationState(row.validation_status).tone" effect="plain" size="small">{{validationState(row.validation_status).label}}</el-tag><small v-if="row.validation_error">{{row.validation_error}}</small></template></el-table-column>
    <el-table-column label="训练可用" width="100"><template #default="{row}">{{row.trainable===true?'可用':row.trainable===false?'不可用':'未核验'}}</template></el-table-column>
    <el-table-column label="SHA256" min-width="150"><template #default="{row}"><code :title="row.sha256">{{row.sha256?String(row.sha256).slice(0,16)+'…':'未提供'}}</code></template></el-table-column>
    <el-table-column label="操作" width="110"><template #default="{row}"><el-button link :loading="verifying===row.asset_id" :disabled="!!verifying" @click="verifyAsset(row)">安全校验</el-button></template></el-table-column>
   </el-table>
  </section>

  <section class="env-card" aria-label="节点母模型清单">
   <header class="env-card-head"><h3>节点已发现母模型</h3><el-button size="small" :loading="reads.busy.inventory" @click="loadInventory">刷新</el-button></header>
   <p class="env-note">来自 Agent 心跳的有界路径清单，只代表“已发现”，不代表已校验或可训练。</p>
   <el-alert v-if="reads.errors.inventory" :title="reads.errors.inventory" type="error" :closable="false"/>
   <el-table :data="inventory" row-key="node_id" size="small" :empty-text="inventoryLoaded?'没有 Agent 上报母模型路径':'尚未读取节点清单'">
    <el-table-column label="节点" min-width="170"><template #default="{row}">{{row.display_name||row.node_id}}<small>{{row.node_id}}</small></template></el-table-column>
    <el-table-column label="在线" width="80"><template #default="{row}">{{row.online?'在线':'离线'}}</template></el-table-column>
    <el-table-column label="清单状态" min-width="140"><template #default="{row}">{{row.status||'未上报'}}<small v-if="row.scanned_at">扫描 {{row.scanned_at}}</small><small v-if="row.truncated">清单已截断</small></template></el-table-column>
    <el-table-column label="已发现权重" min-width="240"><template #default="{row}"><template v-if="row.items?.length"><p v-for="weight in row.items" :key="weight.path">{{weight.name}} · {{sizeText(weight.size_bytes)}} · 未校验</p></template><span v-else>未发现</span></template></el-table-column>
   </el-table>
  </section>

  <section class="env-card" aria-label="母模型安装任务">
   <header class="env-card-head"><h3>母模型安装任务</h3><el-button size="small" :loading="reads.busy.installations" @click="loadInstallations(installCursors.at(-1)||'')">刷新</el-button></header>
   <p class="env-note">安装任务属于全局资源任务，不随项目切换；本页只读展示任务状态与同一代 Agent 安装回执。</p>
   <el-alert v-if="reads.errors.installations" :title="reads.errors.installations" type="error" :closable="false"/>
   <el-table :data="installations" row-key="task_id" size="small" :empty-text="installationsLoaded?'暂无母模型安装任务':'尚未读取安装任务'">
    <el-table-column prop="task_id" label="任务" min-width="180"/>
    <el-table-column label="资产 / 节点" min-width="200"><template #default="{row}">{{row.asset_id||'未提供'}} · {{row.node_id||'未提供'}}</template></el-table-column>
    <el-table-column label="状态" min-width="130"><template #default="{row}">{{row.status||'未提供'}}<small v-if="row.stage">{{row.stage}}</small><small v-if="row.error">{{row.error}}</small></template></el-table-column>
    <el-table-column label="回执" min-width="150"><template #default="{row}">{{row.installed?'Agent 安装回执已核验':'未核验'}}<small v-if="row.verified_sha256">SHA {{String(row.verified_sha256).slice(0,12)}}…</small></template></el-table-column>
    <el-table-column prop="created_at" label="创建时间" min-width="160"/>
   </el-table>
   <div class="env-actions env-pager">
    <el-button size="small" :disabled="installCursors.length<2||reads.busy.installations" @click="previousInstallations">上一页</el-button>
    <el-button size="small" :disabled="!installNext||reads.busy.installations" @click="nextInstallations">下一页</el-button>
   </div>
   <p class="env-note">安装到节点需要已校验资产与具备安装能力的在线 Agent，属独立安全流程；本页不提供安装、取消或自动重试。</p>
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
.env-pager{margin-top:8px}
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
