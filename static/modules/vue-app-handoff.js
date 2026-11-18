// Consumed only by the complete legacy page after its canonical project loads.
// The independent Vue app performs a full navigation; it never calls these owners.
const pages=new Set(['总览','质量中心','算法列表','训练任务','数据集','视频切帧','自动标注及清洗','标签管理','服务节点','部署资源','模型配置','存储配置','平台对接','畅联云数据','AI算法底座']);
export async function resumeVueHandoff({state,navigate,request,windowRoot=window,documentRoot=document}){
 const query=new URLSearchParams(windowRoot.location.search);
 if(query.get('spa_handoff')!=='1')return;
 const project=query.get('project_id'),page=query.get('page'),algorithmId=query.get('algorithm_id')||'',versionId=query.get('version_id')||'',action=query.get('action')||'';
 if(!project||state.project?.id!==project||!pages.has(page)||!['','train','conversion','delivery'].includes(action))throw new Error('新版入口的项目或页面身份不匹配，未执行操作');
 if(action&&(!algorithmId||page!=='算法列表'||(action!=='train'&&!versionId)))throw new Error('版本操作身份不完整');
 if(algorithmId){
  const result=await request(`/api/v12/projects/${encodeURIComponent(project)}/algorithms/${encodeURIComponent(algorithmId)}`);
  if(result.algorithm?.id!==algorithmId||(versionId&&!result.algorithm.versions?.some(row=>row.id===versionId)))throw new Error('原算法或版本已不存在');
  state.algorithms=(state.algorithms||[]).filter(row=>row.id!==algorithmId).concat([result.algorithm]);
 }
 if(state.project?.id!==project)throw new Error('项目已切换，未执行操作');
 await navigate(page);
 if(state.project?.id!==project||state.page!==page)throw new Error('原业务页未就绪，未执行操作');
 const link=documentRoot.createElement('a');link.textContent='返回新版算法库';link.href=`/app/#/projects/${encodeURIComponent(project)}/algorithms${algorithmId?'?algorithm='+encodeURIComponent(algorithmId):''}`;
 Object.assign(link.style,{position:'fixed',right:'24px',bottom:'24px',zIndex:'10001',background:'#fff',color:'#222',padding:'12px 18px',border:'1px solid #aaa',borderRadius:'8px'});documentRoot.body.append(link);
 // Refreshing the old page must not replay an action or reopen a form.
 windowRoot.history.replaceState(null,'',windowRoot.location.pathname);
 if(action==='train')return windowRoot.startAlgorithmTraining429?.(algorithmId);
 if(action==='conversion')return windowRoot.openVersionConvert428?.(algorithmId,versionId);
 if(action==='delivery')return windowRoot.ExternalAlgorithmPublishRuntime?.publishVersion?.(algorithmId,versionId);
}
