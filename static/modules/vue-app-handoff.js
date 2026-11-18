// Consumed only by the complete legacy page after its canonical project loads.
// The independent Vue app performs a full navigation; it never calls these owners.
const pages=new Set(['总览','质量中心','算法列表','训练任务','数据集','视频切帧','自动标注及清洗','标签管理','服务节点','部署资源','模型配置','存储配置','平台对接','畅联云数据','AI算法底座']);
export async function resumeVueHandoff({state,navigate,request,windowRoot=window,documentRoot=document}){
 const query=new URLSearchParams(windowRoot.location.search);
 if(query.get('spa_handoff')!=='1')return;
 const versionActions=new Set(['conversion','delivery','report','lineage','evaluation','delete-version','rollback','download']);
 const actions=new Set(['','train','algorithm-report','delete-algorithm',...versionActions]);
 let algorithm;
 const project=query.get('project_id'),page=query.get('page'),algorithmId=query.get('algorithm_id')||'',versionId=query.get('version_id')||'',action=query.get('action')||'';
 if(!project||state.project?.id!==project||!pages.has(page)||!actions.has(action))throw new Error('新版入口的项目或页面身份不匹配，未执行操作');
 if(action&&(!algorithmId||page!=='算法列表'||(versionActions.has(action)&&!versionId)))throw new Error('版本操作身份不完整');
 if(algorithmId){
  const result=await request(`/api/v12/projects/${encodeURIComponent(project)}/algorithms/${encodeURIComponent(algorithmId)}`);
  if(result.algorithm?.id!==algorithmId||(versionId&&!result.algorithm.versions?.some(row=>row.id===versionId)))throw new Error('原算法或版本已不存在');
  algorithm=result.algorithm;
  state.algorithms=(state.algorithms||[]).filter(row=>row.id!==algorithmId).concat([result.algorithm]);
 }
 const external=String(algorithm?.source_type||'').toUpperCase()==='EXTERNAL';
 const changLian=external&&String(algorithm?.provider_type||'').toUpperCase()==='CHANG_LIAN';
 const version=algorithm?.versions?.find(row=>row.id===versionId);
 if((action==='delete-algorithm'&&external)||(['delete-version','rollback'].includes(action)&&changLian))throw new Error('外部算法禁止此删除或回退入口');
 if(action==='rollback'&&(!algorithm?.current_version_id||!algorithm.versions?.some(row=>row.id===algorithm.current_version_id)||algorithm.current_version_id===versionId))throw new Error('当前版本或回退目标无效');
 if(action==='delivery'&&algorithm?.external_deletion_status&&algorithm.external_deletion_status!=='NORMAL')throw new Error('外部算法状态待核实或正在清理，新发布暂缓');
 if(action==='download'&&!String(version?.stored_path||'').trim())throw new Error('该版本没有可下载模型');
 if(state.project?.id!==project)throw new Error('项目已切换，未执行操作');
 await navigate(page);
 if(state.project?.id!==project||state.page!==page)throw new Error('原业务页未就绪，未执行操作');
 const link=documentRoot.createElement('a');link.textContent='返回新版算法库';link.href=`/app/#/projects/${encodeURIComponent(project)}/algorithms${algorithmId?'?algorithm='+encodeURIComponent(algorithmId):''}`;
 Object.assign(link.style,{position:'fixed',right:'24px',bottom:'24px',zIndex:'10001',background:'#fff',color:'#222',padding:'12px 18px',border:'1px solid #aaa',borderRadius:'8px'});documentRoot.body.append(link);
 // Refreshing the old page must not replay an action or reopen a form.
 windowRoot.history.replaceState(null,'',windowRoot.location.pathname);
 const owners={'report':'openVersionReport429','lineage':'openVersionLineage429','evaluation':'openVersionEvaluation429','algorithm-report':'algorithmReport429','delete-algorithm':'delAlgorithm','delete-version':'delVersion','rollback':'openVersionRollback'};
 if(action==='download')return windowRoot.location.assign(`/api/v12/projects/${encodeURIComponent(project)}/algorithms/${encodeURIComponent(algorithmId)}/versions/${encodeURIComponent(versionId)}/download`);
 if(owners[action]){
  if(typeof windowRoot[owners[action]]!=='function')throw new Error('原业务操作入口未就绪');
  return windowRoot[owners[action]](algorithmId,...(versionActions.has(action)?[versionId]:[]));
 }
 if(action==='train')return windowRoot.startAlgorithmTraining429?.(algorithmId);
 if(action==='conversion')return windowRoot.openVersionConvert428?.(algorithmId,versionId);
 if(action==='delivery')return windowRoot.ExternalAlgorithmPublishRuntime?.publishVersion?.(algorithmId,versionId);
}
