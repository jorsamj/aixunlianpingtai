import test from 'node:test';
import assert from 'node:assert/strict';
import {resumeVueHandoff} from '../../static/modules/vue-app-handoff.js';
function context(project='p',action='conversion'){
 const calls=[],links=[],state={project:{id:project},page:'总览',algorithms:[]};
 const windowRoot={location:{pathname:'/',search:'?'+new URLSearchParams({spa_handoff:'1',project_id:'p',page:'算法列表',algorithm_id:'a',version_id:'v',action})},history:{replaceState(){calls.push('consume')}},openVersionConvert428(a,v){calls.push([a,v])}};
 return {calls,links,state,windowRoot,documentRoot:{createElement:()=>({style:{}}),body:{append:link=>links.push(link)}},
  navigate:async page=>{calls.push(page);state.page=page},request:async()=>({ok:true,algorithm:{id:'a',versions:[{id:'v'}]}})};
}
test('legacy handoff keeps exact project/version and consumes the action once on the old page',async()=>{
 const c=context();await resumeVueHandoff(c);assert.deepEqual(c.calls,['算法列表','consume',['a','v']]);assert.equal(c.links[0].href,'/app/#/projects/p/algorithms?algorithm=a');
});
test('legacy handoff refuses a foreign project before loading data or opening a form',async()=>{
 const c=context('other');c.request=()=>assert.fail('foreign read');await assert.rejects(resumeVueHandoff(c),/身份不匹配/);assert.deepEqual(c.calls,[]);
});
test('legacy handoff refuses a missing selected version',async()=>{
 const c=context();c.request=async()=>({algorithm:{id:'a',versions:[]}});await assert.rejects(resumeVueHandoff(c),/版本已不存在/);assert.deepEqual(c.calls,[]);
});

for(const [action,owner,version] of [['report','openVersionReport429',true],['lineage','openVersionLineage429',true],['evaluation','openVersionEvaluation429',true],['algorithm-report','algorithmReport429',false],['delete-algorithm','delAlgorithm',false],['delete-version','delVersion',true],['rollback','openVersionRollback',true]]){
 test(`handoff dispatches ${action} to its existing owner`,async()=>{
  const c=context('p',action);c.request=async()=>({algorithm:{id:'a',current_version_id:'current',versions:[{id:'v'},{id:'current'}]}});
  c.windowRoot[owner]=(...args)=>c.calls.push(args);await resumeVueHandoff(c);
  assert.deepEqual(c.calls,['算法列表','consume',version?['a','v']:['a']]);
 });
}
for(const action of ['delete-algorithm','delete-version','rollback']){
 test(`${action} refuses external identity before navigation`,async()=>{
  const c=context('p',action);c.request=async()=>({algorithm:{id:'a',source_type:'EXTERNAL',provider_type:'CHANG_LIAN',versions:[{id:'v'}]}});
  await assert.rejects(resumeVueHandoff(c),/外部算法/);assert.deepEqual(c.calls,[]);
 });
}
for(const current of [undefined,'v','missing']){
 test(`rollback refuses invalid current ${current}`,async()=>{
  const c=context('p','rollback');c.request=async()=>({algorithm:{id:'a',current_version_id:current,versions:[{id:'v'}]}});
  await assert.rejects(resumeVueHandoff(c),/回退目标无效/);assert.deepEqual(c.calls,[]);
 });
}
test('handoff rejects foreign algorithm identity',async()=>{
 const c=context('p','report');c.request=async()=>({algorithm:{id:'foreign',versions:[{id:'v'}]}});
 await assert.rejects(resumeVueHandoff(c),/版本已不存在/);assert.deepEqual(c.calls,[]);
});
test('download uses only the validated scoped endpoint',async()=>{
 const c=context('p','download');c.request=async()=>({algorithm:{id:'a',versions:[{id:'v',stored_path:'model.pt'}]}});c.windowRoot.location.assign=url=>c.calls.push(url);
 await resumeVueHandoff(c);assert.equal(c.calls.at(-1),'/api/v12/projects/p/algorithms/a/versions/v/download');
});

