import test from 'node:test';
import assert from 'node:assert/strict';
import {algorithmManagementApi} from '../../frontend/src/api/algorithm-management.ts';
test('original write is followed by authoritative basic GET, never version mutation',async()=>{
 const calls=[],packet={name:'本地',remark:'备注',industry:'安全',algorithm_type:'custom_python'};
 const api=algorithmManagementApi({projectId:'p',get:async url=>{calls.push(['GET',url]);return {ok:true,project_id:'p',algorithm:{id:'a',...packet,editable:true}}},writeAlgorithm:async(method,id,body)=>{calls.push([method,id,body]);return {ok:true,algorithm:{id:'a'}}}});
 assert.equal((await api.save('',packet,new AbortController().signal)).id,'a');
 assert.deepEqual(calls.map(row=>row[0]),['POST','GET']);assert.match(calls[1][1],/basic_only=true/);
});
test('unconfirmed read-back cannot be described as successful save',async()=>{
 const api=algorithmManagementApi({projectId:'p',writeAlgorithm:async()=>({ok:true,algorithm:{id:'a'}}),get:async()=>({ok:true,project_id:'q',algorithm:{id:'a'}})});
 await assert.rejects(()=>api.save('a',{name:'x',remark:'',industry:'',algorithm_type:''},new AbortController().signal),/身份|核验/);
});

test('readback403 after a committed write is not a rejected write',async()=>{
 const api=algorithmManagementApi({projectId:'p',writeAlgorithm:async()=>({ok:true,algorithm:{id:'a'}}),get:async()=>{throw Object.assign(new Error('denied'),{httpStatus:403})}});
 await assert.rejects(()=>api.save('',{name:'x',remark:'',industry:'',algorithm_type:''},new AbortController().signal),error=>error.httpStatus===403&&error.writeRejected!==true);
});
