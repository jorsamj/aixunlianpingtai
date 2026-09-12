from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'static' / 'app.js'
INDEX = ROOT / 'static' / 'index.html'

app = APP.read_text(encoding='utf-8')
marker = 'window.refreshSourceImportTasksV36=async function(){'
start = app.find(marker)
if start < 0:
    raise SystemExit('live refreshSourceImportTasksV36 owner not found')
end = app.find('\n  };', start)
if end < 0:
    raise SystemExit('refreshSourceImportTasksV36 owner end not found')
end += len('\n  };')
owner = app[start:end]

old = """    }else{
      await loadRelated();
    }
"""
new = """    }else{
      await window.refreshLabels414?.(false);
      if(state.page==='数据集')await window.reloadMaterialPage61?.();
    }
"""
if owner.count(old) != 1:
    raise SystemExit(f'expected one terminal broad refresh in live source-import owner, got {owner.count(old)}')
owner = owner.replace(old, new, 1)
app = app[:start] + owner + app[end:]
APP.write_text(app, encoding='utf-8')

index = INDEX.read_text(encoding='utf-8')
old_cache = '/static/app.js?v=42.25.90'
new_cache = '/static/app.js?v=42.25.91'
if index.count(old_cache) != 1:
    raise SystemExit(f'expected one app cache marker {old_cache}')
INDEX.write_text(index.replace(old_cache, new_cache, 1), encoding='utf-8')

print('R20l source-import terminal refresh migrated')
