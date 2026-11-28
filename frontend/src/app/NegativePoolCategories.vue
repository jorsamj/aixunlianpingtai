<script setup lang="ts">
import {computed,ref,watch} from 'vue';
import {request} from './http';
import type {PoolCategory} from '../types/negative-pool';

// Reuses the existing v61 negative-pool category owner (GET/POST/PATCH). The
// category list itself lives in the workbench parent so the member filter always
// sees the same data; category deletion keeps its original reference protection.
// The parent's read error stays separate from this panel's write error, and an
// unverified write keeps its real operation identity until a trusted read-back.
interface PendingWrite{operation:'create'|'rename'|'enable'|'disable';targetId:string;targetName:string;submitted:{name?:string;enabled?:boolean};at:string}
const props=defineProps<{projectId:string;categories:PoolCategory[];loading:boolean;readError:string}>();
const emit=defineEmits<{refresh:[]}>();
const saving=ref(false),writeError=ref(''),notice=ref('');
const pendingWrite=ref<PendingWrite|null>(null),readBackTrusted=ref(false);
const draftName=ref(''),editing=ref(''),editName=ref('');
const root=()=>`/api/v61/projects/${encodeURIComponent(props.projectId)}/negative-pool/categories`;
const enabledOf=(row:PoolCategory)=>row.enabled!==false&&row.enabled!==0;
// The v61 PATCH returns the stored row: SQLite keeps `enabled` as 1/0 and the repo
// type is boolean|number. A receipt is only accepted with an explicit, matching
// value; a missing/null field is never read as "enabled".
const confirmedEnabled=(value:PoolCategory['enabled'])=>(value===true||value===1)?true:(value===false||value===0)?false:null;
const definite=(status?:number)=>status===400||status===404||status===409||status===422;
// A reload requested while the parent is already reading must not be dropped.
const pendingReload=ref(false);
function refresh(){
  if(props.loading){pendingReload.value=true;return}
  emit('refresh');
}
// The pending record may only be cleared after a read that started after the
// unknown write finished successfully: the parent stopped loading with no read
// error. A failed read leaves the record unverified.
watch(()=>props.loading,(value:boolean)=>{
  if(value)return;
  if(pendingReload.value){pendingReload.value=false;emit('refresh');return}
  if(pendingWrite.value)readBackTrusted.value=!props.readError;
});
const pendingText=computed(()=>{
  const pending=pendingWrite.value;
  if(!pending)return '';
  const operation={create:'新增分类',rename:'改名',enable:'启用',disable:'停用'}[pending.operation];
  const submitted=[pending.submitted.name!==undefined?`name=${pending.submitted.name}`:'',pending.submitted.enabled!==undefined?`enabled=${pending.submitted.enabled}`:''].filter(Boolean).join('、');
  return `${operation} · ${pending.targetId?`${pending.targetName}（${pending.targetId}）`:`${pending.targetName}（尚未分配 ID）`} · 提交字段 ${submitted||'未提供'} · ${pending.at}`;
});
function unknown(pending:Omit<PendingWrite,'at'>,message:string){
  pendingWrite.value={...pending,at:new Date().toLocaleString('zh-CN',{hour12:false})};
  readBackTrusted.value=false;
  writeError.value=`写入结果未知：${message}。已保留待核记录并回读原分类状态，未重复提交。`;
  refresh();
}
async function write(pending:Omit<PendingWrite,'at'>,action:()=>Promise<PoolCategory>,accept:(row:PoolCategory)=>boolean,success:(row:PoolCategory)=>string){
  if(saving.value)return;
  if(pendingWrite.value){
    writeError.value=`已存在未核对的写入（${pendingText.value}）；请重新读取并核对分类列表后再提交，本次未发出请求。`;
    return;
  }
  saving.value=true;writeError.value='';notice.value='';
  try{
    const row=await action();
    if(!row||typeof row.id!=='string'||!row.id||!accept(row)){unknown(pending,'回执未确认实际分类身份');return}
    notice.value=success(row);
    refresh();
  }catch(cause){
    const status=(cause as {httpStatus?:number}).httpStatus;
    if(definite(status))writeError.value=(cause as Error).message;
    else unknown(pending,(cause as Error).message);
  }finally{saving.value=false}
}
function create(){
  const name=draftName.value.trim();
  if(!name||saving.value)return;
  void write({operation:'create',targetId:'',targetName:name,submitted:{name}},
    ()=>request<PoolCategory>(root(),{method:'POST',body:JSON.stringify({name})}),
    row=>typeof row.name==='string'&&row.name===name,(row)=>{draftName.value='';return `已新增分类 ${row.name}（${row.id}）。`});
}
function patch(row:PoolCategory,body:{name?:string;enabled?:boolean}){
  if(saving.value)return;
  const operation:'rename'|'enable'|'disable'=body.name!==undefined?'rename':body.enabled?'enable':'disable';
  void write({operation,targetId:row.id,targetName:row.name,
      submitted:{...(body.name!==undefined?{name:body.name}:{}),...(body.enabled!==undefined?{enabled:body.enabled}:{})}},
    ()=>request<PoolCategory>(`${root()}/${encodeURIComponent(row.id)}`,{method:'PATCH',body:JSON.stringify(body)}),
    (result)=>result.id===row.id
      &&(body.name===undefined||result.name===body.name)
      &&(body.enabled===undefined||confirmedEnabled(result.enabled)===body.enabled),
    (result)=>{editing.value='';return `已更新分类 ${result.name}。`});
}
function startEdit(row:PoolCategory){editing.value=row.id;editName.value=row.name}
function clearPending(){
  if(!pendingWrite.value)return;
  if(!readBackTrusted.value){writeError.value='分类列表尚未重新读取成功，不能清除待核记录。';return}
  pendingWrite.value=null;writeError.value='';notice.value='已核对分类列表，待核记录已清除。';
}
function saveEdit(row:PoolCategory){
  const name=editName.value.trim();
  if(!name||name===row.name){editing.value='';return}
  patch(row,{name});
}</script>

<template>
 <details class="pool-categories" aria-label="负样本分类管理">
  <summary>负样本分类（{{categories.length}}）</summary>
  <el-alert v-if="writeError" :title="writeError" type="error" :closable="false"/>
  <el-alert v-if="readError" :title="`分类读取失败：${readError}`" type="warning" :closable="false"/>
  <p v-if="notice" role="status">{{notice}}</p>
  <p v-if="pendingWrite" class="pool-category-pending" role="alert">待核验写入：{{pendingText}}。请重新读取并核对下方分类列表后再继续操作。<el-button link :disabled="!readBackTrusted" @click="clearPending">{{readBackTrusted?'已核对分类列表':'分类列表尚未重新读取'}}</el-button></p>
  <p v-if="readError&&!categories.length" class="pool-category-note">读取失败，当前没有可信分类列表。</p>
  <p v-else-if="readError" class="pool-category-note">读取失败，下方为上次成功读取的分类状态。</p>
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
.pool-category-pending{margin:8px 0 0;font-size:12px;color:var(--el-color-warning)}
</style>
