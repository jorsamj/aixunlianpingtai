from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'static/app.js'
MATERIAL = ROOT / 'static/modules/material-pagination-runtime.js'
MAIN = ROOT / 'static/main.mjs'
INDEX = ROOT / 'static/index.html'
TEST = ROOT / 'tests/frontend/lifecycle-event-ownership.test.mjs'


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 match, found {count}')
    return text.replace(old, new, 1)


app = APP.read_text(encoding='utf-8')
start = "  // Patch ZIP completion: preserve v42.11 progress, but review batch after completion and use fast reload.\n"
end = "  // Plain image upload after success: ask for cleaning decision instead of leaving raw images indefinitely.\n"
if app.count(start) != 1 or app.count(end) != 1:
    raise SystemExit('ZIP review observer markers changed')
left, rest = app.split(start, 1)
old_block, right = rest.split(end, 1)
if "obs.observe(document.body,{childList:true,subtree:true});" not in old_block:
    raise SystemExit('body-wide ZIP observer missing from expected block')
if "const oldZip412=window.doUploadZip426;" not in old_block:
    raise SystemExit('oldZip412 capture missing from expected block')
new_block = """  // ZIP review is owned by the explicit successful import-completion event.\n  window.completeZipImportReview412=function(jobId){\n    const t=state.import411;if(!t||String(t.jobId||'')!==String(jobId||'')||t.__reviewBound)return;\n    t.__reviewBound=true;\n    const extra=`<div class=\"row end\"><button class=\"btn primary review412-btn\" onclick=\"showImportReview412('${t.jobId}')\">整理本次导入素材</button></div>`;\n    if(!String(t.resultHtml||'').includes('review412-btn'))t.resultHtml=String(t.resultHtml||'')+extra;\n    const syncReview=()=>{const r=document.getElementById('zip411Result');if(r&&!r.querySelector('.review412-btn'))r.insertAdjacentHTML('beforeend',extra);if(r&&!t.__autoReviewOpened){t.__autoReviewOpened=true;setTimeout(()=>showImportReview412(t.jobId),280)}};\n    syncReview();setTimeout(syncReview,30);\n  };\n\n"""
app = left + new_block + end + right
app = replace_once(
    app,
    "});invalidateQuality411();await related411();if(state.page==='数据集')renderDatasets424()",
    "});window.completeZipImportReview412?.(job.id);invalidateQuality411();await related411();if(state.page==='数据集')renderDatasets424()",
    'ZIP completion hook call',
)
if 'const oldZip412=window.doUploadZip426;' in app:
    raise SystemExit('oldZip412 survived migration')
if 'obs.observe(document.body,{childList:true,subtree:true});' in app:
    raise SystemExit('body-wide ZIP observer survived migration')
if app.count('window.completeZipImportReview412=function(jobId)') != 1:
    raise SystemExit('completion owner count mismatch')
if app.count('window.completeZipImportReview412?.(job.id)') != 1:
    raise SystemExit('completion hook call count mismatch')
APP.write_text(app, encoding='utf-8')

material = MATERIAL.read_text(encoding='utf-8')
material = replace_once(
    material,
    "  async function refreshSummary61() {\n    const pid = projectId();\n    if (!pid || transport.mode !== 'paged') return;\n    try {",
    "  async function refreshSummary61() {\n    const pid = projectId();\n    if (!pid || !isPagedDataset()) return;\n    const expectedPage = state.page;\n    try {",
    'material summary entry guard',
)
material = replace_once(
    material,
    "      if (transport.mode !== 'paged') return;\n      state.materialSummary61 = {",
    "      if (state.page !== expectedPage || !isPagedDataset()) return;\n      state.materialSummary61 = {",
    'material summary stale response guard',
)
MATERIAL.write_text(material, encoding='utf-8')

main = MAIN.read_text(encoding='utf-8')
main = replace_once(
    main,
    "./modules/material-pagination-runtime.js?v=422205",
    "./modules/material-pagination-runtime.js?v=422206",
    'material runtime module cache',
)
MAIN.write_text(main, encoding='utf-8')

index = INDEX.read_text(encoding='utf-8')
index = replace_once(index, '/static/app.js?v=42.25.72', '/static/app.js?v=42.25.73', 'app cache')
index = replace_once(index, '/static/main.mjs?v=42.25.76', '/static/main.mjs?v=42.25.77', 'main cache')
INDEX.write_text(index, encoding='utf-8')

TEST.write_text("""import test from 'node:test';\nimport assert from 'node:assert/strict';\nimport fs from 'node:fs';\n\nconst app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');\nconst material = fs.readFileSync(new URL('../../static/modules/material-pagination-runtime.js', import.meta.url), 'utf8');\n\ntest('ZIP import review is event-owned and the body-wide observer cannot return', () => {\n  assert.equal(app.includes('const oldZip412=window.doUploadZip426;'), false);\n  assert.equal(app.includes('obs.observe(document.body,{childList:true,subtree:true});'), false);\n  assert.equal(app.split('window.completeZipImportReview412=function(jobId)').length - 1, 1);\n  assert.equal(app.split('window.completeZipImportReview412?.(job.id)').length - 1, 1);\n  assert.equal(app.includes('t.__reviewBound=true;'), true);\n  assert.equal(app.includes('t.__autoReviewOpened=true;'), true);\n  assert.equal(app.includes("t.resultHtml=String(t.resultHtml||'')+extra"), true);\n});\n\ntest('material summary timers are scoped to the live paged dataset page', () => {\n  assert.equal(material.includes("if (!pid || !isPagedDataset()) return;"), true);\n  assert.equal(material.includes('const expectedPage = state.page;'), true);\n  assert.equal(material.includes("if (state.page !== expectedPage || !isPagedDataset()) return;"), true);\n  assert.equal(material.includes("if (!pid || transport.mode !== 'paged') return;"), false);\n  assert.equal(material.includes('setTimeout(refreshSummary61, 1200);'), true);\n});\n""", encoding='utf-8')

if (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')

print('R16 lifecycle event owners consolidated')
