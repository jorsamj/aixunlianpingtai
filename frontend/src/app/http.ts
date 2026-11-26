import {messageFromApiError,withRequestDeadline} from '../../../static/modules/api.js';
export function login(){location.replace('/login?next='+encodeURIComponent(location.pathname+location.search+location.hash))}
function apiError(body:unknown,status:number){
  let message='';
  const record=(body&&typeof body==='object'?body:{}) as Record<string,unknown>;
  try{message=messageFromApiError((record.error||((record.message?record:{message:typeof record.detail==='string'?record.detail:'请求失败'}))) as Record<string,unknown>)}catch{message=''}
  const code=(record.code??(record.error as {code?:unknown}|undefined)?.code);
  return Object.assign(new Error(message||`请求失败（HTTP ${status}）`),{httpStatus:status,code});
}
export function request<T>(url:string,options:RequestInit={},timeoutMs?:number):Promise<T>{
  return withRequestDeadline(async signal=>{
    const headers=new Headers(options.headers);
    if(!(options.body instanceof FormData)&&!headers.has('Content-Type'))headers.set('Content-Type','application/json');
    const response=await fetch(url,{...options,credentials:'same-origin',signal,headers});
    const body=await response.json();
    if(!response.ok){if(response.status===401)login();throw apiError(body,response.status)}
    return body as T;
  },{signal:options.signal||undefined,mutation:!!options.method&&options.method!=='GET',timeoutMs});
}
// Text responses (logs/reports) keep the same 401/deadline/cancel contract as JSON reads.
export function requestText(url:string,options:RequestInit={}):Promise<string>{
  return withRequestDeadline(async signal=>{
    const response=await fetch(url,{...options,credentials:'same-origin',signal,headers:{Accept:'text/plain',...options.headers}});
    const body=await response.text();
    if(!response.ok){
      if(response.status===401)login();
      let parsed:unknown=body;
      try{parsed=JSON.parse(body)}catch{/* plain-text error body stays as-is */}
      const error=apiError(typeof parsed==='string'?{detail:parsed.slice(0,600)}:parsed,response.status);
      throw error;
    }
    return body;
  },{signal:options.signal||undefined,mutation:!!options.method&&options.method!=='GET'});
}
