from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'static/app.js'
INDEX=ROOT/'static/index.html'
FILE_TEST=ROOT/'tests/frontend/file-input-beautification-owner.test.mjs'
START_TEST=ROOT/'tests/frontend/startup-render-owner.test.mjs'
NEW_TEST=ROOT/'tests/frontend/modal-content-owner.test.mjs'


def one(s,old,new,label):
    n=s.count(old)
    if n!=1: raise SystemExit(f'{label}: expected 1, got {n}')
    return s.replace(old,new,1)

app=APP.read_text(encoding='utf-8')
app=one(app,
"function modal(title,body,wide=false){$('#modalTitle').textContent=title;$('#modalBody').innerHTML=body;",
"function replaceModalContent(root,html){if(!root)return null;root.innerHTML=html;if(root.id==='modalBody')window.PostRenderNormalizationRuntime?.apply?.(root);return root} window.ModalContentRuntime=Object.freeze({replace:replaceModalContent});\nfunction modal(title,body,wide=false){$('#modalTitle').textContent=title;window.ModalContentRuntime.replace($('#modalBody'),body);",
'base modal content owner')
app=one(app,
"loadImportJobs().then(()=>{document.getElementById('modalBody').innerHTML=renderImportJobsPanel()})",
"loadImportJobs().then(()=>window.ModalContentRuntime.replace(document.getElementById('modalBody'),renderImportJobsPanel()))",
'import dock refresh')
app=one(app,
"if(!$('#modal').classList.contains('hidden'))$('#modalBody').innerHTML=renderImportJobsPanel();",
"if(!$('#modal').classList.contains('hidden'))window.ModalContentRuntime.replace($('#modalBody'),renderImportJobsPanel());",
'import dock delete refresh')
app=one(app,"if(body)body.innerHTML=previewBody426()","if(body)window.ModalContentRuntime.replace(body,previewBody426())",'preview426')
app=one(app,"if(body&&list[i])body.innerHTML=previewHtml411(list[i],list,i)","if(body&&list[i])window.ModalContentRuntime.replace(body,previewHtml411(list[i],list,i))",'preview411')
if app.count('if(body)body.innerHTML=reviewHtml412()')!=3: raise SystemExit(f'review412 writes={app.count("if(body)body.innerHTML=reviewHtml412()")}, expected 3')
app=app.replace('if(body)body.innerHTML=reviewHtml412()','if(body)window.ModalContentRuntime.replace(body,reviewHtml412())')
if app.count('if(body)body.innerHTML=importReview414Html()')!=4: raise SystemExit(f'review414 writes={app.count("if(body)body.innerHTML=importReview414Html()")}, expected 4')
app=app.replace('if(body)body.innerHTML=importReview414Html()','if(body)window.ModalContentRuntime.replace(body,importReview414Html())')
observer="""  window.PostRenderNormalizationRuntime=Object.freeze({apply:cleanup});
  const modalObserver=new MutationObserver(muts=>{for(const m of muts){m.addedNodes.forEach(n=>{if(n.nodeType===1)cleanup(n)})}});
  const modalBody=document.getElementById('modalBody');
  if(modalBody)modalObserver.observe(modalBody,{childList:true,subtree:true});
})();
"""
replacement="""  window.PostRenderNormalizationRuntime=Object.freeze({apply:cleanup});
})();
"""
app=one(app,observer,replacement,'modal normalization observer')
if 'new MutationObserver' in app: raise SystemExit('MutationObserver survived R19')
if "document.getElementById('modalBody').innerHTML=" in app: raise SystemExit('direct document modalBody write survived')
# closeModal is the only allowed direct #modalBody innerHTML assignment; it only clears content.
if app.count("$('#modalBody').innerHTML=")!=1 or "$('#modalBody').innerHTML=''" not in app:
    raise SystemExit('unexpected direct #modalBody innerHTML owner remains')
APP.write_text(app,encoding='utf-8')

idx=INDEX.read_text(encoding='utf-8')
idx=one(idx,'/static/app.js?v=42.25.75','/static/app.js?v=42.25.76','app cache')
INDEX.write_text(idx,encoding='utf-8')

