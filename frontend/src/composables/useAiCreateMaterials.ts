import {computed,ref,shallowRef} from 'vue';
import type {MaterialFilters,MaterialPage} from '../types/materials';
import {materialsApi} from '../api/materials';
import {aiMaterialMembership,freezeAiMaterials,type SelectionInput} from '../api/ai-annotation-create';
import {useReadScope} from './useReadScope';
import {request} from '../app/http';

export function useAiCreateMaterials(projectId:string,controller:AbortController,initial:MaterialFilters,initialIds:string[]){
  const reads=useReadScope(controller);
  const api=materialsApi({projectId,get:request,signal:controller.signal,memory:{}});
  const page=shallowRef<MaterialPage>();
  const filters=shallowRef(initial);
  const members=shallowRef(new Set<string>());
  const selected=shallowRef(new Set(initialIds)),excluded=shallowRef(new Set<string>());
  const frozen=shallowRef<{selection_ref:string;count:number}>();
  const busy=computed(()=>!!(reads.busy.page||reads.busy.freeze));
  const count=computed(()=>(frozen.value?.count??0)-excluded.value.size+selected.value.size);
  const canFreeze=computed(()=>{
    const {storage_source_id,source_batch_id,quality_status,created_from,created_to,annotation_state}=filters.value;
    return !storage_source_id&&!source_batch_id&&!quality_status&&!created_from&&!created_to&&annotation_state!=='needs_review';
  });
  const warning=ref('');
  const error=computed(()=>warning.value||reads.errors.page||reads.errors.freeze);
  function load(number=1,scope=filters.value){
    warning.value='';
    const selection=frozen.value?.selection_ref;
    return reads.run('page',async signal=>{
      const result=await api.list(scope,number,signal);
      const matched=selection?await aiMaterialMembership(projectId,selection,result.items.map(row=>row.id),signal):[];
      return {result,matched};
    },({result,matched})=>{
      page.value=result;
      filters.value=scope;
      members.value=new Set(matched);
    });
  }
  function isSelected(id:string){
    return selected.value.has(id)||(members.value.has(id)&&!excluded.value.has(id));
  }
  function setSelected(id:string,value:boolean){
    if(busy.value||isSelected(id)===value)return;
    warning.value='';
    if(members.value.has(id)){
      if(!value&&excluded.value.size>=10000){warning.value='单次最多排除 10000 张，请缩小冻结范围。';return}
      const next=new Set(excluded.value);
      if(value)next.delete(id);else next.add(id);
      excluded.value=next;
    }else{
      if(value&&selected.value.size>=50000){warning.value='请使用筛选范围冻结来选择更多素材。';return}
      const next=new Set(selected.value);
      if(value)next.add(id);else next.delete(id);
      selected.value=next;
    }
  }
  function selectPage(){for(const row of page.value?.items||[])setSelected(row.id,true)}
  function clear(){
    if(busy.value)return;
    frozen.value=undefined;selected.value=new Set();excluded.value=new Set();members.value=new Set();
  }
  function input():SelectionInput{
    return {image_ids:[...selected.value],previous_ref:frozen.value?.selection_ref,excluded_image_ids:[...excluded.value]};
  }
  async function freeze(){
    if(busy.value||!page.value||!canFreeze.value)return;
    const scope=filters.value;
    await reads.run('freeze',async signal=>{
      const result=await freezeAiMaterials(projectId,{
        query:scope.query,labels:scope.label?[scope.label]:[],annotation_state:scope.annotation_state||null,
      },input(),signal);
      const matched=await aiMaterialMembership(projectId,result.selection_ref,page.value?.items.map(row=>row.id)||[],signal);
      return {result,matched};
    },({result,matched})=>{
      frozen.value=result;
      selected.value=new Set();excluded.value=new Set();members.value=new Set(matched);
    });
  }
  return {page,frozen,excluded,busy,error,count,canFreeze,isSelected,setSelected,selectPage,clear,input,freeze,load};
}
