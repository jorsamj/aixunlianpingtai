import test from 'node:test';
import assert from 'node:assert/strict';
import {installTrainingTaskRuntime} from '../../static/modules/training-task-runtime.js';

test('fresh task history invalidates the snapshot so algorithm success aggregation revalidates on return',async()=>{
 const state={page:'训练任务',project:{id:'p'},jobs:[{id:'j',task_status:'RUNNING'}],__coreSnapshotGeneratedAt:Date.now()};
 globalThis.window={fetch:async()=>({ok:true,json:async()=>[{id:'j',task_status:'SUCCEEDED',result_ref:'result.json'}]})};
 const runtime=installTrainingTaskRuntime({getState:()=>state,projectId:()=>state.project.id});
 await runtime.refresh({render:false,force:true});
 assert.equal(state.__coreSnapshotGeneratedAt,0);
 assert.equal(state.jobs[0].task_status,'SUCCEEDED');
 runtime.destroy();delete globalThis.window;
});