ft=FILE_TEST.read_text(encoding='utf-8')
old="""test('modal426 stays retired while modalBody keeps the only normalization observer', () => {
  assert.equal(app.includes('const modal426=modal;'), false);
  assert.equal(app.includes('requestAnimationFrame(()=>beautifyFileInputs426(layer||document))'), false);
  assert.equal(app.includes("const view=document.getElementById('view'),modalBody=document.getElementById('modalBody');"), false);
  assert.equal(app.includes("observer.observe(view,{childList:true,subtree:true})"), false);
  assert.equal(app.includes("const modalBody=document.getElementById('modalBody');"), true);
  assert.equal(app.includes("if(modalBody)modalObserver.observe(modalBody,{childList:true,subtree:true});"), true);
});
"""
new="""test('modal426 and modal normalization observers stay retired behind ModalContentRuntime', () => {
  assert.equal(app.includes('const modal426=modal;'), false);
  assert.equal(app.includes('requestAnimationFrame(()=>beautifyFileInputs426(layer||document))'), false);
  assert.equal(app.includes('new MutationObserver'), false);
  assert.equal(app.includes('window.ModalContentRuntime=Object.freeze({replace:replaceModalContent});'), true);
  assert.equal(app.includes("if(root.id==='modalBody')window.PostRenderNormalizationRuntime?.apply?.(root);"), true);
  assert.equal(app.includes("window.ModalContentRuntime.replace($('#modalBody'),body);"), true);
});
"""
ft=one(ft,old,new,'file input modal owner guard')
FILE_TEST.write_text(ft,encoding='utf-8')

st=START_TEST.read_text(encoding='utf-8')
st=one(st,
"  assert.equal(app.includes(\"if(modalBody)modalObserver.observe(modalBody,{childList:true,subtree:true});\"), true);",
"  assert.equal(app.includes('new MutationObserver'), false);\n  assert.equal(app.includes('window.ModalContentRuntime=Object.freeze({replace:replaceModalContent});'), true);",
'startup modal observer guard')
START_TEST.write_text(st,encoding='utf-8')

NEW_TEST.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('base modal content replacement is explicit and observer-free', () => {
  assert.equal(app.includes('new MutationObserver'), false);
  assert.equal(app.includes('window.ModalContentRuntime=Object.freeze({replace:replaceModalContent});'), true);
  assert.equal(app.includes("window.ModalContentRuntime.replace($('#modalBody'),body);"), true);
  assert.equal(app.includes("if(root.id==='modalBody')window.PostRenderNormalizationRuntime?.apply?.(root);"), true);
});

test('known post-open base modal refresh paths use ModalContentRuntime', () => {
  assert.equal(app.includes("loadImportJobs().then(()=>window.ModalContentRuntime.replace(document.getElementById('modalBody'),renderImportJobsPanel()))"), true);
  assert.equal(app.includes("if(!$('#modal').classList.contains('hidden'))window.ModalContentRuntime.replace($('#modalBody'),renderImportJobsPanel());"), true);
  assert.equal(app.includes("document.getElementById('modalBody').innerHTML="), false);
});

test('modal-like preview and review rewrites route through one content replacement owner', () => {
  assert.equal(app.includes('if(body)body.innerHTML=previewBody426()'), false);
  assert.equal(app.includes('if(body&&list[i])body.innerHTML=previewHtml411(list[i],list,i)'), false);
  assert.equal(app.includes('if(body)body.innerHTML=reviewHtml412()'), false);
  assert.equal(app.includes('if(body)body.innerHTML=importReview414Html()'), false);
  assert.equal(app.split('window.ModalContentRuntime.replace(body,reviewHtml412())').length - 1, 3);
  assert.equal(app.split('window.ModalContentRuntime.replace(body,importReview414Html())').length - 1, 4);
});
""",encoding='utf-8')

if (ROOT/'VERSION.txt').read_text(encoding='utf-8').strip()!='42.24.0': raise SystemExit('formal VERSION changed')
print('R19 modal content owner consolidated')
