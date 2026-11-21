import {onUnmounted,reactive} from 'vue';
import {browseError} from '../api/model-browse';
export function useReadScope(context:{signal:AbortSignal}){
 const busy=reactive<Record<string,boolean>>({}),errors=reactive<Record<string,string>>({});
 const controllers=new Map<string,AbortController>();let alive=true;
 function cancel(key:string){controllers.get(key)?.abort();controllers.delete(key);busy[key]=false;errors[key]=''}
 async function run<T>(key:string,read:(signal:AbortSignal)=>Promise<T>,apply:(value:T)=>void){
  if(!alive)return;cancel(key);const c=new AbortController();controllers.set(key,c);busy[key]=true;
  try{const value=await read(c.signal);if(alive&&!c.signal.aborted)apply(value)}
  catch(error){if(alive&&!c.signal.aborted)errors[key]=browseError(error)}
  finally{if(controllers.get(key)===c){controllers.delete(key);busy[key]=false}}
 }
 function dispose(){alive=false;controllers.forEach(c=>c.abort());controllers.clear();context.signal.removeEventListener('abort',dispose)}
 context.signal.addEventListener('abort',dispose,{once:true});onUnmounted(dispose);
 return {busy,errors,run,cancel};
}
