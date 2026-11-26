import type {MaterialContext,MaterialFilters,MaterialPage,MaterialDetail} from '../types/materials';
export function materialQuery(filters:MaterialFilters,page:number){const q=new URLSearchParams({reader_view:'true',page:String(page),page_size:'48'});for(const [key,value] of Object.entries(filters))if(value.trim())q.append(key,value.trim());return q}
export function materialMediaUrl(value:unknown,project:string,id:string,kind:'thumbnail'|'content') {if(typeof value!=='string')return '';const expected=`/api/v61/projects/${encodeURIComponent(project)}/materials/${encodeURIComponent(id)}/content`;try{const u=new URL(value,'https://material.invalid');if(u.origin!=='https://material.invalid'||u.hash||!([expected+(kind==='thumbnail'?'/thumbnail':'')].concat(kind==='thumbnail'?[`/api/v62/projects/${encodeURIComponent(project)}/training-materials/${encodeURIComponent(id)}/thumbnail`]:[])).includes(u.pathname))return '';return u.pathname+u.search}catch{return ''}}
export function materialsApi(context:MaterialContext){
 const base=`/api/v61/projects/${encodeURIComponent(context.projectId)}/materials`;
 function identity(value:{ok:boolean;project_id:string}){
  if(!value?.ok||value.project_id!==context.projectId)throw new Error('素材响应项目身份不一致');
 }
 async function list(filters:MaterialFilters,page:number,signal:AbortSignal){
  const result=await context.get<MaterialPage>(`${base}?${materialQuery(filters,page)}`,{signal});
  identity(result);
  if(!Array.isArray(result.items)||result.page!==page||result.items.some(row=>!row.id)||new Set(result.items.map(row=>row.id)).size!==result.items.length)
   throw new Error('素材列表响应无效');
  return result;
 }
 async function listAtOrBefore(filters:MaterialFilters,page:number,signal:AbortSignal){
  try{return await list(filters,page,signal)}
  catch(cause){
   // The numbered repository contract returns the last available page on this specific 400.
   const error=cause as {httpStatus?:number;message?:string};
   const end=/^page (\d+) exceeds total_pages (\d+)$/.exec(error.message||'');
   const last=Number(end?.[2]);
   if(signal.aborted||error.httpStatus!==400||Number(end?.[1])!==page||!Number.isSafeInteger(last)||last<1||last>=page)throw cause;
   return list(filters,last,signal);
  }
 }
 async function detail(id:string,signal:AbortSignal){
  const result=await context.get<MaterialDetail>(`/api/projects/${encodeURIComponent(context.projectId)}/annotations/${encodeURIComponent(id)}?reader_view=true`,{signal});
  identity(result);
  if(result.image?.id!==id||!Array.isArray(result.annotation?.boxes))throw new Error('素材详情身份不一致');
  return result;
 }
 return {list,listAtOrBefore,detail};
}
