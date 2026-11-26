<script setup lang="ts">
import {onBeforeUnmount,ref,onMounted} from 'vue';
import {request} from '../app/http';
import {retryVersionCleanup,type VersionOperation} from '../api/algorithm-lifecycle';
import {browseError} from '../api/model-browse';

const props=defineProps<{projectId:string;algorithmId:string;algorithmName:string;mode:'deletion'|'history'}>();
const emit=defineEmits<{close:[]}>();
const scope=new AbortController();
onBeforeUnmount(()=>scope.abort());
const base=`/api/v12/projects/${encodeURIComponent(props.projectId)}/algorithms/${encodeURIComponent(props.algorithmId)}`;
type Identity={project_id:string;algorithm_id:string};
type Admission=Identity&{allowed:boolean;code:string;message:string;version_count?:number;current_version_id?:string;version_operation_count?:number};
type Row={id:string;action:VersionOperation['action'];deleted_version_id:string;from_version_id?:string;to_version_id?:string;cleanup_status:VersionOperation['cleanup_status'];created_at?:string};
const admission=ref<Admission>(), rows=ref<Row[]>([]),offset=ref(0),total=ref(0),busy=ref(false),error=ref(''),notice=ref('');
const awaitingProof=ref(false);
const size=20;
const status:Record<string,string>={cleanup_completed:'清理完成',cleanup_pending:'待清理',cleanup_failed:'清理失败'};
function verify(value:Identity){
  if(value.project_id!==props.projectId||value.algorithm_id!==props.algorithmId)throw new Error('算法响应身份不一致');
}
async function load(start=0){
  if(busy.value)return;
  error.value='';busy.value=true;
  try{
    if(props.mode==='deletion'){
      const value=await request<Admission>(base+'/deletion-preflight',{signal:scope.signal});
      verify(value);admission.value=value;
    }else{
      const value=await request<Identity&{items:Row[];total:number}>(base+'/version-operations?'+new URLSearchParams({offset:String(start),limit:String(size)}),{signal:scope.signal});
      verify(value);
      if(!Array.isArray(value.items)||value.items.length>size||value.items.some(row=>!row.id))throw new Error('版本操作回执分页无效');
      rows.value=value.items;total.value=value.total;offset.value=start;
      awaitingProof.value=false;
    }
  }catch(cause){if(!scope.signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false}
}
async function retry(row:Row){
  if(busy.value||awaitingProof.value||!['cleanup_pending','cleanup_failed'].includes(row.cleanup_status))return;
  if(!window.confirm(`确认按原回执重试版本 ${row.deleted_version_id} 的产物清理？`))return;
  error.value='';notice.value='';busy.value=true;
  try{
    const receipt=await retryVersionCleanup(props.projectId,{...row,algorithm_id:props.algorithmId,operation_id:row.id});
    if(scope.signal.aborted)return;
    notice.value=status[receipt.cleanup_status]||'清理回执待核验';
    if(receipt.cleanup_errors?.length)error.value=receipt.cleanup_errors.map(item=>browseError(new Error(item))).join('；');
    rows.value=rows.value.map(item=>item.id===row.id?{...item,cleanup_status:receipt.cleanup_status}:item);
  }catch(cause){if(!scope.signal.aborted){awaitingProof.value=true;error.value='清理结果待核验。'+browseError(cause)}}
  finally{busy.value=false}
}
onMounted(()=>void load());
</script>

<template>
 <el-dialog :model-value="true" :title="mode==='deletion'?'删除算法检查':'版本操作历史'" width="min(850px,94vw)"
  :close-on-click-modal="false" :show-close="!busy" :close-on-press-escape="!busy" @close="emit('close')">
  <p>{{algorithmName}} · {{algorithmId}}</p>
  <el-alert v-if="error" :title="error" type="error" :closable="false"/>
  <p v-if="notice" role="status">{{notice}}</p>
  <template v-if="mode==='deletion'&&admission">
   <el-alert type="warning" :title="admission.message" :closable="false"/>
   <p v-if="admission.version_count!==undefined">模型版本 {{admission.version_count}} · 版本历史 {{admission.version_operation_count}} · 当前版本 {{admission.current_version_id||'无'}}</p>
  </template>
  <el-table v-if="mode==='history'" v-loading="busy" :data="rows" row-key="id" empty-text="暂无版本操作记录">
   <el-table-column label="操作" min-width="140"><template #default="{row}">{{row.action==='rollback_and_delete'?'回退并退役':'退役版本'}}<br>{{row.id}}</template></el-table-column>
   <el-table-column prop="deleted_version_id" label="退役版本" min-width="110"/>
   <el-table-column prop="to_version_id" label="回退目标" min-width="108"/>
   <el-table-column prop="created_at" label="时间" min-width="140"/>
   <el-table-column label="产物清理" min-width="130"><template #default="{row}">{{status[row.cleanup_status]||'待核验'}}
    <el-button v-if="['cleanup_pending','cleanup_failed'].includes(row.cleanup_status)" link :disabled="busy||awaitingProof" @click="retry(row)">重试</el-button>
   </template></el-table-column>
  </el-table>
  <template #footer>
   <el-button v-if="mode==='history'" :disabled="busy||offset<=0" @click="load(offset-size)">上一页</el-button>
   <el-button v-if="mode==='history'" :disabled="busy||offset+size>=total" @click="load(offset+size)">下一页</el-button>
   <el-button :loading="busy" @click="load(offset)">刷新</el-button>
  </template>
 </el-dialog>
</template>
