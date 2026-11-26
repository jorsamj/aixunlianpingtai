import {request} from '../app/http';
import type {DeployResource} from '../types/conversion-job';

export interface ResourceConfiguration {
  name:string;
  kind:string;
  mode:'local'|'remote'|'agent';
  base_url:string;
  api_key:string;
  python_path:string;
  ultralytics_python:string;
  paddledet_dir:string;
  paddle2onnx_path:string;
  tool_root:string;
  trtexec_path:string;
  atc_path:string;
  env_script:string;
  remark:string;
}

const resources='/api/v39/deploy/resources';
const resourcePath=(id:string)=>`${resources}/${encodeURIComponent(id)}`;

function verifyResource(value:DeployResource,id?:string){
  if(!value?.id||(id&&value.id!==id))throw new Error('转换资源响应身份不一致');
  return value;
}

export async function saveResourceConfiguration(id:string,configuration:ResourceConfiguration,signal:AbortSignal){
  return verifyResource(await request<DeployResource>(id?resourcePath(id):resources,
    {method:id?'PUT':'POST',body:JSON.stringify(configuration),signal}),id);
}

export async function startResourceCheck(resource:DeployResource,signal:AbortSignal){
  // Saved resources share a single in-flight SDK check across workers and views.
  // Built-ins keep the original explicit detection endpoint.
  const suffix=resource.builtin?'/detect':'/detect/start';
  return verifyResource(await request<DeployResource>(resourcePath(resource.id)+suffix,
    {method:'POST',signal}),resource.id);
}

export async function readResourceCheck(id:string,signal:AbortSignal){
  return verifyResource(await request<DeployResource>(resourcePath(id)+'/detect/status',{signal}),id);
}
