<script setup lang="ts">
import {onBeforeUnmount,ref} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import MaterialLibrary from '../views/MaterialLibrary.vue';
import MaterialBatchGovernance from '../components/MaterialBatchGovernance.vue';
import MaterialDatasets from '../components/MaterialDatasets.vue';
import type {MaterialContext,MaterialFilters,MaterialHistory,MaterialMemory} from '../types/materials';
import {request} from './http';
import {useWorkspace} from './main';
import {legacyUrl} from './navigation';

const route=useRoute(),router=useRouter(),controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
const projectId=String(route.params.projectId);
const workspace=useWorkspace(),actorKey=workspace.actorKey;
const selectionKey='materials.selection:'+JSON.stringify([actorKey,projectId]);
const storageFailed=ref(false);
const aiHandoffError=ref('');
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
const library=ref<InstanceType<typeof MaterialLibrary>>();
const governance=ref(false),governanceScope=ref<{ids:string[];filters:MaterialFilters}>();
const datasets=ref(false),datasetSelection=ref<string[]>([]);
function openDatasets(){
  datasetSelection.value=[...current.selectedItems];datasets.value=true;
}

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
  projectId,actorKey:workspace.actorKey,signal:controller.signal,get:request,
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
  legacyMaterials(action,id){
    if(action==='annotate'){openAnnotation(id);return}
    location.assign(original(action==='upload'?'material-upload':'material-manage','数据集',id));
  },
  async renameMaterial(id,name){
    const result=await request<{ok:boolean;image:{id:string;filename:string}}>(
      `/api/v47/projects/${encodeURIComponent(projectId)}/images/${encodeURIComponent(id)}`,
      {method:'PUT',body:JSON.stringify({name})},
    );
    if(result.ok!==true||result.image?.id!==id||!result.image.filename)throw new Error('改名结果待核对');
    return result.image.filename;
  },
  openNativeUpload(){void router.push({name:'material-upload',params:{projectId}})},
  openNativeZip(){void router.push({name:'material-zip-import',params:{projectId}})},
  openUploadTasks(){void router.push({name:'upload-tasks',params:{projectId}})},
  history(id,page,signal){
    // Existing read-only history contract uses POST to carry the material scope.
    return request<MaterialHistory>(`/api/v62/projects/${encodeURIComponent(projectId)}/training-materials/history`,{
      method:'POST',signal,body:JSON.stringify({image_id:id,algorithm_asset_id:'',page,page_size:20}),
    });
  },
};

function openAnnotation(image?:string){
  void router.push({name:'formal-annotation',params:{projectId},query:{...routeQuery(current),image}});
}
async function locationFor(action:string,page:string){
  if(action==='material-manual'){openAnnotation();return}
  if(action==='material-clean'){await router.push({name:'native-cleaning',params:{projectId}});return}
  if(action==='material-manage'){
    governanceScope.value={ids:[...current.selectedItems],filters:{...current.filters}};
    governance.value=true;return;
  }
  if(action==='material-ai'){
    if(!actorKey||workspace.actorKey!==actorKey)return;
    aiHandoffError.value='';
    const imageIds=[...current.selectedItems];
    if(imageIds.length>50000){aiHandoffError.value='一次最多继承 50000 张已选素材，请缩小已选范围。';return}
    try{
      await router.push({name:'ai-create',params:{projectId},
        query:{...current.filters,material_scope:imageIds.length?'selected':'filters'},
        state:imageIds.length?{aiCreateSelection:{projectId,actorKey,imageIds}}:undefined});
    }catch{aiHandoffError.value='无法带入已选素材，请保留当前选择并重试。'}
    return;
  }
  if(page==='标签管理'){void router.push({name:'labels',params:{projectId}});return}
  location.assign(original(action,page))
}

const legacyActions=[
  ['上传图片','material-upload','数据集'],['ZIP 数据集导入','material-zip','数据集'],
  ['人工标注','material-manual','数据集'],['AI 预标注','material-ai','自动标注及清洗'],
  ['素材清洗','material-clean','自动标注及清洗'],['历史算法池','material-negative','数据集'],
  ['标签管理','material-labels','标签管理'],['批量治理','material-manage','数据集'],
  ['删除与安全审核','material-integrity','数据集'],
];
</script>

<template>
  <MaterialLibrary ref="library" :context="context" standalone delete-enabled>
    <template #actions>
      <nav class="material-actions" aria-label="素材操作">
        <el-button tag="router-link" :to="{name:'public-negative-pool',params:{projectId}}">负样本池</el-button>
        <el-button @click="openDatasets">数据集目录</el-button>
        <el-button v-for="[label,action,page] in legacyActions" :key="label" @click="locationFor(action,page)">{{label}}</el-button>
        <el-button tag="a" :href="original('material-manage')">原素材治理</el-button>
      </nav>
      <el-alert v-if="storageFailed" title="浏览器无法保留选择，刷新或离开页面后需重新核对。" type="warning" :closable="false"/>
      <el-alert v-if="aiHandoffError" :title="aiHandoffError" type="error" :closable="false"/>
    </template>
  </MaterialLibrary>
  <MaterialBatchGovernance v-if="governanceScope" v-model:open="governance" :project-id="projectId" :actor-key="actorKey"
    :ids="governanceScope.ids" :filters="governanceScope.filters" @changed="library?.refresh()" />
  <MaterialDatasets v-model:open="datasets" :project-id="projectId" :actor-key="actorKey"
    :selected="datasetSelection" @changed="library?.refresh()" />
</template>

<style scoped>
.material-actions{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
.material-actions :deep(.el-button){margin:0}
</style>
