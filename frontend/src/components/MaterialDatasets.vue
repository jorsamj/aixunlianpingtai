<script setup lang="ts">
import {computed,onBeforeUnmount,ref,shallowRef,watch} from 'vue';
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
// The membership endpoint locks and updates one material per request.
const membershipLimit=100;
const selectedIds=computed(()=>[...new Set(props.selected)]);
const canMove=computed(()=>selectedIds.value.length>0&&selectedIds.value.length<=membershipLimit
  &&rows.value.some(row=>row.id===destination.value)
  &&(selectedIds.value.length>1||!!image.value&&destination.value!==dataset(image.value)));
const results=shallowRef<{id:string;state:string}[]>([]);
const submittedCount=ref(0);
const root='/api/projects/'+encodeURIComponent(props.projectId)+'/datasets';
function dataset(row:MaterialRow){return row.dataset_id||'default'}
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
    const id=pending.value?.id||(selectedIds.value.length===1?selectedIds.value[0]:undefined);
    if(id){
      const detail=await api.detail(id,controller.signal);
      if(selectedIds.value.length===1&&selectedIds.value[0]===id)image.value=detail.image;
      if(pending.value&&pending.value.dataset===dataset(detail.image)){
        results.value=results.value.map(result=>result.id===id?{id,state:'已核验目标归属'}:result);
        pending.value=undefined;
        if(submittedCount.value===1)reported.value='已核验素材的新归属。';
        emit('changed');
      }
    }
    if(!destination.value)destination.value=image.value?dataset(image.value):'';
  }catch(cause){issue(cause)}
  finally{busy.value=false}
}
async function move(){
  const ids=selectedIds.value,target=destination.value;
  if(!canMove.value||busy.value||pending.value)return;
  busy.value=true;err.value='';reported.value='';
  results.value=[];submittedCount.value=ids.length;
  const outcomes: {id:string;state:string}[]=[];
  try{
    if(workspaceActorKey(await readWorkspaceSession(controller.signal))!==props.actorKey)throw new Error('登录已变化，请重新打开素材库');
    for(const id of ids){
      pending.value={id,dataset:target};
      try{
        const {ok}=await request<{ok:boolean}>(`/api/v12/projects/${encodeURIComponent(props.projectId)}/images/${encodeURIComponent(id)}`,{
          method:'PATCH',signal:controller.signal,body:JSON.stringify({dataset_id:target}),
        });
        if(ok!==true)throw new Error('素材归属待核验');
        if(ids.length>1)pending.value=undefined;
        outcomes.push({id,state:pending.value?'待核验':'已更新'});
      }catch(cause){
        const status=(cause as {httpStatus?:number})?.httpStatus;
        if(status&&status>=400&&status<500)pending.value=undefined;
        outcomes.push({id,state:pending.value?'待核验':browseError(cause)});
        issue(cause);
        break;
      }
    }
    results.value=outcomes;
    if(outcomes.length===ids.length&&outcomes.every(result=>result.state==='已更新'))
      reported.value=`已将 ${ids.length} 张素材的归属更新为 ${name(target)}。`;
    if(outcomes.some(result=>result.state==='已更新'))emit('changed');
  }catch(cause){issue(cause)}
  finally{busy.value=false}
  if(pending.value){
    const writeError=err.value;
    await load();
    if(writeError&&pending.value&&!err.value)err.value=writeError;
  }
}
watch(open,visible=>{
  if(!visible)return;
  if(!pending.value){destination.value='';results.value=[];submittedCount.value=0;reported.value=''}
  void load();
});
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
  <template v-else-if="selectedIds.length && selectedIds.length<=membershipLimit">
   <p v-if="image">{{image.filename}} · {{name(dataset(image))}}</p>
   <p v-else>已选 {{selectedIds.length}} 张素材</p>
   <el-select v-model="destination" aria-label="目标数据集" :disabled="busy">
    <el-option v-for="row in rows" :key="row.id" :label="row.name" :value="row.id" />
   </el-select>
   <p v-if="selectedIds.length>1&&destination">所选素材将从原数据集移至 {{name(destination)}}。移出专用数据集时可选择默认数据集。</p>
   <el-button :disabled="busy || !canMove" @click="move">{{selectedIds.length===1?'确认调整归属':'确认批量调整归属'}}</el-button>
  </template>
  <p v-else-if="selectedIds.length">本入口一次可调整 {{membershipLimit}} 张已选素材，请缩小选区。</p>
  <p v-else>勾选素材后可以调整数据集归属。</p>
  <details v-if="results.length">
   <summary>归属处理结果 · 已提交 {{results.length}} 张 · 未提交 {{submittedCount-results.length}} 张</summary>
   <el-table :data="results" max-height="200">
    <el-table-column label="素材 ID" prop="id" min-width="180" />
    <el-table-column label="结果" prop="state" min-width="240" />
   </el-table>
  </details>
  <template #footer><el-button :loading="busy" @click="load">{{pending?'核验归属':'刷新目录'}}</el-button></template>
 </el-dialog>
</template>
