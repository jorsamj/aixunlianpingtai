import test from 'node:test';
import assert from 'node:assert/strict';
import {createAnnotoriousEditor,loadAnnotorious} from '../../static/modules/annotorious-editor.js';

class Node extends EventTarget {
  style = {}; dataset = {}; scrollLeft = 0; scrollTop = 0;
  clientWidth = 500; clientHeight = 400; naturalWidth = 1000; naturalHeight = 800;
  src = 'test.jpg'; complete = true; ownerDocument;
  closest() { return null; }
  getBoundingClientRect() { return {left:0,top:0,width:500,height:400}; }
}
const box = (id, label='person') => ({id,label,class_id:label==='person'?1:2,x1:10,y1:20,x2:50,y2:80,source:'ai_confirmed',source_task_id:'task',confidence:.8});
async function setup(extra={}) {
  const doc = new Node(), image = new Node(), viewport = new Node(), world = new Node();
  image.ownerDocument = doc;
  let boxes=[box('a'),box('b','car')], selected=null;
  const listeners=new Map(), commits=[], calls=[], errors=[];
  let annotations=[],officialSelected=null;
  const anno={on:(key,fn)=>listeners.set(key,fn),off:(key)=>listeners.delete(key),setAnnotations:rows=>{annotations=rows;calls.push(['set',rows]);},getAnnotations:()=>annotations,getSelected:()=>annotations.filter(a=>a.id===officialSelected),setDrawingTool:()=>{},setDrawingEnabled:value=>calls.push(['draw',value]),setUserSelectAction:()=>{},setSelected:(id,editable)=>{officialSelected=id;calls.push(['select',id,editable]);},cancelSelected:()=>officialSelected=null,cancelDrawing:()=>calls.push(['cancel']),destroy:()=>calls.push(['destroy'])};
  const editor=await createAnnotoriousEditor({image,viewport,world,getBoxes:()=>boxes,getLabels:()=>[{code:'person',class_id:1},{code:'car',class_id:2}],getLabel:()=>({code:'person',class_id:1}),getSelectedId:()=>selected,onSelect:id=>selected=id,onCommit:(next,detail)=>{commits.push(detail);boxes=next;},onError:e=>errors.push(e),isActive:()=>true,createAnnotator:(im,opts)=>{assert.equal(opts.disableUndoRedoKeys,true);assert.equal(opts.autoSave,true);return anno;},...extra});
  return {editor,doc,image,viewport,world,anno,listeners,commits,calls,errors,get boxes(){return boxes;}};
}
function key(doc,key,props={}) {const e=new Event('keydown',{cancelable:true});Object.defineProperties(e,Object.fromEntries(Object.entries({key,ctrlKey:false,metaKey:false,shiftKey:false,...props}).map(([k,v])=>[k,{value:v}])));doc.dispatchEvent(e);return e;}

