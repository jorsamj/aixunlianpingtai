import test from 'node:test';import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=path=>readFileSync(new URL('../../frontend/src/'+path,import.meta.url),'utf8');
const main=source('app/main.ts'),app=source('app/App.vue'),algorithms=source('app/Algorithms.vue'),review=source('app/AiReview.vue'),navigation=source('app/navigation.ts');

test('W13 native routes stay ahead of legacy/catch-all and keep every existing route name',()=>{
 const catchAll=main.indexOf("path:'/:pathMatch(.*)*'"),legacy=main.indexOf("name:'legacy'");
 assert.ok(catchAll>0&&legacy>0);
 const native=[['ai-tasks',"path:'/projects/:projectId/ai/tasks'"],['version-conversions',"path:'/projects/:projectId/algorithms/:algorithmId/versions/:versionId/conversions'"],['service-nodes-native',"path:'/projects/:projectId/nodes'"]];
 for(const [name,path] of native){
  assert.ok(main.includes(path),`route path missing: ${path}`);
  const at=main.indexOf("name:'"+name+"'");
  assert.ok(at>0&&at<catchAll,`route must be registered before catch-all: ${name}`);
  assert.ok(at<legacy,`route must be registered before the legacy handoff: ${name}`);
 }
 for(const name of ['algorithms','public-negative-pool','materials','material-upload','material-zip-import','upload-tasks','training-tasks','training-report','version-report','training-create','ai-review-native','legacy','not-found'])
  assert.ok(main.includes("name:'"+name+"'"),`existing route was dropped: ${name}`);
});

test('W13 entries are additive: old conversion/review entries and menu names stay',()=>{
 assert.ok(algorithms.includes("original(selected,'conversion',row.id)"),'old conversion workflow link must stay');
 assert.ok(algorithms.includes('转换 · 原流程'),'old conversion label must stay');
 assert.ok(algorithms.includes('转换记录（原生）'),'native conversion entry missing');
 assert.ok(algorithms.includes("name:'version-conversions'"),'native conversion route target missing');
 assert.ok(review.includes('返回原工作台'),'old AI workbench link must stay');
 assert.ok(review.includes('返回任务列表'),'native back-to-list link missing');
 assert.ok(review.includes("name:'ai-tasks'"),'native task-list route target missing');
 assert.ok(app.includes("route.name==='ai-tasks'")&&app.includes("route.name==='version-conversions'")&&app.includes("route.name==='service-nodes-native'"),'native page titles missing from shell');
 assert.ok(app.includes("if(page==='算法列表')return {name:'algorithms',params:project};"),'menu target mapping for the algorithm library changed');
 assert.ok(app.includes("if(page==='训练任务')return {name:'training-tasks',params:project};"),'menu target mapping for training tasks changed');
 assert.ok(navigation.includes("['算力与节点','服务节点']"),'service-node menu name/hierarchy changed');
 assert.ok(navigation.includes("['自动标注及清洗','自动标注及清洗']"),'AI annotation menu name/hierarchy changed');
});
