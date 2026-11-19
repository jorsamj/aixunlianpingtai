<script setup lang="ts">
import {onBeforeUnmount,ref} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import MaterialLibrary from '../views/MaterialLibrary.vue';
import type {MaterialContext,MaterialFilters,MaterialHistory,MaterialMemory} from '../types/materials';
import {request} from './http';
import {useWorkspace} from './main';
import {legacyUrl} from './navigation';

const route=useRoute(),router=useRouter(),controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
const projectId=String(route.params.projectId);
const username=useWorkspace().username;
const selectionKey='materials.selection:'+JSON.stringify([username,projectId]);
const storageFailed=ref(false);
const filterKeys=['query','label','annotation_state','quality_status','storage_source_id','source_batch_id','created_from','created_to'] as const;
const queryValue=(key:string)=>typeof route.query[key]==='string'?route.query[key] as string:'';
const filters=Object.fromEntries(filterKeys.map(key=>[key,queryValue(key)])) as unknown as MaterialFilters;
const page=Number(queryValue('page'));
let selectedItems:string[]=[];
try {
  const stored:unknown=JSON.parse(sessionStorage.getItem(selectionKey)||'[]');
  if(Array.isArray(stored))selectedItems=[...new Set(stored.filter((id):id is string=>typeof id==='string'&&id.length>0))];
}catch{storageFailed.value=true}
let current:MaterialMemory={
  filters,page:Number.isSafeInteger(page)&&page>=1?page:1,
  layout:queryValue('layout')==='list'?'list':'grid',detailId:queryValue('detail'),selectedItems,
};

function routeQuery(value:MaterialMemory):Record<string,string> {
  const query:Record<string,string>={};
  for(const key of filterKeys)if(value.filters[key])query[key]=value.filters[key];
  if(value.page>1)query.page=String(value.page);
  if(value.layout==='list')query.layout='list';
  if(value.detailId)query.detail=value.detailId;
  return query;
}

function original(action:string,page='数据集',id=''){
  const extra=new URLSearchParams({return_query:new URLSearchParams(routeQuery(current)).toString()});
  if(id)extra.set('material_id',id);
  return legacyUrl(projectId,page,'','',action)+'&'+extra;
}

const context:MaterialContext={
  projectId,signal:controller.signal,get:request,
  memory:{
    get materials(){return current},
    set materials(value:MaterialMemory|undefined){
      if(!value||controller.signal.aborted)return;
      if(value.selectedItems!==current.selectedItems){
        try{sessionStorage.setItem(selectionKey,JSON.stringify(value.selectedItems));storageFailed.value=false}
        catch{storageFailed.value=true}
      }
      current=value;
      const query=routeQuery(value);
      if(router.resolve({name:'materials',params:{projectId},query}).fullPath!==route.fullPath)
        void router.replace({name:'materials',params:{projectId},query});
    },
  },
  legacyMaterials(action,id){location.assign(original(action==='annotate'?'material-annotate':action==='upload'?'material-upload':'material-manage','数据集',id))},
  history(id,page,signal){
    // Existing read-only history contract uses POST to carry the material scope.
    return request<MaterialHistory>(`/api/v62/projects/${encodeURIComponent(projectId)}/training-materials/history`,{
      method:'POST',signal,body:JSON.stringify({image_id:id,algorithm_asset_id:'',page,page_size:20}),
    });
  },
};

function locationFor(action:string,page:string){location.assign(original(action,page))}

const legacyActions=[
  ['上传图片','material-upload','数据集'],['ZIP 数据集导入','material-zip','数据集'],
  ['人工标注','material-manual','数据集'],['AI 预标注','material-ai','自动标注及清洗'],
  ['素材清洗','material-clean','自动标注及清洗'],['负样本池','material-negative','数据集'],
  ['标签管理','material-labels','标签管理'],['批量治理','material-manage','数据集'],
  ['删除与安全审核','material-integrity','数据集'],
];
</script>

<template>
  <MaterialLibrary :context="context" standalone>
    <template #actions>
      <nav class="material-actions" aria-label="原工作台操作">
        <el-button v-for="[label,action,page] in legacyActions" :key="label" @click="locationFor(action,page)">{{label}}</el-button>
      </nav>
      <el-alert v-if="storageFailed" title="浏览器无法保留选择，刷新或离开页面后需重新核对。" type="warning" :closable="false"/>
    </template>
  </MaterialLibrary>
</template>

<style scoped>
.material-actions{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
.material-actions :deep(.el-button){margin:0}
</style>
