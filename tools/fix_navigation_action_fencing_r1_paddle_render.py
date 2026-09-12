from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'static' / 'app.js'

text = APP.read_text(encoding='utf-8')

replacements = [
    (
        "      await refreshPaddleTrainingTargets20d();\n      if(action&&!action.isCurrent())return;\n      await window.setPage?.('训练资源'); toast('飞桨环境已启用');",
        "      await refreshPaddleTrainingTargets20d();\n      if(action&&!action.isCurrent())return;\n      render(); toast('飞桨环境已启用');",
        'manual Paddle activation',
    ),
    (
        "      await refreshPaddleTrainingTargets20d();\n      if(action&&!action.isCurrent())return;\n      await window.setPage?.('训练资源'); toast('已启用飞桨环境');",
        "      await refreshPaddleTrainingTargets20d();\n      if(action&&!action.isCurrent())return;\n      render(); toast('已启用飞桨环境');",
        'quick Paddle activation',
    ),
]

for old, new, label in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected one exact current owner, found {count}')
    text = text.replace(old, new, 1)

if "state.page='训练资源'" in text:
    raise SystemExit('direct training-resource page mutation reintroduced')
if "await window.setPage?.('训练资源'); toast('飞桨环境已启用');" in text:
    raise SystemExit('manual Paddle activation still performs redundant same-page navigation')
if "await window.setPage?.('训练资源'); toast('已启用飞桨环境');" in text:
    raise SystemExit('quick Paddle activation still performs redundant same-page navigation')

APP.write_text(text, encoding='utf-8')
print('Paddle same-page Action Fencing follow-up applied')
