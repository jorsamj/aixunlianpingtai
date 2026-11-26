<script setup lang="ts">
import {onBeforeUnmount,ref,shallowRef,watch} from 'vue';
import {getReviewLabels,readAmbiguitySelection,saveAmbiguityDrafts} from '../api/ai-review';
import type {AmbiguityDraft,ReviewAddress,ReviewLabel} from '../api/ai-review';
import {browseError} from '../api/model-browse';
import {aiPlanKeepAmbiguousLabel60} from '../../../static/modules/annotation-ambiguity.js';
import {readWorkspaceSession,workspaceActorKey} from './main';

const props=defineProps<{scope:ReviewAddress;actorKey:string;range:{id:string;revision:number;excluded:string[];count:number}}>();
const open=defineModel<boolean>('open',{required:true});
const emit=defineEmits<{busy:[value:boolean];settled:[]}>();
const scope={...props.scope},actor=props.actorKey;
const controller=new AbortController();
const threshold=ref(0.9),mode=ref<'manual'|'auto'>('manual'),label=ref('');
const labels=shallowRef<ReviewLabel[]>([]);
type DraftIdentity=Pick<AmbiguityDraft,'revision'|'source_content_sha256'>;
const plan=shallowRef<Map<string,DraftIdentity>>(),reasons=shallowRef<Record<string,number>>({});
const scanned=ref(0),removed=ref(0),fallback=ref(0),saved=ref(0),failed=ref(0);
const scanning=ref(false),writing=ref(false),error=ref(''),finished=ref(false),confirmed=ref(false);
const configChanged=()=>{plan.value=undefined;confirmed.value=false};
watch([threshold,mode,label],configChanged);
watch(open,async visible=>{
  if(!visible||labels.value.length)return;
  try{labels.value=await getReviewLabels(scope.projectId,controller.signal)}
  catch(cause){if(!controller.signal.aborted)error.value=browseError(cause)}
},{immediate:true});

async function prepare(){
  if(scanning.value||writing.value||finished.value||threshold.value<0.5||threshold.value>1
    ||(mode.value==='manual'&&!labels.value.some(item=>item.code===label.value)))return;
  scanning.value=true;plan.value=undefined;confirmed.value=false;error.value='';
  scanned.value=0;removed.value=0;fallback.value=0;reasons.value={};
  const snapshot=props.range,excluded=new Set(snapshot.excluded),seen=new Set<string>(),entries=new Map<string,DraftIdentity>();
  const skipped=new Map<string,number>();
  const skip=(reason:string)=>skipped.set(reason,(skipped.get(reason)??0)+1);
  const options={mode:mode.value,label:label.value,threshold:threshold.value};
  try{
    let cursor:string|null='0';
    const visited=new Set<string>();
    do{
      const page=await readAmbiguitySelection(scope,snapshot.id,cursor,controller.signal);
      if(page.review_revision!==snapshot.revision||page.selection_revision!==snapshot.revision||page.items.length>100)
        throw new Error('审核选区已变化，请重新冻结');
      for(const row of page.items){
        if(excluded.has(row.image_id))continue;
        if(!row.image_id||seen.has(row.image_id)||seen.size>=snapshot.count)throw new Error('候选范围身份不一致');
        seen.add(row.image_id);
        const hash=row.source_content_sha256||row.content_sha256;
        if(row.gt_committed||!hash){skip('已有正式 GT 或缺少源素材证据');continue}
        const result=aiPlanKeepAmbiguousLabel60(row,options);
        if('reason' in result){skip(result.reason);continue}
        entries.set(row.image_id,{revision:result.revision,source_content_sha256:hash});
        removed.value+=result.removed;fallback.value+=result.fallbackGroups;
      }
      scanned.value=seen.size;cursor=page.next_cursor;
      if(cursor!==null){
        if(visited.has(cursor)||visited.size>=500)throw new Error('候选分页无法继续核验');
        visited.add(cursor);
      }
    }while(cursor!==null);
    if(seen.size!==snapshot.count)throw new Error('服务端候选范围未完整覆盖，请重新冻结');
    plan.value=entries;
    reasons.value=Object.fromEntries(skipped);
  }catch(cause){if(!controller.signal.aborted)error.value=browseError(cause)}
  finally{scanning.value=false}
}