for(const action of ['delete-version','rollback'])test(`other external provider permits ${action}`,async()=>{
 const c=context('p',action);c.request=async()=>({algorithm:{id:'a',source_type:'EXTERNAL',provider_type:'OTHER',current_version_id:'current',versions:[{id:'v'},{id:'current'}]}});
 c.windowRoot[action==='rollback'?'openVersionRollback':'delVersion']=(...args)=>c.calls.push(args);await resumeVueHandoff(c);assert.deepEqual(c.calls.at(-1),['a','v']);
});
test('delivery refuses pending external deletion',async()=>{
 const c=context('p','delivery');c.request=async()=>({algorithm:{id:'a',external_deletion_status:'PENDING',versions:[{id:'v'}]}});await assert.rejects(resumeVueHandoff(c),/新发布暂缓/);assert.deepEqual(c.calls,[]);
});
test('download refuses missing stored artifact',async()=>{
 const c=context('p','download');await assert.rejects(resumeVueHandoff(c),/没有可下载模型/);assert.deepEqual(c.calls,[]);
});
test('report fails explicitly when legacy owner is unavailable',async()=>{
 const c=context('p','report');await assert.rejects(resumeVueHandoff(c),/操作入口未就绪/);
});

test('evaluation handoff checks the frozen evidence identity after entering the old page',async()=>{
  const c=context('p','evaluation');
  c.windowRoot.location.search+='&expected_evaluation_id=expected';
  c.windowRoot.openVersionEvaluation429=(...args)=>c.calls.push(args);
  c.request=async()=>({algorithm:{id:'a',versions:[{id:'v',evaluation:{evaluation_id:'different'}}]}});
  await assert.rejects(resumeVueHandoff(c),/冻结评测已变化/);
  assert.deepEqual(c.calls,['算法列表']);
  c.request=async()=>({algorithm:{id:'a',versions:[{id:'v',evaluation:{evaluation_id:'expected'}}]}});
  await resumeVueHandoff(c);
  assert.deepEqual(c.calls.slice(-3),['算法列表','consume',['a','v']]);
});

