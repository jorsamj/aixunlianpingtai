// Consumed only by the complete legacy page after its canonical project loads.
// The independent Vue app performs a full navigation; it never calls these owners.
const pages=new Set(['总览','质量中心','算法列表','训练任务','数据集','视频切帧','自动标注及清洗','标签管理','服务节点','部署资源','模型配置','存储配置','平台对接','畅联云数据','AI算法底座']);
const materialPages={
 'material-manage':'数据集','material-manual':'数据集','material-upload':'数据集',
 'material-zip':'数据集','material-annotate':'数据集','material-negative':'数据集',
 'material-integrity':'数据集','material-ai':'自动标注及清洗','material-clean':'自动标注及清洗',
 'material-labels':'标签管理',
};
async function resumeMaterials({project,action,query,state,navigate,request,windowRoot,documentRoot}){
 const page=materialPages[action];
 if(query.get('page')!==page)throw new Error('素材工作台入口不匹配');
 await navigate(page);
 const active=()=>state.project?.id===project&&state.page===page;
 if(!active())throw new Error('原素材工作台未就绪');
 const id=query.get('material_id')||'';
 if(action==='material-annotate'){
  if(!id||/[\\/]/.test(id)||id==='.'||id==='..')throw new Error('素材身份无效');
  const result=await request(`/api/projects/${encodeURIComponent(project)}/annotations/${encodeURIComponent(id)}?reader_view=true`);
  if(result?.ok!==true||result.project_id!==project||result.image?.id!==id||!active())
   throw new Error('素材身份不一致，未打开标注');
 }
 const incoming=new URLSearchParams(query.get('return_query')||'');
 const back=new URLSearchParams();
 for(const key of ['query','label','annotation_state','quality_status','storage_source_id','source_batch_id',
  'created_from','created_to','page','layout','detail']){
  const value=incoming.get(key);
  if(value)back.set(key,value);
 }
 if(action==='material-annotate')back.set('detail',id);
 const link=documentRoot.createElement('a');
 link.textContent='返回新版素材库';
 link.href=`/app/#/projects/${encodeURIComponent(project)}/materials${back.size?'?'+back:''}`;
 Object.assign(link.style,{position:'fixed',right:'24px',bottom:'24px',zIndex:'10001',background:'#fff',color:'#222',padding:'12px 18px',border:'1px solid #aaa',borderRadius:'8px'});
 documentRoot.body.append(link);
 windowRoot.history.replaceState(null,'',windowRoot.location.pathname);
 const openers={
  'material-annotate':()=>windowRoot.openAnnotation?.(id),
  'material-manual':()=>windowRoot.setData412Tab?.('unannotated'),
  'material-upload':()=>typeof windowRoot.ImageUppyView?.open==='function'
   ?windowRoot.ImageUppyView.open({projectId:project}):windowRoot.openDataUpload426?.(),
  'material-zip':()=>windowRoot.openUppyZipUpload?.(),
  'material-negative':()=>windowRoot.NegativePoolRuntime?.open?.(),
  'material-ai':()=>windowRoot.createAiLabel429?.(),
  'material-clean':()=>windowRoot.createClean427?.(),
  'material-integrity':()=>windowRoot.openMaterialIntegrityAudit47?.(),
 };
 return openers[action]?.();
}
async function resumeTrainingTask({project, action, query, state, navigate, request, windowRoot, documentRoot}) {
 const taskId = query.get('task_id') || '';
 if (!taskId || query.get('page') !== '训练任务') throw new Error('训练任务身份不完整');
 const readUrl = `/api/v62/projects/${encodeURIComponent(project)}/tasks/${encodeURIComponent(taskId)}?reader_view=true`;
 await navigate('训练任务');
 if (state.project?.id !== project || state.page !== '训练任务') throw new Error('原训练任务页未就绪');
 const result = await request(readUrl);
 const task = result?.task;
 if (result?.ok !== true || result.project_id !== project || task?.project_id !== project ||
     task.task_id !== taskId || task.kind !== 'TRAINING' || state.project?.id !== project || state.page !== '训练任务') {
  throw new Error('训练任务身份不一致，未执行操作');
 }
 if (action === 'task-stop' && (!['QUEUED','WAITING_RESOURCE','RUNNING','PAUSED'].includes(task.status) ||
     ['cancelling','stopping','starting','pausing','resuming','cleaning_training_process','process_cleanup_blocked'].includes(task.phase))) {
  throw new Error('任务当前状态不允许再次停止，请刷新核对');
 }
 const owner = action === 'task-stop' ? windowRoot.stopTrain428 : action === 'task-report' ? windowRoot.openJobReport429 : windowRoot.openTrainingRecoveryDetail;
 if (typeof owner !== 'function') throw new Error('原训练任务操作入口未就绪');
 const back = new URLSearchParams({task:taskId});
 for (const key of ['query','kind','status','cursor','previous']) {
  for (const value of query.getAll(key)) back.append(key,value);
 }
 const link = documentRoot.createElement('a');
 link.textContent = '返回新版训练任务';
 link.href = `/app/#/projects/${encodeURIComponent(project)}/training/tasks?${back}`;
 Object.assign(link.style,{position:'fixed',right:'24px',bottom:'24px',zIndex:'10001',background:'#fff',color:'#222',padding:'12px 18px',border:'1px solid #aaa',borderRadius:'8px'});
 documentRoot.body.append(link);
 windowRoot.history.replaceState(null,'',windowRoot.location.pathname);
 return owner.call(windowRoot,taskId);
}
export async function resumeVueHandoff({state,navigate,request,windowRoot=window,documentRoot=document}){
 const query=new URLSearchParams(windowRoot.location.search);
 if(query.get('spa_handoff')!=='1')return;
 const versionActions=new Set(['conversion','delivery','report','lineage','evaluation','delete-version','rollback','download']);
 const actions=new Set(['','train','algorithm-report','delete-algorithm',...versionActions]);
 let algorithm;
 const project=query.get('project_id'),page=query.get('page'),algorithmId=query.get('algorithm_id')||'',versionId=query.get('version_id')||'',action=query.get('action')||'';
 const expectedEvaluation=action==='evaluation' ? query.get('expected_evaluation_id') : '';
 if(project&&state.project?.id===project&&Object.hasOwn(materialPages,action))
  return resumeMaterials({project,action,query,state,navigate,request,windowRoot,documentRoot});
 if(project&&state.project?.id===project&&['task-stop','task-detail','task-report'].includes(action))return resumeTrainingTask({project,action,query,state,navigate,request,windowRoot,documentRoot});
 if(!project||state.project?.id!==project||!pages.has(page)||!actions.has(action))throw new Error('新版入口的项目或页面身份不匹配，未执行操作');
 if(action&&(!algorithmId||page!=='算法列表'||(versionActions.has(action)&&!versionId)))throw new Error('版本操作身份不完整');
 async function readAlgorithm(){
  const result=await request(`/api/v12/projects/${encodeURIComponent(project)}/algorithms/${encodeURIComponent(algorithmId)}`);
  if(result.algorithm?.id!==algorithmId||(versionId&&!result.algorithm.versions?.some(row=>row.id===versionId)))throw new Error('原算法或版本已不存在');
  if(state.project?.id!==project)throw new Error('项目已切换，未执行操作');
  if(expectedEvaluation&&result.algorithm.versions.find(row=>row.id===versionId)?.evaluation?.evaluation_id!==expectedEvaluation)throw new Error('冻结评测已变化，请返回重新读取报告');
  algorithm=result.algorithm;
  state.algorithms=(state.algorithms||[]).filter(row=>row.id!==algorithmId).concat([result.algorithm]);
 }
 if(algorithmId&&!expectedEvaluation)await readAlgorithm();
 const external=String(algorithm?.source_type||'').toUpperCase()==='EXTERNAL';
 const changLian=external&&String(algorithm?.provider_type||'').toUpperCase()==='CHANG_LIAN';
 const version=algorithm?.versions?.find(row=>row.id===versionId);
 if((action==='delete-algorithm'&&external)||(['delete-version','rollback'].includes(action)&&changLian))throw new Error('外部算法禁止此删除或回退入口');
 if(action==='rollback'&&(!algorithm?.current_version_id||!algorithm.versions?.some(row=>row.id===algorithm.current_version_id)||algorithm.current_version_id===versionId))throw new Error('当前版本或回退目标无效');
 if(action==='delivery'&&algorithm?.external_deletion_status&&algorithm.external_deletion_status!=='NORMAL')throw new Error('外部算法状态待核实或正在清理，新发布暂缓');
 if(action==='download'&&!String(version?.stored_path||'').trim())throw new Error('该版本没有可下载模型');
 if(state.project?.id!==project)throw new Error('项目已切换，未执行操作');
 await navigate(page);
 if(expectedEvaluation)await readAlgorithm();
 if(state.project?.id!==project||state.page!==page)throw new Error('原业务页未就绪，未执行操作');
 const link=documentRoot.createElement('a');
 link.textContent='返回新版算法库';
 const path=`/projects/${encodeURIComponent(project)}/algorithms`;
 const back=new URLSearchParams();
 const [returnPath,returnQuery]=(query.get('return_to')||'').split('?',2);
 if(algorithmId)back.set('algorithm',algorithmId);
 if(action==='report'||action==='evaluation'){
  back.set('version',versionId);
  if(returnPath===path){
   const original=new URLSearchParams(returnQuery);
   for(const key of ['query','algorithm_type','industry','source_type','training_state','category_ids','sort','page','version_page']){
    const value=original.get(key);
    if(value)back.set(key,value);
   }
  }
 }
 link.href=`/app/#${path}${back.size?'?'+back:''}`;
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
