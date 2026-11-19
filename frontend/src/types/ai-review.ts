import type {AiEditorContext,AiEditorSnapshot} from './ai-editor';
import type {MaterialBox} from './materials';
export interface ReviewItem {
  image_id:string;filename?:string;width?:number;height?:number;boxes?:MaterialBox[];original_boxes?:MaterialBox[];
  box_count?:number;thumbnail_url?:string;content_url?:string;status:string;error?:string;error_code?:string;
  gt_committed?:boolean;review_state?:string;draft_revision?:number;manual_review_required?:boolean;
  review_operation_id?:string;conflicts?:{labels:string[];iou:number;box_indices:number[]}[];selected:boolean;accepted?:boolean|null;selectable:boolean;
}
export interface ReviewSnapshot {
  taskId:string;projectId:string;items:ReviewItem[];offset:number;limit:number;total:number;filter:string;
  summary:Record<string,number|null>;loading:boolean;error?:string;selection:{count:number;frozenCount?:number;excludedCount?:number;id?:string;purpose?:'gt'|'transfer'|'ambiguity';filteredTotal?:number};
  status?:string;pending?:{request_id:string}|null;busy:boolean;labels:{code:string;display_name?:string}[];
  ambiguity:{mode:string;label:string;threshold:string|number;scanning:boolean;saving:boolean;
    preview?:{total:number;scanned:number;actionCount:number;actions:{id?:string;name?:string;removed?:number;removedBoxes?:MaterialBox[];keptLabel?:string}[];skippedCount:number;skipped:{name?:string;reason?:string}[]}|null;result?:string};
  edit:AiEditorSnapshot|null;
}
export interface AiReviewContext {
  snapshot():ReviewSnapshot;subscribe(fn:(value:ReviewSnapshot)=>void):()=>void;editor:AiEditorContext|null;
  actions:{filter(key:string):unknown;page(delta:number):unknown;reload():unknown;toggle(imageId:string,on:boolean):unknown;
    pageSelect(on:boolean):unknown;filtered(purpose?:"gt"|"transfer"|"ambiguity"):unknown;clear():unknown;decision(id:string,accepted:boolean):unknown;
    edit(id:string):unknown;close():unknown;approve():unknown;lookup():unknown;ambiguityMode(value:string):unknown;
    ambiguityLabel(code:string):unknown;ambiguityThreshold(value:string):unknown;ambiguityPreview():unknown;ambiguityApply():unknown;
    preview(id:string):unknown;legacy():unknown;openTransfer():unknown;resumeTransfer():unknown;transferReceipt(id:string):unknown;diagnostics(button:HTMLButtonElement,id:string):unknown;};
}
