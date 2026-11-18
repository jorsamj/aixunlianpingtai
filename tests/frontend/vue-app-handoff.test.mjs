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
