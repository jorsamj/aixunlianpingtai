import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const paginationSource=readFileSync(new URL('../../static/modules/material-pagination-runtime.js',import.meta.url),'utf8');
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
 const thumbnail=h.window.materialMedia412({id:'i',filename:'image',url:'/content/i',thumbnail_url:'/content/i/thumbnail?edge=384',width:400,height:800});
 assert.ok(thumbnail.includes('src="/content/i/thumbnail?edge=384"'));
 assert.ok(!thumbnail.includes('src="/content/i"'));
});
test('dataset shell keeps selection controls above the gallery and filters in the top toolbar',()=>{
 const line=source.split('\n').find(row=>row.includes('window.renderDatasets424=function()'));
 assert.ok(line,'dataset shell owner must exist');
 const page={innerHTML:''};
 const state={
  data412Tab:'all',data412Labels:new Set(),data412Selected:new Set(),storageSources61:[],
  materialView412:'list',storageSourcesLoadedAt61:1,
 };
 const window={};
 vm.runInNewContext(line,{
  state,window,document:{getElementById:id=>id==='view'?page:null},
  actualLabels412:()=>[],esc:String,renderData412Cards:()=>{},
 });
 window.renderDatasets424();
 const html=page.innerHTML;
 const toolbar=html.indexOf('class="data426-toolbar"');
 const filters=html.indexOf('class="material-filters549"');
 const tags=html.indexOf('class="data426-filtertop"');
 const results=html.indexOf('class="material-results-heading"');
 const selectPage=html.indexOf('选择本页');
 const gallery=html.indexOf('id="data412Grid"');
 assert.ok(toolbar>=0 && toolbar<filters && filters<tags && tags<results && results<selectPage && selectPage<gallery,
  `markup positions ${JSON.stringify({toolbar,filters,tags,results,selectPage,gallery})}`);
 assert.equal((html.match(/id="data412Count"/g)||[]).length,1);
 assert.equal((html.match(/class="material-select-tools549"/g)||[]).length,1);
 assert.match(html,/data-material-view="list" aria-pressed="true"/);
 assert.match(html,/data-material-view="grid" aria-pressed="false"/);
 assert.match(html,/id="materialFilterCount" hidden/);
 assert.match(html,/onclick="selectAll412\(\)"/);
 assert.match(html,/onclick="invert412\(\)"/);
 assert.match(html,/id="data412Pager"/);
});
test('dataset visual rhythm has scoped spacing, a compact filter popover and keyboard focus',()=>{
 const css=readFileSync(new URL('../../static/material-workspace.css',import.meta.url),'utf8');
 assert.match(css,/\.material-workspace412 \.data426-toolbar \{[^}]*padding:16px 24px/s);
 assert.match(css,/\.material-workspace412 \.data426-grid \{[^}]*gap:16px;[^}]*padding:24px/s);
 assert.match(css,/\.material-workspace412 \.material-filter-popover \{[^}]*position:absolute;[^}]*max-height:/s);
 assert.match(css,/\.material-workspace412 \.material-view-switch button\[aria-pressed="true"\]/);
 assert.match(css,/\.material-workspace412 button:focus-visible/);
 assert.match(css,/@media\(prefers-reduced-motion:reduce\)/);
});
test('filter trigger count reflects active label and advanced filter state',()=>{
 const begin=paginationSource.indexOf('  function decorateDataset61() {');
 const end=paginationSource.indexOf('  function patchPagedDataset61()',begin);
 assert.ok(begin>=0 && end>begin,'paged dataset owner must expose its decorator');
 const count={textContent:'',hidden:true};
 const state={
  data412Labels:new Set(['person','smoke']),materialBatchFilter61:'batch-1',
  materialQualityFilter61:'',materialCreatedFrom61:'2026-11-01',materialCreatedTo61:'',
  materialPage61:{total:200},data412Selected:new Set(),
 };
 const document={
  querySelectorAll:()=>[],
  getElementById:id=>id==='materialFilterCount'?count:null,
 };
 const sandbox={
  state,document,window:{},transport:{pageSize:48},
  decorateStorage61:()=>{},decorateLabelSearch61:()=>{},restoreControls61:()=>{},
  syncLabelChipState61:()=>{},decorateSummary61:()=>{},
 };
 vm.runInNewContext(paginationSource.slice(begin,end)+'\nwindow.testDecorate=decorateDataset61;',sandbox);
 sandbox.window.testDecorate();
 assert.equal(count.textContent,'4');
 assert.equal(count.hidden,false);
 state.data412Labels.clear();
 state.materialBatchFilter61='';state.materialCreatedFrom61='';
 sandbox.window.testDecorate();
 assert.equal(count.textContent,'0');
 assert.equal(count.hidden,true);
});
