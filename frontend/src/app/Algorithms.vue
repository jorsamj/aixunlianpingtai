<script setup lang="ts">
import {computed,onUnmounted,reactive,ref,watch} from 'vue';
import {useRoute,useRouter,type LocationQuery} from 'vue-router';
import {modelBrowseApi,browseError} from '../api/model-browse';
import {algorithmManagementApi,type AlgorithmForm,type AlgorithmBasic} from '../api/algorithm-management';
import {deletedVersion,retryVersionCleanup,type LifecycleTarget,type VersionOperation} from '../api/algorithm-lifecycle';
import type {AlgorithmCategory,AlgorithmSummary,ModelVersion,Paged,VersionPage,VersionDetail} from '../types/model-browse';
import {useReadScope} from '../composables/useReadScope';
import AlgorithmLifecycleDialog from '../components/AlgorithmLifecycleDialog.vue';
import ModelVersionDetails from '../components/ModelVersionDetails.vue';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
import {request} from './http';
import {useWorkspace} from './main';
import {legacyUrl} from './navigation';
const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId),scope=new AbortController();
onUnmounted(()=>scope.abort());
// Reuse the existing project-scoped algorithm journal format; it is not business truth.
type PendingWrite={algorithmId:string;versionId?:undefined;body:AlgorithmForm}|{algorithmId:string;versionId:string;body:{remark:string}};
const pendingKey='cl_vue_algorithm_pending_v1:'+projectId,pending=ref<PendingWrite|null>(null),pendingError=ref(''),checking=ref(false),checkId=ref('');
try{
 const stored=JSON.parse(sessionStorage.getItem(pendingKey)||'null');
 if(stored){
  const versionWrite=Object.hasOwn(stored,'versionId');
  const keys=versionWrite?['remark']:['name','remark','industry','algorithm_type'];
  if(typeof stored.algorithmId!=='string'||(versionWrite&&(!stored.algorithmId||typeof stored.versionId!=='string'||!stored.versionId))||!stored.body||!keys.every(key=>typeof stored.body[key]==='string')||Object.keys(stored.body).length!==keys.length)throw new Error('待核记录无效');
  pending.value=stored;
  checkId.value=stored.algorithmId;
 }
}catch{pendingError.value='待核记录无法读取，请到原完整算法管理核对；本页暂不提交。'}
const unconfirmed=computed(()=>!!pending.value||!!pendingError.value);
function savePending(value:PendingWrite|null){if(value)sessionStorage.setItem(pendingKey,JSON.stringify(value));else sessionStorage.removeItem(pendingKey);pending.value=value}
const owner={projectId,algorithmLibrary:true,algorithmPageSize:10,get:<T,>(url:string,options?:{signal?:AbortSignal})=>request<T>(url,options),
 async writeAlgorithm(method:'POST'|'PUT',id:string,body:AlgorithmForm){const result=await request<{ok:boolean;algorithm:{id:string}}>(`/api/v12/projects/${encodeURIComponent(projectId)}/algorithms${id?'/'+encodeURIComponent(id):''}?asset_view=true`,{method,body:JSON.stringify(body)});if(result.ok&&result.algorithm?.id&&(!id||id===result.algorithm.id)){savePending({algorithmId:result.algorithm.id,body});checkId.value=result.algorithm.id}return result}};
