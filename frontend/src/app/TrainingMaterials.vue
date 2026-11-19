<script setup lang="ts">
import {computed,ref,onBeforeUnmount} from 'vue';
import {request} from './http';
import {trainingMaterialRevision,verifyTrainingSelection,selectionMembership,listTrainingMaterials} from './training-api';
const props=defineProps<{projectId:string;identity:Record<string,any>;role:'train'|'test';allowedReference?:string;allowedIds?:string[];explicitOnly?:boolean;poolOnly?:boolean;positiveOnly?:boolean;initial?:{ids:string[];reference?:string;count:number}}>();
const emit=defineEmits<{confirm:[value:any];cancel:[]}>();
const selected=ref(new Set(props.initial?.ids||[])),reference=ref(props.initial?.reference||''),count=ref(props.initial?.count||0),rows=ref<any[]>([]),page=ref(1),hasNext=ref(false),query=ref(''),sort=ref('newest'),busy=ref(false),error=ref(''),summary=ref<any>(null),revision=ref<any>({}),members=ref<string[]>([]);
const labelFilter=ref(''),annotationFilter=ref(props.positiveOnly?'annotated':''),poolCategory=ref(''),publicPool=ref(!!props.poolOnly);
const categories=ref<{id:string;name:string;enabled:boolean}[]>([]);
let freezeAttempt:{key:string;id:string}|null=null;
function freezeRequestId(scope: Record<string, unknown>) {
  const key = JSON.stringify(scope);
  if (freezeAttempt?.key === key) return freezeAttempt.id;

  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  const id = [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
  freezeAttempt = {key, id};
  return id;
}
function clearSelection() {
  selected.value = new Set();
  reference.value = '';
  count.value = 0;
  summary.value = null;
  freezeAttempt = null;
}
const allowedMembers=ref(new Set<string>());
const controller=new AbortController();
async function allowed(ids:string[]){if(props.allowedReference){const found:string[]=[];for(let offset=0;offset<ids.length;offset+=100){const response=await selectionMembership(props.projectId,{...identity(),selection_ref:props.allowedReference,image_ids:ids.slice(offset,offset+100)},controller.signal);found.push(...response.items);}return new Set(found);}return new Set(props.allowedIds||ids);}onBeforeUnmount(()=>controller.abort());
const base=`/api/v62/projects/${encodeURIComponent(props.projectId)}/training-materials`;
const identity=()=>({...props.identity,role:props.role});
const hasTargetLabels=computed(()=>Boolean(props.identity.base_version_id||props.identity.train_labels?.length));
async function run(action:()=>Promise<void>){busy.value=true;error.value='';try{await action()}catch(e){if(!controller.signal.aborted)error.value=(e as Error).message}finally{busy.value=false}}
async function loadCategories(){
 if(categories.value.length)return;
 try{const value=await request<{items:typeof categories.value}>(`/api/v61/projects/${encodeURIComponent(props.projectId)}/negative-pool/categories`,{signal:controller.signal});categories.value=value.items;}
 catch(cause){if(!controller.signal.aborted)error.value=(cause as Error).message;}
}
const poolFilters=()=>publicPool.value?{negative_pool_only:true,negative_category_ids:poolCategory.value?[poolCategory.value]:[]}:{};
async function load(){await run(async()=>{const result=await listTrainingMaterials(props.projectId,{...identity(),...poolFilters(),role_view:!!props.poolOnly&&hasTargetLabels.value,defer_role_counts:true,page:page.value,page_size:40,query:query.value,sort_order:sort.value,count_mode:'deferred',labels:labelFilter.value?labelFilter.value.split(',').map(v=>v.trim()).filter(Boolean):[],annotation_state:annotationFilter.value},controller.signal);if(controller.signal.aborted)return;const pageRevision=await trainingMaterialRevision(props.projectId,props.identity.algorithm_asset_id,controller.signal);if(['repository_revision','annotation_revision','usage_revision'].some(key=>(result as any)[key]!=null&&(result as any)[key]!==pageRevision[key as keyof typeof pageRevision]))throw new Error('素材列表证据已变化，请刷新列表后重新选择');const incoming=result.items||[];allowedMembers.value=await allowed(incoming.map((row:any)=>row.id));if(controller.signal.aborted)return;rows.value=incoming.map((row:any)=>({...row,selectable:row.selectable!==false&&allowedMembers.value.has(row.id)}));revision.value=pageRevision;if(reference.value){const membership=await selectionMembership(props.projectId,{...identity(),selection_ref:reference.value,image_ids:rows.value.map(row=>row.id)},controller.signal);members.value=membership.items;}hasNext.value=Boolean(result.has_next);});}
function toggle(id:string){if(reference.value||!allowedMembers.value.has(id))return;const next=new Set(selected.value);if(next.has(id))next.delete(id);else{if(next.size>=2000){error.value=props.role==='train'?'逐张选择达到 2000 张，请清除后使用服务器冻结筛选结果':'独立 Test 逐张选择最多 2000 张';return;}next.add(id);}selected.value=next;count.value=next.size;summary.value=null;}
async function freeze(){if(props.explicitOnly)return;await run(async()=>{if(selected.value.size)throw new Error('请先清除逐张选择，再冻结筛选范围');const scope={...identity(),...poolFilters(),query:query.value,labels:labelFilter.value?labelFilter.value.split(',').map(v=>v.trim()).filter(Boolean):[],annotation_state:annotationFilter.value,sort_order:sort.value,sample_role:props.poolOnly?'confirmed_negative':''};const result=await request<any>(`${base}/selection-reference`,{method:'POST',signal:controller.signal,body:JSON.stringify({...scope,request_id:freezeRequestId(scope)})});if(controller.signal.aborted)return;reference.value=result.selection_ref;count.value=result.count;revision.value=await trainingMaterialRevision(props.projectId,props.identity.algorithm_asset_id,controller.signal);summary.value=null;});}
async function confirm(){await run(async()=>{if(props.allowedReference||props.allowedIds){const membership=await allowed([...selected.value]);if([...selected.value].some(id=>!membership.has(id)))throw new Error('增强原图已不在训练选择范围，请重新选择');}if(!count.value&&!props.poolOnly&&!props.positiveOnly)throw new Error('请选择素材');if(props.poolOnly||!count.value){emit('confirm',{ids:[...selected.value],reference:reference.value,count:count.value,revision:revision.value});return}const result=await verifyTrainingSelection(props.projectId,{...identity(),algorithm_asset_id:props.identity.algorithm_asset_id,...(reference.value?{train_selection_ref:reference.value}:{image_ids:[...selected.value]})},revision.value,count.value,controller.signal);if(controller.signal.aborted)return;summary.value=result;emit('confirm',{ids:[...selected.value],reference:reference.value,count:count.value,summary:result,revision:revision.value});});}
if(publicPool.value)void loadCategories();
void load();
</script>
<template><section class="training-materials"><header><h2>{{poolOnly?'项目公共负样本池':role==='train'?'训练素材':'独立 Test 素材'}}</h2><p>已选 {{count}} 张 · 跨页保留选择</p></header><el-alert v-if="error" :title="error" type="error" :closable="false"/><form @submit.prevent="page=1;load()"><el-input v-model="query" placeholder="搜索图片名称" :disabled="busy"/><el-select v-model="sort"><el-option value="newest" label="最近加入"/><el-option value="oldest" label="最早加入"/></el-select><el-input v-model="labelFilter" placeholder="标签编码，逗号分隔"/><el-select v-model="annotationFilter"><el-option value="" label="全部标注状态"/><el-option value="annotated" label="已标注"/><el-option value="confirmed_empty" label="正式确认零框"/><el-option value="unannotated" label="未标注"/></el-select><el-checkbox v-if="role==='test'" v-model="publicPool" @change="loadCategories">仅查看项目公共负样本池</el-checkbox><el-select v-if="publicPool" v-model="poolCategory" aria-label="公共池分类"><el-option value="" label="全部分类"/><el-option v-for="category in categories" :key="category.id" :label="category.name" :value="category.id"/></el-select><el-button native-type="submit" :disabled="busy">搜索</el-button></form><div class="actions"><el-button :disabled="busy||!!reference" @click="rows.filter(r=>r.selectable!==false&&(!poolOnly||r.sample_role!=='positive')).forEach(r=>{if(!selected.has(r.id))toggle(r.id)})">选择本页</el-button><el-button v-if="role==='train'&&!explicitOnly" :disabled="busy||!!reference||(poolOnly&&!hasTargetLabels)" @click="freeze">{{poolOnly?'冻结筛选中已确认负样本':'冻结全部筛选结果'}}</el-button><el-button :disabled="busy" @click="clearSelection">清除选择</el-button></div><el-alert v-if="reference" :title="`服务器冻结 ${count} 张；修改范围请先清除选择`" type="info" :closable="false"/><el-table :data="rows" v-loading="busy"><el-table-column label="选择" width="70"><template #default="{row}"><el-checkbox :model-value="reference?members.includes(row.id):selected.has(row.id)" :disabled="busy||!!reference||row.selectable===false||(poolOnly&&row.sample_role==='positive')" @change="toggle(row.id)"/></template></el-table-column><el-table-column label="预览" width="110"><template #default="{row}"><img v-if="row.thumbnail_url" :src="row.thumbnail_url" loading="lazy" :alt="row.filename||row.name" style="width:80px;height:60px;object-fit:contain"/></template></el-table-column><el-table-column label="素材" prop="filename"/><el-table-column label="正式标注" prop="annotation_state"/><el-table-column label="标注框" prop="box_count"/><el-table-column label="正式角色"><template #default="{row}">{{row.sample_role||'待核验'}}</template></el-table-column><el-table-column v-if="poolOnly" label="资格说明" prop="sample_role_issue_type"/></el-table><div class="actions"><el-button :disabled="busy||page<=1" @click="page--;load()">上一页</el-button><span>第 {{page}} 页</span><el-button :disabled="busy||!hasNext" @click="page++;load()">下一页</el-button></div><footer><el-button :disabled="busy" @click="emit('cancel')">取消</el-button><el-button type="primary" :disabled="busy||(!count&&!poolOnly&&!positiveOnly)" @click="confirm">{{poolOnly?'应用负样本选择':'读取正式标签并核验选择'}}</el-button></footer></section></template>
<style scoped>.training-materials{padding:20px}form,.actions,footer{display:flex;gap:12px;align-items:center;margin:16px 0}form .el-input{max-width:360px}footer{justify-content:flex-end}</style>
