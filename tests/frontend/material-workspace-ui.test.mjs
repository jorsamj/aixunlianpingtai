import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
function harness(){
 const grid={dataset:{}},buttons=[{dataset:{materialView:'grid'},setAttribute(k,v){this[k]=v}},{dataset:{materialView:'list'},setAttribute(k,v){this[k]=v}}];
 const state={data412Tab:'processed',data412Selected:new Set(),labels:[]};
 const window={annotationMaterialActionV66:()=>'<button>标注</button>'};
 const document={getElementById:id=>id==='data412Grid'?grid:null,querySelectorAll:()=>buttons};
 const start=source.indexOf('  function materialMedia412('),end=source.indexOf('  function dataCardSignature412(',start);
 assert.ok(start>=0,'material media and display projection must exist in original card owner');
 vm.runInNewContext(source.slice(start,end),{state,window,document,esc:String,ov412:()=>'<i class="data412-box"></i>',fmtSize424:()=>'',displayLabel412:String});
 return {window,state,grid,buttons};
}
test('view changes only display state and keeps original material nodes and selection',()=>{
 const h=harness();h.state.data412Selected.add('i1');h.window.setMaterialView412('list');
 assert.equal(h.grid.dataset.materialView,'list');assert.equal(h.buttons[1]['aria-pressed'],'true');assert.deepEqual([...h.state.data412Selected],['i1']);
 h.window.setMaterialView412('bad');assert.equal(h.grid.dataset.materialView,'list');
});
test('image failure hides the exact projection and retry reuses its original URL',()=>{
 const h=harness();const status={hidden:true},media={dataset:{},querySelector:()=>status};
 const image={dataset:{},src:'/content/i1',hidden:false,closest:()=>media};
 h.window.materialImageFailed412(image);assert.equal(media.dataset.imageState,'failed');assert.equal(image.hidden,true);assert.equal(status.hidden,false);
 media.querySelector=selector=>selector==='img'?image:status;
 h.window.retryMaterialImage412({closest:()=>media});assert.equal(image.src,'/content/i1');assert.equal(media.dataset.imageState,'loading');assert.equal(image.hidden,false);
 h.window.materialImageLoaded412(image);assert.equal(media.dataset.imageState,'ready');assert.equal(status.hidden,true);
});
test('contain media keeps original aspect plane and reports image failure without losing actions',()=>{
 const h=harness();const html=h.window.materialMedia412({id:'i',filename:'long name',url:'/content/i',width:400,height:800,annotated:true});
 assert.match(html,/material-media-plane/);assert.match(html,/width:37.5%/);assert.match(html,/height:100%/);assert.match(html,/materialImageFailed412/);assert.match(html,/retryMaterialImage412/);
});
