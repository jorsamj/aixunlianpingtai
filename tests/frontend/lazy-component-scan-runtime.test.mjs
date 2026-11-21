import test from 'node:test';
import assert from 'node:assert/strict';
import {installComponentScanRuntime} from '../../static/modules/component-scan-runtime.js';

test('component scan installation restores sanitized cache without performing HTTP',()=>{
  const oldWindow=globalThis.window,oldStorage=globalThis.localStorage;
  let requests=0;
  try {
    globalThis.window={};
    globalThis.localStorage={
      getItem:()=>JSON.stringify({ts:Date.now(),scan:{id:'scan-1',status:'done',
        components:[{name:'Python',status:'ready'}],token:'secret',summary:{ready:1,total:1}}}),
      setItem:()=>{},
    };
    const state={};
    const runtime=installComponentScanRuntime({state,
      api:()=>{requests++;return Promise.resolve({})},safe:async promise=>promise,
      toast:()=>{},esc:String});
    assert.equal(requests,0);
    assert.equal(state.componentScan.id,'scan-1');
    assert.equal('token' in state.componentScan,false);
    assert.equal(typeof runtime.render,'function');
    assert.equal(typeof window.startComponentScanV40,'function');
    assert.equal(typeof window.pollComponentScanV40,'function');
  } finally {
    if(oldWindow===undefined)delete globalThis.window;else globalThis.window=oldWindow;
    if(oldStorage===undefined)delete globalThis.localStorage;else globalThis.localStorage=oldStorage;
  }
});
