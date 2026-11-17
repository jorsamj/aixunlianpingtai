// Instrument only responses served to the isolated original Playwright acceptance.
import {readFileSync,appendFileSync} from 'node:fs';
function once(source,needle,replacement,name){
 const matches=source.split(needle).length-1;
 if(matches!==1)throw new Error(`OVERLAY_INJECTION_FAILED ${name}: expected 1 match, got ${matches}`);
 console.log('OVERLAY_INJECTION_MATCH '+JSON.stringify({name,matches}));
 return source.replace(needle,replacement);
}
export function instrumentApp(source){
 // Verify the real checkbox, inline event and media argument contracts as well as probes.
 for(const [name,needle] of [
  ['checkbox','<label class="material-box-toggle"><input type="checkbox"'],
  ['change-handler','onchange="toggleMaterialBoxes549(this.checked)"'],
  ['card-media','materialMedia412(x,!state.materialShowBoxes549)']
 ])source=once(source,needle,needle,name);
 source=once(source,'window.toggleMaterialBoxes549=on=>{state.materialShowBoxes549=on;renderData412Cards()}',
  'window.toggleMaterialBoxes549=on=>{window.__overlayTrace("toggle-before",state,{on});state.materialShowBoxes549=on;window.__overlayTrace("toggle-state",state);renderData412Cards();window.__overlayTrace("toggle-after",state)}','toggle-and-state');
 source=once(source,'window.renderData412Cards=function(){','window.renderData412Cards=function(){window.__overlayTrace("base-render",state);','original-render');
 source=once(source,'function dataCardSignature412(x){','function dataCardSignature412(x){window.__overlayTrace("signature-input",state,{materialId:x.id});','signature-input');
 source=once(source,'const key=String(row.id),signature=dataCardSignature412(row);keep.add(key);',
  'const key=String(row.id),signature=dataCardSignature412(row);window.__overlayTrace("signature-comparison",state,{materialId:key,computedSignature:signature,oldSignature:existing.get(key)?.dataset.renderSignature,oldNode:window.__overlayNodeId(existing.get(key))});keep.add(key);','signature-comparison');
 source=once(source,'node.replaceWith(next);node=next',
  'window.__overlayTrace("replace-before",state,{materialId:key,oldNode:window.__overlayNodeId(node),newNode:window.__overlayNodeId(next)});node.replaceWith(next);node=next;window.__overlayTrace("replace-after",state,{materialId:key})','node-replacement');
 source=once(source,'function materialMedia412(x,raw=false){','function materialMedia412(x,raw=false){window.__overlayTrace("media",state,{materialId:x.id,raw});','media-argument');
 source=once(source,'window.renderDatasets424=function(){','window.renderDatasets424=function(){window.__overlayTrace("dataset-render",state);','dataset-redraw');
 return source;
}
export function instrumentPagination(source){
 source=once(source,'const baseRenderCards = window.renderData412Cards;',
  'const baseRenderCards = window.renderData412Cards;window.__overlayTrace("base-captured",state,{base:String(baseRenderCards).slice(0,150)});','base-capture');
 source=once(source,'function pagedMaterialCards() {',
  'function pagedMaterialCards() {window.__overlayTrace("paged-render",state,{suppressCardReload,paged:isPagedDataset(),base:String(baseRenderCards).slice(0,150)});','paged-wrapper');
 source=once(source,'try { baseRenderCards(); }',
  'try { window.__overlayTrace("patch-before-base",state);baseRenderCards();window.__overlayTrace("patch-after-base",state); }','base-call');
 source=once(source,'async function loadMaterialPage61({reset = false, page = undefined} = {}) {',
  'async function loadMaterialPage61({reset = false, page = undefined} = {}) {window.__overlayTrace("page-load-start",state,{reset,page});','page-load');
 source=once(source,'state.images = Array.isArray(materialPage.items) ? materialPage.items : [];',
  'window.__overlayTrace("page-apply-before",state);state.images = Array.isArray(materialPage.items) ? materialPage.items : [];window.__overlayTrace("page-apply-after",state);','page-apply');
 return source;
}
export async function installOverlayDiagnostics({page},testInfo){
 const seen=new Set();
 const record=line=>{console.log(line);appendFileSync('test-results/material-overlay-diagnostic/overlay.jsonl',line+'\n')};
 page.on('console',m=>{if(m.text().startsWith('OVERLAY'))record(m.text())});
 page.on('pageerror',e=>record('OVERLAY_PAGEERROR '+String(e)));
 page.on('request',r=>{if(/materials|bootstrap/.test(r.url()))record('OVERLAY_REQUEST '+JSON.stringify({time:Date.now(),method:r.method(),path:new URL(r.url()).pathname}))});
 page.on('response',r=>{if(/materials|bootstrap/.test(r.url()))record('OVERLAY_RESPONSE '+JSON.stringify({time:Date.now(),status:r.status(),path:new URL(r.url()).pathname}))});
 await page.addInitScript(()=>{
  const ids=new WeakMap();let id=0;
  window.__overlayNodeId=node=>{if(!node)return null;if(!ids.has(node))ids.set(node,++id);return ids.get(node)};
  window.__overlayTrace=(phase,s,extra={})=>{
   const q=document.querySelector('.material-box-toggle input');
   const cards=[...document.querySelectorAll('.data412-card')].filter(c=>c.textContent.includes('annotation-flow.bmp'));
   console.log('OVERLAY '+JSON.stringify({phase,time:performance.now(),epoch:Date.now(),checked:q?.checked,checkboxNode:window.__overlayNodeId(q),state:s?.materialShowBoxes549??null,renderer:String(window.renderData412Cards).slice(0,150),cards:cards.map(c=>({materialId:c.dataset.materialId,node:window.__overlayNodeId(c),signature:c.dataset.renderSignature,boxes:c.querySelectorAll('.data412-box').length})),...extra}));
  };
  document.addEventListener('change',e=>{if(e.target.matches('.material-box-toggle input')){
   window.__overlayTrace('change-capture',Function('return state')());
   // A microtask here is not evidence that the inline target handler has run.
   queueMicrotask(()=>window.__overlayTrace('capture-microtask',Function('return state')()));
  }},true);
  document.addEventListener('change',e=>{if(e.target.matches('.material-box-toggle input'))window.__overlayTrace('change-bubble',Function('return state')())});
 });
 await page.route('**/static/modules/material-pagination-runtime.js*',async r=>{
  seen.add('pagination');await r.fulfill({contentType:'text/javascript',body:instrumentPagination(readFileSync('static/modules/material-pagination-runtime.js','utf8'))});
 });
 await page.route('**/static/app.js?*',async r=>{
  seen.add('app');await r.fulfill({contentType:'text/javascript',body:instrumentApp(readFileSync('static/app.js','utf8'))});
 });
 testInfo.onOverlaySeen=seen;
 // Route usage is checked by the generated test afterEach, including failed tests.
 page.on('close',()=>record('OVERLAY_ROUTES '+JSON.stringify([...seen])));
}

export async function finishOverlayDiagnostics({page},testInfo){
 const seen=testInfo.onOverlaySeen;
 for(const name of ['app','pagination'])if(!seen?.has(name))throw new Error('OVERLAY_INJECTION_FAILED response route never matched: '+name);
 if(!page.isClosed())await page.evaluate(()=>window.__overlayTrace?.('test-end',Function('return state')()));
 console.log('OVERLAY_ROUTES_VERIFIED '+JSON.stringify([...seen]));
}
