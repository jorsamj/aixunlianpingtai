from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'static/app.js'
INDEX = ROOT / 'static/index.html'
TEST = ROOT / 'tests/frontend/startup-render-owner.test.mjs'


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 match, found {count}')
    return text.replace(old, new, 1)

app = APP.read_text(encoding='utf-8')
old = """  const modalBody=document.getElementById('modalBody');
  if(modalBody)modalObserver.observe(modalBody,{childList:true,subtree:true});
  setTimeout(()=>{renderTop();cleanup(document);},100);
})();
"""
new = """  const modalBody=document.getElementById('modalBody');
  if(modalBody)modalObserver.observe(modalBody,{childList:true,subtree:true});
})();
"""
app = replace_once(app, old, new, 'bounded startup cleanup timer')
if "setTimeout(()=>{renderTop();cleanup(document);},100);" in app:
    raise SystemExit('bounded startup cleanup timer survived')
if app.count("window.PostRenderNormalizationRuntime?.apply(document.getElementById('view'))") != 1:
    raise SystemExit('final page normalization owner count changed')
if app.count("modalObserver.observe(modalBody,{childList:true,subtree:true})") != 1:
    raise SystemExit('modal observer wiring changed unexpectedly')
APP.write_text(app, encoding='utf-8')

index = INDEX.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.74', '/static/app.js?v=42.25.75', 'app cache')
INDEX.write_text(index, encoding='utf-8')

test = TEST.read_text(encoding='utf-8')
old_test = """test('bounded cleanup timer is not confused with retired startup renders', () => {
  assert.equal(app.includes(\"setTimeout(()=>{renderTop();cleanup(document);},100);\"), true);
});
"""
new_test = """test('bounded startup cleanup timer cannot return after final render ownership', () => {
  assert.equal(app.includes(\"setTimeout(()=>{renderTop();cleanup(document);},100);\"), false);
  assert.equal(app.includes('window.PostRenderNormalizationRuntime=Object.freeze({apply:cleanup});'), true);
  assert.equal(app.split(\"window.PostRenderNormalizationRuntime?.apply(document.getElementById('view'))\").length - 1, 1);
  assert.equal(app.includes(\"if(modalBody)modalObserver.observe(modalBody,{childList:true,subtree:true});\"), true);
});
"""
test = replace_once(test, old_test, new_test, 'startup timer permanent guard')
TEST.write_text(test, encoding='utf-8')

if (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')

print('R18 bounded startup cleanup timer retired')
