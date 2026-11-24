<script setup lang="ts">
import {computed,onBeforeUnmount,reactive,ref} from 'vue';
import {browseError} from '../api/model-browse';
import {useReadScope} from '../composables/useReadScope';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
import {request} from './http';
import {legacyUrl} from './navigation';
// Native migration of the existing platform-integration configuration read and
// its existing save contract. Secrets are only ever rendered as the masked /
// boolean state returned by the server; this page never reads, stores or logs a
// credential. Master switch, connection test, sync and diagnostics stay on the
// original page because they perform outbound external operations.
interface CredentialState {configured?:boolean;masked?:string;available?:boolean;error?:string;backend?:string;writable?:boolean;environment_name?:string}
interface PlatformConfig {
  schema_version?:string|null;mode?:string;provider?:string;provider_name?:string;base_url?:string;
  auto_sync_enabled?:boolean;auto_sync_interval_seconds?:number;auto_sync_schedule_local_times?:string[];
  auto_sync_timezone?:string;auto_publish_enabled?:boolean;auth_mode?:string;business_auth_mode?:string;
  credentials?:CredentialState;endpoints?:Record<string,string>;updated_at?:string|null;
  last_sync?:{status?:string;sync_type?:string;started_at?:string|null;finished_at?:string|null;error?:string;detail?:string}|null;
  cache?:{synced_at?:string|null;master_data_digest?:string;category_count?:number;product_count?:number;analysis_count?:number;compute_platform_count?:number};
  api_document_summary?:{total?:number;wired?:number;documented?:number;reference?:number};
}
interface TargetMapping {compute_platform_id?:string;chip_code?:string;chip_mappings?:Record<string,string>;enabled?:boolean;local_vendor_id?:string}
interface LocalVendor {id:string;name?:string;enabled?:boolean;template_id?:string}
interface LocalChip {id:string;name?:string;sdk_code?:string;vendor_id?:string;enabled?:boolean}
interface StorageSource {id:string;name?:string;type?:string;enabled?:boolean;is_default?:boolean;health_status?:string;health_message?:string;secret_configured?:boolean;secret_masked?:string}
interface ComputePlatformRow {computePlatformId?:string|number;computePlatformName?:string;computePlatformCode?:string;parentId?:string|number|null;delFlag?:string|number|null;id?:string;name?:string;code?:string}
interface PublishConfigBody {
  ok:boolean;
  config?:{publish_original_model?:boolean;mapping_revision?:number;mapping_history?:unknown[];target_mappings?:Record<string,TargetMapping>;version_list_by_product?:string;weight_list_by_version?:string;updated_at?:string|null};
  storage_sources?:StorageSource[];compute_platforms?:ComputePlatformRow[];
  chip_dictionary?:Record<string,string[]>;
  local_catalog?:{revision?:number;vendors?:LocalVendor[];chips?:LocalChip[]};
  mapping_diagnostics?:{vendors?:Record<string,{status?:string;reason?:string}>;legacy_proposals?:{legacy_target?:string;local_vendor_id?:string;status?:string;reason?:string}[]};
}
const props=defineProps<{projectId:string}>();
const controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
const reads=useReadScope(controller);
const config=ref<PlatformConfig|null>(null),publish=ref<PublishConfigBody|null>(null);
const editing=ref(false),saving=ref(false),writeError=ref(''),notice=ref('');
const form=reactive({base_url:'',access_key:'',access_secret:''});
const legacyHref=legacyUrl(props.projectId,'平台对接');
const date=(value?:string|null)=>value?String(value).replace('T',' ').slice(0,19):'未提供';
// Provider/OSS/storage errors can embed addresses, tokens or local paths; hide
// them before rendering, exactly as the legacy delivery/config projections do.
function safe(value:unknown){
 return String(value??'').replace(/https?:\/\/\S+/g,'[地址已隐藏]')
  .replace(/(?:Bearer\s+)[^\s,;]+/gi,'Bearer [已隐藏]')
  .replace(/(token|password|secret|api[_-]?key|authorization)["']?\s*[:=]\s*[^\s,;}]+/gi,'$1=[已隐藏]')
  .replace(/[A-Za-z]:[\\/][^\s,;]+|(?:\/[\w.\-]+){2,}/g,'[路径已隐藏]').slice(0,800);
}
const external=computed(()=>config.value?.mode==='external');
const credential=computed<CredentialState>(()=>config.value?.credentials||{});
const credentialManaged=computed(()=>credential.value.backend==='environment');
const credentialUnavailable=computed(()=>credential.value.available===false);
const credentialText=computed(()=>{
 const value=credential.value;
 if(value.available===false)return '安全存储不可用';
 if(value.configured)return `已配置（${value.masked||'已保存'}）`;
 return '未配置';
});
// Same save -> locked -> edit -> save product contract as the original page.
const savedConnectionReady=computed(()=>external.value&&!!String(config.value?.base_url||'').trim()&&credential.value.configured===true);
const locked=computed(()=>savedConnectionReady.value&&!editing.value);
const modeLabel=computed(()=>external.value?'外部平台对接模式':'独立部署模式');
const syncLabel=(value?:string|null)=>({success:'成功',failed:'失败',running:'执行中',pending:'等待'} as Record<string,string>)[String(value||'')]||String(value||'')||'未提供';
function resetForm(){
 form.base_url=String(config.value?.base_url||'');
 form.access_key='';
 form.access_secret='';
}
function loadPlatform(){
 void reads.run('platform',signal=>request<{ok:boolean;config:PlatformConfig}>('/api/v63/external-algorithm-platform/config',{signal}).then(body=>{
  if(body?.ok!==true||!body.config)throw new Error('平台配置响应格式无效');
  return body.config;
 }),value=>{config.value=value;if(!editing.value)resetForm()});
}
function loadPublish(){
 void reads.run('publish',signal=>request<PublishConfigBody>('/api/v64/external-publish/config',{signal}).then(body=>{
  if(body?.ok!==true||!body.config)throw new Error('交付映射配置响应格式无效');
  return body;
 }),value=>{publish.value=value});
}
function load(){loadPlatform();loadPublish()}
load();
function startEdit(){editing.value=true;writeError.value='';notice.value='';resetForm()}
function cancelEdit(){editing.value=false;writeError.value='';notice.value='';resetForm()}
async function save(){
 if(saving.value||locked.value)return;
 const mode=external.value?'external':'local';
 // Contract-compatible with the original save payload: same field names, same
 // blank-secret semantics and the server-provided endpoint map unchanged.
 const body={mode,provider:'changlian',base_url:form.base_url.trim(),
  auto_sync_enabled:mode==='external',auto_publish_enabled:mode==='external',
  access_key:form.access_key.trim()||null,access_secret:form.access_secret||null,
  endpoints:config.value?.endpoints||{}};
 saving.value=true;writeError.value='';notice.value='';
 try{
  const saved=await request<{ok:boolean;config:PlatformConfig}>('/api/v63/external-algorithm-platform/config',{method:'PUT',body:JSON.stringify(body)});
  if(saved?.ok!==true||!saved.config)throw new Error('保存结果未返回权威配置，请刷新核对');
  config.value=saved.config;
  editing.value=false;resetForm();
  notice.value='平台对接配置已保存并锁定，后续将持续使用此配置';
 }catch(cause){if(!controller.signal.aborted)writeError.value=browseError(cause)}
 finally{saving.value=false}
}
const configurationFacts=computed<[string,unknown][]>(()=>{
 const value=config.value;
 if(!value)return[];
 return [
  ['运行模式',`${modeLabel.value}（${value.mode||'未提供'}）`],
  ['提供方',value.provider_name||value.provider],
  ['API 服务地址',value.base_url],
  ['配置更新时间',date(value.updated_at)],
  ['自动同步',value.auto_sync_enabled],
  ['同步计划',(value.auto_sync_schedule_local_times||[]).join(' / ')||'未提供'],
  ['同步时区',value.auto_sync_timezone],
  ['自动发布',value.auto_publish_enabled],
  ['应用鉴权模式',value.auth_mode],
  ['业务鉴权模式',value.business_auth_mode],
  ['凭据状态',credentialText.value],
  ['凭据存储后端',credential.value.backend],
  ['字段级配置版本',value.schema_version],
 ];
});
const syncFacts=computed<[string,unknown][]>(()=>{
 const value=config.value?.last_sync;
 if(!value)return[];
 return [['最近同步结果',syncLabel(value.status)],['同步方式',value.sync_type==='manual'?'手动':'自动'],['开始时间',date(value.started_at)],['完成时间',date(value.finished_at)],['同步错误',value.error?safe(value.error):value.error],['同步详情',value.detail?safe(value.detail):value.detail]];
});
const cacheFacts=computed<[string,unknown][]>(()=>{
 const value=config.value?.cache||{};
 return [['主数据同步时间',date(value.synced_at)],['主数据摘要',value.master_data_digest],['算法品目',value.category_count],['算法产品',value.product_count],['分析方式',value.analysis_count],['算力环境',value.compute_platform_count]];
});
const endpointRows=computed(()=>Object.entries(config.value?.endpoints||{}).map(([key,path])=>({key,path})));
const mappingLabels:Record<string,string>={original:'通用原始模型',onnx:'通用 ONNX',paddle_inference:'Paddle Inference'};
function platformIndex(rows:ComputePlatformRow[]){
 const index=new Map<string,ComputePlatformRow>();
 for(const row of rows){const id=String(row.computePlatformId??row.id??'').trim();if(id&&!index.has(id))index.set(id,row)}
 return index;
}
function platformPath(id?:string|null){
 const value=String(id||'').trim();
 if(!value)return '未绑定';
 const index=platformIndex(publish.value?.compute_platforms||[]),row=index.get(value);
 if(!row)return `ID ${value}（当前主数据未同步或已失效）`;
 const names=[String(row.computePlatformName||row.name||value)],seen=new Set([value]);
 let parent=String(row.parentId??'').trim().replace(/^(0|-1)$/,'');
 for(let depth=0;parent&&index.has(parent)&&!seen.has(parent)&&depth<8;depth+=1){
  const item=index.get(parent) as ComputePlatformRow;
  seen.add(parent);names.unshift(String(item.computePlatformName||item.name||parent));
  parent=String(item.parentId??'').trim().replace(/^(0|-1)$/,'');
 }
 const deleted=row.delFlag!=null&&String(row.delFlag)!=='0';
 return `${names.join(' / ')}${deleted?'（已删除/停用）':''} · ID ${value}`;
}
function chipLabel(localId:string){
 const chip=(publish.value?.local_catalog?.chips||[]).find(row=>row.id===localId);
 if(!chip)return `本地芯片 ${localId}（本地字典缺失）`;
 const vendor=(publish.value?.local_catalog?.vendors||[]).find(row=>row.id===chip.vendor_id);
 return `${vendor?.name||chip.vendor_id||'厂商未提供'} / ${chip.name||chip.id}${chip.sdk_code?`（${chip.sdk_code}）`:''}`;
}
const mappingRows=computed(()=>{
 const mappings=publish.value?.config?.target_mappings||{};
 const keys=[...new Set([...Object.keys(mappingLabels),...Object.keys(mappings)])];
 return keys.map(key=>{
  const mapping=mappings[key]||{};
  const vendor=key.startsWith('vendor:')?(publish.value?.local_catalog?.vendors||[]).find(row=>row.id===key.slice(7)):undefined;
  const chips=Object.entries(mapping.chip_mappings||{}).map(([localId,remoteId])=>({localId,local:chipLabel(localId),remote:platformPath(remoteId)}));
  const diagnostic=vendor?(publish.value?.mapping_diagnostics?.vendors||{})[vendor.id]:undefined;
  return {key,label:vendor?.name||mappingLabels[key]||key,enabled:mapping.enabled!==false,platform:platformPath(mapping.compute_platform_id),chip:mapping.chip_code||'',chips,diagnostic};
 });
});
const mappingFacts=computed<[string,unknown][]>(()=>{
 const value=publish.value?.config;
 if(!value)return[];
 return [
  ['映射版本',value.mapping_revision],
  ['本地字典版本',publish.value?.local_catalog?.revision],
  ['发布原始模型',value.publish_original_model],
  ['版本列表接口',value.version_list_by_product],
  ['权重列表接口',value.weight_list_by_version],
  ['映射历史条数',Array.isArray(value.mapping_history)?value.mapping_history.length:undefined],
  ['配置更新时间',date(value.updated_at)],
 ];
});
</script>
<template>
 <section aria-label="外部平台配置（原生只读与既有保存契约）">
  <div class="page-toolbar">
   <p>外部平台配置 / 平台对接 · 既有 API</p>
   <div>
    <el-button :loading="reads.busy.platform||reads.busy.publish" @click="load">刷新</el-button>
    <el-button tag="a" :href="legacyHref" type="primary">原平台对接（总开关 / 同步 / 测试）</el-button>
   </div>
  </div>
  <el-alert title="本页复用既有平台配置读取与保存接口；不触发连接测试、立即同步、联调诊断或任何外部平台请求。" type="info" :closable="false"/>
  <el-alert title="Secret 仅由后端安全存储持有。本页只显示后端返回的已配置布尔值与脱敏标识，不读取、不回显、不写入 localStorage 或 URL。" type="warning" :closable="false"/>
  <el-alert v-if="writeError" :title="writeError" type="error" :closable="false"/>
  <el-alert v-if="notice" :title="notice" type="success" :closable="false"/>
  <section class="version-panel" v-loading="reads.busy.platform" aria-label="平台配置概览">
   <header><div><h2>平台配置</h2><h3>来源：/api/v63/external-algorithm-platform/config</h3></div><el-tag :type="external?'success':'info'">{{ modeLabel }}</el-tag></header>
   <el-alert v-if="reads.errors.platform" :title="reads.errors.platform" type="error" :closable="false"/>
   <template v-if="config">
    <ReadOnlyFacts :fields="configurationFacts"/>
    <h3>最近同步</h3>
    <el-alert v-if="!config.last_sync" title="尚无同步记录；主数据以外部平台为准，本页不触发同步。" type="info" :closable="false"/>
    <template v-else>
     <ReadOnlyFacts :fields="syncFacts"/>
     <el-alert v-if="config.last_sync.error" :title="safe(config.last_sync.error)" type="error" :closable="false"/>
    </template>
    <h3>已同步主数据缓存</h3>
    <ReadOnlyFacts :fields="cacheFacts"/>
   </template>
  </section>
  <section class="version-panel" v-loading="reads.busy.platform" aria-label="连接配置">
   <header><div><h2>连接配置</h2><h3>{{ locked?'当前配置已锁定；点击“编辑配置”后才能修改':'保存成功后立即重新锁定' }}</h3></div>
    <div><el-button v-if="locked" type="primary" @click="startEdit">编辑配置</el-button><template v-else><el-button type="primary" :loading="saving" :disabled="!config" @click="save">保存配置</el-button><el-button v-if="savedConnectionReady" :disabled="saving" @click="cancelEdit">取消编辑</el-button></template></div>
   </header>
   <form v-if="config" class="algorithm-form" @submit.prevent="save">
    <label>外部平台<el-input :model-value="config.provider_name||config.provider||'未提供'" aria-label="外部平台" disabled/></label>
    <label>API 服务地址<el-input v-model="form.base_url" aria-label="API 服务地址" placeholder="https://api.example.com" maxlength="500" :disabled="locked||saving"/></label>
    <label>AccessKey<el-input v-model="form.access_key" aria-label="AccessKey" autocomplete="off" spellcheck="false" :disabled="locked||saving||credentialManaged||credentialUnavailable" :placeholder="credentialManaged?'由环境变量管理':credential.configured?'已配置，留空表示继续使用原 AccessKey':'请输入 AccessKey'"/></label>
    <label>AccessSecret<el-input v-model="form.access_secret" aria-label="AccessSecret" type="password" autocomplete="new-password" spellcheck="false" :disabled="locked||saving||credentialManaged||credentialUnavailable" :placeholder="credentialManaged?'由环境变量管理':credential.configured?'已配置，编辑时留空表示继续使用原 Secret':'请输入 AccessSecret'"/></label>
    <p>凭据状态：{{ credentialText }} · 存储后端：{{ credential.backend||'未提供' }}。{{ credentialUnavailable?'安全存储不可用，保存凭据会失败关闭，不会降级为明文。':credentialManaged?'凭据由环境变量管理，本页不覆盖。':'AccessSecret 仅提交给后端安全存储，保存后立即清空输入。' }}</p>
    <el-alert v-if="credentialUnavailable" title="安全存储不可用：只能查看公开配置，不能保存新的 AccessKey / AccessSecret。" type="warning" :closable="false"/>
    <p><small>总开关（mode）、立即同步、连接测试与联调诊断仍只在 <a :href="legacyHref">原平台对接</a> 中执行；本页保存不会替代这些外部操作。</small></p>
   </form>
   <el-alert v-else-if="!reads.busy.platform" title="平台配置尚未读取成功，暂不提供编辑。" type="info" :closable="false"/>
  </section>
  <section class="version-panel" v-loading="reads.busy.platform" aria-label="平台接口路径配置">
   <header><div><h2>平台接口路径</h2><h3>只读展示后端权威路径；保存时原样回传</h3></div></header>
   <details>
    <summary>展开 {{ endpointRows.length }} 项固定路径</summary>
    <el-table :data="endpointRows" row-key="key" size="small" empty-text="尚未读取到接口路径">
     <el-table-column prop="key" label="配置键" min-width="180"/>
     <el-table-column prop="path" label="路径" min-width="320"/>
    </el-table>
   </details>
  </section>
  <section class="version-panel" v-loading="reads.busy.publish" aria-label="交付映射配置（只读）">
   <header><div><h2>交付映射配置</h2><h3>来源：/api/v64/external-publish/config · 只读</h3></div><el-tag type="info">映射编辑使用原平台对接</el-tag></header>
   <el-alert v-if="reads.errors.publish" :title="reads.errors.publish" type="error" :closable="false"/>
   <template v-if="publish?.config">
    <ReadOnlyFacts :fields="mappingFacts"/>
    <el-table :data="mappingRows" row-key="key" size="small" empty-text="尚无映射配置">
     <el-table-column label="交付目标" min-width="190"><template #default="{row}"><strong>{{ row.label }}</strong><small>{{ row.key }}</small><small>发布启用：{{ row.enabled?'是':'否' }}</small></template></el-table-column>
     <el-table-column label="畅联云算力环境" min-width="260"><template #default="{row}">{{ row.platform }}<small v-if="row.chip">固定芯片编码 {{ row.chip }}</small></template></el-table-column>
     <el-table-column label="芯片绑定（本地 → 远端）" min-width="300"><template #default="{row}"><template v-if="row.chips.length"><p v-for="chip in row.chips" :key="chip.localId">{{ chip.local }} → {{ chip.remote }}</p></template><span v-else>未绑定芯片</span></template></el-table-column>
     <el-table-column label="映射诊断" min-width="180"><template #default="{row}"><el-tag v-if="row.diagnostic" :type="row.diagnostic.status==='BOUND'?'success':row.diagnostic.status==='DISABLED'?'info':'warning'">{{ row.diagnostic.status||'未提供' }}</el-tag><small>{{ row.diagnostic?.reason||'未提供诊断' }}</small></template></el-table-column>
    </el-table>
    <template v-if="(publish.mapping_diagnostics?.legacy_proposals||[]).length">
     <h3>历史映射迁移建议（仅提示，不自动采用）</h3>
     <p v-for="(proposal,index) in publish.mapping_diagnostics?.legacy_proposals||[]" :key="index">{{ proposal.legacy_target||'未提供目标' }} → {{ proposal.local_vendor_id||'未提供厂商' }} · {{ proposal.status||'未提供状态' }} · {{ proposal.reason||'' }}</p>
    </template>
    <h3>发布存储源</h3>
    <el-table :data="publish.storage_sources||[]" row-key="id" size="small" empty-text="尚无发布存储源">
     <el-table-column label="存储源" min-width="200"><template #default="{row}"><strong>{{ row.name||row.id }}</strong><small>{{ row.id }} · {{ row.type||'类型未提供' }}</small></template></el-table-column>
     <el-table-column label="状态" min-width="180"><template #default="{row}"><el-tag :type="row.health_status==='HEALTHY'?'success':'info'">{{ row.health_status||'未提供' }}</el-tag><small>{{ row.is_default?'默认存储源':'非默认' }} · {{ row.enabled===false?'已停用':'已启用' }}</small></template></el-table-column>
     <el-table-column label="密钥状态" min-width="200"><template #default="{row}"><el-tag :type="row.secret_configured?'success':'warning'">{{ row.secret_configured?'已配置':'未配置' }}</el-tag><small>{{ row.secret_masked||'无脱敏标识' }}</small></template></el-table-column>
    </el-table>
    <p><small>映射与存储源的编辑仍使用 <a :href="legacyHref">原平台对接 / 存储配置</a>；本页不回传或改写映射，避免绕过既有校验与 revision 合同。</small></p>
   </template>
  </section>
 </section>
</template>
