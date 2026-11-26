<script setup lang="ts">
import {onBeforeUnmount,onMounted,ref} from 'vue';
import {useRouter} from 'vue-router';
import NegativePool from '../views/NegativePool.vue';
import NegativePoolCategories from './NegativePoolCategories.vue';
import type {PoolCategory,PoolContext} from '../types/negative-pool';
import {frozenPoolPacket} from '../api/negative-pool';
import {request} from './http';
import {readWorkspaceSession,useWorkspace,workspaceActorKey} from './main';
import {legacyUrl} from './navigation';

const {projectId}=defineProps<{projectId:string}>();
const router=useRouter(),actor=useWorkspace().actorKey,controller=new AbortController();
const selectionKey='materials.selection:'+JSON.stringify([actor,projectId]);
const pendingKey='algorithm-negative-pool:'+JSON.stringify([actor,projectId]);
const filters={query:'',label:'',annotation_state:'',quality_status:'',storage_source_id:'',
  source_batch_id:'',created_from:'',created_to:''};
let selected:string[]=[];
try{
  const stored:unknown=JSON.parse(sessionStorage.getItem(selectionKey)||'[]');
  if(Array.isArray(stored))selected=[...new Set(stored.filter((id):id is string=>typeof id==='string'&&!!id))];
}catch{}
const memory:PoolContext['memory']={materials:{filters,page:1,layout:'grid',selectedItems:selected}};
// The workbench parent owns the single category source: the management panel and
// the member filter both read it, so a rename or enable toggle is visible at once
// without a second loader or a global store.
const categories=ref<PoolCategory[]>([]),categoryLoading=ref(false),categoryError=ref('');
async function loadCategories(){
  if(categoryLoading.value)return;
  categoryLoading.value=true;
  try{
    const result=await request<{items:PoolCategory[]}>(`/api/v61/projects/${encodeURIComponent(projectId)}/negative-pool/categories`,{signal:controller.signal});
    if(!Array.isArray(result.items))throw new Error('分类响应格式无效');
    categories.value=result.items;categoryError.value='';
  }catch(cause){if(!controller.signal.aborted)categoryError.value=(cause as Error).message}
  finally{categoryLoading.value=false}
}
const context:PoolContext={
  projectId,actorKey:actor,get:request,signal:controller.signal,memory,
  poolPending:{
    get value(){return JSON.parse(sessionStorage.getItem(pendingKey)||'null')},
    save(value){
      if(!actor)throw new Error('无法确认当前登录账号');
      if(value)sessionStorage.setItem(pendingKey,JSON.stringify(value));
      else sessionStorage.removeItem(pendingKey);
    },
  },
  createOperationId(){
    return Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
  },
  async poolWrite(value){
    const packet=frozenPoolPacket(value);
    if(!packet||packet.project_id!==projectId||!actor||workspaceActorKey(await readWorkspaceSession(controller.signal))!==actor)
      throw new Error('负样本池项目或登录账号已变化');
    const {project_id,...body}=packet;
    return request(`/api/v61/projects/${encodeURIComponent(project_id)}/negative-pool/members`,
      {method:'POST',signal:controller.signal,body:JSON.stringify(body)});
  },
  legacyPool(){location.assign(legacyUrl(projectId,'数据集','','','material-negative'))},
  openMaterials(){
    try{sessionStorage.setItem(selectionKey,JSON.stringify(memory.materials?.selectedItems||[]))}catch{}
    void router.push({name:'materials',params:{projectId}});
  },
};
onMounted(()=>void loadCategories());
onBeforeUnmount(()=>controller.abort());
</script>

<template>
 <NegativePoolCategories :project-id="projectId" :categories="categories" :loading="categoryLoading"
  @refresh="loadCategories"/>
 <el-alert v-if="categoryError" :title="`分类读取失败：${categoryError}`" type="warning" :closable="false"/>
 <NegativePool :context="context" :pool-categories="categories"/>
</template>
