// Metadata only. The original navigation and page owners render and route.
import {PREVIEW_PAGE,MANAGEMENT_PAGE,NODES_PAGE,CONFIGURATION_PAGE,ASSETS_PAGE,MATERIALS_PAGE,POOL_PAGE,AI_TASKS_PAGE,TASKS_PAGE,REPORT_PAGE,HISTORY_PAGE} from './catalog-preview-runtime.js?v=20261117p1z1';
export function installProductWorkbenchRuntime({enabled=false}={}){
 if(!enabled)return null;
 const knownPages=Object.freeze([PREVIEW_PAGE,MANAGEMENT_PAGE,NODES_PAGE,CONFIGURATION_PAGE,ASSETS_PAGE,MATERIALS_PAGE,POOL_PAGE,AI_TASKS_PAGE,TASKS_PAGE,REPORT_PAGE,HISTORY_PAGE,'统一工作台','素材上传与治理']);
 const known=new Set(knownPages);
 const aliases=new Map([['总览','统一工作台'],['算法列表',ASSETS_PAGE],['数据集',MATERIALS_PAGE],['训练任务',TASKS_PAGE],['自动标注及清洗',AI_TASKS_PAGE],['服务节点',NODES_PAGE]]);
 const labels=new Map([['统一工作台','工作台'],[ASSETS_PAGE,'算法与模型'],[MATERIALS_PAGE,'素材库'],[AI_TASKS_PAGE,'AI 标注'],[TASKS_PAGE,'训练任务'],[NODES_PAGE,'资源与节点'],[CONFIGURATION_PAGE,'配置中心'],['素材上传与治理','上传与治理'],[POOL_PAGE,'算法负样本池'],[HISTORY_PAGE,'版本转换记录'],[REPORT_PAGE,'训练报告'],[PREVIEW_PAGE,'厂商与芯片预览'],[MANAGEMENT_PAGE,'厂商与芯片管理']]);
 const parents=new Map([[HISTORY_PAGE,ASSETS_PAGE],[REPORT_PAGE,ASSETS_PAGE],[POOL_PAGE,MATERIALS_PAGE],['素材上传与治理',MATERIALS_PAGE],[PREVIEW_PAGE,CONFIGURATION_PAGE],[MANAGEMENT_PAGE,CONFIGURATION_PAGE]]);
 const primary=[{title:'工作台',items:['统一工作台']},{title:'业务工作流',items:[ASSETS_PAGE,MATERIALS_PAGE,AI_TASKS_PAGE,TASKS_PAGE]},{title:'资源与配置',items:[NODES_PAGE,CONFIGURATION_PAGE]}];
 return Object.freeze({knownPages,navigationOwner:page=>parents.get(page)||page,navigation(originalGroups=[],advanced=false){return [...primary,...(advanced?originalGroups:[])].map(group=>({...group,items:[...group.items]}))},navigationLabel:page=>labels.get(page)||page,initialPage:page=>aliases.get(page)||page,canRestore:page=>known.has(page)});
}
