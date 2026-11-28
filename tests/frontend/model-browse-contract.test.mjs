import test from 'node:test';
import assert from 'node:assert/strict';
import {modelBrowseApi,shownValue,browseError} from '../../frontend/src/api/model-browse.ts';

test('summary uses original GET owner and mismatched project or version cannot populate current view',async()=>{
 const calls=[];
 const context={projectId:'p',get:async url=>{calls.push(url);return {ok:true,project_id:'other',items:[],total:0,page:1,page_size:20}}};
 await assert.rejects(()=>modelBrowseApi(context).algorithms({page:1,query:''},new AbortController().signal),/身份/);
 assert.ok(calls[0].includes('summary_only=true')&&calls[0].includes('asset_view=true'));
 const history={projectId:'p',get:async()=>({ok:true,project_id:'p',algorithm_id:'a',version_id:'wrong',items:[],total:0,page:1,page_size:20})};
 await assert.rejects(()=>modelBrowseApi(history).history('a','v',{page:1},new AbortController().signal),/身份/);
});
test('absent metric stays absent while a measured zero is retained',()=>{
 assert.equal(shownValue(null),'未提供');assert.equal(shownValue(undefined),'未提供');assert.equal(shownValue(''),'未提供');assert.equal(shownValue(false),'未提供');assert.equal(shownValue(0),'0');assert.equal(shownValue(.72),'0.72');
});

test('read errors redact quoted credentials and UNC paths',()=>{
 const result=browseError(new Error(String.raw`{"token":"SECRET_SENTINEL"} \\server\private\file`));
 assert.ok(!result.includes('SECRET_SENTINEL')&&!result.includes('server'));
});
