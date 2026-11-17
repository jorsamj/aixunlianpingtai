// Optional workbench metadata; formal navigation and owners remain authoritative.
import {PREVIEW_PAGE,MANAGEMENT_PAGE,NODES_PAGE,CONFIGURATION_PAGE,ASSETS_PAGE,MATERIALS_PAGE,POOL_PAGE,AI_TASKS_PAGE,TASKS_PAGE,REPORT_PAGE,HISTORY_PAGE} from './catalog-preview-runtime.js?v=20261117p2preserve1';
export function installProductWorkbenchRuntime({enabled=false,trialPages=[]}={}){
 if(!enabled)return null;
 const supported=new Set([PREVIEW_PAGE,MANAGEMENT_PAGE,NODES_PAGE,CONFIGURATION_PAGE,ASSETS_PAGE,MATERIALS_PAGE,POOL_PAGE,AI_TASKS_PAGE,TASKS_PAGE,REPORT_PAGE,HISTORY_PAGE,'素材上传与治理']);
 const knownPages=Object.freeze(['统一工作台',...new Set(trialPages.filter(page=>supported.has(page)))]);
 const known=new Set(knownPages);
 return Object.freeze({knownPages,navigationOwner:page=>page,navigation(originalGroups=[]){return [...originalGroups.map(group=>({...group,items:[...group.items]})),{title:'Vue 试点',items:knownPages.filter(page=>!originalGroups.some(group=>group.items.includes(page)))}]},navigationLabel:page=>page==='统一工作台'?'工作台':supported.has(page)?`Vue ${page}（试点）`:page,initialPage:page=>page,canRestore:page=>known.has(page)});
}
