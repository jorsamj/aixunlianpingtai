<script setup lang="ts">
import {computed,onUnmounted,reactive,ref,watch} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {modelBrowseApi,browseError} from '../api/model-browse';
import {algorithmManagementApi,type AlgorithmForm,type AlgorithmBasic} from '../api/algorithm-management';
import type {AlgorithmSummary,Paged,VersionPage,VersionDetail} from '../types/model-browse';
import {useReadScope} from '../composables/useReadScope';
import ModelVersionDetails from '../components/ModelVersionDetails.vue';
import {request} from './http';
import {legacyUrl} from './navigation';
const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId),scope=new AbortController();
onUnmounted(()=>scope.abort());
// Reuse the existing project-scoped algorithm journal format; it is not business truth.
type PendingWrite={algorithmId:string;body:AlgorithmForm};
const pendingKey='cl_vue_algorithm_pending_v1:'+projectId,pending=ref<PendingWrite|null>(null),pendingError=ref(''),checking=ref(false),checkId=ref('');
try{pending.value=JSON.parse(sessionStorage.getItem(pendingKey)||'null');if(pending.value&&(typeof pending.value.algorithmId!=='string'||!pending.value.body||!['name','remark','industry','algorithm_type'].every(key=>typeof pending.value!.body[key as keyof AlgorithmForm]==='string')))throw new Error('待核记录无效');checkId.value=pending.value?.algorithmId||''}catch{pendingError.value='待核记录无法读取，请到原完整算法管理核对；本页暂不提交。'}
const unconfirmed=computed(()=>!!pending.value||!!pendingError.value);
function savePending(value:PendingWrite|null){pending.value=value;if(value)sessionStorage.setItem(pendingKey,JSON.stringify(value));else sessionStorage.removeItem(pendingKey)}
const owner={projectId,algorithmPageSize:10,get:<T,>(url:string,options?:{signal?:AbortSignal})=>request<T>(url,options),
 async writeAlgorithm(method:'POST'|'PUT',id:string,body:AlgorithmForm){const result=await request<{ok:boolean;algorithm:{id:string}}>(`/api/v12/projects/${encodeURIComponent(projectId)}/algorithms${id?'/'+encodeURIComponent(id):''}?asset_view=true`,{method,body:JSON.stringify(body)});if(result.ok&&result.algorithm?.id&&(!id||id===result.algorithm.id)){savePending({algorithmId:result.algorithm.id,body});checkId.value=result.algorithm.id}return result}};
