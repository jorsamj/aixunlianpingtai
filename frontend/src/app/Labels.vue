<script setup lang="ts">
import {computed,onBeforeUnmount,ref,shallowRef} from 'vue';
import {onBeforeRouteLeave,useRoute,useRouter} from 'vue-router';
import {readLabels,removeLabel,type ProjectLabel} from '../api/label-management';
import {browseError} from '../api/model-browse';
import LabelEditor from '../components/LabelEditor.vue';
import LabelUnify from '../components/LabelUnify.vue';
import LabelAudit from '../components/LabelAudit.vue';
const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId),controller=new AbortController();
const items=shallowRef<ProjectLabel[]>([]),governance=shallowRef<ProjectLabel[]>([]),busy=shallowRef(false),error=shallowRef(''),notice=shallowRef(''),usageReady=shallowRef(false);
const editing=shallowRef(false),selected=shallowRef<ProjectLabel|null>(null),writePending=shallowRef(false),unifyPending=shallowRef(false),deleting=shallowRef<ProjectLabel|null>(null),deleteBusy=shallowRef(false),deleteUnknown=shallowRef(false),deleteError=shallowRef('');
const search=ref(typeof route.query.query==='string'?route.query.query:''),page=shallowRef(1);
const filtered=computed(()=>items.value.filter(row=>`${row.code} ${row.display_name||''} ${(row.aliases||[]).join(' ')}`.toLowerCase().includes(search.value.trim().toLowerCase())));
const rows=computed(()=>filtered.value.slice((page.value-1)*50,page.value*50));
const auditBusy=ref(false);
const tab=computed({get:()=>route.query.tab==='unify'||route.query.tab==='audit'?route.query.tab:'catalog',set:(value:string)=>{if(!blocked.value)void router.replace({query:{...route.query,tab:value==='catalog'?undefined:value}})}});
const blocked=computed(()=>writePending.value||deleteUnknown.value||deleteBusy.value||unifyPending.value||auditBusy.value);
const previousDisabled=computed(()=>governance.value.filter(row=>row.status&&row.status!=='active').length);
let readController:AbortController|undefined;
async function load(usage=usageReady.value){
 readController?.abort();const c=new AbortController();readController=c;busy.value=true;error.value='';
 try{const result=await readLabels(projectId,c.signal,usage);if(c.signal.aborted)return;items.value=result.items;governance.value=result.governance||[];usageReady.value=usage;if((page.value-1)*50>=filtered.value.length)page.value=1}
 catch(cause){if(!c.signal.aborted)error.value=browseError(cause)}finally{if(readController===c)busy.value=false}
}
function applySearch(){page.value=1;void router.replace({query:{...route.query,query:search.value.trim()||undefined}})}
function edit(row:ProjectLabel|null){if(blocked.value)return;selected.value=row;editing.value=true}
function saved(){editing.value=false;notice.value='标签已保存。';void load()}
function beginDelete(row:ProjectLabel){if(blocked.value)return;deleting.value=row;deleteError.value='';deleteUnknown.value=false}
async function verifyDelete(){
 if(!deleting.value)return;
 const result=await readLabels(projectId,controller.signal);
 if(result.items.some(row=>row.class_id===deleting.value?.class_id))throw new Error('该标签仍在有效目录中，请在原管理记录中核对删除结果，勿重复提交。');
 deleteUnknown.value=false;deleting.value=null;notice.value='标签已停用，历史类别 ID 保留。';void load();
}
async function remove(){
 if(!deleting.value||deleteBusy.value||deleteUnknown.value)return;
 deleteBusy.value=true;deleteError.value='';
 try{
  deleteUnknown.value=true;
  try{await removeLabel(projectId,deleting.value.class_id)}catch(cause){const status=(cause as {httpStatus?:number}).httpStatus;if(status&&[400,401,403,404,409,422].includes(status))deleteUnknown.value=false;throw cause}
  await verifyDelete();
 }catch(cause){if(!controller.signal.aborted)deleteError.value=browseError(cause)}finally{deleteBusy.value=false}
}
async function checkDeletion(){deleteBusy.value=true;deleteError.value='';try{await verifyDelete()}catch(cause){if(!controller.signal.aborted)deleteError.value=browseError(cause)}finally{deleteBusy.value=false}}
function openUnify(){if(blocked.value)return;tab.value='unify';if(!usageReady.value)void load(true)}
function beforeUnload(event:BeforeUnloadEvent){if(blocked.value){event.preventDefault();event.returnValue=''}}
window.addEventListener('beforeunload',beforeUnload);
onBeforeRouteLeave(()=>!blocked.value);
onBeforeUnmount(()=>{controller.abort();readController?.abort();window.removeEventListener('beforeunload',beforeUnload)});
void load(tab.value==='unify');
</script>
<template><section class="labels-page" aria-label="标签管理">
 <div class="page-toolbar"><div class="label-tabs" role="tablist" aria-label="标签工作区"><el-button :type="tab==='catalog'?'primary':'default'" :disabled="blocked" @click="tab='catalog'">标签目录</el-button><el-button :type="tab==='unify'?'primary':'default'" :disabled="blocked" @click="openUnify">统一历史标签</el-button><el-button :type="tab==='audit'?'primary':'default'" :disabled="blocked" @click="tab='audit'">标签审计与修复</el-button></div><div class="label-tools"><el-button :disabled="blocked" @click="load()" :loading="busy">刷新</el-button><el-button type="primary" :disabled="blocked" @click="edit(null)">新增标签</el-button></div></div>
 <el-alert v-if="error" :title="error" type="error" :closable="false"/><p v-if="notice" role="status">{{notice}}</p>
 <section v-show="tab==='catalog'" class="label-catalog"><form class="label-search" @submit.prevent="applySearch"><el-input v-model="search" aria-label="搜索标签" placeholder="搜索编码、名称或别名" clearable @clear="applySearch"/><el-button native-type="submit">查询</el-button><span>{{filtered.length}} 个有效标签</span><span v-if="previousDisabled">{{previousDisabled}} 个历史停用标签保留原类别 ID</span><el-button v-if="!usageReady" :loading="busy" @click="load(true)">读取引用统计</el-button></form>
 <el-table :data="rows" row-key="class_id" v-loading="busy" empty-text="暂无匹配标签"><el-table-column label="标签" min-width="190"><template #default="{row}"><div class="label-identity"><i :style="{backgroundColor:row.color||'#737373'}"/><div><strong>{{row.display_name||row.code}}</strong><code>{{row.code}}</code></div></div></template></el-table-column><el-table-column prop="class_id" label="类别 ID" width="95"/><el-table-column label="别名" min-width="160"><template #default="{row}">{{row.aliases?.join('、')||'—'}}</template></el-table-column><el-table-column prop="hotkey" label="快捷键" width="90"/><el-table-column label="引用素材 / 框" min-width="145"><template #default="{row}">{{row.affected_images??'—'}} / {{row.usage_boxes??'—'}}</template></el-table-column><el-table-column label="操作" width="150" fixed="right"><template #default="{row}"><el-button link :disabled="blocked" @click="edit(row)">编辑</el-button><el-button link type="danger" :disabled="blocked" @click="beginDelete(row)">删除</el-button></template></el-table-column></el-table>
 <el-pagination v-if="filtered.length>50" v-model:current-page="page" :page-size="50" :total="filtered.length" layout="prev,pager,next"/>
 </section>
 <LabelUnify v-if="usageReady" v-show="tab==='unify'" :project-id="projectId" :labels="items" @settled="load(true)" @pending="unifyPending=$event"/><el-skeleton v-else-if="tab==='unify'&&busy" :rows="6"/>
 <LabelAudit v-if="tab==='audit'" :project-id="projectId" :labels="items" @busy="auditBusy=$event"/>
 <el-dialog v-model="editing" :title="selected?'编辑标签':'新增标签'" width="min(520px,94vw)" :close-on-click-modal="false" :close-on-press-escape="!writePending" :show-close="!writePending" destroy-on-close><LabelEditor v-if="editing" :project-id="projectId" :label="selected" @saved="saved" @close="editing=false" @pending="writePending=$event"/></el-dialog>
 <el-dialog :model-value="!!deleting" title="删除标签" width="min(520px,94vw)" :close-on-click-modal="false" :close-on-press-escape="!deleteBusy&&!deleteUnknown" :show-close="!deleteBusy&&!deleteUnknown" @close="deleting=null"><p>确认删除标签「{{deleting?.display_name||deleting?.code}}」？</p><p>正式标注、无目标范围或待审核反馈仍有引用时将拒绝删除；历史类别 ID 保留。</p><el-alert v-if="deleteError" :title="deleteError" type="error" :closable="false"/><el-alert v-if="deleteUnknown" title="删除结果待核对，请勿重复提交。" type="warning" :closable="false"/><template #footer><el-button :disabled="deleteBusy||deleteUnknown" @click="deleting=null">取消</el-button><el-button v-if="deleteUnknown" type="primary" :loading="deleteBusy" @click="checkDeletion">核对删除结果</el-button><el-button v-else type="danger" :loading="deleteBusy" @click="remove">确认删除</el-button></template></el-dialog>
</section></template>
<style scoped>
.label-tabs,.label-tools,.label-search{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.labels-page :deep(.el-button+.el-button){margin-left:0}.label-catalog{background:#fff;border:1px solid #dedede;border-radius:8px;padding:20px}.label-search{margin-bottom:18px}.label-search .el-input{width:280px}.label-search span{font-size:12px;color:#737373}.label-identity{display:flex;align-items:center;gap:10px}.label-identity i{width:10px;height:10px;border-radius:2px;flex-shrink:0}.label-identity code{display:block;font-size:12px;color:#737373;overflow-wrap:anywhere}.labels-page :deep(.el-pagination){margin-top:18px}.labels-page>p{font-size:13px;color:#525252}.labels-page :deep(.el-dialog__body){max-height:calc(85dvh - 120px);overflow:auto}@media(max-width:1366px){.page-toolbar{align-items:flex-start;flex-wrap:wrap}.label-catalog{padding:16px}}
</style>
