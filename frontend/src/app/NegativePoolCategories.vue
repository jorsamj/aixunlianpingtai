<script setup lang="ts">
import {onBeforeUnmount,onMounted,ref} from 'vue';
import {request} from './http';

// Reuses the existing v61 negative-pool category owner (GET/POST/PATCH). Category
// deletion keeps its original protection and is not exposed here.
const {projectId}=defineProps<{projectId:string}>();
const controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
type Category={id:string;name:string;enabled?:boolean|number;material_count?:number};
const categories=ref<Category[]>([]),busy=ref(false),error=ref(''),notice=ref('');
const draftName=ref(''),editing=ref(''),editName=ref('');
const root=`/api/v61/projects/${encodeURIComponent(projectId)}/negative-pool/categories`;
const enabledOf=(row:Category)=>row.enabled!==false&&row.enabled!==0;
async function load(){
  if(busy.value)return;
  busy.value=true;error.value='';
  try{
    const result=await request<{items:Category[]}>(root,{signal:controller.signal});
    if(!Array.isArray(result.items))throw new Error('分类响应格式无效');
    categories.value=result.items;
  }catch(cause){if(!controller.signal.aborted)error.value=(cause as Error).message}
  finally{busy.value=false}
}
async function create(){
  const name=draftName.value.trim();
  if(!name||busy.value)return;
  busy.value=true;error.value='';notice.value='';
  try{
    const result=await request<Category>(root,{method:'POST',body:JSON.stringify({name}),signal:controller.signal});
    if(!result?.id||result.name!==name)throw new Error('分类创建回执不完整');
    notice.value=`已新增分类 ${result.name}。`;draftName.value='';await load();
  }catch(cause){if(!controller.signal.aborted)error.value=(cause as Error).message}
  finally{busy.value=false}
}
async function patch(row:Category,body:{name?:string;enabled?:boolean}){
  if(busy.value)return;
  busy.value=true;error.value='';notice.value='';
  try{
    const result=await request<Category>(`${root}/${encodeURIComponent(row.id)}`,{method:'PATCH',body:JSON.stringify(body),signal:controller.signal});
    if(result?.id!==row.id)throw new Error('分类更新回执身份不一致');
    notice.value=`已更新分类 ${result.name}。`;editing.value='';await load();
  }catch(cause){if(!controller.signal.aborted)error.value=(cause as Error).message}
  finally{busy.value=false}
}
function startEdit(row:Category){editing.value=row.id;editName.value=row.name}
function saveEdit(row:Category){
  const name=editName.value.trim();
  if(!name||name===row.name){editing.value='';return}
  void patch(row,{name});
}
onMounted(load);
</script>

<template>
 <details class="pool-categories" aria-label="负样本分类管理">
  <summary>负样本分类（{{categories.length}}）</summary>
  <el-alert v-if="error" :title="error" type="error" :closable="false"/>
  <p v-if="notice" role="status">{{notice}}</p>
  <form class="pool-category-create" @submit.prevent="create">
    <el-input v-model="draftName" aria-label="新分类名称" placeholder="新分类名称（1–100 字）" maxlength="100" :disabled="busy"/>
    <el-button native-type="submit" :loading="busy" :disabled="!draftName.trim()">新增分类</el-button>
    <el-button :loading="busy" @click="load">刷新</el-button>
  </form>
  <el-table :data="categories" row-key="id" size="small" empty-text="暂无负样本分类" max-height="260">
    <el-table-column label="分类" min-width="170">
      <template #default="{row}">
        <template v-if="editing===row.id">
          <el-input v-model="editName" aria-label="分类名称" maxlength="100" :disabled="busy" @keyup.enter="saveEdit(row)"/>
        </template>
        <template v-else><strong>{{row.name}}</strong></template>
      </template>
    </el-table-column>
    <el-table-column label="引用素材" width="100"><template #default="{row}">{{typeof row.material_count==='number'?row.material_count:'未提供'}}</template></el-table-column>
    <el-table-column label="状态" width="90"><template #default="{row}"><el-tag :type="enabledOf(row)?'success':'info'" effect="plain" size="small">{{enabledOf(row)?'启用':'停用'}}</el-tag></template></el-table-column>
    <el-table-column label="操作" width="170">
      <template #default="{row}">
        <el-button v-if="editing===row.id" link :loading="busy" @click="saveEdit(row)">保存</el-button>
        <el-button v-else link :disabled="busy" @click="startEdit(row)">改名</el-button>
        <el-button v-if="editing===row.id" link :disabled="busy" @click="editing=''">取消</el-button>
        <el-button link :disabled="busy" @click="patch(row,{enabled:!enabledOf(row)})">{{enabledOf(row)?'停用':'启用'}}</el-button>
      </template>
    </el-table-column>
  </el-table>
  <p class="pool-category-note">分类写入复用原负样本池事务与修订号；分类删除涉及成员引用保护，仍在原管理入口处理。</p>
 </details>
</template>

<style scoped>
.pool-categories{border:1px solid var(--workspace-line,#e4e4e7);border-radius:8px;padding:10px 12px;margin:10px 0;background:var(--workspace-surface,#fff)}
.pool-categories summary{cursor:pointer;font-size:13px;font-weight:600}
.pool-category-create{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0}
.pool-category-create .el-input{width:min(100%,260px)}
.pool-category-note{margin:8px 0 0;font-size:12px;color:var(--workspace-muted,#52525b)}
</style>