const api=modelBrowseApi(owner),management=algorithmManagementApi(owner),reads=useReadScope(scope);
const filters=reactive({query:String(route.query.query||''),algorithm_type:String(route.query.algorithm_type||''),industry:String(route.query.industry||''),source_type:String(route.query.source_type||''),status:String(route.query.status||''),sort:String(route.query.sort||'updated'),page:Number(route.query.page)||1});
const algorithms=ref<Paged<AlgorithmSummary>|null>(null),versions=ref<VersionPage|null>(null),detail=ref<VersionDetail|null>(null),basic=ref<AlgorithmBasic|null>(null);
const selected=computed(()=>String(route.query.algorithm||'')),versionPage=ref(1),drawer=ref(false),editing=ref(false),editingId=ref(''),saving=ref(false),writeError=ref('');
const form=reactive<AlgorithmForm>({name:'',remark:'',industry:'',algorithm_type:''});
function load(){void reads.run('algorithms',signal=>api.algorithms(filters,signal),value=>{algorithms.value=value})}
function search(page=1){void router.push({query:{...route.query,...filters,page}})}
function choose(id:string){void router.push({query:{...route.query,algorithm:id}})}
function loadVersions(){if(selected.value)void reads.run('versions',signal=>api.versions(selected.value,versionPage.value,signal),value=>{versions.value=value})}
function changeVersionPage(value:number){versionPage.value=value;loadVersions()}
function versionDetail(id:string){drawer.value=true;detail.value=null;void reads.run('detail',signal=>api.detail(selected.value,id,signal),value=>{detail.value=value})}
function closeDetail(){reads.cancel('detail');drawer.value=false}
function edit(id=''){reads.cancel('basic');editing.value=true;editingId.value=id;basic.value=null;writeError.value='';Object.assign(form,{name:'',remark:'',industry:'',algorithm_type:''});if(id)void reads.run('basic',signal=>management.basic(id,signal),value=>{basic.value=value;Object.assign(form,{name:value.name,remark:value.remark||'',industry:value.industry||'',algorithm_type:value.algorithm_type||''})})}
async function save(){
 if(saving.value||unconfirmed.value)return;
 if(!form.name.trim()){writeError.value='请填写算法名称';return}
 const body={...form,name:form.name.trim(),industry:form.industry.trim(),algorithm_type:form.algorithm_type.trim()};
 try{savePending({algorithmId:editingId.value,body});checkId.value=editingId.value}catch{pendingError.value='待核记录无法保存，本次未提交。';return}
 saving.value=true;writeError.value='';
 try{const saved=await management.save(editingId.value,body,scope.signal);savePending(null);if(scope.signal.aborted)return;editing.value=false;if(selected.value===saved.id){load();loadVersions()}else choose(saved.id)}
 catch(cause){if((cause as {writeRejected?:boolean}).writeRejected){try{savePending(null)}catch{pendingError.value='待核记录无法清除，请核对后再操作。'}}if(!scope.signal.aborted)writeError.value=browseError(cause)}
 finally{saving.value=false}
}
async function verifyPending(){
 const savedPending=pending.value,id=savedPending?.algorithmId||checkId.value.trim();if(!savedPending||!id||checking.value)return;
 checking.value=true;pendingError.value='';
 try{const saved=await management.basic(id,scope.signal);if(scope.signal.aborted)return;if(Object.keys(savedPending.body).some(key=>saved[key as keyof AlgorithmForm]!==savedPending.body[key as keyof AlgorithmForm]))throw new Error('权威记录与待核内容不同，请到原完整算法管理核对。');savePending(null);editing.value=false;load();choose(saved.id)}catch(cause){if(!scope.signal.aborted)pendingError.value=browseError(cause)}finally{checking.value=false}
}
watch(()=>route.query,()=>{
 Object.assign(filters,{query:String(route.query.query||''),page:Number(route.query.page)||1,algorithm_type:String(route.query.algorithm_type||''),industry:String(route.query.industry||''),source_type:String(route.query.source_type||''),status:String(route.query.status||''),sort:String(route.query.sort||'updated')});
 closeDetail();reads.cancel('versions');versions.value=null;versionPage.value=1;load();loadVersions();
},{immediate:true});
</script>
<template><section aria-label="算法库卡片管理">
 <div class="page-toolbar"><p>项目算法与模型版本</p><div><el-button tag="a" :href="legacyUrl(projectId,'算法列表')">原完整算法管理</el-button><el-button type="primary" :disabled="unconfirmed" @click="edit()">新增本地算法</el-button></div></div>
 <form class="algorithm-filters" @submit.prevent="search()"><el-input v-model="filters.query" aria-label="搜索算法" placeholder="搜索算法名称 / ID" clearable/>
  <el-select v-for="[key,label] in [['algorithm_type','算法类型'],['industry','分类'],['source_type','来源'],['status','状态']] as const" :key="key" v-model="filters[key]" :aria-label="label" :placeholder="label" clearable><el-option label="全部" value=""/><el-option v-for="value in algorithms?.filter_options?.[key]||[]" :key="value" :label="value" :value="value"/></el-select>
  <el-select v-model="filters.sort" aria-label="排序"><el-option label="最近更新" value="updated"/><el-option label="最近创建" value="created"/><el-option label="名称升序" value="name"/><el-option label="名称降序" value="name_desc"/></el-select><el-button native-type="submit" :loading="reads.busy.algorithms">查询</el-button><el-button @click="load">刷新</el-button>
 </form>
 <div v-if="unconfirmed"><el-alert title="保存结果尚未核验，请先核对，勿重复提交。" type="warning" :closable="false"/><p v-if="pending">{{ pending.algorithmId?'编辑或创建回执已记录，将读取该算法核对。':'创建回执未返回算法 ID，请从原完整算法管理核对后填写对应 ID。' }}</p><el-input v-if="pending" v-model="checkId" aria-label="待核算法 ID" placeholder="待核算法 ID" :disabled="!!pending.algorithmId||checking"/><el-button v-if="pending" :loading="checking" :disabled="!(pending.algorithmId||checkId.trim())" @click="verifyPending">核对保存结果</el-button><el-alert v-if="pendingError" :title="pendingError" type="error" :closable="false"/></div>
 <el-alert v-if="reads.errors.algorithms" :title="reads.errors.algorithms" type="error" :closable="false"/>
 <el-skeleton v-if="!algorithms&&reads.busy.algorithms" :rows="6" animated/>
 <div v-else class="algorithm-cards"><article v-for="algorithm in algorithms?.items||[]" :key="algorithm.id" class="algorithm-card" :class="{selected:selected===algorithm.id}">
  <div class="card-heading"><span class="algorithm-symbol" aria-hidden="true">◇</span><el-tag type="info">{{ algorithm.source_type||'来源未提供' }}</el-tag></div>
  <h2><button class="title-button" @click="choose(algorithm.id)">{{ algorithm.name }}</button></h2><code>{{ algorithm.id }}</code>
  <dl><div><dt>算法类型</dt><dd>{{ algorithm.algorithm_type||'未设置' }}</dd></div><div><dt>分类</dt><dd>{{ algorithm.industry||'未设置' }}</dd></div><div><dt>版本</dt><dd>{{ algorithm.version_count??'未提供' }}</dd></div><div><dt>当前版本</dt><dd>{{ algorithm.current_version?.version_name||algorithm.current_version_id||'未设置' }}</dd></div></dl>
  <footer><el-button @click="choose(algorithm.id)">详情与版本</el-button><el-button :disabled="unconfirmed" @click="edit(algorithm.id)">基本编辑</el-button><a :href="legacyUrl(projectId,'算法列表',algorithm.id,'','train')">训练 · 原流程</a></footer>
 </article></div>
 <el-empty v-if="algorithms&&!algorithms.items.length" description="暂无匹配算法"/>
 <div v-if="algorithms" class="pagination"><span>共 {{ algorithms.total }} 个算法</span><el-pagination :current-page="filters.page" :page-size="10" :total="algorithms.total" layout="prev, pager, next" @current-change="search"/></div>
 <section v-if="selected" class="version-panel" aria-label="算法详情与版本"><header><div><h2>{{ versions?.algorithm.name||'算法详情' }}</h2><code>{{ selected }}</code></div><el-button @click="edit(selected)">详情 / 基本编辑</el-button></header>
  <el-alert v-if="reads.errors.versions" :title="reads.errors.versions" type="error" :closable="false"/>
  <el-table :data="versions?.items||[]" row-key="id" v-loading="reads.busy.versions" empty-text="暂无版本"><el-table-column label="模型版本" min-width="180"><template #default="{row}"><strong>{{ row.version_name||row.id }}</strong><el-tag v-if="versions?.algorithm.current_version_id===row.id" type="info">当前版本</el-tag><small class="version-id">{{ row.id }}</small></template></el-table-column><el-table-column prop="training_status" label="训练状态"/><el-table-column prop="framework" label="框架"/><el-table-column label="操作" min-width="340"><template #default="{row}"><el-button link @click="versionDetail(row.id)">版本详情</el-button><a :href="legacyUrl(projectId,'算法列表',selected,row.id,'conversion')">转换 · 原流程</a><a :href="legacyUrl(projectId,'算法列表',selected,row.id,'delivery')">交付 · 原流程</a></template></el-table-column></el-table>
  <el-pagination v-if="versions" :current-page="versionPage" :page-size="20" :total="versions.total" layout="prev, pager, next" @current-change="changeVersionPage"/>
 </section>
 <el-drawer v-model="editing" :title="editingId?'算法基本编辑':'新增本地算法'" size="min(560px,100vw)" :close-on-click-modal="!saving" :show-close="!saving" :close-on-press-escape="!saving"><el-alert v-if="writeError||reads.errors.basic" :title="writeError||reads.errors.basic" type="error" :closable="false"/><el-skeleton v-if="reads.busy.basic" :rows="5"/><form v-else class="algorithm-form" @submit.prevent="save"><label>算法名称<el-input v-model="form.name" aria-label="算法名称" maxlength="160" :disabled="saving||!!editingId&&!basic?.editable"/></label><label>行业 / 分类<el-input v-model="form.industry" aria-label="行业分类" maxlength="160" :disabled="saving||!!editingId&&!basic?.editable"/></label><label>算法类型<el-input v-model="form.algorithm_type" aria-label="算法类型标识" maxlength="160" :disabled="saving||!!editingId&&!basic?.editable"/></label><label>备注<el-input v-model="form.remark" aria-label="算法备注" type="textarea" maxlength="4000" :disabled="saving||!!editingId&&!basic?.editable"/></label><p v-if="basic&&!basic.editable">外部算法只读，请使用原完整管理入口。</p><el-button native-type="submit" type="primary" :loading="saving" :disabled="unconfirmed||!!editingId&&!basic?.editable">保存并核验</el-button></form></el-drawer>
 <el-drawer :model-value="drawer" title="模型版本详情" size="min(720px,100vw)" :before-close="closeDetail"><el-skeleton v-if="reads.busy.detail" :rows="8"/><el-alert v-else-if="reads.errors.detail" :title="reads.errors.detail" type="error"/><ModelVersionDetails v-else-if="detail" :detail="detail"/></el-drawer>
</section></template>
