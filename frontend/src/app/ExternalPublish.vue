<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {modelBrowseApi} from '../api/model-browse';
import type {AlgorithmSummary,Paged,VersionPage} from '../types/model-browse';
import {useReadScope} from '../composables/useReadScope';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
import {request} from './http';
import {legacyUrl} from './navigation';
// Read-only native view of the existing external-publish owner. Every fact
// comes from the existing v64 status projection; this page never calls the
// publish/run-auto/selection endpoints and never contacts the external platform.
interface PublishQuality {
  schema?:string;target?:string;numeric_required?:boolean;numeric_status?:string;
  numeric_status_alone_is_sufficient?:boolean;
  numeric_evidence?:{eligible?:boolean;code?:string;reasons?:string[];verdict?:string;detection_status?:string;
    sample_count?:number|null;binding_status?:string;identity_status?:string;verification_id?:string;evidence_ref?:string}|null;
  runtime_verified?:boolean;hardware_verified?:boolean;hardware_acceptance?:string;
  formal_activation_eligible?:boolean;delivery_presentation?:string;attachment_delivery_allowed?:boolean;
  present_as_formal_activation?:boolean;present_as_hardware_accepted?:boolean;code?:string;reasons?:string[];
}
interface PublishArtifact {
  artifact_id?:string;file_name?:string;target?:string;chip_code?:string;mapped_chip_code?:string;remote_chip_code?:string;
  compute_platform_id?:string;publish_mapping_status?:string;publish_mapping_detail?:string;
  sync_status?:string;storage_status?:string;upload_status?:string;external_weight_id?:string;
  delivery_role?:string;included_in_delivery?:boolean;remote_registered?:boolean;
  metadata_sync_status?:string;metadata_note?:string;last_error?:string;review_required?:boolean;
  recovery_plan?:{code?:string;reason?:string;suggested_operation?:string;automatic_write_allowed?:boolean}|null;
  remote_identity_status?:string;sha256?:string;size_bytes?:number|null;quality_preflight?:PublishQuality;
  formal_activation_eligible?:boolean;delivery_presentation?:string;hardware_acceptance?:string;
}
interface Publication {
  publication_key?:string;status?:string;last_error?:string;attempts?:number;
  created_at?:string|null;updated_at?:string|null;published_at?:string|null;
  remote_checked_at?:string|null;remote_check_error?:string;external_algo_version_id?:string;
  external_product_id?:string;external_analysis_id?:string;version_name?:string;version_no?:string;
}
interface IdentityIssue {code?:string;message?:string;detail?:string;solution?:string}
interface TransportIssue {code?:string;message?:string;detail?:string;solution?:string}
interface PublishStatus {
  ok:boolean;project_id:string;
  algorithm:{id:string;name?:string;external_product_id?:string};
  version:{id:string;version_name?:string;version_no?:string;external_algo_version_id?:string;
    external_publish_status?:string;model_metadata?:Record<string,unknown>;label_codes?:string[]};
  publication:Publication|null;artifacts:PublishArtifact[];discovered?:PublishArtifact[];
  weight_delivery_status?:string;requires_sync?:boolean;
  mapped_artifact_count?:number;blocked_artifact_count?:number;ignored_artifact_count?:number;deferred_conversion_count?:number;
  transport_ready?:boolean;transport_issues?:TransportIssue[];public_base_url_configured?:boolean;
  identity_ready?:boolean;identity_issues?:IdentityIssue[];
  publish_ready?:boolean;conversion_active?:boolean;
}
const props=defineProps<{projectId:string}>();
const route=useRoute(),router=useRouter(),controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
const reads=useReadScope(controller);
const api=modelBrowseApi({projectId:props.projectId,algorithmPageSize:20,get:request});
const queryText=(key:string)=>typeof route.query[key]==='string'?String(route.query[key]):'';
const pageNumber=(key:string)=>{const value=Number(queryText(key));return Number.isSafeInteger(value)&&value>0?value:1};
const algorithmPage=computed(()=>pageNumber('page')),versionPage=computed(()=>pageNumber('version_page'));
const selected=computed(()=>queryText('algorithm')),versionId=computed(()=>queryText('version'));
const algorithms=ref<Paged<AlgorithmSummary>|null>(null),versions=ref<VersionPage|null>(null),status=ref<PublishStatus|null>(null);
const selectedAlgorithm=computed(()=>algorithms.value?.items.find(row=>row.id===selected.value)||null);
const selectedVersion=computed(()=>versions.value?.items.find(row=>row.id===versionId.value)||null);
function loadAlgorithms(){void reads.run('algorithms',signal=>api.algorithms({source_type:'external',page:algorithmPage.value},signal),value=>{algorithms.value=value})}
function loadVersions(){if(!selected.value)return;void reads.run('versions',signal=>api.versions(selected.value,versionPage.value,signal),value=>{versions.value=value})}
function loadStatus(){
 const aid=selected.value,vid=versionId.value;
 if(!aid||!vid)return;
 void reads.run('publication',signal=>request<PublishStatus>(
  `/api/v64/external-publish/projects/${encodeURIComponent(props.projectId)}/algorithms/${encodeURIComponent(aid)}/versions/${encodeURIComponent(vid)}`,
  {signal},
 ).then(value=>{
  // The page only presents a projection that proves the exact project/algorithm/version identity.
  if(value?.ok!==true||value.project_id!==props.projectId||value.algorithm?.id!==aid||value.version?.id!==vid)throw new Error('交付状态响应身份不一致');
  return value;
 }),value=>{status.value=value});
}
watch(algorithmPage,()=>{reads.cancel('algorithms');algorithms.value=null;loadAlgorithms()},{immediate:true});
watch([selected,versionPage],()=>{reads.cancel('versions');versions.value=null;loadVersions()},{immediate:true});
watch([selected,versionId],()=>{reads.cancel('publication');status.value=null;loadStatus()},{immediate:true});
function choose(id:string){void router.push({query:{...route.query,algorithm:id||undefined,version:undefined,version_page:undefined}})}
function openStatus(id:string){void router.push({query:{...route.query,version:id||undefined}})}
function changeVersionPage(value:number){void router.push({query:{...route.query,version_page:value===1?undefined:String(value)}})}
function paginate(value:number){void router.push({query:{...route.query,page:value===1?undefined:String(value)}})}
const legacyHref=computed(()=>legacyUrl(props.projectId,'算法列表',selected.value,versionId.value,'delivery'));
const legacyListHref=legacyUrl(props.projectId,'算法列表');
const legacyDeliveryHref=computed(()=>versionId.value?legacyHref.value:legacyListHref);
const text=(value:unknown)=>value===null||value===undefined||value===''?'未提供':String(value);
// Same sanitisation the legacy delivery snapshot applies before rendering
// provider/OSS errors: hide addresses, tokens and local paths, never echo a
// credential-shaped value back into the page.
function safe(value:unknown){
 return String(value??'').replace(/https?:\/\/\S+/g,'[地址已隐藏]')
  .replace(/(?:Bearer\s+)[^\s,;]+/gi,'Bearer [已隐藏]')
  .replace(/(token|password|secret|api[_-]?key|authorization)["']?\s*[:=]\s*[^\s,;}]+/gi,'$1=[已隐藏]')
  .replace(/[A-Za-z]:[\\/][^\s,;]+|(?:\/[\w.\-]+){2,}/g,'[路径已隐藏]').slice(0,800);
}
const date=(value?:string|null)=>value?String(value).replace('T',' ').slice(0,19):'未提供';
type TagType='success'|'danger'|'warning'|'info';
function tagType(value?:string|null):TagType{
 const state=String(value||'').toUpperCase();
 if(['SYNCED','PUBLISHED','SUCCESS','SUCCEEDED','VERIFIED','READ_BACK'].includes(state))return 'success';
 if(['FAILED','CONFLICT','ERROR'].includes(state))return 'danger';
 if(['UNKNOWN','PARTIAL','PENDING','PENDING_READBACK','NOT_VERIFIED','REVIEW'].includes(state))return 'warning';
 return 'info';
}
function presentation(row:PublishArtifact){
 const raw=String(row.delivery_presentation||row.quality_preflight?.delivery_presentation||'').trim();
 if(raw==='FORMAL_ACTIVATION')return {raw,label:'正式启用',type:'success' as TagType,note:''};
 if(raw==='UNVERIFIED_ATTACHMENT')return {raw,label:'未验证附件 · 不可视为正式启用',type:'warning' as TagType,note:'仅可作为未验证附件交付'};
 return {raw:raw||'未提供',label:'交付呈现未提供 · 不视为正式启用',type:'info' as TagType,note:''};
}
function quality(row:PublishArtifact):PublishQuality{return row.quality_preflight||{}}
function reasonsText(value?:string[]){return Array.isArray(value)&&value.length?value.slice(0,4).join('；'):''}
function mappingLabel(row:PublishArtifact){
 const state=String(row.publish_mapping_status||'');
 return ({mapped:'已映射',blocked:'映射阻塞',ignored:'已关闭发布'} as Record<string,string>)[state]||state||'未提供';
}
function roleLabel(row:PublishArtifact){
 const state=String(row.delivery_role||'');
 const labels:Record<string,string>={HISTORICAL:'历史成果',CONFIRMED_OWNER:'当前交付',AUTOMATIC_CURRENT:'自动当前交付',SINGLE_CANDIDATE:'自动交付候选',UNVERIFIED:'未验证登记',UNSELECTED:'未选中'};
 return labels[state]||state||'未提供';
}
const statusFacts=computed<[string,unknown][]>(()=>{
 const value=status.value;
 if(!value)return[];
 const publication=value.publication||{};
 return [
  ['算法',`${text(value.algorithm.name)}（${value.algorithm.id}）`],
  ['外部产品 ID',value.algorithm.external_product_id],
  ['版本',`${text(value.version.version_name)}（${value.version.id}）`],
  ['版本号',value.version.version_no],
  ['外部算法版本 ID',value.version.external_algo_version_id],
  ['版本交付状态（后端投影）',value.version.external_publish_status],
  ['发布记录状态',publication.status],
  ['权重交付状态',value.weight_delivery_status],
  ['需要同步',value.requires_sync],
  ['版本发布准入',value.publish_ready],
  ['外部身份校验',value.identity_ready],
  ['交付传输就绪',value.transport_ready],
  ['公开访问地址已配置',value.public_base_url_configured],
  ['转换进行中',value.conversion_active],
 ];
});
const publicationFacts=computed<[string,unknown][]>(()=>{
 const value=status.value?.publication;
 if(!value)return[];
 return [
  ['发布记录标识',value.publication_key],
  ['发布记录状态',value.status],
  ['失败原因',value.last_error?safe(value.last_error):value.last_error],
  ['尝试次数',value.attempts],
  ['外部算法版本 ID',value.external_algo_version_id],
  ['外部产品 ID',value.external_product_id],
  ['外部分析方式 ID',value.external_analysis_id],
  ['创建时间',date(value.created_at)],
  ['更新时间',date(value.updated_at)],
  ['发布时间',date(value.published_at)],
  ['远端核对时间',date(value.remote_checked_at)],
  ['远端核对错误',value.remote_check_error?safe(value.remote_check_error):value.remote_check_error],
 ];
});
</script>
<template>
 <section aria-label="外部发布列表与只读详情">
  <div class="page-toolbar">
   <p>外部发布 / 新畅联交付 · 只读核对</p>
   <div>
    <el-button @click="loadAlgorithms();loadVersions();loadStatus()">刷新</el-button>
    <el-button tag="a" :href="legacyListHref">原完整算法管理</el-button>
    <el-button tag="a" :href="legacyDeliveryHref" type="primary">原「新畅联交付」</el-button>
   </div>
  </div>
  <el-alert title="本页只读：直接读取既有交付状态投影，不提供发布、同步、重试或权重选择操作，也不会访问外部平台。" type="info" :closable="false"/>
  <el-alert title="数值质量状态、硬件验证状态、发布准入状态是三项独立事实；只有后端判定可正式启用时才呈现 FORMAL_ACTIVATION，UNVERIFIED_ATTACHMENT 仅为未验证附件。" type="warning" :closable="false"/>
  <el-alert v-if="reads.errors.algorithms" :title="reads.errors.algorithms" type="error" :closable="false"/>
  <section class="version-panel" aria-label="外部平台算法列表">
   <header><div><h2>外部平台算法</h2><h3>来源为外部平台（external）；新畅联交付投影仅适用于 CHANG_LIAN 提供方</h3></div><span v-if="algorithms">共 {{ algorithms.total }} 个算法</span></header>
   <el-table :data="algorithms?.items||[]" row-key="id" v-loading="reads.busy.algorithms" empty-text="当前项目没有外部平台算法">
    <el-table-column label="算法" min-width="220"><template #default="{row}"><strong>{{ row.name }}</strong><small>{{ row.id }}</small></template></el-table-column>
    <el-table-column label="提供方" width="130"><template #default="{row}"><el-tag :type="String(row.provider_type||'').toUpperCase()==='CHANG_LIAN'?'success':'info'">{{ row.provider_type||'未提供' }}</el-tag></template></el-table-column>
    <el-table-column label="外部产品 / 当前版本" min-width="200"><template #default="{row}"><span>{{ row.external_product_id||'未提供' }}</span><small>{{ row.current_version?.version_name||row.current_version_id||'未设置' }}</small></template></el-table-column>
    <el-table-column label="版本数" width="90"><template #default="{row}">{{ row.version_count??'未提供' }}</template></el-table-column>
    <el-table-column label="操作" min-width="140"><template #default="{row}"><el-button link :type="selected===row.id?'primary':'default'" @click="choose(selected===row.id?'':row.id)">{{ selected===row.id?'收起版本':'查看版本' }}</el-button></template></el-table-column>
   </el-table>
   <div v-if="algorithms" class="pagination"><span>第 {{ algorithms.page }} / {{ Math.max(1,Math.ceil(algorithms.total/algorithms.page_size)) }} 页</span><el-pagination :current-page="algorithms.page" :page-size="algorithms.page_size" :total="algorithms.total" layout="prev, pager, next" @current-change="paginate"/></div>
  </section>
  <section v-if="selected" class="version-panel" aria-label="算法版本与交付状态入口">
   <header><div><h2>{{ versions?.algorithm.name||selectedAlgorithm?.name||selected }}</h2><h3>选择版本后读取只读交付状态（列表状态取自版本记录字段，详情以发布记录投影为准）</h3></div><span v-if="versions">共 {{ versions.total }} 个版本</span></header>
   <el-alert v-if="reads.errors.versions" :title="reads.errors.versions" type="error" :closable="false"/>
   <el-alert v-if="selectedAlgorithm&&String(selectedAlgorithm.provider_type||'').toUpperCase()!=='CHANG_LIAN'" title="当前算法提供方不是 CHANG_LIAN；新畅联交付投影可能只返回身份未就绪等事实，不作为可交付依据。" type="warning" :closable="false"/>
   <el-table :data="versions?.items||[]" row-key="id" v-loading="reads.busy.versions" empty-text="暂无版本">
    <el-table-column label="模型版本" min-width="200"><template #default="{row}"><strong>{{ row.version_name||row.id }}</strong><small>{{ row.id }}</small></template></el-table-column>
    <el-table-column prop="version_no" label="版本号" width="120"/>
    <el-table-column label="训练状态" min-width="110"><template #default="{row}">{{ row.training_status||'未提供' }}</template></el-table-column>
    <el-table-column label="版本记录字段 · 发布状态" min-width="150"><template #default="{row}"><el-tag :type="tagType(row.external_publish_status)">{{ row.external_publish_status||'未提供' }}</el-tag></template></el-table-column>
    <el-table-column label="完成时间" min-width="150"><template #default="{row}">{{ date(row.finished_at||row.created_at) }}</template></el-table-column>
    <el-table-column label="操作" min-width="190"><template #default="{row}"><el-button link :disabled="versionId===row.id" @click="openStatus(row.id)">{{ versionId===row.id?'当前只读详情':'查看交付状态（只读）' }}</el-button></template></el-table-column>
   </el-table>
   <el-pagination v-if="versions" :current-page="versions.page" :page-size="versions.page_size" :total="versions.total" layout="prev, pager, next" @current-change="changeVersionPage"/>
  </section>
  <section v-if="versionId" class="version-panel" aria-label="外部发布只读详情" v-loading="reads.busy.publication">
   <header><div><h2>交付状态只读详情</h2><h3>{{ selectedVersion?.version_name||versionId }} · 后端原始投影</h3></div><el-button @click="loadStatus">重新读取</el-button></header>
   <el-alert v-if="reads.errors.publication" :title="reads.errors.publication" type="error" :closable="false"/>
   <template v-if="status">
    <ReadOnlyFacts :fields="statusFacts"/>
    <el-alert v-if="status.identity_ready===false" type="warning" :closable="false" title="外部身份未就绪，版本不能进入正式交付">
     <p v-for="issue in status.identity_issues||[]" :key="issue.code||issue.message">{{ issue.code||'EXTERNAL_IDENTITY_NOT_READY' }} · {{ safe(issue.message||issue.detail)||'未提供原因' }}</p>
    </el-alert>
    <el-alert v-if="status.transport_ready===false" type="warning" :closable="false" title="交付传输未就绪">
     <p v-for="issue in status.transport_issues||[]" :key="issue.code||issue.message">{{ issue.code||'' }} {{ safe(issue.message||issue.detail)||'未提供原因' }}</p>
    </el-alert>
    <p>已发现可交付产物：{{ (status.discovered||[]).length }} · 已映射 {{ status.mapped_artifact_count??'未提供' }} · 阻塞 {{ status.blocked_artifact_count??'未提供' }} · 关闭发布 {{ status.ignored_artifact_count??'未提供' }} · 延后转换 {{ status.deferred_conversion_count??'未提供' }}</p>
    <h3>发布记录</h3>
    <el-alert v-if="!status.publication" title="尚未创建发布记录：该版本还没有进入外部交付流程。" type="info" :closable="false"/>
    <template v-else>
     <ReadOnlyFacts :fields="publicationFacts"/>
     <el-alert v-if="status.publication.last_error" :title="'发布失败原因：'+safe(status.publication.last_error)" type="error" :closable="false"/>
    </template>
    <h3>交付产物与独立事实</h3>
    <el-table :data="status.artifacts||[]" empty-text="该版本尚未发现可交付产物">
     <el-table-column label="产物 / 目标芯片" min-width="210"><template #default="{row}"><strong>{{ row.file_name||row.artifact_id||'未登记' }}</strong><small>目标 {{ row.target||'未提供' }} · 芯片 {{ row.remote_chip_code||row.mapped_chip_code||row.chip_code||'通用' }}</small><small>产物 {{ row.artifact_id||'未登记' }} · {{ row.size_bytes??'大小未提供' }} bytes</small></template></el-table-column>
     <el-table-column label="外部平台关联（映射）" min-width="220"><template #default="{row}"><el-tag :type="row.publish_mapping_status==='mapped'?'success':row.publish_mapping_status==='blocked'?'warning':'info'">{{ mappingLabel(row) }} {{ row.publish_mapping_status||'' }}</el-tag><small>算力环境 {{ row.compute_platform_id||'未绑定' }}</small><small v-if="row.publish_mapping_detail">{{ safe(row.publish_mapping_detail) }}</small><small>交付角色 {{ roleLabel(row) }} · {{ row.delivery_role||'' }}</small><small>包含在本次交付：{{ row.included_in_delivery===false?'否':'是' }} · 远端已登记：{{ row.remote_registered?'是':'否' }}</small></template></el-table-column>
     <el-table-column label="发布记录与同步状态" min-width="240"><template #default="{row}"><el-tag :type="tagType(row.sync_status)">{{ row.sync_status||'未提供' }}</el-tag><small>Weight {{ row.external_weight_id||'未确认' }}</small><small>上传 {{ row.upload_status||'未提供' }} · 存储 {{ row.storage_status||'未提供' }}</small><small>元数据同步 {{ row.metadata_sync_status||'未提供' }} · 远端身份 {{ row.remote_identity_status||'未提供' }}</small><small v-if="row.last_error" class="algorithm-blocked">失败原因：{{ safe(row.last_error) }}</small><small v-if="row.metadata_note">{{ safe(row.metadata_note) }}</small><small v-if="row.review_required" class="algorithm-blocked">需人工核对：{{ safe(row.recovery_plan?.reason)||row.recovery_plan?.code||'未提供原因' }}（建议 {{ row.recovery_plan?.suggested_operation||'READ_ONLY_RECOVERY' }}）</small></template></el-table-column>
     <el-table-column label="数值质量状态（独立事实）" min-width="210"><template #default="{row}"><el-tag :type="tagType(quality(row).numeric_status)">{{ quality(row).numeric_status||'未提供' }}</el-tag><small>{{ quality(row).numeric_required===true?'转换产物需数值证据':quality(row).numeric_required===false?'原始模型不要求数值证据':'数值证据要求未提供' }}</small><small>证据 {{ quality(row).numeric_evidence?.eligible===true?'合格':quality(row).numeric_evidence?.eligible===false?'不合格':'未提供' }} · 结论 {{ quality(row).numeric_evidence?.verdict||'未提供' }} · 样本 {{ quality(row).numeric_evidence?.sample_count??'未提供' }}</small><small>{{ quality(row).numeric_status_alone_is_sufficient===false?'数值状态本身不构成准入依据':'未提供充分性说明' }}</small></template></el-table-column>
     <el-table-column label="硬件验证状态（独立事实）" min-width="170"><template #default="{row}"><el-tag :type="quality(row).hardware_acceptance==='VERIFIED'?'success':'warning'">{{ quality(row).hardware_acceptance||'未提供' }}</el-tag><small>{{ quality(row).hardware_verified===true?'已记录实机验证':'未记录实机验证，不得视为通过' }}</small></template></el-table-column>
     <el-table-column label="发布准入状态（独立事实）" min-width="210"><template #default="{row}"><el-tag :type="quality(row).formal_activation_eligible===true?'success':'warning'">{{ quality(row).formal_activation_eligible===true?'可正式启用':quality(row).formal_activation_eligible===false?'不可正式启用':'未提供 · 不视为可正式启用' }}</el-tag><small>后端 formal_activation_eligible={{ quality(row).formal_activation_eligible===true?'true':quality(row).formal_activation_eligible===false?'false':'未提供' }}</small><small v-if="quality(row).code">准入码 {{ quality(row).code }}</small><small v-if="reasonsText(quality(row).reasons)">原因：{{ reasonsText(quality(row).reasons) }}</small></template></el-table-column>
     <el-table-column label="交付呈现（后端原值）" min-width="200"><template #default="{row}"><el-tag :type="presentation(row).type">{{ presentation(row).raw }}</el-tag><small>{{ presentation(row).label }}</small><small v-if="presentation(row).note">{{ presentation(row).note }}</small><small>仅附件可交付：{{ quality(row).attachment_delivery_allowed===true?'是':quality(row).attachment_delivery_allowed===false?'否':'未提供' }}</small></template></el-table-column>
    </el-table>
    <p><small>数值质量、硬件验证、发布准入分别由后端投影原样展示，互不替代。正式交付与人工确认请使用 <a :href="legacyDeliveryHref">原「新畅联交付」</a>。</small></p>
   </template>
  </section>
  <el-empty v-if="!algorithms&&!reads.busy.algorithms" description="暂无外部平台算法"/>
 </section>
</template>
