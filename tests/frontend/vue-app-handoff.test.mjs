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


test('training task handoff preserves identity and invokes only the original stop and recovery owners', async () => {
 for (const [action,owner] of [['task-stop','stopTrain428'],['task-detail','openTrainingRecoveryDetail']]) {
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
