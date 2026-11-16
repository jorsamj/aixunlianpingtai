import {defineStore} from 'pinia';
import {reactive,ref} from 'vue';
import {catalogApi} from '../api/catalog';
import type {CatalogPage,CatalogDetail,Entity,Filters,PreviewContext} from '../types/catalog';
export const useCatalogView=defineStore('catalog-preview',()=>{
  const filters=reactive<Record<Entity,Filters>>({vendors:{query:'',enabled:'',template_id:'',page:1,sort:'name'},chips:{query:'',enabled:'',template_id:'',page:1,sort:'name'}});
  const pages=reactive<Record<Entity,CatalogPage|null>>({vendors:null,chips:null});
  const busy=reactive({vendors:false,chips:false,detail:false});
  const errors=reactive({vendors:'',chips:'',detail:''});
  const selected=ref(''),selectedName=ref(''),detail=ref<CatalogDetail|null>(null),drawer=ref(false);
  let api:ReturnType<typeof catalogApi>,alive=true;
  const requests=new Map<string,AbortController>();
  function stop(key:string){requests.get(key)?.abort();requests.delete(key)}
  function start(key:string){stop(key);const c=new AbortController();requests.set(key,c);return c}
  function message(e:unknown){return e instanceof Error?e.message:'读取失败，请重试'}
  async function load(entity:Entity){
    if(!alive)return;
    const c=start(entity);busy[entity]=true;errors[entity]='';pages[entity]=null;
    if(entity==='vendors'){stop('chips');pages.chips=null;busy.chips=false;errors.chips='';selected.value='';selectedName.value='';closeDetail()}
    try{
      const page=await api.list(entity,filters[entity],selected.value,c.signal);
      if(!alive||c.signal.aborted)return;
      pages[entity]=page;
      if(entity==='vendors'&&page.items.length){await choose(page.items[0].id,page.items[0].name)}
    }catch(e){if(alive&&!c.signal.aborted)errors[entity]=message(e)}
    finally{if(requests.get(entity)===c){busy[entity]=false;requests.delete(entity)}}
  }
  async function choose(id:string,name:string){selected.value=id;selectedName.value=name;filters.chips.page=1;closeDetail();await load('chips')}
  async function showDetail(entity:Entity,id:string){
    const c=start('detail');drawer.value=true;detail.value=null;errors.detail='';busy.detail=true;
    try{const value=await api.detail(entity,id,c.signal);if(alive&&!c.signal.aborted)detail.value=value}
    catch(e){if(alive&&!c.signal.aborted)errors.detail=message(e)}
    finally{if(requests.get('detail')===c){busy.detail=false;requests.delete('detail')}}
  }
  function closeDetail(){stop('detail');drawer.value=false;detail.value=null;busy.detail=false;errors.detail=''}
  function dispose(){alive=false;requests.forEach(c=>c.abort());requests.clear()}
  function initialize(context:PreviewContext){api=catalogApi(context);context.signal.addEventListener('abort',dispose,{once:true});return load('vendors')}
  return {filters,pages,busy,errors,selected,selectedName,detail,drawer,load,choose,showDetail,closeDetail,initialize,dispose};
});
