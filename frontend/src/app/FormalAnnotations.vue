<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,shallowRef} from 'vue';
import {onBeforeRouteLeave,onBeforeRouteUpdate,useRoute,useRouter} from 'vue-router';
import FormalAnnotationEditor from './FormalAnnotationEditor.vue';
import {getReviewLabels,type ReviewLabel} from '../api/ai-review';
import {materialsApi} from '../api/materials';
import {useReadScope} from '../composables/useReadScope';
import type {MaterialFilters,MaterialPage} from '../types/materials';
import {request} from './http';
import {legacyUrl} from './navigation';

const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId);
const controller=new AbortController(),reads=useReadScope(controller),api=materialsApi({projectId,get:request,signal:controller.signal,memory:{}});
const filters:MaterialFilters={query:'',label:'',annotation_state:'',quality_status:'',storage_source_id:'',source_batch_id:'',created_from:'',created_to:''};
for(const key of Object.keys(filters) as (keyof MaterialFilters)[]){
  const value=route.query[key];
  if(typeof value==='string')filters[key]=value;
}
const search=ref(filters.query),annotationState=ref(filters.annotation_state);
const active=computed(()=>typeof route.query.image==='string'?route.query.image:'');
const start=Number(route.query.page);
const pageNumber=ref(Number.isSafeInteger(start)&&start>0?start:1);
const queueSettling=ref(false);
const page=shallowRef<MaterialPage>(),labels=shallowRef<ReviewLabel[]>();
const editor=ref<InstanceType<typeof FormalAnnotationEditor>>();
const index=computed(()=>page.value?.items.findIndex(row=>row.id===active.value)??-1);
const hasNext=computed(()=>index.value>=0&&!!page.value&&(index.value+1<page.value.items.length||page.value.has_next));
const originals=computed(()=>{
  const query=new URLSearchParams(returnQuery());
  if(active.value)query.set('detail',active.value);
  const path=legacyUrl(projectId,'数据集','','',active.value?'material-annotate':'material-manual');
  return path+'&'+new URLSearchParams({material_id:active.value,return_query:query.toString()});
});
function returnQuery(){
  const query:Record<string,string>={};
  for(const key of [...Object.keys(filters),'page','layout','detail']){
    const value=route.query[key];if(typeof value==='string'&&value)query[key]=value;
  }
  return query;
}
function select(id:string){
  if(id!==active.value)return router.replace({query:{...route.query,image:id}});
}
async function loadPage(number:number,edge?:'first'|'last',nextFilters=filters){
  let loaded:MaterialPage|undefined;
  await reads.run('page',signal=>api.listAtOrBefore(nextFilters,number,signal),result=>{loaded=result});
  if(!loaded||controller.signal.aborted)return;
  const target=edge==='last'?loaded.items.at(-1):(edge||!active.value?loaded.items[0]:undefined);
  if((target||edge)&&await select(target?.id||''))return;
  if(controller.signal.aborted)return;
  page.value=loaded;pageNumber.value=loaded.page;Object.assign(filters,nextFilters);
}
async function refreshAfterSave(id:string,advance:boolean){
  if(active.value!==id||queueSettling.value)return;
  queueSettling.value=true;
  const requested=pageNumber.value;
  const prior=page.value?.items||[];
  const oldIndex=prior.findIndex(row=>row.id===id);
  let fresh:MaterialPage|undefined;
  try{
    await reads.run('page',signal=>api.listAtOrBefore(filters,requested,signal),result=>{fresh=result});
    if(!fresh||controller.signal.aborted||active.value!==id)return;
    const current=fresh.items.findIndex(row=>row.id===id);
    page.value=fresh;pageNumber.value=fresh.page;
    if(current>=0){
      if(advance)await moveWithinFreshPage(current);
      return;
    }
    const following=new Set(oldIndex<0?[]:prior.slice(oldIndex+1).map(row=>row.id));
    const next=fresh.items.find(row=>following.has(row.id))||fresh.items[0];
    await select(next?.id||'');
  }finally{queueSettling.value=false}
}
async function moveWithinFreshPage(current:number){
  const next=page.value?.items[current+1];
  if(next)await select(next.id);
  else if(page.value?.has_next)await loadPage(pageNumber.value+1,'first');
}
function navigate(delta:number){
  if(queueSettling.value||reads.busy.page||index.value<0||!page.value)return;
  const target=page.value.items[index.value+delta];
  if(target){select(target.id);return}
  if(delta<0&&pageNumber.value>1)changePage(-1,'last');
  if(delta>0&&page.value.has_next)changePage(1,'first');
}
function changePage(delta:number,edge:'first'|'last'){
  if(queueSettling.value||reads.busy.page)return;
  void loadPage(pageNumber.value+delta,edge);
}
function searchQueue(){
  if(queueSettling.value||reads.busy.page)return;
  void loadPage(1,'first',{...filters,query:search.value.trim(),annotation_state:annotationState.value});
}
function loadLabels(){return reads.run('labels',signal=>getReviewLabels(projectId,signal),value=>{labels.value=value})}
function back(){void router.push({name:'materials',params:{projectId},query:returnQuery()})}
function exitToLegacy(){if(!editor.value||editor.value.mayLeave())location.assign(originals.value)}
function beforeLogout(event:Event){if(editor.value&&!editor.value.mayLeave())event.preventDefault()}
onBeforeRouteLeave(()=>editor.value?.mayLeave()??true);
onBeforeRouteUpdate((to,from)=>
  (to.params.projectId===from.params.projectId&&to.query.image===from.query.image)||(editor.value?.mayLeave()??true));
