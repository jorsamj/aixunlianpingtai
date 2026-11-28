import test from 'node:test';import assert from 'node:assert/strict';
import {aiTasksApi} from '../../frontend/src/api/ai-tasks.ts';
test('annotation reader preserves indexing state without fake task total and uses original GET owner',async()=>{let path;const api=aiTasksApi({projectId:'p',get:async url=>{path=url;return {ok:true,project_id:'p',indexing:true,indexed:2,total:8,remaining:6,items:[],next_cursor:null}}});const value=await api.list('model','FAILED','',new AbortController().signal);assert.equal(value.indexing,true);assert.equal(value.remaining,6);assert.ok(path.startsWith('/api/v60/projects/p/annotation-tasks?'));assert.equal(new URL(path,'https://local').searchParams.get('reader_view'),'true')});
test('annotation reader rejects cross-task failure rows and cross-project detail',async()=>{const api=aiTasksApi({projectId:'p',get:async()=>({ok:true,project_id:'p',task_id:'other',items:[]})});await assert.rejects(()=>api.failures('t','0',new AbortController().signal),/身份/);const foreign=aiTasksApi({projectId:'p',get:async()=>({ok:true,project_id:'q',task:{id:'t'}})});await assert.rejects(()=>foreign.detail('t',new AbortController().signal),/身份/)});

import {trainingReaderApi} from '../../frontend/src/api/training-reader.ts';
test('recent task readers request five server rows, retain default twenty and refuse oversized reads',async()=>{
 const calls=[],context={projectId:'p',get:async url=>{calls.push(url);return {ok:true,project_id:'p',items:[],next_cursor:null}}},signal=new AbortController().signal;
 const ai=aiTasksApi(context),training=trainingReaderApi(context);
 await ai.list('','','',signal,5);await training.tasks({},signal,5);await ai.list('','','',signal);await training.tasks({},signal);
 assert.deepEqual(calls.map(url=>new URL(url,'https://local').searchParams.get('limit')),['5','5','20','20']);
 await assert.rejects(()=>ai.list('','','',signal,21),/超出边界/);await assert.rejects(()=>training.tasks({},signal,0),/超出边界/);assert.equal(calls.length,4);
});
