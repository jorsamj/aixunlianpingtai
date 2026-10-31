import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

test('startup snapshot has a deadline even if the network never settles, with cleanup',async()=>{
 const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
 const start=source.indexOf(' window.loadStartupSnapshot413=async function');
 const end=source.indexOf('\n window.__clInit=',start);
 const timers=new Map();let next=0,applied=false;
 const context={window:{},document:{getElementById:()=>null},paintBoot(){},apply(){applied=true},api:()=>new Promise(()=>{}),waitReady(){throw Error('must not wait for noncritical background initialization')},AbortController,Promise,Error,setTimeout:(fn,ms)=>{const id=++next;timers.set(id,{fn,ms});return id},clearTimeout:id=>timers.delete(id)};
 vm.runInNewContext(source.slice(start,end),context);
 const pending=context.window.loadStartupSnapshot413();
 assert.ok([...timers.values()].some(t=>t.ms===20000),'snapshot deadline is bounded');
 for(const t of [...timers.values()])if(t.ms===20000)t.fn();
 await assert.rejects(pending,/核心页面读取超时/);
 assert.equal(applied,false);assert.equal(timers.size,0);
});