onMounted(()=>{window.addEventListener('workspace-before-logout',beforeLogout);void loadLabels();void loadPage(pageNumber.value)});
onBeforeUnmount(()=>{window.removeEventListener('workspace-before-logout',beforeLogout);controller.abort()});
</script>

<template>
  <div class="formal-workbench">
    <aside class="formal-queue">
      <div class="queue-tools"><el-button v-if="!active||!labels" @click="back">返回素材库</el-button><el-button link @click="exitToLegacy">原标注台</el-button></div>
      <h2>素材队列</h2>
      <form class="queue-filter" @submit.prevent="searchQueue">
        <el-input v-model="search" aria-label="队列名称" placeholder="搜索图片"/>
        <el-select v-model="annotationState" aria-label="队列标注状态">
          <el-option label="全部状态" value=""/><el-option label="待标注" value="unannotated"/>
          <el-option label="已标注" value="annotated"/><el-option label="已确认无目标" value="confirmed_empty"/>
          <el-option label="范围不完整" value="partial"/><el-option label="待审核" value="needs_review"/>
        </el-select>
        <el-button native-type="submit" :loading="reads.busy.page">查询</el-button>
      </form>
      <el-alert v-if="reads.errors.page" :title="reads.errors.page" type="error" :closable="false"/>
      <el-skeleton v-if="!page&&reads.busy.page" :rows="4" animated/>
      <div class="queue-list" v-else>
        <button v-for="item in page?.items" :key="item.id" type="button" :aria-current="item.id===active?'true':undefined"
          :disabled="reads.busy.page||queueSettling" @click="select(item.id)">{{ item.filename }}</button>
      </div>
      <div class="queue-tools">
        <el-button :disabled="index<0||reads.busy.page||(index===0&&pageNumber===1)" @click="navigate(-1)">上一张</el-button>
        <el-button :disabled="!hasNext||reads.busy.page" @click="navigate(1)">下一张</el-button>
      </div>
      <div class="queue-tools">
        <el-button link :disabled="pageNumber<=1||reads.busy.page" @click="changePage(-1,'first')">上一页</el-button>
        <span>第 {{pageNumber}} 页</span>
        <el-button link :disabled="!page?.has_next||reads.busy.page" @click="changePage(1,'first')">下一页</el-button>
      </div>
    </aside>
    <section class="formal-stage">
      <FormalAnnotationEditor v-if="active&&labels" :key="active" ref="editor" :project-id="projectId"
        :image-id="active" :labels="labels" :has-next="hasNext" @back="back" @navigate="navigate" @settled="refreshAfterSave"/>
      <div v-else class="queue-empty">
        <el-alert v-if="reads.errors.labels" :title="reads.errors.labels" type="error" :closable="false"/>
        <el-button v-if="reads.errors.labels" @click="loadLabels">重试标签读取</el-button>
        <p v-else-if="reads.busy.labels||reads.busy.page" role="status">正在读取素材和标签…</p>
        <p v-else>当前范围没有可标注的图片。</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.formal-workbench{display:grid;grid-template-columns:minmax(160px,210px) minmax(0,1fr);gap:12px;height:calc(100dvh - 135px);min-height:560px}
.formal-stage,.formal-queue{min-height:0;min-width:0;background:#fff;border:1px solid #dedede;border-radius:8px;overflow:hidden}
.formal-queue{display:flex;flex-direction:column;gap:10px;padding:12px}.formal-queue h2{font-size:15px;margin:0}.formal-queue p{font-size:12px;color:#666;margin:0}
.queue-list{flex:1;overflow:auto}.queue-list button{display:block;white-space:nowrap;text-overflow:ellipsis;overflow:hidden;width:100%;padding:9px 6px;text-align:left;border:0;border-bottom:1px solid #eee;background:white;cursor:pointer}
.queue-list button[aria-current=true]{background:#ededed;font-weight:600}.queue-tools{display:flex;align-items:center;gap:4px;flex-wrap:wrap}.queue-tools :deep(.el-button){margin:0}.queue-tools span{font-size:12px}
.queue-filter{display:grid;gap:6px}.queue-empty{padding:20px}.formal-stage :deep(.editor-canvas){background:#ededed}
</style>
