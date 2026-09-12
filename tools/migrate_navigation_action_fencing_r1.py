from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'static' / 'app.js'
NAV = ROOT / 'static' / 'modules' / 'navigation-stability.js'
MAIN = ROOT / 'static' / 'main.mjs'
INDEX = ROOT / 'static' / 'index.html'
WORKFLOW = ROOT / '.github' / 'workflows' / 'frontend-runtime-stabilization.yml'


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly one match, got {count}')
    return text.replace(old, new, 1)


nav = NAV.read_text(encoding='utf-8')
if 'action(ownerPage = currentState().page)' in nav:
    raise SystemExit('Navigation action fence API already exists; baseline is not clean')
needle = "    repairCurrentPage() {\n      notify?.('旧页面结果已被拦截');\n      return false;\n    },"
action_api = """    action(ownerPage = currentState().page) {
      const normalizedOwner = normalizeNavigationPage(ownerPage || currentState().page || '');
      const token = guard.token(normalizedOwner);
      const current = () => guard.isCurrent(token, normalizeNavigationPage(currentState().page || ''));
      return Object.freeze({
        token,
        ownerPage: normalizedOwner,
        isCurrent: current,
        commit(effect) {
          if (!current()) return false;
          if (typeof effect === 'function') effect();
          return true;
        },
      });
    },
    repairCurrentPage() {
      notify?.('旧页面结果已被拦截');
      return false;
    },"""
nav = replace_once(nav, needle, action_api, 'navigation action API')
NAV.write_text(nav, encoding='utf-8')

app = APP.read_text(encoding='utf-8')
old_save_server = "window.saveServer=async()=>{await safe(api('/api/train_servers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#sname').value||'训练服务器',base_url:$('#surl').value})}));closeModal();const opts=await safe(api(`/api/training_options?project_id=${pid()}`));if(opts)state.targets=opts.targets||[];render();toast('已保存服务器')};"
new_save_server = "window.saveServer=async()=>{const action=window.NavigationStability?.action?.(state.page);const saved=await safe(api('/api/train_servers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#sname').value||'训练服务器',base_url:$('#surl').value})}));if(!saved||(action&&!action.isCurrent()))return;closeModal();const opts=await safe(api(`/api/training_options?project_id=${pid()}`));if(action&&!action.isCurrent())return;if(opts)state.targets=opts.targets||[];render();toast('已保存服务器')};"
app = replace_once(app, old_save_server, new_save_server, 'saveServer action fence')

app = replace_once(
    app,
    "  window.detectPaddle=async function(){\n    const btn=window.event?.currentTarget; setBtnBusy(btn,true,'检测中'); state.resourceBusy=true;",
    "  window.detectPaddle=async function(){\n    const action=window.NavigationStability?.action?.(state.page);\n    const btn=window.event?.currentTarget; setBtnBusy(btn,true,'检测中'); state.resourceBusy=true;",
    'detectPaddle capture',
)
app = replace_once(
    app,
    "      await api('/api/paddle_env/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});\n      const r=await api('/api/paddle_env/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});\n      if(box)box.textContent=`paddle=${r.modules?.paddle||'-'}，PaddleDetection=${r.paddledet_exists?'存在':'未找到'}`;\n      await refreshPaddleTrainingTargets20d(); state.page='训练资源'; render(); toast('飞桨环境已启用');",
    "      await api('/api/paddle_env/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});\n      if(action&&!action.isCurrent())return;\n      const r=await api('/api/paddle_env/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});\n      if(action&&!action.isCurrent())return;\n      if(box)box.textContent=`paddle=${r.modules?.paddle||'-'}，PaddleDetection=${r.paddledet_exists?'存在':'未找到'}`;\n      await refreshPaddleTrainingTargets20d();\n      if(action&&!action.isCurrent())return;\n      await window.setPage?.('训练资源'); toast('飞桨环境已启用');",
    'detectPaddle completion',
)
app = replace_once(
    app,
    "  window.quickPaddleDetect=async function(){\n    const btn=window.event?.currentTarget; setBtnBusy(btn,true,'扫描中');",
    "  window.quickPaddleDetect=async function(){\n    const action=window.NavigationStability?.action?.(state.page);\n    const btn=window.event?.currentTarget; setBtnBusy(btn,true,'扫描中');",
    'quickPaddle capture',
)
app = replace_once(
    app,
    "      const r=await api('/api/paddle_env/detect',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});\n      const env=(r?.candidates||[])[0]; if(!env)throw new Error('未检测到飞桨环境');\n      await api('/api/paddle_env/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(env)});\n      await refreshPaddleTrainingTargets20d(); state.page='训练资源'; render(); toast('已启用飞桨环境');",
    "      const r=await api('/api/paddle_env/detect',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});\n      if(action&&!action.isCurrent())return;\n      const env=(r?.candidates||[])[0]; if(!env)throw new Error('未检测到飞桨环境');\n      await api('/api/paddle_env/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(env)});\n      if(action&&!action.isCurrent())return;\n      await refreshPaddleTrainingTargets20d();\n      if(action&&!action.isCurrent())return;\n      await window.setPage?.('训练资源'); toast('已启用飞桨环境');",
    'quickPaddle completion',
)

