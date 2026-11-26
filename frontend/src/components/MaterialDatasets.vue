<script setup lang="ts">
import {onBeforeUnmount,ref,shallowRef,watch} from 'vue';
import {request} from '../app/http';
import {readWorkspaceSession,workspaceActorKey} from '../app/main';
import {materialsApi} from '../api/materials';
import {browseError} from '../api/model-browse';
import type {MaterialRow} from '../types/materials';

const props=defineProps<{projectId:string;actorKey:string;selected:string[]}>();
const open=defineModel<boolean>('open',{required:true});
const emit=defineEmits<{changed:[]}>();
const controller=new AbortController();
const api=materialsApi({projectId:props.projectId,get:request,signal:controller.signal,memory:{}});
const rows=shallowRef<{id:string;name:string;description?:string}[]>([]);
const image=shallowRef<MaterialRow>();
const destination=ref(''),reported=ref(''),err=ref(''),busy=ref(false);
const pending=shallowRef<{id:string;dataset:string}>();
const root='/api/projects/'+encodeURIComponent(props.projectId)+'/datasets';
function dataset(row?:MaterialRow){return row?.dataset_id||'default'}
function name(id:string){return rows.value.find(row=>row.id===id)?.name||id}
function issue(cause:unknown){if(!controller.signal.aborted)err.value=browseError(cause)}

async function load(){
  if(busy.value)return;
  busy.value=true;err.value='';image.value=undefined;
  try{
    const data=await request<{ok:boolean;project_id:string;items:typeof rows.value}>(root+'?directory_only=true',{signal:controller.signal});
    if(!data.ok||data.project_id!==props.projectId||!Array.isArray(data.items)
      ||new Set(data.items.map(row=>row.id)).size!==data.items.length||data.items.some(row=>!row.id))
      throw new Error('数据集目录响应身份不一致');
    rows.value=data.items;
    const id=pending.value?.id||(props.selected.length===1?props.selected[0]:undefined);
    if(id)image.value=(await api.detail(id,controller.signal)).image;
    destination.value=pending.value?.dataset||dataset(image.value);
    if(pending.value&&destination.value===dataset(image.value)){
      pending.value=undefined;reported.value='已核验素材的新归属。';emit('changed');
    }
  }catch(cause){issue(cause)}
  finally{busy.value=false}
}
async function move(){
  const row=image.value,target=destination.value;
  if(!row||busy.value||pending.value||target===dataset(row)||!rows.value.some(item=>item.id===target))return;
  busy.value=true;err.value='';reported.value='';
  try{
    if(workspaceActorKey(await readWorkspaceSession(controller.signal))!==props.actorKey)throw new Error('登录已变化，请重新打开素材库');
    pending.value={id:row.id,dataset:target};
    const {ok}=await request<{ok:boolean}>(`/api/v12/projects/${encodeURIComponent(props.projectId)}/images/${encodeURIComponent(row.id)}`,{
      method:'PATCH',signal:controller.signal,body:JSON.stringify({dataset_id:target}),
    });
    if(!ok)throw new Error('素材归属待核验');
  }catch(cause){
    const status=(cause as {httpStatus?:number})?.httpStatus;
    if(status&&status>=400&&status<500)pending.value=undefined;
    issue(cause);
  }finally{busy.value=false}
  if(pending.value)await load();
}
watch(open,visible=>{if(visible)void load()});
onBeforeUnmount(()=>controller.abort());
</script>

<template>
 <el-dialog v-model="open" title="数据集目录" width="min(640px,94vw)" :show-close="!busy"
  :close-on-press-escape="!busy" :close-on-click-modal="false">
  <el-alert v-if="err" :title="err" type="error" :closable="false" />
  <p v-if="reported" role="status">{{reported}}</p>
  <el-table :data="rows" max-height="280" v-loading="busy" empty-text="暂无数据集">
   <el-table-column label="数据集" prop="name" min-width="180" />
   <el-table-column label="说明" prop="description" min-width="240" />
  </el-table>
  <p v-if="pending" role="status">归属结果待核验。目标为 {{ name(pending.dataset) }}。</p>
  <template v-else-if="image">
   <p>{{image.filename}} · {{name(dataset(image))}}</p>
   <el-select v-model="destination" aria-label="目标数据集" :disabled="busy">
    <el-option v-for="row in rows" :key="row.id" :label="row.name" :value="row.id" />
   </el-select>
   <el-button :disabled="busy || destination===dataset(image)" @click="move">确认调整归属</el-button>
  </template>
  <p v-else>勾选一张素材后可以调整它的数据集归属。</p>
  <template #footer><el-button :loading="busy" @click="load">{{pending?'核验归属':'刷新目录'}}</el-button></template>
 </el-dialog>
</template>
