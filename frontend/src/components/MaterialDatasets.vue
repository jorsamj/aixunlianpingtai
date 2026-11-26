<script setup lang="ts">
import {onBeforeUnmount,ref,shallowRef,watch} from 'vue';
import {request} from '../app/http';
import {browseError} from '../api/model-browse';
import type {MaterialFilters} from '../types/materials';
import MaterialAssignmentPanel from './MaterialAssignmentPanel.vue';

const props=defineProps<{projectId:string;actorKey:string;selected:string[];filters:MaterialFilters}>();
const open=defineModel<boolean>('open',{required:true});
const emit=defineEmits<{changed:[]}>();
const controller=new AbortController();
const rows=shallowRef<{id:string;name:string;description?:string}[]>([]);
const destination=ref(''),error=ref(''),busy=ref(false);

async function load(){
  if(busy.value)return;
  busy.value=true;error.value='';
  try{
    const data=await request<{ok:boolean;project_id:string;items:typeof rows.value}>(
      '/api/projects/'+encodeURIComponent(props.projectId)+'/datasets?directory_only=true',{signal:controller.signal});
    if(!data.ok||data.project_id!==props.projectId||!Array.isArray(data.items)
      ||new Set(data.items.map(row=>row.id)).size!==data.items.length||data.items.some(row=>!row.id))
      throw new Error('数据集目录响应身份不一致');
    rows.value=data.items;
    if(!rows.value.some(row=>row.id===destination.value))destination.value='';
  }catch(cause){if(!controller.signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false}
}
watch(open,visible=>{if(visible)void load()});
onBeforeUnmount(()=>controller.abort());
</script>

<template>
 <el-dialog v-model="open" title="数据集目录" width="min(680px,94vw)" :close-on-click-modal="false">
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <el-table :data="rows" max-height="240" v-loading="busy" empty-text="暂无数据集">
   <el-table-column label="数据集" prop="name" min-width="180" />
   <el-table-column label="说明" prop="description" min-width="240" />
  </el-table>
  <el-form label-position="top">
   <el-form-item label="调整素材归属">
    <el-select v-model="destination" placeholder="选择目标数据集" aria-label="目标数据集" :disabled="busy">
     <el-option v-for="row in rows" :key="row.id" :label="row.name" :value="row.id" />
    </el-select>
   </el-form-item>
  </el-form>
  <MaterialAssignmentPanel :visible="open" :project-id="projectId" :actor-key="actorKey" :ids="selected"
   :filters="filters" operation="MOVE_DATASET" :target="destination" @changed="emit('changed')" />
  <template #footer><el-button :loading="busy" @click="load">刷新目录</el-button></template>
 </el-dialog>
</template>
