import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const start=source.indexOf('function aiCandidateEditImage60()');
const block=source.slice(start,source.indexOf('window.completeAiReview60=async mode=>',start));
test('candidate editor reuses the one official kernel and retires all custom pointer geometry',()=>{
  assert.match(block,/PlatformCore\?\.createAnnotoriousEditor/);
  assert.match(block,/editor\?\.flush/);
  assert.doesNotMatch(block,/paintAiCandidateBox60|ai66-edit-box|ai66-edit-draw|addEventListener\('pointer/);
  assert.match(block,/destroyAiCandidateEditor60/);
  assert.match(block,/state\.ai60Edit===edit/);
  assert.doesNotMatch(block,/saveAnn\(|\/annotations\//);
});
function harness(extra={}){
  const original={label:'person',class_id:1,x1:10,y1:10,x2:40,y2:40,confidence:.7,source_task_id:'ai-task'};
  const item={image_id:'i',filename:'i.png',width:100,height:100,url:'i.png',boxes:[original]};
  const state={ai60Review:{id:'review',seen:new Map([['i',item]]),edits:new Map(),decisions:new Map(),ownerPage:'ops'},page:'ops',labels:[{code:'person',class_id:1}]};
  let ids=0,closed=0;const errors=[];
  const context={state,document:{querySelector:()=>({}),getElementById:()=>null,querySelectorAll:()=>[]},window:{BrowserCapabilityRuntime:{createClientId:()=>`new-${++ids}`}},imageById:()=>item,aiReviewLabels60:()=>state.labels,esc:String,toast:error=>errors.push(error),modal:()=>{},closeModal:()=>closed++,renderReviewPage:()=>{},AbortController,Set,Map,JSON,Number,String,Promise};
  Object.assign(context,extra);context.window.window=context.window;vm.runInNewContext(block,context);
  return {state,window:context.window,item,original,errors,get closed(){return closed;}};
}
test('candidate opening assigns missing IDs once, preserves metadata and never changes review until explicit save',()=>{
  const h=harness();h.window.editAiCandidate60('i');const edit=h.state.ai60Edit;
  assert.equal(edit.boxes[0].id,'new-1');assert.equal(h.original.id,undefined);assert.equal(h.state.ai60Review.edits.size,0);
  h.window.updateAiCandidateBox60(0,'x1','12');assert.equal(edit.boxes[0].x1,12);assert.equal(h.item.boxes[0].x1,10);
  h.window.saveAiCandidateEdit60();assert.equal(h.state.ai60Review.edits.get('i')[0].source_task_id,'ai-task');assert.equal(h.state.ai60Review.edits.get('i')[0].id,'new-1');assert.equal(h.state.ai60Review.edits.get('i')[0].source,'ai_candidate_reviewed');assert.equal(h.closed,0,'saving candidate changes must not close the review workspace');assert.equal(h.state.ai60Edit,null);
});
test('candidate coordinates reject out of image and invalid rectangles without mutating draft',()=>{
  const h=harness();h.window.editAiCandidate60('i');const edit=h.state.ai60Edit;
  h.window.updateAiCandidateBox60(0,'x2','101');assert.equal(edit.boxes[0].x2,40);
  h.window.updateAiCandidateBox60(0,'x1','50');assert.equal(edit.boxes[0].x1,10);
  h.window.updateAiCandidateBox60(0,'y1','NaN');assert.equal(edit.boxes[0].y1,10);assert.equal(h.errors.length,3);assert.equal(h.state.ai60Review.edits.size,0);
});
test('candidate cancellation fences late factory completion and discards draft changes',async()=>{
  let resolveFactory,destroyed=0;const root={isConnected:true,querySelectorAll:()=>[],querySelector:()=>null};
  const image={complete:true,naturalWidth:100,naturalHeight:100,getAttribute:()=> 'i.png',setAttribute:()=>{}};
  const document={querySelector:selector=>selector.includes('[data-')?null:root,getElementById:id=>id==='ai60EditImg'?image:id==='ai60EditViewport'||id==='ai60EditStage'?{}:null,querySelectorAll:()=>[]};
  const h=harness({document,pid:()=> 'p'});h.window.PlatformCore={createAnnotoriousEditor:()=>new Promise(resolve=>resolveFactory=resolve)};
  h.window.editAiCandidate60('i');const edit=h.state.ai60Edit,pending=edit.pending;
  h.window.updateAiCandidateBox60(0,'x1','12');h.window.destroyAiCandidateEditor60();
  resolveFactory({destroy:()=>destroyed++});await pending;
  assert.equal(destroyed,1);assert.equal(h.state.ai60Review.edits.size,0);assert.equal(h.item.boxes[0].x1,10);assert.equal(edit.closed,true);
});
test('candidate draft has one history and undo/redo never write reviewed decisions',()=>{
  const h=harness();h.window.editAiCandidate60('i');h.window.updateAiCandidateBox60(0,'x1','12');h.window.updateAiCandidateBox60(0,'x1','14');
  h.window.undoAiCandidate60();assert.equal(h.state.ai60Edit.boxes[0].x1,12);h.window.undoAiCandidate60();assert.equal(h.state.ai60Edit.boxes[0].x1,10);
  h.window.redoAiCandidate60();h.window.redoAiCandidate60();assert.equal(h.state.ai60Edit.boxes[0].x1,14);assert.equal(h.state.ai60Review.edits.size,0);assert.equal(h.state.ai60Review.decisions.size,0);
});
test('hidden candidate geometry inputs and object selection cannot bypass kernel visibility',()=>{
  const h=harness();h.window.editAiCandidate60('i');const edit=h.state.ai60Edit;edit.activeBox=null;
  edit.editor={snapshot:()=>({visible:false,filteredCodes:null}),select:()=>false};
  h.window.updateAiCandidateBox60(0,'x1','12');h.window.selectAiCandidateBox60(0);
  assert.equal(edit.boxes[0].x1,10);assert.equal(edit.activeBox,null);assert.equal(edit.history.length,0);
});
