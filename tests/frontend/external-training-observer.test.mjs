import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {externalAlgorithmTrainingReadiness, externalAnalysisOptions, isExternalAlgorithm} from '../../static/modules/external-algorithm-platform.js';

const source=readFileSync(new URL('../../static/modules/external-algorithm-platform.js',import.meta.url),'utf8');
const start=source.indexOf('  function decorateTrainingAnalysisSelector() {');
const end=source.indexOf('\n  function scheduleRender()',start);
assert.ok(start>=0&&end>start,'execute the actual external training modal decorator');

function harness(){
  const nodes=[];
  const form={
    querySelector(selector){
      if(selector==='[data-external-training-blocked]')return nodes.find(node=>Object.hasOwn(node.dataset,'externalTrainingBlocked'))||null;
      if(selector==='[data-external-analysis-selector]')return nodes.find(node=>Object.hasOwn(node.dataset,'externalAnalysisSelector'))||null;
      return null;
    },
    prepend(node){nodes.unshift(node);},
  };
  const document={querySelector:selector=>selector==='.train429-create'?form:null,
    createElement:tag=>({tag,dataset:{},textContent:'',className:'',remove(){const index=nodes.indexOf(this);if(index>=0)nodes.splice(index,1);}})};
  const algorithm={id:'external-1',source_type:'EXTERNAL',provider_type:'CHANG_LIAN',external_active:false,
    external_master_data_digest:'digest-current',external_analyses:[{analysis_id:'visual-1',analysis_type:'1',status:'1'}]};
  const state={trainingDraft:{algorithmId:algorithm.id},algorithms:[algorithm],externalAnalysisSelection:{}};
  let readinessUpdates=0;
  const context={document,state:()=>state,isExternalAlgorithm,externalAlgorithmTrainingReadiness,externalAnalysisOptions,
    currentMasterDataDigest:()=> 'digest-current',
    window:{TrainingSubmitRuntime:{updateReadiness(){readinessUpdates++;}}}};
  vm.runInNewContext(source.slice(start,end),context);
  return {decorate:context.decorateTrainingAnalysisSelector,nodes,state,algorithm,
    readinessUpdates:()=>readinessUpdates};
}

test('a blocked external training dialog does not self-trigger unbounded warning inserts',()=>{
  const ui=harness();
  for(let index=0;index<30;index++)ui.decorate();
  assert.equal(ui.nodes.length,1,'a body MutationObserver may call this decorator repeatedly');
  assert.equal(ui.nodes[0].dataset.externalTrainingBlocked,'external-inactive');
  assert.equal(ui.readinessUpdates(),1,'stable warning should not recompute submit readiness per DOM mutation');

  ui.algorithm.external_active=true;
  ui.decorate();
  assert.equal(ui.nodes.length,0,'clearing an external blocker removes its obsolete warning');
  assert.equal(ui.readinessUpdates(),2);
  for(let index=0;index<10;index++)ui.decorate();
  assert.equal(ui.nodes.length,0);

  ui.algorithm.external_active=false;
  for(let index=0;index<10;index++)ui.decorate();
  assert.equal(ui.nodes.length,1,'a newly blocked session still shows exactly one current warning');
  assert.equal(ui.readinessUpdates(),3);

  ui.state.trainingDraft.algorithmId='local-1';
  ui.decorate();
  assert.equal(ui.nodes.length,0,'switching to a local algorithm clears the old external warning');
  assert.equal(ui.readinessUpdates(),4);
  ui.decorate();
  assert.equal(ui.readinessUpdates(),4,'the settled local dialog does not mutate itself');
});
