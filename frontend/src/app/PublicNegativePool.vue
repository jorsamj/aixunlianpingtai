<script setup lang="ts">
import {computed,onBeforeUnmount,ref} from 'vue';
import {useRoute} from 'vue-router';
import MaterialPreview from '../components/MaterialPreview.vue';
import type {MaterialRow} from '../types/materials';
import {request} from './http';

type Category={id:string;name:string;enabled:boolean};
type PoolRow=MaterialRow&{negative_pool?:{categories?:Category[];review_status?:string}};
type Packet={operation_kind:'negative_pool.members.v2';operation_id:string;expected_revision:string;action:'add'|'remove'|'set';image_ids:string[];category_ids:string[];categories_only:boolean};
type Receipt={project_id:string;operation_id:string;operation_kind:string;action:string;affected:number;negative_pool_revision:string};
const projectId=String(useRoute().params.projectId),project=encodeURIComponent(projectId);
const base=`/api/v61/projects/${project}/negative-pool`, key='public-negative-pool:'+projectId;
const controller=new AbortController();
onBeforeUnmount(()=>controller.abort());
const categories=ref<Category[]>([]),rows=ref<PoolRow[]>([]),selected=ref<string[]>([]),assigned=ref<string[]>([]);
const page=ref(1),total=ref(0),revision=ref('0'),query=ref(''),category=ref(''),review=ref(''),catalog=ref(false);
const editing=ref(''),categoryName=ref(''),busy=ref(false),error=ref(''),message=ref(''),pending=ref<Packet|null>(null);
const confirmation=ref<Packet['action']|null>(null);
const visibleNames=computed(()=>rows.value.filter(row=>selected.value.includes(row.id)).map(row=>row.filename));
try{pending.value=JSON.parse(sessionStorage.getItem(key)||'null')}catch{}
async function run(action:()=>Promise<void>){
 if(busy.value)return;
 busy.value=true;error.value='';message.value='';
 try{await action()}catch(cause){if(!controller.signal.aborted)error.value=(cause as Error).message}
 finally{busy.value=false}
}
async function fetchCategories(){
 categories.value=(await request<{items:Category[]}>(base+'/categories',{signal:controller.signal})).items;
}
async function fetchRows(){
 const q=new URLSearchParams({reader_view:'true',page:String(page.value),page_size:'48',query:query.value});
 if(!catalog.value&&category.value)q.set('category_id',category.value);
 if(!catalog.value&&review.value)q.set('review_status',review.value);
 const result=await request<{project_id:string;items:PoolRow[];total:number;negative_pool_revision?:string}>(
   (catalog.value?`/api/v61/projects/${project}/materials`:base)+'?'+q,{signal:controller.signal});
 if(result.project_id!==projectId)throw new Error('素材项目不一致');
 rows.value=result.items;total.value=result.total;
 if(result.negative_pool_revision)revision.value=result.negative_pool_revision;
 else {
  const current=await request<{project_id:string;negative_pool_revision:string}>(base+'?reader_view=true&page=1&page_size=1',{signal:controller.signal});
  if(current.project_id!==projectId)throw new Error('负样本池项目不一致');
  revision.value=current.negative_pool_revision;
 }
 selected.value=[];
}
function browse(pageNumber=1){void run(async()=>{page.value=pageNumber;await fetchRows()})}
function operationId(){return Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('')}
function journal(packet:Packet|null){
 if(packet)sessionStorage.setItem(key,JSON.stringify(packet));
 else sessionStorage.removeItem(key);
 pending.value=packet;
}
async function accept(result:Receipt,packet:Packet){
 if(result.project_id!==projectId||result.operation_id!==packet.operation_id||result.operation_kind!=='negative_pool.members.v2'||result.action!==packet.action||!/^\d+$/.test(result.negative_pool_revision))
  throw new Error('回执身份异常，结果待确认');
 journal(null);
 await fetchRows();
 message.value='操作已核实';
}
function execute(){
 const action=confirmation.value;
 if(!action||pending.value||!selected.value.length)return;
 void run(async()=>{
  const packet:Packet={operation_kind:'negative_pool.members.v2',action,image_ids:[...selected.value],expected_revision:revision.value,operation_id:operationId(),
    categories_only:action==='set',category_ids:action==='remove'?[]:[...assigned.value]};
  journal(packet);confirmation.value=null;
  let result:Receipt;
  try{result=await request<Receipt>(base+'/members',{method:'POST',body:JSON.stringify(packet)});}
  catch(cause){
   if([400,401,403,409,422].includes(Number((cause as {httpStatus?:number}).httpStatus)))journal(null);
   throw cause;
  }
  await accept(result,packet);
 });
}
function recover(){
 const packet=pending.value;
 if(packet)void run(async()=>accept(await request<Receipt>(base+'/operations/'+encodeURIComponent(packet.operation_id)+'?operation_kind=negative_pool.members.v2',{signal:controller.signal}),packet));
}
function saveCategory(){
 if(!categoryName.value.trim())return;
 void run(async()=>{
  await request(base+'/categories'+(editing.value?'/'+encodeURIComponent(editing.value):''),{
   method:editing.value?'PATCH':'POST',body:JSON.stringify({name:categoryName.value.trim()}),
  });
  editing.value='';categoryName.value='';
  await fetchCategories();await fetchRows();
 });
}
void run(async()=>{await fetchCategories();await fetchRows()});
</script>

