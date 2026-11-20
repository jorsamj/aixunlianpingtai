import type {CandidateDraft} from '../api/ai-review';

export interface DraftScope {actorKey:string;projectId:string;taskId:string;imageId:string}
export function draftRecoveryKey({actorKey,projectId,taskId,imageId}:DraftScope){
  return 'ai-candidate-draft:v1:'+JSON.stringify([actorKey,projectId,taskId,imageId]);
}
export interface DraftRecovery {
  scope:DraftScope;
  draft:CandidateDraft;
  confirmedRevision?:number;
}
const isRecord=(value:unknown):value is Record<string,unknown>=>
  value!==null&&typeof value==='object'&&!Array.isArray(value);
const finite=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value);
const invalid=()=>new Error('原草稿恢复记录无效，已保留该记录。请在原工作台核对服务端草稿。');

export function parseDraftRecovery(raw:string,scope:DraftScope):DraftRecovery {
  const value:unknown=JSON.parse(raw);
  if(!isRecord(value))throw invalid();
  const wrapped=Object.hasOwn(value,'scope')||Object.hasOwn(value,'draft')||Object.hasOwn(value,'confirmedRevision');
  // The caller reads only the exact account/project/task/image storage key.
  // Older records carried only the draft body under that same scoped key.
  const draft=wrapped?value.draft:value;
  const confirmed=wrapped?value.confirmedRevision:undefined;
  if(wrapped){
    const savedScope=value.scope;
    if(!isRecord(savedScope)||Object.entries(scope).some(([key,id])=>savedScope[key]!==id))throw invalid();
  }
  if(!isRecord(draft)||Object.keys(draft).some(key=>!['boxes','revision','request_id','source_content_sha256'].includes(key))
      ||typeof draft.revision!=='number'||!Number.isSafeInteger(draft.revision)||draft.revision<0
      ||typeof draft.request_id!=='string'||!/^[A-Za-z0-9_-]{12,80}$/.test(draft.request_id)
      ||!Array.isArray(draft.boxes)||draft.boxes.length>300
      ||(draft.source_content_sha256!==undefined&&
        (typeof draft.source_content_sha256!=='string'||!/^[a-f\d]{64}$/i.test(draft.source_content_sha256))))throw invalid();
  const ids=new Set<string>();
  for(const box of draft.boxes){
    if(!isRecord(box)||!(typeof box.id==='string'||finite(box.id))||!String(box.id).trim()
      ||typeof box.label!=='string'||!box.label.trim()
      ||!finite(box.x1)||!finite(box.y1)||!finite(box.x2)||!finite(box.y2)
      ||box.x1<0||box.y1<0||box.x2<=box.x1||box.y2<=box.y1||ids.has(String(box.id)))throw invalid();
    ids.add(String(box.id));
  }
  if(confirmed!==undefined&&(typeof confirmed!=='number'||!Number.isSafeInteger(confirmed)||confirmed!==draft.revision+1))throw invalid();
  return {scope,draft:draft as unknown as CandidateDraft,confirmedRevision:confirmed};
}