test('evaluation back link restores same-project filters and the verified version without a handoff action',async()=>{
  for(const source of ['/projects/p/algorithms?query=fire&sort=name&version_page=2&algorithm=other&version=wrong&action=rollback',
    '/projects/other/algorithms?query=foreign','https://example.test/projects/p/algorithms?query=external']){
    const c=context('p','evaluation');
    c.windowRoot.location.search+='&return_to='+encodeURIComponent(source);
    c.windowRoot.openVersionEvaluation429=(...args)=>c.calls.push(args);
    await resumeVueHandoff(c);
    const back=new URL(c.links[0].href,'https://app.example.test');
    assert.equal(back.pathname,'/app/');
    assert.match(back.hash,/^#\/projects\/p\/algorithms\?algorithm=a&version=v/);
    assert.equal(back.hash.includes('query=fire&sort=name&version_page=2'),source.startsWith('/projects/p/'));
    assert.doesNotMatch(back.hash,/rollback|foreign|external|spa_handoff/);
    assert.deepEqual(c.calls,['算法列表','consume',['a','v']]);
  }
});


test('training task handoff preserves identity and invokes only the original stop, recovery and report owners', async () => {
 for (const [action,owner] of [['task-stop','stopTrain428'],['task-detail','openTrainingRecoveryDetail'],['task-report','openJobReport429']]) {
  const c=context('p',action);
  c.windowRoot.location.search='?spa_handoff=1&project_id=p&page='+encodeURIComponent('训练任务')+'&task_id=t&status=QUEUED&cursor=next&action='+action;
  c.request=async url=>{
   assert.equal(url,'/api/v62/projects/p/tasks/t?reader_view=true');
   return {ok:true,project_id:'p',task:{task_id:'t',project_id:'p',kind:'TRAINING',status:'WAITING_RESOURCE'}};
  };
  c.windowRoot[owner]=id=>c.calls.push(id);
  await resumeVueHandoff(c);
  assert.deepEqual(c.calls,['训练任务','consume','t']);
  assert.equal(c.links[0].href,'/app/#/projects/p/training/tasks?task=t&status=QUEUED&cursor=next');
  c.calls.length=0;
  c.request=async()=>({ok:true,project_id:'p',task:{task_id:'t',project_id:'other',kind:'TRAINING',status:'QUEUED'}});
  await assert.rejects(resumeVueHandoff(c), /身份不一致/);
  assert.deepEqual(c.calls,['训练任务']);
  if(action==='task-stop'){
   c.request=async()=>({ok:true,project_id:'p',task:{task_id:'t',project_id:'p',kind:'TRAINING',status:'CANCEL_REQUESTED'}});
   await assert.rejects(resumeVueHandoff(c), /不允许再次停止/);
   assert.deepEqual(c.calls,['训练任务','训练任务']);
  }
 }
});

test('material bridge verifies annotation identity and preserves only the browse context',async()=>{
 const c=context('p','material-annotate');
 const query=new URLSearchParams({spa_handoff:'1',project_id:'p',page:'数据集',action:'material-annotate',material_id:'m1',
  return_query:'page=2&layout=list&label=smoke&project_id=other&action=material-ai'});
 c.windowRoot.location.search='?'+query;
 c.windowRoot.openAnnotation=id=>c.calls.push(id);
 c.request=async url=>{
  assert.equal(url,'/api/projects/p/annotations/m1?reader_view=true');
  return {ok:true,project_id:'other',image:{id:'m1'}};
 };
 await assert.rejects(resumeVueHandoff(c),/素材身份不一致/);
 assert.deepEqual(c.calls,['数据集']);
 c.request=async()=>({ok:true,project_id:'p',image:{id:'m1'}});
 await resumeVueHandoff(c);
 assert.deepEqual(c.calls.slice(-3),['数据集','consume','m1']);
 assert.equal(c.links[0].href,'/app/#/projects/p/materials?label=smoke&page=2&layout=list&detail=m1');
});

test('material links enter the original owner after loading the scoped page',async()=>{
 const cases=[
  ['material-upload','数据集','ImageUppyView','open'],['material-zip','数据集','openUppyZipUpload'],
  ['material-manual','数据集','setData412Tab'],['material-negative','数据集','NegativePoolRuntime','open'],
  ['material-ai','自动标注及清洗','createAiLabel429'],['material-clean','自动标注及清洗','createClean427'],
  ['material-integrity','数据集','openMaterialIntegrityAudit47'],
 ];
 for(const [action,page,owner,method] of cases){
  const c=context('p',action);
  c.windowRoot.location.search='?'+new URLSearchParams({spa_handoff:'1',project_id:'p',page,action});
  const run=()=>{c.calls.push(owner)};
  c.windowRoot[owner]=method?{[method]:run}:run;
  c.windowRoot.openDataUpload426=()=>assert.fail('unexpected upload fallback');
  c.request=()=>assert.fail('unexpected request or mutation');
  await resumeVueHandoff(c);
  assert.deepEqual(c.calls,[page,'consume',owner]);
 }
});

test('material handoff rejects missing owners and keeps navigation-only entries usable',async()=>{
 for(const [action,page,error] of [
  ['material-zip','数据集',/ZIP 导入入口未就绪/],
  ['material-negative','数据集',/负样本池入口未就绪/],
  ['material-manage','数据集',null],
  ['material-labels','标签管理',null],
 ]){
  const c=context('p',action);
  c.windowRoot.location.search='?'+new URLSearchParams({spa_handoff:'1',project_id:'p',page,action});
  if(error)await assert.rejects(resumeVueHandoff(c),error);
  else await resumeVueHandoff(c);
  assert.deepEqual(c.calls,[page,'consume']);
  assert.equal(c.links[0].href,'/app/#/projects/p/materials');
 }
});

test('material handoff rejects a different server-owned project before navigation',async()=>{
 const c=context('other','material-annotate');
 c.windowRoot.location.search='?'+new URLSearchParams({spa_handoff:'1',project_id:'p',page:'数据集',action:'material-annotate',material_id:'m1'});
 c.request=()=>assert.fail('must not read the material');
 c.windowRoot.openAnnotation=()=>assert.fail('must not open annotation');
 await assert.rejects(resumeVueHandoff(c),/当前项目与请求项目不一致/);
 assert.deepEqual(c.calls,[]);
});