test('filtered official events merge one ID into full authoritative GT and retain provenance',async()=>{
  const h=await setup();h.editor.setClassFilter(['person']);
  assert.equal(h.calls.filter(c=>c[0]==='set').at(-1)[1].length,1);
  const annotation=h.calls.filter(c=>c[0]==='set').at(-1)[1][0];
  annotation.target.selector.geometry.x=15;
  h.listeners.get('updateAnnotation')(annotation);
  assert.equal(h.boxes.length,2);assert.equal(h.boxes[0].x1,15);assert.equal(h.boxes[0].source_task_id,'task');assert.equal(h.boxes[1].id,'b');assert.equal(h.commits.length,1);
  h.editor.destroy();
});
test('sync is silent, hidden boxes cannot be selected or deleted, invalid rotation is rejected',async()=>{
  const h=await setup();h.editor.sync({boxes:h.boxes,selectedId:'a'});assert.equal(h.commits.length,0);
  h.editor.setVisibility(false);h.editor.select('a');h.editor.deleteSelected();assert.equal(h.boxes.length,2);
  h.editor.setVisibility(true);const annotation=h.calls.filter(c=>c[0]==='set').at(-1)[1][0];annotation.target.selector.geometry.rot=.5;
  h.listeners.get('updateAnnotation')(annotation);assert.equal(h.commits.length,0);assert.equal(h.errors.length,1);h.editor.destroy();
});
test('keyboard owns only active non-input editor and releases all listeners on destroy',async()=>{
  let saves=0,active=true;const h=await setup({isActive:()=>active,onSave:()=>saves++});
  key(h.doc,'s',{ctrlKey:true});assert.equal(saves,1);active=false;key(h.doc,'s',{ctrlKey:true});assert.equal(saves,1);active=true;
  h.editor.select('a');const input=new Node();input.tagName='INPUT';key(h.doc,'Delete',{target:input});key(h.doc,'s',{ctrlKey:true,target:input});assert.equal(h.boxes.length,2);assert.equal(saves,1);
  h.editor.select('a');assert.equal(key(h.doc,'Escape').defaultPrevented,true);assert.equal(h.editor.snapshot().selectedId,null);
  h.editor.destroy();key(h.doc,'s',{ctrlKey:true});assert.equal(saves,1);assert.equal(h.editor.snapshot().destroyed,true);assert.equal(h.listeners.size,0);
});
test('new rectangles require selected class and deletes retain filtered-out GT',async()=>{
  const h=await setup();h.editor.setClassFilter(['person']);
  const created={id:'new',bodies:[],target:{selector:{type:'RECTANGLE',geometry:{x:2,y:3,w:10,h:20,bounds:{minX:2,minY:3,maxX:12,maxY:23}}}}};
  h.listeners.get('createAnnotation')(created);assert.equal(h.boxes.length,3);assert.equal(h.boxes[2].class_id,1);assert.equal(h.boxes[2].label,'person');
  assert.equal(h.editor.snapshot().selectedId,null,'draw mode remains ready for the next rectangle');
  h.editor.select('new');h.editor.deleteSelected();assert.deepEqual(h.boxes.map(row=>row.id),['a','b']);assert.equal(h.commits.length,2);
  h.editor.sync({locked:true});h.editor.select('a');h.editor.reclassSelected('car');h.listeners.get('createAnnotation')(created);assert.equal(h.commits.length,2);h.editor.destroy();
});
test('selected reclassification preserves metadata and never edits hidden classes',async()=>{
  const h=await setup();h.editor.select('a');h.editor.reclassSelected('car');assert.equal(h.boxes[0].class_id,2);assert.equal(h.boxes[0].source,'ai_confirmed');
  h.editor.setClassFilter(['person']);assert.equal(h.editor.snapshot().selectedId,null);h.editor.deleteSelected();assert.equal(h.boxes.length,2);h.editor.destroy();
});
test('viewport fits original pixels, zoom does not mutate GT and resets only for image identity',async()=>{
  const h=await setup();h.editor.fit();assert.equal(h.editor.snapshot().scale,.5);h.editor.zoom(.1);assert.equal(h.editor.snapshot().scale,.6);
  h.editor.sync({boxes:h.boxes});assert.equal(h.editor.snapshot().scale,.6);assert.equal(h.commits.length,0);
  h.image.currentSrc=h.image.src;h.image.src='next.jpg';h.editor.sync({boxes:h.boxes});assert.equal(h.editor.snapshot().scale,1);
  h.editor.resetZoom();assert.equal(h.editor.snapshot().scale,1);assert.match(h.world.style.transform,/scale\(1\)/);h.editor.destroy();
});
test('Escape leaves drawing mode before modal close and selected rectangles are explicitly editable',async()=>{
  const h=await setup();h.editor.select('a');assert.deepEqual(h.calls.filter(c=>c[0]==='select').at(-1),['select','a',true]);
  key(h.doc,'Escape');assert.equal(h.editor.snapshot().selectedId,null);assert.equal(h.editor.snapshot().mode,'select');
  h.editor.setMode('draw');
  assert.equal(key(h.doc,'Escape').defaultPrevented,true);assert.equal(h.editor.snapshot().mode,'select');
  assert.equal(key(h.doc,'Escape').defaultPrevented,false);h.editor.destroy();
});
test('flush commits current public geometry before delayed official idle events and ignores stale selection payload',async()=>{
  const h=await setup();h.editor.select('a');
  h.anno.getAnnotations()[0].target.selector.geometry.x=30;
  h.editor.flush();assert.equal(h.boxes[0].x1,30);assert.equal(h.commits.length,1);
  h.listeners.get('selectionChanged')([]);assert.equal(h.editor.snapshot().selectedId,'a');
  h.editor.flush();assert.equal(h.commits.length,1);h.editor.destroy();
});
test('aborted factory never creates an official instance and a later abort destroys an active instance',async()=>{
  const abort=new AbortController();abort.abort();await assert.rejects(setup({signal:abort.signal}),{name:'AbortError'});
  const live=new AbortController(),h=await setup({signal:live.signal});live.abort();assert.equal(h.editor.snapshot().destroyed,true);
});

test('immediate Escape and Delete use current public selection before deferred selection events',async()=>{
  const h=await setup();h.editor.setMode('select');
  h.anno.setSelected('a',true);assert.equal(h.editor.snapshot().selectedId,null);
  assert.equal(key(h.doc,'Escape').defaultPrevented,true);assert.equal(h.editor.snapshot().selectedId,null);
  h.editor.select('a');h.anno.cancelSelected();h.editor.deleteSelected();
  assert.equal(h.boxes.length,2,'a delayed deselection must not delete the previously selected box');
  h.anno.setSelected('a',true);h.editor.deleteSelected();assert.deepEqual(h.boxes.map(box=>box.id),['b']);h.editor.destroy();
});
test('local asset loader shares script/CSS, waits for CSS and retries an actual asset failure',async()=>{
  delete globalThis.Annotorious;const nodes=[];
  class Asset extends EventTarget {dataset={};remove(){nodes.splice(nodes.indexOf(this),1)}}
  const doc={querySelector:()=>nodes.find(node=>node.rel==='stylesheet'),createElement:()=>new Asset(),head:{appendChild:node=>nodes.push(node)}};
  const first=loadAnnotorious(doc),second=loadAnnotorious(doc);await Promise.resolve();await Promise.resolve();
  assert.equal(nodes.length,2);const script=nodes.find(node=>node.src),css=nodes.find(node=>node.href);
  globalThis.Annotorious={createImageAnnotator:()=>{}};script.dispatchEvent(new Event('load'));
  let settled=false;first.then(()=>settled=true,()=>{});await Promise.resolve();assert.equal(settled,false);
  css.dispatchEvent(new Event('error'));await assert.rejects(first);await assert.rejects(second);assert.equal(nodes.includes(css),false);
  const retry=loadAnnotorious(doc);await Promise.resolve();await Promise.resolve();const nextCss=nodes.find(node=>node.href);nextCss.dispatchEvent(new Event('load'));await retry;
  assert.equal(nodes.filter(node=>node.src).length,1);delete globalThis.Annotorious;
});
