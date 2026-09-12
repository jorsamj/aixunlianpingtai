from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    ROOT / 'docs/CODEX_CURRENT_STATE.md',
    ROOT / 'docs/frontend-legacy-audit.md',
    ROOT / 'docs/FRONTEND_OWNER_MAP_V42_25.md',
    ROOT / 'docs/TECH_DEBT_CLOSURE_V42_25.md',
]
ACCEPT = '954e9dba9c891ecd5c7f21144cf00d8664c11620'
RUN = '34670319479'


def one(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f'{label}: expected 1, got {n}')
    return text.replace(old, new, 1)


def append_after(text, anchor, addition, label):
    if '### R18 — bounded startup cleanup timer retirement' in text:
        return text
    if anchor not in text:
        raise SystemExit(f'{label}: anchor missing')
    return text.replace(anchor, anchor + addition, 1)

r18 = f'''\n\n### R18 — bounded startup cleanup timer retirement\n\nR18 retired the remaining readiness-bypassing `setTimeout(()=>{{renderTop();cleanup(document);}},100)` wakeup. Final startup already waits for the v53 snapshot/current-page refresh and then calls the final `render()`, while R17 made that final render the sole page-normalization dispatch. The modal observer was deliberately left untouched because post-open base-modal body mutations still depend on normalization.\n\n```text\nproduct:    1572fdf4fad6e0fe8d10b5253a236722e85b3495\nvalidation: {ACCEPT}\nrun:        {RUN}\nfrontend:   PASS\nReal Chrome: 19/19 PASS\n```\n'''

# Current state
p = DOCS[0]; t = p.read_text(encoding='utf-8')
t = one(t, 'latest full code acceptance: f5b8ff8789de0f51d2a03bcabe126191005ba24c', f'latest full code acceptance: {ACCEPT}', 'state accept')
t = one(t, 'Frontend Runtime run:        34669152742', f'Frontend Runtime run:        {RUN}', 'state run')
t = one(t, 'app.js cache:                42.25.74', 'app.js cache:                42.25.75', 'state app cache')
t = one(t, 'main.mjs cache:              42.25.79', 'main.mjs cache:              42.25.80', 'state main cache')
t = one(t, 'Run `34669152742` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions.', f'Run `{RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions.', 'state run sentence')
t = one(t, 'modal observer + bounded cleanup timer lifecycle audit\n→ app.js/global reload/request debt', 'modal observer lifecycle audit\n→ app.js/global reload/request debt', 'state priority')
t = one(t, 'v35/v36/V37 80/100/120ms startup render/version timers\noldZip412', 'v35/v36/V37 80/100/120ms startup render/version timers\nbounded 100ms renderTop/cleanup startup timer\noldZip412', 'state retired timer')
t = one(t, 'The race audit identified three historical startup compatibility timers as unowned render wakeups: v35 80ms, v36 100ms and V37 120ms. They were physically removed. Final startup dispatch remains `queueMicrotask → final __clInit`; the separate bounded `setTimeout(()=>{renderTop();cleanup(document);},100)` cleanup timer remains intentionally live.', 'The race audit identified three historical startup compatibility timers as unowned render wakeups: v35 80ms, v36 100ms and V37 120ms. They were physically removed. Final startup dispatch remains `queueMicrotask → final __clInit`. The separate bounded 100ms cleanup timer was later retired in R18 after final-render normalization ownership was proven.', 'state R15 timer note')
t = append_after(t, 'The first full validation correctly exposed one stale structure-bound storage-owner unit assertion; the product behavior was not reverted. The guard was tightened to require one storage route owner plus one final page-normalization call, then the full suite passed.', r18, 'state R18')
t = one(t, 'modalBody MutationObserver lifecycle + bounded 100ms cleanup timer\nolder base/global render generations still reachable through delegates', 'modalBody MutationObserver lifecycle\nolder base/global render generations still reachable through delegates', 'state remaining')
t = one(t, '1. modalBody MutationObserver + bounded 100ms cleanup timer lifecycle audit', '1. modalBody MutationObserver lifecycle audit', 'state work order')
p.write_text(t, encoding='utf-8')

# Legacy audit
p = DOCS[1]; t = p.read_text(encoding='utf-8')
t = one(t, 'commit:       f5b8ff8789de0f51d2a03bcabe126191005ba24c', f'commit:       {ACCEPT}', 'audit accept')
t = one(t, 'run:          34669152742', f'run:          {RUN}', 'audit run')
t = one(t, 'app.js                    42.25.74', 'app.js                    42.25.75', 'audit app cache')
t = one(t, 'main.mjs                  42.25.79', 'main.mjs                  42.25.80', 'audit main cache')
t = one(t, 'v35/v36/V37 80/100/120ms startup render/version timers\noldZip412', 'v35/v36/V37 80/100/120ms startup render/version timers\nbounded 100ms renderTop/cleanup startup timer\noldZip412', 'audit retired')
t = one(t, 'Final startup remains owned by `queueMicrotask → final __clInit`. The separate bounded cleanup timer that calls `renderTop(); cleanup(document);` at 100ms is intentionally retained.', 'Final startup remains owned by `queueMicrotask → final __clInit`. The separate 100ms `renderTop(); cleanup(document)` wakeup was later retired in R18 after final-render normalization ownership was proven.', 'audit R15 note')
t = append_after(t, 'The first full validation correctly exposed one stale structure-bound storage-owner unit assertion; the product behavior was not reverted. The guard was tightened to require one storage route owner plus one final page-normalization call, then the full suite passed.', r18, 'audit R18')
t = one(t, 'modalBody MutationObserver lifecycle + bounded 100ms cleanup timer\nolder base/global render generations reached through delegates', 'modalBody MutationObserver lifecycle\nolder base/global render generations reached through delegates', 'audit remaining')
t = one(t, 'modal observer + bounded cleanup timer lifecycle audit\nloadAll / loadRelated / loadCore412 ownership', 'modal observer lifecycle audit\nloadAll / loadRelated / loadCore412 ownership', 'audit targets')
t = one(t, '1. modalBody MutationObserver + bounded 100ms cleanup timer lifecycle audit', '1. modalBody MutationObserver lifecycle audit', 'audit work order')
t = one(t, 'Current accepted Real Chrome suite: **19/19** in run `34669152742`.', f'Current accepted Real Chrome suite: **19/19** in run `{RUN}`.', 'audit run sentence')
p.write_text(t, encoding='utf-8')

