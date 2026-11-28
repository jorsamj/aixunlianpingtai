import {request} from '../app/http';
import type {AiEditorBox} from '../types/ai-editor';
import type {MaterialRow} from '../types/materials';
import type {annotationSavePayload} from '../../../static/modules/annotation-workbench.js';

export type FormalPayload=ReturnType<typeof annotationSavePayload>;
interface FormalAnnotation {
  version:number;
  boxes:AiEditorBox[];
  annotation_state?:string;
  annotation_scope?:string[];
}
interface FormalDocument {
  ok:boolean;
  image:MaterialRow & {content_sha256:string};
  annotation:FormalAnnotation;
}
function endpoint(project:string,id:string){
  return `/api/projects/${encodeURIComponent(project)}/annotations/${encodeURIComponent(id)}`;
}
function validate(value:FormalDocument,id:string){
  if(value.ok!==true||value.image?.id!==id||!Array.isArray(value.annotation?.boxes)
    ||!Number.isSafeInteger(value.annotation.version)||value.annotation.version<0){
    throw new Error('正式标注记录身份或版本不一致');
  }
  return value;
}
export async function readFormalAnnotation(project:string,id:string,signal:AbortSignal){
  // reader_view is a bounded preview without stable box IDs or full metadata.
  return validate(await request<FormalDocument>(endpoint(project,id),{signal,cache:'no-store'}),id);
}
export async function writeFormalAnnotation(project:string,id:string,payload:FormalPayload){
  const value=validate(await request<FormalDocument>(endpoint(project,id),{
    method:'POST',body:JSON.stringify(payload),
  }),id);
  if(value.image.content_sha256!==payload.source_content_sha256||value.annotation.version<=payload.expected_version)
    throw new Error('正式标注回执的图片代际或版本不一致');
  return value;
}
export function sameFormalBoxes(left:AiEditorBox[],right:AiEditorBox[]){
  const evidence=(rows:AiEditorBox[])=>JSON.stringify(rows.map(box=>({
    ...box,source:box.source||'manual',x1:round(box.x1),x2:round(box.x2),y1:round(box.y1),y2:round(box.y2),
  })),(_key,value)=>value&&typeof value==='object'&&!Array.isArray(value)
    ?Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b))):value);
  return evidence(left)===evidence(right);
}
const round=(value:number)=>Math.round(value*100)/100;
