import type {CompletedDecision,ReviewCandidate,SingleDecision} from '../api/ai-review';
import type {DraftScope} from '../app/ai-draft-recovery';

export interface DecisionRecovery {
  scope:DraftScope;
  body:SingleDecision;
  status:'pending'|'completed'|'rejected';
  receipt?:CompletedDecision;
  reason?:string;
}

const validId=/^[A-Za-z0-9_-]{12,80}$/;
export const validRevision=(value:unknown):value is number=>
  typeof value==='number'&&Number.isSafeInteger(value)&&value>=0;
export function decisionKey({actorKey,projectId,taskId,imageId}:DraftScope) {
  return 'ai-review-decision:v1:'+JSON.stringify([actorKey,projectId,taskId,imageId]);
}
export function matchesCompletion(result:CompletedDecision|undefined,body:SingleDecision) {
  return result?.status==='completed'&&result.request_id===body.request_id
    &&result.image_id===body.decisions[0].image_id&&result.accepted===body.decisions[0].accepted
    &&result.review_revision===body.review_revision+1;
}
export function loadDecision(scope:DraftScope):DecisionRecovery|undefined {
  const raw=sessionStorage.getItem(decisionKey(scope));
  if(raw===null)return;
  const saved=JSON.parse(raw) as Partial<DecisionRecovery>|null;
  const body=saved?.body;
  const row=body?.decisions?.[0];
  if(!saved?.scope||Object.entries(scope).some(([key,id])=>saved.scope?.[key as keyof DraftScope]!==id)
    ||!body||typeof body.request_id!=='string'||!validId.test(body.request_id)||!validRevision(body.review_revision)
    ||!Array.isArray(body.decisions)||body.decisions.length!==1||row?.image_id!==scope.imageId
    ||typeof row.accepted!=='boolean'||!['pending','completed','rejected'].includes(saved.status??'')
    ||(saved.status==='completed'&&!matchesCompletion(saved.receipt,body))) {
    throw new Error('审核恢复记录无效，请核对原操作。');
  }
  // Only read back receipts after recovery. A stored body is never posted again.
  return saved as DecisionRecovery;
}

export function hasUnresolvedAmbiguity(row:ReviewCandidate) {
  const boxes=row.boxes??[];
  if(row.manual_review_required){
    if(!row.draft_revision||row.draft?.auto_resolution!==false)return true;
    if(boxes.some((left,index)=>{
      const area=(box:typeof left)=>(box.x2-box.x1)*(box.y2-box.y1);
      return boxes.slice(index+1).some(right=>{
        if(left.label===right.label)return false;
        const x=Math.max(0,Math.min(left.x2,right.x2)-Math.max(left.x1,right.x1));
        const y=Math.max(0,Math.min(left.y2,right.y2)-Math.max(left.y1,right.y1));
        return x*y>0.5*(area(left)+area(right)-x*y);
      });
    }))return true;
  }
  return false;
}

export function canAdopt(row:ReviewCandidate,scope:string[]) {
  if(hasUnresolvedAmbiguity(row))return false;
  const boxes=row.boxes??[];
  if(row.review_scope_policy!=='per_image_required')return true;
  const missing=row.missing_review_scope??[];
  return scope.length>0&&scope.length<=128&&scope.every(code=>missing.includes(code))
    &&boxes.every(box=>scope.includes(box.label??''));
}