pattern = re.compile(r"  window\.saveModelConfigV35=async function\(id=''\)\{.*?\n  \};\n  window\.deleteModelConfigV35", re.S)
match = pattern.search(app)
if not match:
    raise SystemExit('saveModelConfigV35 owner not found')
old = match.group(0)
new = """  window.saveModelConfigV35=async function(id=''){
    const action=window.NavigationStability?.action?.(state.page);
    const body={name:$('#mcName').value,provider_type:$('#mcProvider').value,detect_url:$('#mcUrl').value,health_url:$('#mcHealth').value,model_name:$('#mcModel').value,request_mode:$('#mcMode').value,image_field:$('#mcImageField').value,prompt_field:$('#mcPromptField').value,api_key:$('#mcApiKey').value,remark:$('#mcRemark').value,model_kind:'vision_detect'};
    const saved=await safe(api(id?`/api/v35/model-configs/${id}`:'/api/v35/model-configs',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));
    if(!saved||(action&&!action.isCurrent()))return;
    closeModal();await loadAll();
    if(action&&!action.isCurrent())return;
    await window.setPage?.('模型配置');toast('已保存模型配置');
  };
  window.deleteModelConfigV35"""
app = app[:match.start()] + new + app[match.end():]

app = replace_once(
    app,
    "  window.startDeployVersion=(aid,vid)=>{state.deployPresetSourceId=`version::${aid}::${vid}`;closeModal();state.page='部署转换';state.deployLoaded=false;render()};",
    "  window.startDeployVersion=(aid,vid)=>{state.deployPresetSourceId=`version::${aid}::${vid}`;closeModal();state.deployLoaded=false;return window.setPage?.('部署转换')};",
    'deployment navigation owner',
)
app = replace_once(
    app,
    "  window.startAlgorithmTraining423=function(id){state.page='训练任务';render();setTimeout(()=>openTrain425(id),30)};",
    "  window.startAlgorithmTraining423=function(id){window.setPage?.('训练任务');setTimeout(()=>{if(state.page==='训练任务')openTrain425(id)},30)};",
    'training navigation owner',
)
app = replace_once(
    app,
    "    if(state.page==='新建算法'||state.page==='自动迭代')state.page='算法列表';",
    "    if(state.page==='新建算法'||state.page==='自动迭代'){window.setPage?.('算法列表');return}",
    'legacy renderer direct navigation',
)

for page in ('训练资源', '模型配置', '部署转换', '训练任务'):
    if re.search(rf"state\.page\s*=\s*['\"]{re.escape(page)}['\"]", app):
        raise SystemExit(f'direct fixed-page business write remains: {page}')
if "if(state.page==='新建算法'||state.page==='自动迭代')state.page='算法列表'" in app:
    raise SystemExit('legacy renderer direct page rewrite remains')
APP.write_text(app, encoding='utf-8')

main = MAIN.read_text(encoding='utf-8')
main = replace_once(main, "./modules/navigation-stability.js?v=422511", "./modules/navigation-stability.js?v=422512", 'navigation module cache')
MAIN.write_text(main, encoding='utf-8')

index = INDEX.read_text(encoding='utf-8')
index = replace_once(index, "/static/app.js?v=42.25.87", "/static/app.js?v=42.25.88", 'app cache')
index = replace_once(index, "/static/main.mjs?v=42.25.88", "/static/main.mjs?v=42.25.89", 'main cache')
INDEX.write_text(index, encoding='utf-8')

workflow = WORKFLOW.read_text(encoding='utf-8')
guard_anchor = "      - name: Frontend unit tests\n        run: node --test tests/frontend/*.test.mjs"
guard = """      - name: Navigation action fencing guard
        run: |
          node --test tests/frontend/navigation-action-fencing.test.mjs
          python - <<'PY'
          import re
          from pathlib import Path
          app = Path('static/app.js').read_text(encoding='utf-8')
          for page in ('训练资源', '模型配置', '部署转换', '训练任务'):
              if re.search(rf"state\\.page\\s*=\\s*['\\\"]{re.escape(page)}['\\\"]", app):
                  raise SystemExit(f'direct fixed-page business write reintroduced: {page}')
          nav = Path('static/modules/navigation-stability.js').read_text(encoding='utf-8')
          if 'action(ownerPage = currentState().page)' not in nav:
              raise SystemExit('NavigationStability action fence API is missing')
          PY
      - name: Frontend unit tests
        run: node --test tests/frontend/*.test.mjs"""
workflow = replace_once(workflow, guard_anchor, guard, 'permanent action fence guard')
workflow = replace_once(
    workflow,
    "          tests/browser/navigation-stability.spec.mjs\n          tests/browser/navigation-readiness.spec.mjs",
    "          tests/browser/navigation-stability.spec.mjs\n          tests/browser/navigation-action-fencing.spec.mjs\n          tests/browser/navigation-readiness.spec.mjs",
    'permanent browser action fence suite',
)
WORKFLOW.write_text(workflow, encoding='utf-8')

print('Navigation Action Fencing R1 migration applied')