# Owner map
p = DOCS[2]; t = p.read_text(encoding='utf-8')
t = one(t, 'Latest fully accepted code point: `f5b8ff8789de0f51d2a03bcabe126191005ba24c` / run `34669152742`', f'Latest fully accepted code point: `{ACCEPT}` / run `{RUN}`', 'map accept')
t = one(t, '| R17 | page baseRender/RAF wrapper + `#view` normalization observer | `f5b8ff87...` / `34669152742` |', '| R17 | page baseRender/RAF wrapper + `#view` normalization observer | `f5b8ff87...` / `34669152742` |\n| R18 | bounded 100ms `renderTop/cleanup` startup wakeup | `954e9dba...` / `34670319479` |', 'map row')
t = append_after(t, 'The early page normalization wrapper, RAF cleanup and `#view` observer are permanently retired; `#modalBody` remains independent.', r18, 'map R18')
t = one(t, 'v35/v36/V37 80/100/120ms startup render/version timers\n```', 'v35/v36/V37 80/100/120ms startup render/version timers\nbounded 100ms renderTop/cleanup startup timer\n```', 'map retired')
t = one(t, 'modalBody MutationObserver lifecycle + bounded 100ms cleanup timer\nolder base/global render generations still reachable through delegates', 'modalBody MutationObserver lifecycle\nolder base/global render generations still reachable through delegates', 'map remaining')
t = one(t, 'Current accepted Real Chrome suite: **19/19** in run `34669152742`.', f'Current accepted Real Chrome suite: **19/19** in run `{RUN}`.', 'map run')
p.write_text(t, encoding='utf-8')

# Debt ledger
p = DOCS[3]; t = p.read_text(encoding='utf-8')
t = one(t, '**最近完整代码验收点：`f5b8ff8789de0f51d2a03bcabe126191005ba24c`**', f'**最近完整代码验收点：`{ACCEPT}`**', 'debt accept')
t = one(t, '**Frontend Runtime Stabilization：run `34669152742`，frontend 179/179 + Real Chrome 19/19 全绿。**', f'**Frontend Runtime Stabilization：run `{RUN}`，frontend + Real Chrome 全绿，Real Chrome 19/19 passed。**', 'debt run')
t = one(t, 'v35/v36/V37 80/100/120ms startup render/version timers\noldZip412', 'v35/v36/V37 80/100/120ms startup render/version timers\nbounded 100ms renderTop/cleanup startup timer\noldZip412', 'debt retired')
t = one(t, '| page normalization baseRender/RAF/view observer | final `PostRenderNormalizationRuntime.apply` | **CLOSED (R17)** |', '| page normalization baseRender/RAF/view observer | final `PostRenderNormalizationRuntime.apply` | **CLOSED (R17)** |\n| bounded 100ms startup cleanup timer | final `__clInit → render → PostRenderNormalizationRuntime` | **CLOSED (R18)** |', 'debt status')
t = one(t, 'modalBody MutationObserver lifecycle + bounded 100ms cleanup timer\nolder base/global render generations still reachable through delegates', 'modalBody MutationObserver lifecycle\nolder base/global render generations still reachable through delegates', 'debt remaining')
t = one(t, 'app.js cache                     42.25.74', 'app.js cache                     42.25.75', 'debt app cache')
t = one(t, 'main.mjs cache                   42.25.79', 'main.mjs cache                   42.25.80', 'debt main cache')
t = one(t, '- bounded `setTimeout(()=>{renderTop();cleanup(document);},100)` 是独立 cleanup owner，不得与已退休 startup render timer 混淆。', '- bounded `setTimeout(()=>{renderTop();cleanup(document);},100)` 已在 R18 退休，不得回归；startup/page normalization 均由 readiness-aware final render owner 承担。', 'debt timer contract')
t = append_after(t, 'The first full validation correctly exposed one stale structure-bound storage-owner unit assertion; the product behavior was not reverted. The guard was tightened to require one storage route owner plus one final page-normalization call, then the full suite passed.', r18, 'debt R18')
p.write_text(t, encoding='utf-8')

if (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt changed unexpectedly')
for p in DOCS:
    s = p.read_text(encoding='utf-8')
    if ACCEPT not in s or RUN not in s or 'R18' not in s:
        raise SystemExit(f'R18 ledger sync incomplete: {p}')
print('R18 ledgers synchronized')
