<script setup lang="ts">
import {computed,onMounted,reactive,ref} from 'vue';
import type {MaterialContext,MaterialRow,MaterialFilters,MaterialDetail,MaterialPage,MaterialHistory} from '../types/materials';
import {materialsApi} from '../api/materials';
import {useReadScope} from '../composables/useReadScope';
import {useMaterialDelete} from '../composables/useMaterialDelete';
import PageHeader from '../components/PageHeader.vue';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
import MaterialPreview from '../components/MaterialPreview.vue';
import MaterialRename from '../components/MaterialRename.vue';
const props=defineProps<{context:MaterialContext;standalone?:boolean;deleteEnabled?:boolean}>(),api=materialsApi(props.context),reads=useReadScope(props.context),saved=props.context.memory.materials;
const deletion=useMaterialDelete({
 enabled:()=>!!props.standalone&&!!props.deleteEnabled,
 projectId:()=>props.context.projectId,
 actorKey:()=>props.context.actorKey||'',
 async onSettled(result){
   if(result.deletedIds.length){
    const deleted=new Set(result.deletedIds);
    if(page.value){
     const items=page.value.items.filter(row=>!deleted.has(row.id));
     page.value={...page.value,items};
     statsStale.value=true;
    }
    selected.value=selected.value.filter(id=>!deleted.has(id));
    selectionPage.value=Math.min(selectionPage.value,Math.max(1,Math.ceil(selected.value.length/50)));
    if(detailId.value&&deleted.has(detailId.value))resetDetail();
   }
   if(result.terminal&&!result.unknown){filteredAll.value=false;excluded.value=[]}
   await load(true);
  },
});
const deletePending=computed(()=>deletion.pending.value);
const deleteTerminal=computed(()=>deletion.terminal.value);
const filters=reactive<MaterialFilters>({query:'',label:'',annotation_state:'',quality_status:'',storage_source_id:'',source_batch_id:'',created_from:'',created_to:'',...saved?.filters});
const number=ref(saved?.page||1),layout=ref<'grid'|'list'>(saved?.layout||'grid'),selected=ref<string[]>(saved?.selectedItems||[]),page=ref<MaterialPage|null>(null),loadedContext=ref(''),statsStale=ref(false),detail=ref<MaterialDetail|null>(null),drawer=ref(false),showBoxes=ref(true),history=ref<MaterialHistory|null>(null),selectionNote=ref(''),filteredAll=ref(false),excluded=ref<string[]>([]);
const applied={...filters},detailId=ref(saved?.detailId||''),selectionPage=ref(1);
const renameTarget=ref<MaterialRow|null>(null);
function renamed(id:string,filename:string){
 if(page.value)page.value={...page.value,items:page.value.items.map(row=>row.id===id?{...row,filename}:row)};
 if(detail.value?.image.id===id)detail.value={...detail.value,image:{...detail.value.image,filename}};
 renameTarget.value=null;
 // Name changes can change membership of an active name filter.
 if(applied.query.trim())void load();
}
const selectedSet=computed(()=>filteredAll.value?new Set((page.value?.items||[]).filter(row=>!excluded.value.includes(row.id)).map(row=>row.id)):new Set(selected.value));
const visibleSelection=computed(()=>selected.value.slice((selectionPage.value-1)*50,selectionPage.value*50));
const status:Record<string,string>={unannotated:'未标注',annotated:'已标注',confirmed_empty:'已确认无目标',partial:'标注范围不完整',needs_review:'待审核'};
function remember(){props.context.memory.materials={filters:{...applied},page:number.value,layout:layout.value,selectedItems:selected.value,detailId:props.standalone?detailId.value:undefined}}
function resetDetail(){detailId.value='';reads.cancel('detail');reads.cancel('history');drawer.value=false;detail.value=null;history.value=null}
function close(){resetDetail();remember()}
function contextKey(){return JSON.stringify([applied,number.value])}
function load(clamp=false){
 remember();
 const key=contextKey();
 if(loadedContext.value!==key)page.value=null;
 const read=clamp?api.listAtOrBefore:api.list;
 return reads.run('materials',signal=>read(applied,number.value,signal),value=>{
  if(contextKey()!==key)return;
  page.value=value;loadedContext.value=key;statsStale.value=false;
  if(number.value!==value.page){number.value=value.page;loadedContext.value=contextKey();remember()}
 });
}
function search(){Object.assign(applied,filters);number.value=1;resetDetail();filteredAll.value=false;excluded.value=[];void load()}
function turn(delta:number){number.value+=delta;resetDetail();void load()}
function batchFilters(){const {label,storage_source_id,...values}=applied;return {...Object.fromEntries(Object.entries(values).filter(([,value])=>!!value.trim())),...(label.trim()?{labels:[label.trim()]}:{}),...(storage_source_id.trim()?{storage_source_ids:[storage_source_id.trim()]}:{})}}
function clearSelection(){selected.value=[];filteredAll.value=false;excluded.value=[];selectionPage.value=1;remember()}
function selectFiltered(){filteredAll.value=true;selected.value=[];excluded.value=[];selectionNote.value='已选择全部筛选结果；可取消单张排除';remember()}
function choose(id:string,value:boolean){selectionNote.value='';if(filteredAll.value){excluded.value=value?excluded.value.filter(x=>x!==id):[...new Set([...excluded.value,id])];remember();return}if(value&&!selected.value.includes(id)){if(!props.standalone&&selected.value.length>=200){selectionNote.value='最多保留 200 张选择，请先清除部分选择';return}selected.value=[...selected.value,id]}if(!value)selected.value=selected.value.filter(x=>x!==id);selectionPage.value=Math.min(selectionPage.value,Math.max(1,Math.ceil(selected.value.length/50)));remember()}
function choosePage(){
 if(filteredAll.value){for(const row of page.value?.items||[])choose(row.id,true);remember();return}
 if(!props.standalone){for(const row of page.value?.items||[])choose(row.id,true);return}
 selected.value=[...new Set([...selected.value,...(page.value?.items||[]).map(row=>row.id)])];remember()
}
function startDelete(){if(filteredAll.value){void deletion.prepareFiltered({scope:'FILTERED',filters:batchFilters(),excluded_image_ids:[...excluded.value]})}else void deletion.prepareMany(selected.value)}
function open(id:string){resetDetail();detailId.value=id;drawer.value=true;remember();void reads.run('detail',signal=>api.detail(id,signal),value=>{detail.value=value})}
function readHistory(targetPage=1){if(!detail.value||!props.context.history)return;const id=detail.value.image.id;void reads.run('history',signal=>props.context.history!(id,targetPage,signal),value=>{history.value=value})}
function legacy(action:'manage'|'upload'|'annotate',id?:string){remember();if(!props.standalone)close();props.context.legacyMaterials?.(action,id)}
onMounted(()=>{void load();if(detailId.value)open(detailId.value);if(props.standalone&&props.deleteEnabled)void deletion.recover()});
defineExpose({async refresh(){await load(true);if(detailId.value)open(detailId.value)}});
</script>
<template><section class="catalog-preview material-library" :aria-label="standalone?'素材库':'素材库只读浏览'"><PageHeader v-if="!standalone" title="素材库" eyebrow="数据管理 / 素材" description="浏览原素材库与正式标注；上传、标注和管理沿用原工作台。" badge="只读" @back="legacy('manage')"/>
<slot name="actions"/><el-alert v-if="deletePending" type="warning" :closable="false" title="存在未完成的素材删除任务；请先核验原任务，不能新建删除计划。"><el-button size="small" @click="deletion.openTask()">查看删除任务</el-button></el-alert><div class="preview-actions library-actions"><el-button v-if="context.openNativeUpload" type="primary" @click="context.openNativeUpload()">上传图片（原生）</el-button><el-button v-if="context.openNativeZip" @click="context.openNativeZip()">ZIP 数据集（原生）</el-button><el-button v-if="context.openUploadTasks" @click="context.openUploadTasks()">上传任务</el-button><el-button v-if="context.openImports" @click="remember();context.openImports()">上传与治理</el-button><el-button v-if="context.legacyMaterials" @click="legacy('upload')">上传素材</el-button><el-button v-if="context.openNegativePool" @click="remember();context.openNegativePool()">负样本池</el-button><el-button :disabled="reads.busy.materials" @click="load()">刷新素材</el-button></div>
<form class="filters" @submit.prevent="search"><el-input v-model="filters.query" aria-label="素材名称" placeholder="搜索图片名称"/><el-select v-model="filters.annotation_state" aria-label="标注状态"><el-option label="全部标注状态" value=""/><el-option v-for="(label,value) in status" :key="value" :label="label" :value="value"/></el-select><el-button type="primary" native-type="submit">查询素材</el-button><details><summary>更多筛选条件</summary><div class="extra-filters"><label>标签编码<el-input v-model="filters.label" placeholder="任一标签编码"/></label><label>来源 ID<el-input v-model="filters.storage_source_id"/></label><label>导入批次<el-input v-model="filters.source_batch_id"/></label><label>质量状态<el-select v-model="filters.quality_status"><el-option label="全部" value=""/><el-option label="未检查" value="pending_decision"/><el-option label="已处理" value="processed"/><el-option label="有问题" value="issue"/></el-select></label><label>起始日期<input v-model="filters.created_from" type="date"></label><label>截止日期<input v-model="filters.created_to" type="date"></label></div></details></form>
<el-alert v-if="reads.errors.materials" :title="reads.errors.materials" type="error" :closable="false"/><p v-if="reads.errors.materials&&page">当前显示上次读取结果，请重试刷新。</p><el-alert v-if="selectionNote" :title="selectionNote" type="warning" :closable="false"/>
<div class="result-tools"><span>{{ page?`共 ${page.total} 张素材${statsStale?'（删除后统计待刷新）':''}`:reads.busy.materials?'正在读取素材':'素材列表未加载' }}</span><strong class="selection-count" :class="{active:selected.length>0}">已选 {{ filteredAll ? Math.max(0,(page?.total||0)-excluded.length) : selected.length }} 张<template v-if="filteredAll">（已排除 {{ excluded.length }} 张）</template></strong><div class="preview-actions"><el-button @click="choosePage" :disabled="!page||reads.busy.materials">选择本页</el-button><el-button v-if="standalone" @click="selectFiltered" :disabled="!page||reads.busy.materials">全选筛选结果</el-button><el-button @click="clearSelection">清除选择</el-button><el-button v-if="standalone&&deleteEnabled&&(filteredAll?(page&&page.total>excluded.length):selected.length)" type="danger" plain :disabled="deletion.state.busy" @click="startDelete">删除所选 {{ filteredAll ? Math.max(0,(page?.total||0)-excluded.length) : selected.length }} 张</el-button><div class="layout-controls" role="group" aria-label="素材展示方式"><el-button :aria-pressed="layout==='grid'" @click="layout='grid';remember()">网格</el-button><el-button :aria-pressed="layout==='list'" @click="layout='list';remember()">列表</el-button></div><el-checkbox v-model="showBoxes">标注框</el-checkbox></div></div>
<details v-if="selected.length" class="selected-materials"><summary>已选素材摘要 · {{ selected.length }} 张</summary><ul><li v-for="id in visibleSelection" :key="id">{{ page?.items.find(row=>row.id===id)?.filename||id }} <el-button link @click="choose(id,false)">移除</el-button></li></ul><div v-if="selected.length>50" class="preview-actions"><el-button :disabled="selectionPage===1" @click="selectionPage--">上一页已选</el-button><el-button :disabled="selectionPage*50>=selected.length" @click="selectionPage++">下一页已选</el-button></div></details><el-skeleton v-if="!page&&reads.busy.materials" :rows="8" animated/><el-empty v-else-if="page&&!page.items.length" description="当前条件下没有素材"/><div v-if="page" class="material-results" :class="layout" :aria-busy="reads.busy.materials"><article v-for="row in page.items" :key="row.id" class="material-card" :class="{'is-selected':selectedSet.has(row.id)}"><div class="image-button"><MaterialPreview framed :image="row" :project-id="context.projectId" :boxes="row.annotation_preview" :show-boxes="showBoxes"/></div><div class="card-copy"><el-checkbox :model-value="selectedSet.has(row.id)" :aria-label="`选择 ${row.filename}`" @change="(value:unknown)=>choose(row.id,!!value)">{{ row.filename }}</el-checkbox><p class="card-status"><span>{{ status[row.annotation_state||'']||row.annotation_state||'状态未提供' }}</span><span>{{ row.box_count??'—' }} 框</span></p><p>{{ row.width||'—' }} × {{ row.height||'—' }} · {{ row.created_at?.slice(0,10)||'日期未提供' }}</p><p v-if="standalone">质量 {{ row.quality_status||'未提供' }} · 来源 {{ row.storage_source_id||'未提供' }}</p><p>{{ row.labels?.join('、')||'未提供标签' }}</p><small v-if="(row.box_count||0)>(row.annotation_preview?.length||0)">缩略图显示部分框，详情读取完整标注</small><div class="card-actions"><el-button link type="primary" @click="open(row.id)">详情</el-button><el-button v-if="standalone&&context.legacyMaterials" class="annotation-action" size="small" plain @click="legacy('annotate',row.id)">人工标注</el-button><el-button v-if="context.renameMaterial" link @click="renameTarget=row">改名</el-button><el-button v-if="standalone&&deleteEnabled" link type="danger" :disabled="deletion.state.busy" @click="deletion.prepare(row.id)">删除</el-button></div></div></article></div>
<footer v-if="page" class="preview-pagination"><span>第 {{ page.page }} / {{ page.total_pages }} 页 · 每页 {{ page.page_size }} 张</span><div class="preview-actions"><el-button :disabled="number<=1||reads.busy.materials" @click="turn(-1)">上一页</el-button><el-button :disabled="!page.has_next||reads.busy.materials" @click="turn(1)">下一页</el-button></div></footer>
<MaterialRename v-if="renameTarget&&context.renameMaterial" :image="renameTarget" :context="context" @saved="renamed" @close="renameTarget=null"/>
<el-drawer :model-value="drawer" title="素材详情" size="min(960px,100vw)" :append-to-body="false" :lock-scroll="false" :before-close="close"><el-skeleton v-if="reads.busy.detail" :rows="8" animated/><el-alert v-else-if="reads.errors.detail" :title="reads.errors.detail" type="error" :closable="false"/><template v-else-if="detail"><h2>{{ detail.image.filename }}</h2><MaterialPreview :image="detail.image" :project-id="context.projectId" :boxes="detail.annotation.boxes" full/><el-alert v-if="detail.boxes_truncated" :title="`共 ${detail.boxes_total} 框，当前仅展示 ${detail.annotation.boxes.length} 框`" type="warning" :closable="false"/><ReadOnlyFacts :fields="[['标注状态',status[detail.annotation.annotation_state]||detail.annotation.annotation_state],['正式标注框数',detail.boxes_total],['标注版本',detail.annotation.annotation_version],['最近标注时间',detail.annotation.updated_at],['已审核标签',detail.annotation.reviewed_label_codes],['图片宽度',detail.image.width],['图片高度',detail.image.height],['大小（字节）',detail.image.size_bytes],['来源',detail.image.storage_source_id],['导入批次',detail.image.source_batch_id||detail.image.import_batch_id],['存储类型',detail.image.storage_type],['源文件可用性',detail.image.source_available===true?'后端确认可用':detail.image.source_available===false?'后端确认不可用':'未提供'],['标注异常',detail.image.annotation_issue_type],['创建时间',detail.image.created_at],['质量状态',detail.image.quality_status],['素材 ID',detail.image.id],['SHA256',detail.image.content_sha256]]"/><section v-if="context.history"><h3>历史使用</h3><el-button :loading="reads.busy.history" @click="readHistory()">读取历史使用记录</el-button><el-alert v-if="reads.errors.history" :title="reads.errors.history" type="error" :closable="false"/><div v-if="history"><p>当前历史状态：{{ history.state||'未知' }} · 共 {{ history.total }} 条。未检索到记录不等于从未使用。覆盖范围：{{ history.coverage||'未知' }}</p><el-table :data="history.items" empty-text="未查询到使用记录；历史覆盖范围需以原记录为准"><el-table-column prop="task_id" label="训练任务" min-width="160"/><el-table-column prop="algorithm_name" label="算法"/><el-table-column prop="role" label="样本角色"/><el-table-column prop="status" label="任务状态"/></el-table><div class="preview-actions"><el-button :disabled="history.page<=1||reads.busy.history" @click="readHistory(history.page-1)">上一页历史</el-button><span>第 {{ history.page }} 页</span><el-button :disabled="history.page*history.page_size>=history.total||reads.busy.history" @click="readHistory(history.page+1)">下一页历史</el-button></div></div><p v-else>点击后读取原历史记录。</p></section></template><template #footer><el-button @click="close">返回素材库</el-button><el-button v-if="detail&&context.legacyMaterials" type="primary" @click="legacy('annotate',detail.image.id)">{{ standalone?'人工标注':'在原工作台标注' }}</el-button><el-button v-if="detail&&standalone&&deleteEnabled" type="danger" plain :disabled="deletion.state.busy" @click="deletion.prepare(detail.image.id)">删除该素材</el-button></template></el-drawer><el-dialog :model-value="deletion.state.dialog" title="删除素材" width="min(540px,92vw)" :close-on-click-modal="!deletion.state.busy" :show-close="!deletion.state.busy" @close="deletion.close()"><template v-if="deletion.state.estimate?.deletion_preview"><p>本次删除 {{ deletion.state.estimate?.count ?? 0 }} 张素材，将退休素材索引及正式 GT；原图字节保留，本次释放空间 0。</p><p>正式 GT：{{ deletion.state.estimate.deletion_preview.gt_count ?? '未核验' }} 张 · 当前 Test：{{ deletion.state.estimate.deletion_preview.current_test_count ?? '未核验' }} 张</p><p>历史引用：{{ deletion.state.estimate.deletion_preview.historical_reference_count ?? '未核验' }} 张 · 活动引用：{{ deletion.state.estimate.deletion_preview.active_reference_count ?? '未核验' }} 张</p><p v-if="deletion.state.estimate.deletion_preview.reference_diagnostics_state==='UNAVAILABLE'">引用诊断暂不可用，数量保持未核验，不代表没有引用。</p></template><p v-if="deletion.state.task">任务状态：{{ deletion.statusLabel }} · 成功 {{ deletion.state.task.succeeded ?? 0 }} / {{ deletion.state.task.total ?? 1 }} 张</p><p v-if="deletion.state.summary.seen">逐项结果：成功 {{ deletion.state.summary.succeeded }} · 失败 {{ deletion.state.summary.failed }} · 未处理 {{ deletion.state.summary.pending }} · 处理中 {{ deletion.state.summary.running }}<template v-if="deletion.state.summary.conflict"> · 证据冲突 {{ deletion.state.summary.conflict }}</template>（已读 {{ deletion.state.summary.seen }} / 应有 {{ deletion.state.summary.required }}）</p><p v-if="deletion.state.notice" role="status">{{ deletion.state.notice }}</p><p v-if="deletion.state.error" role="alert">{{ deletion.state.error }}</p><template #footer><el-button :disabled="deletion.state.busy" @click="deletion.close()">取消</el-button><el-button v-if="deleteTerminal && deletion.state.unknown" :loading="deletion.state.busy" @click="deletion.verifyResults()">核验删除结果</el-button><el-button type="danger" :disabled="!deletion.state.estimate||deletion.state.busy||!!deletion.state.task||deletion.state.unknown||!!deletion.state.pendingPlanId" :loading="deletion.state.busy" @click="deletion.confirm()">确认删除</el-button></template></el-dialog></section></template>
<style scoped>
.material-library { padding-bottom: 24px; }
.preview-actions, .layout-controls, .card-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.preview-actions :deep(.el-button), .card-actions :deep(.el-button) { margin: 0; }
.library-actions { margin-block: 12px; }
.preview-pagination, .result-tools { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.preview-pagination { justify-content: space-between; margin-top: 14px; }
.result-tools {
  margin: 16px 0;
  padding-block: 10px;
  border-block: 1px solid var(--workspace-line, #dedede);
  color: var(--workspace-muted, #666);
  font-size: 13px;
}
.result-tools .preview-actions { margin-inline-start: auto; }
.selection-count { color: inherit; font-weight: 500; font-variant-numeric: tabular-nums; }
.selection-count.active { color: var(--workspace-ink, #242424); font-weight: 650; }
.layout-controls { gap: 2px; }
.layout-controls :deep([aria-pressed="true"]) {
  background: var(--workspace-hover, #f3f3f3);
  color: var(--workspace-ink, #242424);
  border-color: currentColor;
}
.selected-materials { margin: 12px 0; font-size: 13px; }
.selected-materials summary, .filters summary { cursor: pointer; }
.selected-materials ul { max-height: 180px; overflow: auto; overflow-wrap: anywhere; }
.filters { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0; align-items: center; }
.filters > .el-input { flex: 1; min-width: min(180px, 100%); }
.filters > .el-select { width: 190px; }
.filters details { width: 100%; border: 1px solid var(--workspace-line, #dedede); border-radius: var(--workspace-radius, 8px); padding: 10px 12px; }
.extra-filters { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; padding-top: 16px; }
.extra-filters label { display: grid; gap: 6px; color: var(--workspace-muted, #666); }
.extra-filters input[type=date] { padding: 9px; border: 1px solid var(--workspace-line, #dedede); border-radius: 6px; max-width: 100%; }
.material-results.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 12px; }
.material-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--workspace-line, #dedede);
  border-radius: var(--workspace-radius, 8px);
  background: var(--workspace-surface, #fff);
}
.material-card.is-selected { border-color: var(--workspace-ink, #242424); }
.image-button { min-width: 0; background: var(--workspace-hover, #f3f3f3); }
.card-copy { display: flex; flex: 1; flex-direction: column; gap: 6px; min-width: 0; padding: 12px; overflow-wrap: anywhere; }
.card-copy p, .card-copy small { margin: 0; color: var(--workspace-muted, #666); font-size: 13px; }
.card-status { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.card-status span:first-child {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--workspace-hover, #f3f3f3);
  color: var(--workspace-ink, #242424);
}
.card-copy .el-checkbox { max-width: 100%; height: auto; }
.card-copy :deep(.el-checkbox__label) { color: var(--workspace-ink, #242424); font-weight: 650; white-space: normal; overflow-wrap: anywhere; }
.card-actions { margin-top: auto; padding-top: 4px; }
.card-actions .annotation-action { color: var(--workspace-ink, #242424); }
.list { display: grid; gap: 10px; }
.list .material-card { display: grid; grid-template-columns: 150px minmax(0, 1fr); }
.list .image-button { align-self: start; }
.history-result { max-height: 260px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; background: var(--workspace-hover, #f3f3f3); padding: 12px; border-radius: 8px; }
@media (max-width: 760px) {
  .extra-filters, .material-results.grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .list .material-card { grid-template-columns: 100px minmax(0, 1fr); }
  .result-tools .preview-actions { margin-inline-start: 0; }
}
@media (max-width: 420px) {
  .extra-filters, .material-results.grid { grid-template-columns: 1fr; }
}
</style>
