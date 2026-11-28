<script setup lang="ts">
import {computed,shallowRef} from 'vue';
import {materialsApi} from '../api/materials';
import {browseError} from '../api/model-browse';
import type {MaterialContext,MaterialRow} from '../types/materials';

const props=defineProps<{image:MaterialRow;context:MaterialContext}>();
const emit=defineEmits<{saved:[id:string,filename:string];close:[]}>();
const name=shallowRef(props.image.filename);
const busy=shallowRef(false),pending=shallowRef(false),error=shallowRef('');
const submittedName=computed(()=>name.value.trim());
const valid=computed(()=>{
  const value=submittedName.value;
  return !!value&&value!==props.image.filename&&![...value].some(char=>char==='/'||char==='\\'||char.charCodeAt(0)<32);
});

async function save(){
  if(busy.value||pending.value||!valid.value||!props.context.renameMaterial)return;
  busy.value=true;
  error.value='';
  try{
    const filename=await props.context.renameMaterial(props.image.id,submittedName.value);
    if(!props.context.signal.aborted)emit('saved',props.image.id,filename);
  }catch(cause){
    if(props.context.signal.aborted)return;
    const status=(cause as {httpStatus?:number}).httpStatus;
    pending.value=!status||![400,401,403,404,409,422].includes(status);
    error.value=pending.value?'未收到改名回执，请核对当前名称。':browseError(cause);
  }finally{
    busy.value=false;
  }
}

async function verify(){
  if(busy.value)return;
  busy.value=true;
  try{
    const result=await materialsApi(props.context).detail(props.image.id,props.context.signal);
    if(props.context.signal.aborted)return;
    if(result.image.filename===submittedName.value){
      emit('saved',props.image.id,result.image.filename);
    }else{
      error.value=`当前名称为「${result.image.filename}」。请关闭后刷新素材库再决定是否操作。`;
    }
  }catch(cause){
    if(!props.context.signal.aborted)error.value=browseError(cause);
  }finally{
    busy.value=false;
  }
}
</script>

<template>
  <el-dialog :model-value="true" title="修改素材名称" width="min(480px,94vw)"
    :close-on-click-modal="false" :show-close="!busy" :close-on-press-escape="!busy" @close="emit('close')">
    <form class="rename-form" @submit.prevent="save">
      <label>素材名称
        <el-input v-model="name" aria-label="新素材名称" :disabled="busy||pending" maxlength="220"/>
      </label>
      <p>只能修改展示名称，原图文件及标注引用保持原样。</p>
      <el-alert v-if="error" :title="error" :type="pending?'warning':'error'" :closable="false"/>
      <footer>
        <el-button :disabled="busy" @click="emit('close')">{{ pending?'关闭':'取消' }}</el-button>
        <el-button v-if="pending" type="primary" :loading="busy" @click="verify">核对名称</el-button>
        <el-button v-else type="primary" native-type="submit" :disabled="!valid" :loading="busy">保存名称</el-button>
      </footer>
    </form>
  </el-dialog>
</template>

<style scoped>
.rename-form,.rename-form label{display:grid;gap:8px}.rename-form p{margin:0 0 8px;color:var(--el-text-color-secondary)}.rename-form footer{display:flex;justify-content:flex-end;margin-top:12px}
</style>