async function save(){
  const entries=plan.value;
  if(!entries?.size||!confirmed.value||writing.value||finished.value)return;
  const snapshot=props.range;
  const options={mode:mode.value,label:label.value,threshold:threshold.value};
  const seen=new Set<string>();
  error.value='';writing.value=true;emit('busy',true);
  let attempted=false;
  try{
    if(workspaceActorKey(await readWorkspaceSession(controller.signal))!==actor)throw new Error('会话已切换，请重新打开审核');
    let cursor:string|null='0';
    const visited=new Set<string>(),counts={...reasons.value};
    do{
      const page=await readAmbiguitySelection(scope,snapshot.id,cursor,controller.signal,cursor==='0'?undefined:snapshot.revision);
      if(page.selection_revision!==snapshot.revision||page.items.length>100
        ||(cursor==='0'&&page.review_revision!==snapshot.revision))throw new Error('审核范围已变化，请重新预检');
      const drafts:AmbiguityDraft[]=[];
      for(const row of page.items){
        const identity=entries.get(row.image_id);
        if(!identity)continue;
        if(seen.has(row.image_id))throw new Error('冻结候选重复，请重新预检');
        seen.add(row.image_id);
        const result=aiPlanKeepAmbiguousLabel60(row,options);
        if(row.gt_committed||'reason' in result||result.revision!==identity.revision
          ||(row.source_content_sha256||row.content_sha256)!==identity.source_content_sha256){
          const message='候选身份、版本或资格变化';
          counts[message]=(counts[message]??0)+1;failed.value++;continue;
        }
        const request_id=Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
        drafts.push({...identity,image_id:row.image_id,request_id,boxes:result.boxes,auto_resolution:options.mode==='auto'});
      }
      for(let offset=0;offset<drafts.length;offset+=25){
        const batch=drafts.slice(offset,offset+25);
        const byId=new Map(batch.map(item=>[item.image_id,item]));
        attempted=true;
        const result=await saveAmbiguityDrafts(scope,batch,controller.signal);
        if(result.total!==batch.length||result.items.length!==batch.length
          ||new Set(result.items.map(item=>item.image_id)).size!==batch.length)
          throw new Error('逐项草稿回执不完整，请检查当前候选');
        for(const item of result.items){
          const original=byId.get(item.image_id);
          if(!original||(item.ok&&item.revision!==original.revision+1))
            throw new Error('草稿回执身份或版本不一致');
          if(item.ok)saved.value++;
          else{
            failed.value++;
            const reason=browseError(new Error(typeof item.error==='string'?item.error:item.error?.message||'草稿未保存'));
            counts[reason]=(counts[reason]??0)+1;
          }
        }
      }
      reasons.value=counts;
      cursor=page.next_cursor;
      if(cursor!==null){
        if(visited.has(cursor)||visited.size>=500)throw new Error('候选分页无法继续核验');
        visited.add(cursor);
      }
    }while(cursor!==null);
    if(seen.size!==entries.size)throw new Error('冻结范围未覆盖全部原预检候选');
    finished.value=true;
  }catch(cause){
    if(!controller.signal.aborted)error.value=(attempted?'当前批次可能已有保存，请核对候选草稿。':'')+browseError(cause);
  }finally{
    if(attempted){finished.value=true;emit('settled')}
    writing.value=false;emit('busy',false);
  }
}
onBeforeUnmount(()=>controller.abort());
</script>

<template>
 <el-dialog v-model="open" title="IoU 批量消歧" width="min(640px, 94vw)"
  :close-on-click-modal="false" :show-close="!writing" :close-on-press-escape="!writing">
  <p>已冻结并选中 {{ range.count }} 张。保存后可逐图复核候选草稿。</p>
  <el-alert v-if="error" type="error" :title="error" :closable="false" />
  <el-form label-position="top" :disabled="scanning || writing || finished">
   <el-form-item label="保留策略"><el-radio-group v-model="mode">
    <el-radio value="manual">保留指定标签</el-radio><el-radio value="auto">优先可信置信度</el-radio>
   </el-radio-group></el-form-item>
   <el-form-item v-if="mode==='manual'" label="正式标签">
    <el-select v-model="label" filterable><el-option v-for="item in labels" :key="item.code" :label="item.display_name || item.code" :value="item.code" /></el-select>
   </el-form-item>
   <el-form-item label="处理阈值（IoU 大于或等于）">
    <el-input-number v-model="threshold" :min="0.5" :max="1" :step="0.01" :precision="2" />
   </el-form-item>
  </el-form>
  <p v-if="scanning" role="status">已预检 {{ scanned }} / {{ range.count }} 张</p>
  <template v-if="plan">
   <p>可处理 {{ plan.size }} 张 · 移除 {{ removed }} 个重叠框 · {{ fallback }} 组按原候选顺序保留</p>
   <ul v-if="Object.keys(reasons).length"><li v-for="(count,reason) in reasons" :key="reason">{{ reason }}（{{ count }}）</li></ul>
   <p v-if="writing || finished" role="status">回执已确认保存 {{ saved }} 张、失败 {{ failed }} 张</p>
   <el-checkbox v-else v-model="confirmed">确认批量保存候选草稿</el-checkbox>
  </template>
  <template #footer>
   <el-button :disabled="writing" @click="open=false">关闭</el-button>
   <el-button :loading="scanning" :disabled="writing || finished" @click="prepare">预检消歧</el-button>
   <el-button type="primary" :loading="writing" :disabled="!confirmed || !plan?.size || finished || scanning" @click="save">保存草稿</el-button>
  </template>
 </el-dialog>
</template>
