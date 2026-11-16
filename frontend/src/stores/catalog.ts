import {defineStore} from 'pinia';
import {reactive,ref} from 'vue';
import {catalogApi} from '../api/catalog';
import {submitCatalogOperation,recoverCatalogOperation,definiteRejection} from '../api/catalog-operation';
import type {CatalogPage,CatalogDetail,CatalogOperation,CatalogAction,CatalogRecord,Entity,Filters,PreviewContext} from '../types/catalog';
export const useCatalogView=defineStore('catalog-preview',()=>{
  const filters=reactive<Record<Entity,Filters>>({vendors:{query:'',enabled:'',template_id:'',page:1,sort:'name'},chips:{query:'',enabled:'',template_id:'',page:1,sort:'name'}});
  const pages=reactive<Record<Entity,CatalogPage|null>>({vendors:null,chips:null});
  const busy=reactive({vendors:false,chips:false,detail:false});
  const errors=reactive({vendors:'',chips:'',detail:''});
  const selected=ref(''),selectedName=ref(''),detail=ref<CatalogDetail|null>(null),drawer=ref(false);
  const editor=ref<{entity:Entity;id:string;action:CatalogAction;revision:number;record:Partial<CatalogRecord>;detail:CatalogDetail|null;mutableIdentity:boolean;conflict:boolean}|null>(null);
  const editing=ref(false),saving=ref(false),detecting=ref(''),notice=ref(''),writeError=ref('');
  const pending=ref<CatalogOperation|null>(null);
  let context:PreviewContext;
  let api:ReturnType<typeof catalogApi>,alive=true;
  const requests=new Map<string,AbortController>();
  function stop(key:string){requests.get(key)?.abort();requests.delete(key)}
  function start(key:string){stop(key);const c=new AbortController();requests.set(key,c);return c}
  function message(e:unknown){return e instanceof Error?e.message:'读取失败，请重试'}
  async function load(entity:Entity){
    if(!alive)return;
    const c=start(entity);busy[entity]=true;errors[entity]='';
    if(entity==='vendors'){stop('chips');busy.chips=false;errors.chips='';closeDetail()}
    try{
      const page=await api.list(entity,filters[entity],selected.value,c.signal);
      if(!alive||c.signal.aborted)return;
      pages[entity]=page;
      if(entity==='vendors'){
        const choice=page.items.find(row=>row.id===selected.value)||page.items[0];
        if(choice)await choose(choice.id,choice.name);else{selected.value='';selectedName.value='';pages.chips=null}
      }
    }catch(e){if(alive&&!c.signal.aborted)errors[entity]=message(e)}
    finally{if(requests.get(entity)===c){busy[entity]=false;requests.delete(entity)}}
  }
  async function choose(id:string,name:string){const changed=selected.value!==id;selected.value=id;selectedName.value=name;if(changed){filters.chips.page=1;pages.chips=null;stop('editor');editor.value=null;editing.value=false}closeDetail();await load('chips')}
  async function showDetail(entity:Entity,id:string){
    const c=start('detail');drawer.value=true;detail.value=null;errors.detail='';busy.detail=true;
    try{const value=await api.detail(entity,id,c.signal);if(alive&&!c.signal.aborted)detail.value=value}
    catch(e){if(alive&&!c.signal.aborted)errors.detail=message(e)}
    finally{if(requests.get('detail')===c){busy.detail=false;requests.delete('detail')}}
  }
  function closeDetail(){stop('detail');drawer.value=false;detail.value=null;busy.detail=false;errors.detail=''}
  function setPending(value:CatalogOperation|null){pending.value=value;context.pending?.save(value)}
  async function openEditor(entity:Entity,id='',action:CatalogAction=id?'update':'create'){
    if(!context.management||pending.value||saving.value)return;
    closeDetail();const c=start('editor'),vendor=selected.value;editing.value=true;editor.value=null;writeError.value='';notice.value='';
    try{
      const value=id?await api.detail(entity,id,c.signal):null;
      if(!alive||c.signal.aborted||selected.value!==vendor)return;
      editor.value={entity,id,action,revision:value?.revision??pages[entity]?.revision??pages.vendors?.revision??0,record:value?{...value.item}:{name:'',enabled:true,...(entity==='vendors'?{template_id:pages.vendors?.templates[0]?.id||''}:{vendor_id:vendor,code:'',sdk_code:''})},detail:value,mutableIdentity:!id||value?.references.can_delete===true,conflict:false};
    }catch(e){if(alive&&!c.signal.aborted)writeError.value=message(e)}
    finally{if(requests.get('editor')===c)requests.delete('editor')}
  }
  function closeEditor(){if(saving.value)return;stop('editor');editor.value=null;editing.value=false;if(!pending.value)writeError.value=''}
  async function save(){
    const form=editor.value;if(!form||saving.value||pending.value||form.conflict)return;
    if(form.action==='delete'&&form.detail?.references.can_delete!==true)return;
    if(!context.createOperationId)throw new Error('原操作身份通道未初始化');
    const record:Partial<CatalogRecord>={name:form.record.name?.trim(),enabled:form.record.enabled};
    if(form.entity==='vendors')record.template_id=form.mutableIdentity?form.record.template_id:form.detail?.item.template_id;
    else{record.vendor_id=form.detail?.item.vendor_id||form.record.vendor_id;if(form.mutableIdentity){record.code=form.record.code;record.sdk_code=form.record.sdk_code}}
    const operation:CatalogOperation={entity:form.entity,action:form.action,operation_id:context.createOperationId(),expected_revision:form.revision,...(form.id?{id:form.id}:{}),...(['create','update'].includes(form.action)?{record}:{}),...(form.action==='delete'?{confirm_delete:true}:{})};
    // Keep the exact packet before sending. Leaving or losing a reply never creates a new ID.
    setPending(JSON.parse(JSON.stringify(operation)));await commit(false);
  }
  async function commit(recover:boolean,replay=false){
    const operation=pending.value;if(!operation||saving.value)return;saving.value=true;writeError.value='';
    try{
      const result=recover?await recoverCatalogOperation(api,operation,replay):await submitCatalogOperation(api,operation);
      if(!alive)return;
      setPending(null);editing.value=false;editor.value=null;context.invalidate?.();notice.value=result.replayed?'原操作已确认（幂等回放）':operation.action==='delete'?'已删除':'已保存';
      if(operation.entity==='vendors'&&operation.action==='create')selected.value=result.id;
      await load('vendors');
    }catch(e){if(alive){writeError.value=message(e);if(definiteRejection(e)){setPending(null);if(editor.value&&(e as {code?:string}).code==='CATALOG_REVISION_CONFLICT')editor.value.conflict=true}}}
    finally{if(alive)saving.value=false}
  }
  async function reloadEditor(){const form=editor.value;if(!form||pending.value)return;await load('vendors');if(alive)await openEditor(form.entity,form.id,form.action)}
  async function detect(id:string){
    if(detecting.value||pending.value||!context.management)return;detecting.value=id;writeError.value='';notice.value='';
    try{const result=await api.detect(id);if(!alive)return;if(result.ok!==true||result.id!==id)throw new Error('检测响应身份不一致');context.invalidate?.();await load('chips');if(alive)notice.value='检测请求已完成，状态以最新资源证据为准'}
    catch(e){if(alive)writeError.value=message(e)}finally{if(alive)detecting.value=''}
  }
  function dispose(){alive=false;requests.forEach(c=>c.abort());requests.clear();context?.signal.removeEventListener('abort',dispose)}
  function initialize(value:PreviewContext){context=value;api=catalogApi(context);pending.value=context.pending?.value||null;context.signal.addEventListener('abort',dispose,{once:true});return load('vendors')}
  return {filters,pages,busy,errors,selected,selectedName,detail,drawer,load,choose,showDetail,closeDetail,initialize,dispose,editor,editing,saving,detecting,notice,writeError,pending,openEditor,closeEditor,save,commit,reloadEditor,detect};
});
