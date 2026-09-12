from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'static/app.js'
INDEX = ROOT / 'static/index.html'
POST_TEST = ROOT / 'tests/frontend/post-render-normalization-owner.test.mjs'
FILE_TEST = ROOT / 'tests/frontend/file-input-beautification-owner.test.mjs'


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 match, found {count}')
    return text.replace(old, new, 1)


app = APP.read_text(encoding='utf-8')
old_lifecycle = """  const baseRender=render;
  render=function(){baseRender();cleanup(document.getElementById('view'));requestAnimationFrame(()=>cleanup(document.getElementById('view')))};
  const observer=new MutationObserver(muts=>{for(const m of muts){m.addedNodes.forEach(n=>{if(n.nodeType===1)cleanup(n)})}});
  const view=document.getElementById('view'),modalBody=document.getElementById('modalBody');
  if(view)observer.observe(view,{childList:true,subtree:true});if(modalBody)observer.observe(modalBody,{childList:true,subtree:true});
  setTimeout(()=>{renderTop();cleanup(document);},100);
"""
new_lifecycle = """  window.PostRenderNormalizationRuntime=Object.freeze({apply:cleanup});
  const modalObserver=new MutationObserver(muts=>{for(const m of muts){m.addedNodes.forEach(n=>{if(n.nodeType===1)cleanup(n)})}});
  const modalBody=document.getElementById('modalBody');
  if(modalBody)modalObserver.observe(modalBody,{childList:true,subtree:true});
  setTimeout(()=>{renderTop();cleanup(document);},100);
"""
app = replace_once(app, old_lifecycle, new_lifecycle, 'page cleanup compatibility layer')

old_final = """  const finalRender=render;
  render=function(){if(state.page==='素材存储配置'){renderNav();renderTop();renderSummary();renderStorageSources61();return}finalRender()};
})();
"""
new_final = """  const finalRender=render;
  render=function(){if(state.page==='素材存储配置'){renderNav();renderTop();renderSummary();renderStorageSources61()}else finalRender();window.PostRenderNormalizationRuntime?.apply(document.getElementById('view'))};
})();
"""
app = replace_once(app, old_final, new_final, 'final render normalization owner')

for forbidden in [
    'const baseRender=render;',
    "requestAnimationFrame(()=>cleanup(document.getElementById('view')))",
    "observer.observe(view,{childList:true,subtree:true})",
]:
    if forbidden in app:
        raise SystemExit(f'legacy page normalization owner survived: {forbidden}')
if app.count('window.PostRenderNormalizationRuntime=Object.freeze({apply:cleanup});') != 1:
    raise SystemExit('named normalization runtime count mismatch')
if app.count("window.PostRenderNormalizationRuntime?.apply(document.getElementById('view'))") != 1:
    raise SystemExit('final render normalization call count mismatch')
if app.count("modalObserver.observe(modalBody,{childList:true,subtree:true})") != 1:
    raise SystemExit('modal observer wiring missing')
APP.write_text(app, encoding='utf-8')

index = INDEX.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.73', '/static/app.js?v=42.25.74', 'app cache')
INDEX.write_text(index, encoding='utf-8')

post = POST_TEST.read_text(encoding='utf-8')
append = """

test('final render owns page normalization without legacy view observer or RAF wrapper', () => {
  assert.equal(app.includes('const baseRender=render;'), false);
  assert.equal(app.includes("requestAnimationFrame(()=>cleanup(document.getElementById('view')))"), false);
  assert.equal(app.includes("observer.observe(view,{childList:true,subtree:true})"), false);
  assert.equal(app.split('window.PostRenderNormalizationRuntime=Object.freeze({apply:cleanup});').length - 1, 1);
  assert.equal(app.split("window.PostRenderNormalizationRuntime?.apply(document.getElementById('view'))").length - 1, 1);
  assert.equal(app.includes("render=function(){if(state.page==='素材存储配置'){renderNav();renderTop();renderSummary();renderStorageSources61()}else finalRender();window.PostRenderNormalizationRuntime?.apply(document.getElementById('view'))};"), true);
  assert.equal(app.includes("modalObserver.observe(modalBody,{childList:true,subtree:true})"), true);
});
"""
if "test('final render owns page normalization" in post:
    raise SystemExit('post-render final-owner guard already exists')
POST_TEST.write_text(post.rstrip() + append, encoding='utf-8')

file_test = FILE_TEST.read_text(encoding='utf-8')
old_modal_test = """test('modal426 wrapper cannot return after modalBody observer takeover', () => {
  assert.equal(app.includes('const modal426=modal;'), false);
  assert.equal(app.includes('requestAnimationFrame(()=>beautifyFileInputs426(layer||document))'), false);
  assert.equal(
    app.includes("const view=document.getElementById('view'),modalBody=document.getElementById('modalBody');"),
    true,
  );
  assert.equal(
    app.includes("if(view)observer.observe(view,{childList:true,subtree:true});if(modalBody)observer.observe(modalBody,{childList:true,subtree:true});"),
    true,
  );
});
"""
new_modal_test = """test('modal426 stays retired while modalBody keeps the only normalization observer', () => {
  assert.equal(app.includes('const modal426=modal;'), false);
  assert.equal(app.includes('requestAnimationFrame(()=>beautifyFileInputs426(layer||document))'), false);
  assert.equal(app.includes("const view=document.getElementById('view'),modalBody=document.getElementById('modalBody');"), false);
  assert.equal(app.includes("observer.observe(view,{childList:true,subtree:true})"), false);
  assert.equal(app.includes("const modalBody=document.getElementById('modalBody');"), true);
  assert.equal(app.includes("if(modalBody)modalObserver.observe(modalBody,{childList:true,subtree:true});"), true);
});
"""
file_test = replace_once(file_test, old_modal_test, new_modal_test, 'file-input observer contract')
FILE_TEST.write_text(file_test, encoding='utf-8')

if (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')

print('R17 final page normalization owner consolidated')