<template>
 <section class="project-pool">
  <header><h2>项目公共负样本池</h2><router-link :to="{name:'materials',params:{projectId}}">返回素材库</router-link></header>
  <p>分类用于管理素材。训练角色按当前任务的正式 GT 和确认凭证核验。</p>
  <el-alert v-if="error" :title="error" type="error" :closable="false"/>
  <p v-if="message" role="status">{{message}}</p>
  <div v-if="pending"><el-button :disabled="busy" @click="recover">查询待确认操作回执</el-button></div>
  <form @submit.prevent="browse()">
   <el-select v-model="catalog" aria-label="浏览范围" @change="browse()"><el-option :value="false" label="公共池"/><el-option :value="true" label="从素材库选择入池"/></el-select>
   <el-input v-model="query" aria-label="搜索素材" placeholder="搜索素材名称"/>
   <el-select v-if="!catalog" v-model="category" aria-label="分类筛选"><el-option value="" label="全部分类"/><el-option v-for="row in categories" :key="row.id" :value="row.id" :label="row.name"/></el-select>
   <el-select v-if="!catalog" v-model="review" aria-label="审核状态"><el-option value="" label="全部状态"/><el-option value="confirmed_empty" label="已确认无目标"/><el-option value="annotated" label="已标注"/><el-option value="unannotated" label="未标注"/><el-option value="stale" label="待复核"/></el-select>
   <el-button native-type="submit" :disabled="busy">查询</el-button>
  </form>
  <details><summary>维护分类</summary>
   <form @submit.prevent="saveCategory">
    <el-select v-model="editing" aria-label="编辑分类" @change="categoryName=categories.find(row=>row.id===editing)?.name||''">
     <el-option value="" label="新建分类"/><el-option v-for="row in categories" :key="row.id" :label="row.name" :value="row.id"/>
    </el-select>
    <el-input v-model="categoryName" aria-label="分类名称" placeholder="分类名称"/>
    <el-button native-type="submit" :disabled="busy||!!pending">保存分类</el-button>
   </form>
  </details>
  <div class="pool-tools">
   <span>当前页已选 {{selected.length}} 张</span>
   <el-select v-model="assigned" multiple collapse-tags aria-label="操作分类" placeholder="选择要设置的分类">
    <el-option v-for="row in categories.filter(row=>row.enabled)" :key="row.id" :label="row.name" :value="row.id"/>
   </el-select>
   <el-button v-if="catalog" :disabled="busy||!!pending||!selected.length" @click="confirmation='add'">加入公共池</el-button>
   <template v-else><el-button :disabled="busy||!!pending||!selected.length" @click="confirmation='set'">替换所选素材分类</el-button><el-button :disabled="busy||!!pending||!selected.length" @click="confirmation='remove'">移出公共池</el-button></template>
  </div>
  <el-checkbox-group v-model="selected">
   <div v-loading="busy" class="pool-grid">
    <article v-for="row in rows" :key="row.id">
     <MaterialPreview :image="row" :project-id="projectId" :boxes="row.annotation_preview"/>
     <el-checkbox :value="row.id">{{row.filename}}</el-checkbox>
     <p>{{row.negative_pool?.review_status||row.annotation_state||'未提供'}} · {{row.negative_pool?.categories?.map(c=>c.name).join('、')||'未分类'}}</p>
    </article>
   </div>
  </el-checkbox-group>
  <el-empty v-if="!busy&&!rows.length" description="当前条件下没有素材"/>
  <div class="pool-tools"><el-button :disabled="busy||page<=1" @click="browse(page-1)">上一页</el-button><span>第 {{page}} 页 · 共 {{total}} 张</span><el-button :disabled="busy||page*48>=total" @click="browse(page+1)">下一页</el-button></div>
  <el-dialog :model-value="!!confirmation" title="确认公共池操作" @close="confirmation=null"><p>{{visibleNames.join('、')}}</p><p v-if="confirmation==='set'">当前选择的分类将替换这些素材的原分类。</p><template #footer><el-button @click="confirmation=null">取消</el-button><el-button type="primary" @click="execute">确认</el-button></template></el-dialog>
 </section>
</template>
<style scoped>
.project-pool{padding:16px}.project-pool header,.project-pool form,.pool-tools{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:12px 0}.project-pool :deep(.el-input),.project-pool :deep(.el-select){width:190px}.pool-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(185px,1fr));gap:12px}.pool-grid article{border:1px solid #ddd;border-radius:8px;padding:8px;min-width:0;overflow-wrap:anywhere}
</style>
