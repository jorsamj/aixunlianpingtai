import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {annotationReviewView} from '../../static/modules/annotation-workbench.js';

function harness() {
  const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
  const nodes=Object.fromEntries(['ann420ReviewedLabels','ann420PendingLabels','ann420PendingReviewCount','ann420SaveReview'].map(id=>[id,{innerHTML:'',textContent:''}]));
  const state={activeImage:{id:'i1',content_sha256:'sha'},labels:[{code:'fire'},{code:'smoke'}],ann:{version:1,annotation_state:'annotated',annotation_scope:['fire','smoke'],boxes:[]},annDirty:true,annotationReviewSelected420:new Set(['fire'])};
  const window={};let project='p1';
  vm.runInNewContext(source.slice(source.indexOf('  function annotationReviewRequired420()'),source.indexOf('\n  function updateShell()',source.indexOf('  function annotationReviewRequired420()'))),{
    state,window,pid:()=>project,document:{getElementById:id=>nodes[id]},workbenchApi:()=>({annotationReviewView}),esc:String,Set,JSON,String,toast(){},
  });
  return {state,window,nodes,setProject:value=>project=value};
}

test('dirty empty GT exposes every required class unchecked and clears old selections once',()=>{
  const h=harness();h.window.renderAnnotationReviewScope420();
  assert.equal(h.state.annotationReviewSelected420.size,0);
  assert.match(h.nodes.ann420PendingLabels.innerHTML,/fire/);assert.match(h.nodes.ann420PendingLabels.innerHTML,/smoke/);
  assert.doesNotMatch(h.nodes.ann420PendingLabels.innerHTML,/checked onchange/);
  assert.doesNotMatch(h.nodes.ann420ReviewedLabels.innerHTML,/<span>fire<\/span>/);
  h.window.toggleAnnotationReview420('smoke',true);h.window.renderAnnotationReviewScope420();
  assert.deepEqual([...h.state.annotationReviewSelected420],['smoke']);
  assert.match(h.nodes.ann420PendingLabels.innerHTML,/checked onchange="toggleAnnotationReview420\('smoke'/);
});

test('explicit select-all on cleared GT selects all current classes without inheriting old proof',()=>{
  const h=harness();h.window.selectAllAnnotationReview420();
  assert.deepEqual([...h.state.annotationReviewSelected420],['fire','smoke']);
});

test('ordinary clean confirmed negative keeps its reviewed scope and selections unchanged',()=>{
  const h=harness();h.state.annDirty=false;h.state.ann.annotation_state='confirmed_empty';h.state.ann.annotation_scope=['fire'];h.state.annotationReviewSelected420=new Set(['smoke']);
  h.window.renderAnnotationReviewScope420();h.window.renderAnnotationReviewScope420();
  assert.deepEqual([...h.state.annotationReviewSelected420],['smoke']);
  assert.match(h.nodes.ann420ReviewedLabels.innerHTML,/<span>fire<\/span>/);
});

for(const change of ['image','annotation','project','sha'])test(`fresh dirty-empty review does not carry selections across ${change}`,()=>{
  const h=harness();h.window.renderAnnotationReviewScope420();h.window.toggleAnnotationReview420('smoke',true);
  if(change==='image')h.state.activeImage={id:'i2',content_sha256:'sha'};
  if(change==='annotation')h.state.ann={...h.state.ann,version:2};
  if(change==='project')h.setProject('p2');
  if(change==='sha')h.state.activeImage.content_sha256='other';
  h.window.renderAnnotationReviewScope420();assert.equal(h.state.annotationReviewSelected420.size,0);
});
