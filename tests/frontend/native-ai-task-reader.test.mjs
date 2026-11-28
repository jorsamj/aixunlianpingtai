import test from 'node:test';import assert from 'node:assert/strict';
import {aiTaskReaderApi} from '../../frontend/src/api/ai-task-reader.ts';

const page=(items=[],extra={})=>({ok:true,project_id:'p',items,next_cursor:null,statistics_indexing:false,...extra});
test('native AI task reader reuses the v60 original GET with reader_view, status and cursor and forwards cancellation',async()=>{
 const calls=[];const api=aiTaskReaderApi({projectId:'p',get:async(url,options)=>{calls.push({url,options});return page([{id:'t',project_id:'p',status:'AWAITING_CONFIRMATION',counts:{failed:2}}])}});
 const signal=new AbortController().signal;
 const result=await api.tasks('FAILED','next-cursor',signal);
 assert.equal(result.items[0].id,'t');
 const parsed=new URL(calls[0].url,'https://local');
 assert.equal(parsed.pathname,'/api/v60/projects/p/annotation-tasks');
 assert.equal(parsed.searchParams.get('reader_view'),'true');
 assert.equal(parsed.searchParams.get('limit'),'20');
 assert.equal(parsed.searchParams.get('status'),'FAILED');
 assert.equal(parsed.searchParams.get('cursor'),'next-cursor');
 assert.equal(calls[0].options.signal,signal);
 const first=await aiTaskReaderApi({projectId:'p',get:async(url)=>{calls.push({url});return page()}}).tasks('','',signal);
 assert.equal(first.next_cursor,null);
 assert.equal(new URL(calls[1].url,'https://local').searchParams.get('status'),null);
 assert.equal(new URL(calls[1].url,'https://local').searchParams.get('cursor'),null);
});
test('native AI task reader refuses cross-project rows, invalid cursors and oversized reads',async()=>{
 const signal=new AbortController().signal;
 await assert.rejects(()=>aiTaskReaderApi({projectId:'p',get:async()=>page([{id:'t',project_id:'q'}])}).tasks('','',signal),/分页身份不一致/);
 await assert.rejects(()=>aiTaskReaderApi({projectId:'p',get:async()=>({...page(),project_id:'q'})}).tasks('','',signal),/响应项目身份不一致/);
 await assert.rejects(()=>aiTaskReaderApi({projectId:'p',get:async()=>({...page(),ok:false})}).tasks('','',signal),/响应项目身份不一致/);
 await assert.rejects(()=>aiTaskReaderApi({projectId:'p',get:async()=>page([],{next_cursor:42})}).tasks('','',signal),/分页游标无效/);
 const oversized=aiTaskReaderApi({projectId:'p',get:async()=>page()});
 await assert.rejects(()=>oversized.tasks('','',signal,21),/超出边界/);
 await assert.rejects(()=>oversized.tasks('','',signal,0),/超出边界/);
});
