<script setup lang="ts">
import {ref} from 'vue';
import {request} from './http';
import type {PoolCategory} from '../types/negative-pool';

// Reuses the existing v61 negative-pool category owner (GET/POST/PATCH). The
// category list itself lives in the workbench parent so the member filter always
// sees the same data; category deletion keeps its original reference protection.
const props=defineProps<{projectId:string;categories:PoolCategory[];loading:boolean}>();
const emit=defineEmits<{refresh:[]}>();
const saving=ref(false),error=ref(''),notice=ref('');
const draftName=ref(''),editing=ref(''),editName=ref('');
const root=()=>`/api/v61/projects/${encodeURIComponent(props.projectId)}/negative-pool/categories`;
const enabledOf=(row:PoolCategory)=>row.enabled!==false&&row.enabled!==0;
const definite=(status?:number)=>status===400||status===404||status===409||status===422;

async function write(action:()=>Promise<PoolCategory>,success:(row:PoolCategory)=>string){
  if(saving.value)return;
  saving.value=true;error.value='';notice.value='';
  try{
    const row=await action();
    notice.value=success(row);
    emit('refresh');
  }catch(cause){
    const status=(cause as {httpStatus?:number}).httpStatus;
    // A definite rejection did not apply; anything else is unknown and is
    // resolved by re-reading the category list instead of retrying the write.
    error.value=definite(status)
      ?(cause as Error).message
      :`写入结果未知：${(cause as Error).message}。已改为读取原分类状态，未重复提交。`;
    if(!definite(status))emit('refresh');
  }finally{saving.value=false}
}
function create(){
  const name=draftName.value.trim();
  if(!name||saving.value)return;
  void write(()=>request<PoolCategory>(root(),{method:'POST',body:JSON.stringify({name})}),(row)=>{
    if(row?.id)editing.value='';
    draftName.value='';return `已新增分类 ${row?.name||name}。`;
  });
}
function patch(row:PoolCategory,body:{name?:string;enabled?:boolean}){
  if(saving.value)return;
  void write(()=>request<PoolCategory>(`${root()}/${encodeURIComponent(row.id)}`,{method:'PATCH',body:JSON.stringify(body),signal:undefined}),(result)=>{
    // The server keeps name uniqueness; an identity mismatch is reported instead
    // of silently adopting another category.
    if(result?.id!==row.id)throw new Error('分类更新回执身份不一致');
    editing.value='';
    return `已更新分类 ${result.name}。`;
  });
}
function startEdit(row:PoolCategory){editing.value=row.id;editName.value=row.name}
function saveEdit(row:PoolCategory){
  const name=editName.value.trim();
  if(!name||name===row.name){editing.value='';return}
  patch(row,{name});
}
</script>

<template>
 <details class="pool-categories" aria-label="负样本分类管理">
  <summary>负样本分类（{{categories.length}}）</summary>
  <el-alert v-if="error" :title="error" type="error" :closable="false"/>
  <p v-if="notice" role="status">{{notice}}</p>
  <form class="pool-category-create" @submit.prevent="create">
    <el-input v-model="draftName" aria-label="新分类名称" placeholder="新分类名称（1–100 字）" maxlength="100" :disabled="saving"/>
    <el-button native-type="submit" :loading="saving" :disabled="!draftName.trim()||saving">新增分类</el-button>
    <el-button :loading="loading" :disabled="saving" @click="emit('refresh')">刷新</el-button>
  </form>
  <el-table :data="categories" row-key="id" size="small" empty-text="暂无负样本分类" max-height="260">
    <el-table-column label="分类" min-width="170">
      <template #default="{row}">
        <el-input v-if="editing===row.id" v-model="editName" aria-label="分类名称" maxlength="100" :disabled="saving" @keyup.enter="saveEdit(row)"/>
        <strong v-else>{{row.name}}</strong>
      </template>
    </el-table-column>
    <el-table-column label="引用素材" width="100"><template #default="{row}">{{typeof row.material_count==='number'?row.material_count:'未提供'}}</template></el-table-column>
    <el-table-column label="状态" width="90"><template #default="{row}"><el-tag :type="enabledOf(row)?'success':'info'" effect="plain" size="small">{{enabledOf(row)?'启用':'停用'}}</el-tag></template></el-table-column>
    <el-table-column label="操作" width="180">
      <template #default="{row}">
        <el-button v-if="editing===row.id" link :loading="saving" @click="saveEdit(row)">保存</el-button>
        <el-button v-else link :disabled="saving" @click="startEdit(row)">改名</el-button>
        <el-button v-if="editing===row.id" link :disabled="saving" @click="editing=''">取消</el-button>
        <el-button link :disabled="saving" @click="patch(row,{enabled:!enabledOf(row)})">{{enabledOf(row)?'停用':'启用'}}</el-button>
      </template>
    </el-table-column>
  </el-table>
  <p class="pool-category-note">分类写入复用原负样本池事务与修订号，名称唯一性由服务端判定；分类删除涉及成员引用保护，仍在原管理入口处理。</p>
 </details>
</template>

<style scoped>
.pool-categories{border:1px solid var(--workspace-line,#e4e4e7);border-radius:8px;padding:10px 12px;margin:10px 0;background:var(--workspace-surface,#fff)}
.pool-categories summary{cursor:pointer;font-size:13px;font-weight:600}
.pool-category-create{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0}
.pool-category-create .el-input{width:min(100%,260px)}
.pool-category-note{margin:8px 0 0;font-size:12px;color:var(--workspace-muted,#52525b)}
</style>