const api=modelBrowseApi(owner),management=algorithmManagementApi(owner),reads=useReadScope(scope);
const filterKeys=['query','algorithm_type','industry','source_type','training_state','category_ids','sort'] as const;
const filterLabels={query:'搜索',algorithm_type:'算法类型',industry:'行业',source_type:'来源',training_state:'训练状态',category_ids:'外部分类',sort:'排序'};
const trainingLabels:Record<string,string>={all:'全部',trainable:'可训练',training:'训练中',trained:'已有训练版本',untrained:'尚未训练',blocked:'不可训练'};
const sourceLabels:Record<string,string>={internal:'本平台',external:'外部平台'};
const sortLabels:Record<string,string>={comprehensive:'综合排序',updated:'最近更新',training:'训练次数',metric:'mAP50',created:'最近创建',name:'名称升序',name_desc:'名称降序'};
const statusLabels:Record<string,string>={queued:'排队中',waiting:'等待资源',pending:'等待提交',starting:'启动中',running:'训练中',training:'训练中',paused:'已暂停',succeeded:'已训练',success:'已训练',completed:'已训练',failed:'训练失败',cancelled:'已取消'};
const defaults={query:'',algorithm_type:'',industry:'',source_type:'',training_state:'all',category_ids:'',sort:'comprehensive',page:1};
function routeFilters(routeQuery:LocationQuery){
 const result={...defaults};
 for(const key of filterKeys){if(typeof routeQuery[key]==='string'&&routeQuery[key])result[key]=routeQuery[key]}
 const page=Number(routeQuery.page);
 if(Number.isSafeInteger(page)&&page>0)result.page=page;
 return result;
}
const filterStorageKey='cl_vue_algorithm_library_filters_v1:'+projectId;
const appliedFilters=computed(()=>routeFilters(route.query));
const filters=reactive({...appliedFilters.value});
const categorySelection=computed({
 get:()=>filters.category_ids.split(',').filter(Boolean),
 set:(value:string[])=>{filters.category_ids=(value||[]).join(',')},
});
const categoryProps={multiple:true,emitPath:false,checkStrictly:false};
type CategoryNode={value:string;label:string;children?:CategoryNode[]};
const categoryTree=computed(()=>{
 const groups=new Map<string,AlgorithmCategory[]>();
 const categories=algorithms.value?.categories||[];
 const ids=new Set(categories.map(category=>String(category.id)));
 for(const category of categories){
  const parentId=String(category.parentId||'');
  const parent=ids.has(parentId)?parentId:'';
  const siblings=groups.get(parent)||[];
  siblings.push(category);
  groups.set(parent,siblings);
 }
 function children(parent:string,ancestors:Set<string>):CategoryNode[]{
  return (groups.get(parent)||[]).flatMap(({id,name})=>{
   const value=String(id);
   if(!value||ancestors.has(value))return [];
   const nested=children(value,new Set([...ancestors,value]));
   return [{value,label:name,children:nested.length?nested:undefined}];
  });
 }
 return children('',new Set());
});
const appliedTags=computed(()=>filterKeys.flatMap(key=>{
 const value=appliedFilters.value[key];
 if(value===defaults[key])return [];
 const labels=key==='source_type'?sourceLabels:key==='training_state'?trainingLabels:key==='sort'?sortLabels:undefined;
 const text=key==='category_ids'?value.split(',').map(id=>algorithms.value?.categories?.find(item=>String(item.id)===id)?.name||id).join('、'):labels?.[value]||value;
 return [{key,label:filterLabels[key]+' · '+text}];
}));
function external(algorithm:AlgorithmSummary){return algorithm.source_type?.toLowerCase()==='external'}
function canRetireVersion(algorithm:AlgorithmSummary){return !external(algorithm)||algorithm.provider_type?.toUpperCase()!=='CHANG_LIAN'}
function canOpenExternalPublish(algorithm:AlgorithmSummary){return external(algorithm)&&algorithm.provider_type?.toUpperCase()==='CHANG_LIAN'}
function sourceLabel(algorithm:AlgorithmSummary){
 if(!external(algorithm))return '本平台';
 return algorithm.source_name||(algorithm.provider_type?.toUpperCase()==='CHANG_LIAN'?'新畅联':'外部平台');
}
function stateLabel(status?:string|null){return status?statusLabels[status.toLowerCase()]||status:'未提供'}
function algorithmState(algorithm:AlgorithmSummary){
 if(algorithm.training_status)return stateLabel(algorithm.training_status);
 if(algorithm.trainable===false)return '不可训练';
 if(algorithm.current_version)return '可继续迭代';
 return '尚未训练';
}
function dateLabel(value?:string){return value?value.replace('T',' ').slice(0,19):'未提供'}
function original(aid:string,action:string,vid=''){return legacyUrl(projectId,'算法列表',aid,vid,action)}
function versionReport(algorithmId:string,versionId:string,evaluation=false){
 return {name:'version-report',params:{projectId,algorithmId,versionId},query:{tab:evaluation?'evaluation':undefined,back:route.fullPath}};
}
const algorithms=ref<Paged<AlgorithmSummary>|null>(null),versions=ref<VersionPage|null>(null),detail=ref<VersionDetail|null>(null),basic=ref<AlgorithmBasic|null>(null);
const selected=computed(()=>String(route.query.algorithm||'')),versionPage=ref(1),drawer=ref(false),editing=ref(false),editingId=ref(''),saving=ref(false),writeError=ref('');
const lifecycleTarget=ref<LifecycleTarget|null>(null);
const lifecycleKey='algorithm-lifecycle:'+JSON.stringify([useWorkspace().actorKey,projectId]);
const lifecyclePending=ref<LifecycleTarget|null>(null),lifecycleStorageProblem=ref(false);
try{
 const value=JSON.parse(sessionStorage.getItem(lifecycleKey)||'null');
 if(value!==null){
  if(!['rollback','version-delete'].includes(value.action)||typeof value.algorithmId!=='string'||!value.algorithmId
   ||typeof value.algorithmName!=='string'||typeof value.versionId!=='string'||!value.versionId
   ||typeof value.versionName!=='string'||(value.action==='rollback'&&(typeof value.currentVersionId!=='string'||!value.currentVersionId)))
   throw new Error('待核内容无效');
  lifecyclePending.value=value;
 }
}catch{lifecycleStorageProblem.value=true}
function saveLifecycle(value:LifecycleTarget|null){
 if(value)sessionStorage.setItem(lifecycleKey,JSON.stringify(value));
 else sessionStorage.removeItem(lifecycleKey);
 lifecyclePending.value=value;
}
const lifecycleNotice=ref<{message:string;receipt:VersionOperation}|null>(null);
const cleanupBusy=ref(false),cleanupError=ref('');
const incompleteCleanup=computed(()=>!!lifecycleNotice.value?.receipt&&lifecycleNotice.value.receipt.cleanup_status!=='cleanup_completed');
const cleanupDetails=computed(()=>{
 const receipt=lifecycleNotice.value?.receipt;
 if(cleanupError.value)return cleanupError.value;
 if(!incompleteCleanup.value||!receipt)return '';
 const status=receipt.cleanup_status==='cleanup_failed'?'部分产物清理失败。':'产物清理尚未确认完成。';
 return status+(receipt.cleanup_errors||[]).map(message=>browseError(new Error(message))).join('；');
});
function openVersionLifecycle(action:'version-delete'|'rollback',version:ModelVersion){
 const algorithm=versions.value?.algorithm;
 if(unconfirmed.value||saving.value||cleanupBusy.value||lifecyclePending.value||lifecycleStorageProblem.value
  ||!algorithm||algorithm.id!==selected.value||version.algorithm_id!==algorithm.id||
  !canRetireVersion(algorithm)||algorithm.current_version_id===version.id)return;
 const identity={algorithmId:algorithm.id,algorithmName:algorithm.name,versionId:version.id,versionName:version.version_name||version.id};
 if(action==='rollback'){
  if(!algorithm.current_version_id)return;
  lifecycleTarget.value={...identity,action,currentVersionId:algorithm.current_version_id};
 }else lifecycleTarget.value={...identity,action};
 lifecycleNotice.value=null;
}
async function lifecycleCompleted(target:LifecycleTarget,message:string,receipt:VersionOperation){
 lifecycleTarget.value=null;
 cleanupError.value='';
 lifecycleNotice.value={message,receipt};
 if(selected.value===target.algorithmId){
  if(route.query.version===deletedVersion(target))await router.replace({query:{...route.query,version:undefined}});
  if(selected.value===target.algorithmId)loadVersions();
 }
 load();
}
async function retryCleanup(){
 const notice=lifecycleNotice.value;
 if(!notice?.receipt||!incompleteCleanup.value||cleanupBusy.value)return;
 cleanupBusy.value=true;
 cleanupError.value='';
 try{
  const receipt=await retryVersionCleanup(projectId,notice.receipt);
  if(!scope.signal.aborted)lifecycleNotice.value={message:notice.message,receipt};
 }catch(cause){if(!scope.signal.aborted)cleanupError.value=browseError(cause)}
 finally{cleanupBusy.value=false}
}
const readOnlyAlgorithm=computed(()=>!!editingId.value&&(!basic.value?.editable||basic.value.source_type?.toUpperCase()==='EXTERNAL'));
const form=reactive<AlgorithmForm>({name:'',remark:'',industry:'',algorithm_type:''});
function externalPublishTarget(versionId:string){
 return {name:'external-publish-native',params:{projectId},query:{algorithm:selected.value,version:versionId,version_page:versionPage.value>1?String(versionPage.value):undefined}};
}
function load(){void reads.run('algorithms',signal=>api.algorithms(appliedFilters.value,signal),value=>{algorithms.value=value})}
function filterQuery(next:typeof defaults){
 const query={...route.query};
 for(const key of filterKeys)query[key]=next[key]===defaults[key]?null:next[key];
 for(const key of filterKeys)if(query[key]===null)delete query[key];
 delete query.status;
 if(next.page===1)delete query.page;else query.page=String(next.page);
 return query;
}
function applyFilters(next:typeof defaults){
 const query=filterQuery(next);
 delete query.algorithm;
 delete query.version;
 delete query.version_page;
 Object.assign(filters,next);
 void router.push({query});
}
function search(page=1){applyFilters({...filters,page})}
function paginate(page:number){applyFilters({...appliedFilters.value,page})}
function clearTag(key:typeof filterKeys[number]){applyFilters({...appliedFilters.value,[key]:defaults[key],page:1})}
function toggleTrainable(){applyFilters({...appliedFilters.value,training_state:appliedFilters.value.training_state==='trainable'?'all':'trainable',page:1})}
function choose(id:string){void router.push({query:{...route.query,algorithm:id||undefined,version:undefined,version_page:undefined}})}
function toggle(id:string){choose(selected.value===id?'':id)}
function loadVersions(){if(selected.value)void reads.run('versions',signal=>api.versions(selected.value,versionPage.value,signal),value=>{
 const lastPage=Math.max(1,Math.ceil(value.total/value.page_size));
 if(versionPage.value>lastPage){changeVersionPage(lastPage);return}
 versions.value=value;
})}
function changeVersionPage(value:number){void router.push({query:{...route.query,version_page:value===1?undefined:String(value)}})}
const versionRemark=ref(''),versionSaveError=ref('');
const selectedAlgorithm=computed(()=>algorithms.value?.items.find(algorithm=>algorithm.id===selected.value)||versions.value?.algorithm);
const canEditVersion=computed(()=>!!selectedAlgorithm.value&&selectedAlgorithm.value.id===detail.value?.algorithm_id);
function setDetail(value:VersionDetail){detail.value=value;versionRemark.value=value.version.remark||''}
function versionDetail(id:string){void router.push({query:{...route.query,version:id}})}
function versionDownload(algorithmId:string,versionId:string){
 return `/api/v12/projects/${encodeURIComponent(projectId)}/algorithms/${encodeURIComponent(algorithmId)}/versions/${encodeURIComponent(versionId)}/download`;
}
function loadVersionDetail(id:string){
 drawer.value=true;
 detail.value=null;
 versionSaveError.value='';
 void reads.run('detail',signal=>api.detail(selected.value,id,signal),setDetail);
}
function closeDetail(){
 if(route.query.version)void router.push({query:{...route.query,version:undefined}});
}
async function saveVersionRemark(){
 if(saving.value||unconfirmed.value||!canEditVersion.value||!detail.value||detail.value.algorithm_id!==selected.value)return;
 const algorithmId=detail.value.algorithm_id,versionId=detail.value.version.id,remark=versionRemark.value;
 try{savePending({algorithmId,versionId,body:{remark}});checkId.value=algorithmId}
 catch{pendingError.value='待核记录无法保存，本次未提交。';return}
 saving.value=true;
 versionSaveError.value='';
 try{
  try{
   const url='/api/v12/projects/'+encodeURIComponent(projectId)+'/algorithms/'+encodeURIComponent(algorithmId)+'/versions/'+encodeURIComponent(versionId)+'?asset_view=true';
   const result=await request<{ok:boolean}>(url,{method:'PUT',body:JSON.stringify({remark})});
   if(result.ok!==true)throw new Error('模型版本写入结果尚未核验');
  }catch(cause){
   const status=(cause as {httpStatus?:number}).httpStatus;
   if(status&&[400,401,403,404,409,422].includes(status))savePending(null);
   throw cause;
  }
  const saved=await api.detail(algorithmId,versionId,scope.signal);
  if(saved.version.remark!==remark)throw new Error('版本备注与提交内容不同，请核验后再操作。');
  savePending(null);
  if(scope.signal.aborted)return;
  if(drawer.value&&selected.value===algorithmId&&detail.value?.version.id===versionId)setDetail(saved);
  load();
  if(selected.value===algorithmId)loadVersions();
 }catch(cause){if(!scope.signal.aborted)versionSaveError.value=browseError(cause)}
 finally{saving.value=false}
}
function edit(id=''){reads.cancel('basic');editing.value=true;editingId.value=id;basic.value=null;writeError.value='';Object.assign(form,{name:'',remark:'',industry:'',algorithm_type:''});if(id)void reads.run('basic',signal=>management.basic(id,signal),value=>{basic.value=value;Object.assign(form,{name:value.name,remark:value.remark||'',industry:value.industry||'',algorithm_type:value.algorithm_type||''})})}
async function save(){
 if(saving.value||unconfirmed.value||readOnlyAlgorithm.value)return;
 if(!form.name.trim()){writeError.value='请填写算法名称';return}
 const body={...form,name:form.name.trim(),industry:form.industry.trim(),algorithm_type:form.algorithm_type.trim()};
 try{savePending({algorithmId:editingId.value,body});checkId.value=editingId.value}catch{pendingError.value='待核记录无法保存，本次未提交。';return}
 saving.value=true;writeError.value='';
 try{const saved=await management.save(editingId.value,body,scope.signal);savePending(null);if(scope.signal.aborted)return;editing.value=false;load();if(selected.value===saved.id)loadVersions();else choose(saved.id)}
 catch(cause){if((cause as {writeRejected?:boolean}).writeRejected){try{savePending(null)}catch{pendingError.value='待核记录无法清除，请核对后再操作。'}}if(!scope.signal.aborted)writeError.value=browseError(cause)}
 finally{saving.value=false}
}
async function verifyPending(){
 const savedPending=pending.value,id=savedPending?.algorithmId||checkId.value.trim();if(!savedPending||!id||checking.value)return;
 checking.value=true;pendingError.value='';
 try{
  if(savedPending.versionId!==undefined){
   const saved=await api.detail(id,savedPending.versionId,scope.signal);
   if(scope.signal.aborted)return;
   if(saved.version.remark!==savedPending.body.remark)throw new Error('权威版本备注与待核内容不同，请到原完整算法管理核对。');
   savePending(null);
   if(selected.value===id&&detail.value?.version.id===savedPending.versionId)setDetail(saved);
  }else{
   const saved=await management.basic(id,scope.signal);
   if(scope.signal.aborted)return;
   if(Object.keys(savedPending.body).some(key=>saved[key as keyof AlgorithmForm]!==savedPending.body[key as keyof AlgorithmForm]))throw new Error('权威记录与待核内容不同，请到原完整算法管理核对。');
   savePending(null);
  }
  editing.value=false;load();
  if(selected.value===id)loadVersions();else choose(id);
 }catch(cause){if(!scope.signal.aborted)pendingError.value=browseError(cause)}
 finally{checking.value=false}

}
async function initializeFilters(){
 if(![...filterKeys,'page'].some(key=>key in route.query)){
  try{
   const stored=JSON.parse(sessionStorage.getItem(filterStorageKey)||'null');
   if(stored&&typeof stored==='object'){
    const restored=routeFilters(stored);
    if(JSON.stringify(restored)!==JSON.stringify(appliedFilters.value)){
     const failure=await router.replace({query:filterQuery(restored)});
     if(!failure)return;
    }
   }
  }catch{/* Storage is optional. */}
 }
 if(scope.signal.aborted)return;
 persistFilters(JSON.stringify(appliedFilters.value));
}
function persistFilters(value:string){
 Object.assign(filters,appliedFilters.value);
 try{sessionStorage.setItem(filterStorageKey,value)}catch{/* The current URL still holds the filters. */}
 load();
}
void initializeFilters();
watch(()=>JSON.stringify(appliedFilters.value),persistFilters);
watch([selected,()=>route.query.version_page],()=>{
 reads.cancel('versions');
 versions.value=null;
 const page=Number(route.query.version_page);
 versionPage.value=Number.isSafeInteger(page)&&page>0?page:1;
 loadVersions();
},{immediate:true});
watch([selected,()=>route.query.version],([algorithm,version])=>{
 reads.cancel('detail');
 drawer.value=false;
 if(algorithm&&typeof version==='string'&&version)loadVersionDetail(version);
},{immediate:true});
</script>
<template><section aria-label="算法库卡片管理">
 <div class="page-toolbar"><p>项目算法与模型版本</p><div><el-button tag="a" :href="legacyUrl(projectId,'算法列表')">原完整算法管理</el-button><el-button type="primary" :disabled="unconfirmed" @click="edit()">新增本地算法</el-button></div></div>
 <el-alert v-if="lifecycleStorageProblem" title="版本操作待核记录无法读取，请到原算法管理核对。" type="error" :closable="false"/>
 <el-alert v-if="lifecyclePending && !lifecycleTarget" title="版本操作待核对。" type="warning" :closable="false">
  <el-button @click="lifecycleTarget=lifecyclePending">核对版本操作</el-button>
 </el-alert>
 <el-alert v-if="lifecycleNotice" :title="lifecycleNotice.message" :type="incompleteCleanup?'warning':'success'" :closable="!cleanupBusy" @close="lifecycleNotice=null">
  <p v-if="cleanupDetails">{{ cleanupDetails }}</p>
  <el-button v-if="incompleteCleanup" :loading="cleanupBusy" @click="retryCleanup">重试产物清理</el-button>
 </el-alert>
 <form class="algorithm-filters" @submit.prevent="search()">
  <el-input v-model="filters.query" aria-label="搜索算法" placeholder="搜索算法名称 / ID" clearable/>
  <el-select v-for="key in ['algorithm_type','industry'] as const" :key="key" v-model="filters[key]" :aria-label="filterLabels[key]" :placeholder="filterLabels[key]" clearable>
   <el-option label="全部" value=""/><el-option v-for="value in algorithms?.filter_options?.[key]||[]" :key="value" :label="value" :value="value"/>
  </el-select>
  <el-select v-model="filters.source_type" aria-label="来源" placeholder="来源" clearable>
   <el-option label="全部来源" value=""/><el-option v-for="(label,value) in sourceLabels" :key="value" :label="label" :value="value"/>
  </el-select>
  <el-select v-model="filters.training_state" aria-label="训练状态">
   <el-option v-for="(label,value) in trainingLabels" :key="value" :label="value==='all'?'全部训练状态':label" :value="value"/>
  </el-select>
  <el-cascader v-model="categorySelection" :options="categoryTree" :props="categoryProps" aria-label="外部分类" placeholder="外部分类" clearable filterable collapse-tags collapse-tags-tooltip/>
  <el-select v-model="filters.sort" aria-label="排序">
   <el-option v-for="(label,value) in sortLabels" :key="value" :label="label" :value="value"/>
  </el-select>
  <el-button native-type="submit" type="primary" :loading="reads.busy.algorithms">查询</el-button>
  <el-button @click="load">刷新</el-button>
 </form>
 <div class="algorithm-filter-meta">
  <el-button :aria-pressed="appliedFilters.training_state==='trainable'" :type="appliedFilters.training_state==='trainable'?'primary':'default'" @click="toggleTrainable">仅看可训练</el-button>
  <el-tag v-for="tag in appliedTags" :key="tag.key" closable @close="clearTag(tag.key)">{{ tag.label }}</el-tag>
  <el-button v-if="appliedTags.length" link @click="applyFilters({...defaults})">清空筛选</el-button>
 </div>
 <div v-if="unconfirmed"><el-alert title="保存结果尚未核验，请先核对，勿重复提交。" type="warning" :closable="false"/><p v-if="pending?.versionId">待核算法 {{ pending.algorithmId }} · 版本 {{ pending.versionId }}</p><p v-else-if="pending">{{ pending.algorithmId?'编辑或创建回执已记录，将读取该算法核对。':'创建回执未返回算法 ID，请从原完整算法管理核对后填写对应 ID。' }}</p><el-input v-if="pending" v-model="checkId" aria-label="待核算法 ID" placeholder="待核算法 ID" :disabled="!!pending.algorithmId||checking"/><el-button v-if="pending" :loading="checking" :disabled="!(pending.algorithmId||checkId.trim())" @click="verifyPending">核对保存结果</el-button><el-alert v-if="pendingError" :title="pendingError" type="error" :closable="false"/></div>
 <el-alert v-if="reads.errors.algorithms" :title="reads.errors.algorithms" type="error" :closable="false"/>
 <el-skeleton v-if="!algorithms&&reads.busy.algorithms" :rows="6" animated/>
 <div v-else class="algorithm-cards" v-loading="reads.busy.algorithms">
  <article v-for="algorithm in algorithms?.items||[]" :key="algorithm.id" class="algorithm-card" :class="{selected:selected===algorithm.id}">
   <div class="card-heading">
    <el-tag type="info">{{ sourceLabel(algorithm) }}</el-tag>
    <el-tag :type="algorithm.trainable?'success':'info'" :title="algorithm.trainability_message">{{ algorithm.trainable===true?'可训练':algorithm.trainable===false?'不可训练':'训练条件未提供' }}</el-tag>
   </div>
   <h2><button class="title-button" :aria-expanded="selected===algorithm.id" @click="toggle(algorithm.id)">{{ algorithm.name }}</button></h2>
   <code>{{ algorithm.id }}</code>
   <dl>
    <div><dt>算法类型</dt><dd>{{ algorithm.algorithm_type||'未设置' }}</dd></div>
    <div><dt>行业</dt><dd>{{ algorithm.industry||'未设置' }}</dd></div>
    <div><dt>模型版本</dt><dd>{{ algorithm.version_count??'未提供' }}</dd></div>
    <div><dt>当前版本</dt><dd>{{ algorithm.current_version?.version_name||algorithm.current_version_id||'未设置' }}</dd></div>
    <div><dt>训练状态</dt><dd>{{ algorithmState(algorithm) }}</dd></div>
    <div><dt>成功训练次数</dt><dd>{{ algorithm.successful_training_count??'未提供' }}</dd></div>
    <div><dt>mAP50</dt><dd>{{ algorithm.map50_percent==null?'未提供':algorithm.map50_percent.toFixed(1)+'%' }}</dd></div>
    <div><dt>更新时间</dt><dd>{{ dateLabel(algorithm.updated_at) }}</dd></div>
    <div v-if="external(algorithm)"><dt>产品 / 品目 ID</dt><dd>{{ algorithm.external_product_id||'未提供' }} / {{ algorithm.external_category_id||'未提供' }}</dd></div><div v-if="external(algorithm)"><dt>外部状态</dt><dd>{{ algorithm.external_status||(algorithm.external_active===true?'已启用':algorithm.external_active===false?'已停用':'未提供') }}</dd></div>
   </dl>
   <p v-if="algorithm.remark" class="algorithm-remark">{{ algorithm.remark }}</p>
   <p v-if="algorithm.trainable===false&&algorithm.trainability_message" class="algorithm-blocked">{{ algorithm.trainability_message }}</p>
   <footer>
    <el-button :aria-expanded="selected===algorithm.id" @click="toggle(algorithm.id)">{{ selected===algorithm.id?'收起详情':'详情与版本' }}</el-button>
    <el-button :disabled="unconfirmed&&!external(algorithm)" @click="edit(algorithm.id)">{{ external(algorithm)?'基本信息':'基本编辑' }}</el-button>
    <a v-if="algorithm.trainable===true" :href="'/app/#/projects/'+encodeURIComponent(projectId)+'/training/create?algorithm='+encodeURIComponent(algorithm.id)">训练</a>
    <a :href="original(algorithm.id,'algorithm-report')">算法报告</a>
    <a v-if="external(algorithm)" :href="legacyUrl(projectId,'平台对接')">外部同步 · 原流程</a>
    <a v-else :href="original(algorithm.id,'delete-algorithm')">删除算法 · 原流程</a>
   </footer>

  </article>
 </div>
   <section v-if="selected" class="version-panel" aria-label="算法详情与版本">
    <header><div><h2>{{ versions?.algorithm.name||selected }}</h2><h3>模型版本</h3></div><span v-if="versions">共 {{ versions.total }} 个版本</span></header>
    <el-alert v-if="reads.errors.versions" :title="reads.errors.versions" type="error" :closable="false"/>
    <el-table :data="versions?.items||[]" row-key="id" v-loading="reads.busy.versions" empty-text="暂无版本">
     <el-table-column label="模型版本" min-width="165"><template #default="{row}"><strong>{{ row.version_name||row.id }}</strong><el-tag v-if="versions?.algorithm.current_version_id===row.id" type="info">当前版本</el-tag><small class="version-id">{{ row.id }}</small></template></el-table-column>
     <el-table-column label="训练状态" min-width="100"><template #default="{row}">{{ stateLabel(row.training_status) }}</template></el-table-column>
     <el-table-column prop="framework" label="框架" min-width="90"/>
     <el-table-column label="操作" min-width="310"><template #default="{row}">
      <div class="algorithm-version-actions">
       <el-button link @click="versionDetail(row.id)">版本详情</el-button>
       <router-link :to="versionReport(selected,row.id)">训练报告</router-link>
       <a v-if="row.has_lineage" :href="original(selected,'lineage',row.id)">训练溯源</a>
       <router-link v-if="row.has_evaluation" :to="versionReport(selected,row.id,true)">独立评测</router-link>
       <router-link :to="{name:'version-conversions',params:{projectId,algorithmId:selected,versionId:row.id},query:{algorithm_name:versions?.algorithm.name,version_name:row.version_name}}">转换记录（原生）</router-link>
       <router-link v-if="canOpenExternalPublish(versions?.algorithm||selectedAlgorithm||{id:selected,name:''})" :to="externalPublishTarget(row.id)">新畅联交付（原生只读）</router-link>
       <a :href="original(selected,'conversion',row.id)">转换 · 原流程</a>
       <a :href="original(selected,'delivery',row.id)">交付 · 原流程</a>
       <a v-if="row.has_model" :href="versionDownload(selected,row.id)" target="_blank" rel="noopener">下载模型</a>
       <template v-if="versions&&canRetireVersion(versions.algorithm)&&versions.algorithm.current_version_id!==row.id">
        <el-button v-if="versions.algorithm.current_version_id" link :disabled="unconfirmed||saving||cleanupBusy||reads.busy.versions||!!lifecyclePending||lifecycleStorageProblem" @click="openVersionLifecycle('rollback',row)">回退</el-button>
        <el-button link :disabled="unconfirmed||saving||cleanupBusy||reads.busy.versions||!!lifecyclePending||lifecycleStorageProblem" @click="openVersionLifecycle('version-delete',row)">删除版本</el-button>
       </template>
      </div>
     </template></el-table-column>
    </el-table>
    <el-pagination v-if="versions" :current-page="versionPage" :page-size="20" :total="versions.total" layout="prev, pager, next" @current-change="changeVersionPage"/>
   </section>
 <el-empty v-if="algorithms&&!algorithms.items.length" description="暂无匹配算法"/>
 <div v-if="algorithms" class="pagination"><span>共 {{ algorithms.total }} 个算法</span><el-pagination :current-page="appliedFilters.page" :page-size="10" :total="algorithms.total" layout="prev, pager, next" @current-change="paginate"/></div>
 <el-drawer v-model="editing" :title="editingId?(basic&&readOnlyAlgorithm?'算法基本信息':'算法基本编辑'):'新增本地算法'" size="min(560px,100vw)" :close-on-click-modal="!saving" :show-close="!saving" :close-on-press-escape="!saving"><el-alert v-if="writeError||reads.errors.basic" :title="writeError||reads.errors.basic" type="error" :closable="false"/><el-skeleton v-if="reads.busy.basic" :rows="5"/><form v-else class="algorithm-form" @submit.prevent="save"><ReadOnlyFacts v-if="basic" :fields="[['算法 ID',basic.id],['来源',basic.source_type],['当前版本 ID',basic.current_version_id],['创建时间',basic.created_at],['更新时间',basic.updated_at]]"/><ReadOnlyFacts v-if="basic?.source_type?.toUpperCase()==='EXTERNAL'" :fields="[['提供方',basic.provider_type],['外部产品 ID',basic.external_product_id],['产品编码',basic.external_product_code],['品目 ID',basic.external_category_id],['默认分析 ID',basic.external_analysis_id],['启用状态',basic.external_active==null?null:!!basic.external_active],['同步时间',basic.external_last_synced_at],['主数据摘要',basic.external_master_data_digest]]"/><label>算法名称<el-input v-model="form.name" aria-label="算法名称" maxlength="160" :disabled="saving||readOnlyAlgorithm"/></label><label>行业 / 分类<el-input v-model="form.industry" aria-label="行业分类" maxlength="160" :disabled="saving||readOnlyAlgorithm"/></label><label>算法类型<el-input v-model="form.algorithm_type" aria-label="算法类型标识" maxlength="160" :disabled="saving||readOnlyAlgorithm"/></label><label>备注<el-input v-model="form.remark" aria-label="算法备注" type="textarea" maxlength="4000" :disabled="saving||readOnlyAlgorithm"/></label><p v-if="basic&&readOnlyAlgorithm">外部算法只读，请使用原完整管理入口。</p><el-button native-type="submit" type="primary" :loading="saving" :disabled="unconfirmed||readOnlyAlgorithm">保存并核验</el-button></form></el-drawer>
 <el-drawer :model-value="drawer" title="模型版本详情" size="min(720px,100vw)" :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :before-close="closeDetail">
  <el-skeleton v-if="reads.busy.detail" :rows="8"/>
  <el-alert v-else-if="reads.errors.detail" :title="reads.errors.detail" type="error"/>
  <template v-else-if="detail">
   <ModelVersionDetails :detail="detail"/>
   <p><router-link :to="versionReport(detail.algorithm_id,detail.version.id)">训练报告</router-link>　<router-link v-if="detail.version.has_evaluation" :to="versionReport(detail.algorithm_id,detail.version.id,true)">独立评测</router-link></p>
   <form class="algorithm-form version-remark-form" @submit.prevent="saveVersionRemark">
    <label>版本备注<el-input v-model="versionRemark" aria-label="版本备注" type="textarea" :readonly="!canEditVersion" :disabled="saving"/></label>
    <el-alert v-if="versionSaveError" :title="versionSaveError" type="error" :closable="false"/>
    <el-button v-if="canEditVersion" native-type="submit" type="primary" :loading="saving" :disabled="unconfirmed||versionRemark===(detail.version.remark||'')">保存版本备注并核验</el-button>
   </form>
  </template>
 </el-drawer>
 <AlgorithmLifecycleDialog v-if="lifecycleTarget" :project-id="projectId" :target="lifecycleTarget"
  :recovering="!!lifecyclePending" :save-intent="saveLifecycle" @close="lifecycleTarget=null" @completed="lifecycleCompleted"/>
</section></template>
