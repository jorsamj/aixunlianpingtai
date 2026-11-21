import {messageFromApiError,withRequestDeadline} from '../../../static/modules/api.js';
export function login(){location.replace('/login?next='+encodeURIComponent(location.pathname+location.search+location.hash))}
export function request<T>(url:string,options:RequestInit={}):Promise<T>{
  return withRequestDeadline(async signal=>{
    const response=await fetch(url,{...options,credentials:'same-origin',signal,headers:{'Content-Type':'application/json',...options.headers}});
    const body=await response.json();
    if(!response.ok){if(response.status===401)login();const error=new Error(messageFromApiError(body.error||(body.message?body:{message:typeof body.detail==='string'?body.detail:'请求失败'})));Object.assign(error,{httpStatus:response.status,code:body.code||body.error?.code});throw error}
    return body as T;
  },{signal:options.signal||undefined,mutation:!!options.method&&options.method!=='GET'});
}
