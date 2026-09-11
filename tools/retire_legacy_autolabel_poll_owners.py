from pathlib import Path

PATH = Path("static/app.js")
text = PATH.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
    "state.auto422Timer=null;",
    "",
    "retire auto422 timer state",
)
replace_once(
    "window.renderAutoLabel422=async function(){await loadAll();clearInterval(state.auto422Timer);const tasks=",
    "window.renderAutoLabel422=async function(){await loadAll();const tasks=",
    "retire auto422 render clear",
)
replace_once(
    "renderAutoRows422();state.auto422Timer=setInterval(()=>{if(state.page==='自动标注')refreshAuto422();else clearInterval(state.auto422Timer)},2500)};",
    "renderAutoRows422()};",
    "retire auto422 interval creation",
)
replace_once(
    "window.setPage=function(p){clearInterval(state.source422Timer);clearInterval(state.auto422Timer);if(p==='新建算法'||p==='自动迭代')p='算法列表';set422Base(p)}",
    "window.setPage=function(p){clearInterval(state.source422Timer);if(p==='新建算法'||p==='自动迭代')p='算法列表';set422Base(p)}",
    "retire auto422 navigation clear",
)
replace_once(
    "if((state.v427OpsTab||'label')==='clean')return previousRenderOps?.();",
    "if((state.v427OpsTab||'label')==='clean'){window.AutoLabelPollRuntime?.deactivate?.();return previousRenderOps?.()}",
    "deactivate managed polling on clean tab",
)
replace_once(
    "    clearTimeout(state.ai60ListTimer);\n",
    "",
    "retire ai60 legacy timeout clear",
)
replace_once(
    "      if(state.annotationTasks60.some(task=>taskView(task).active))state.ai60ListTimer=setTimeout(()=>{if(state.page==='自动标注及清洗'&&(state.v427OpsTab||'label')==='label')renderOps427()},1800);",
    "      window.AutoLabelPollRuntime?.activate?.(state.annotationTasks60);",
    "replace ai60 timer with managed activation",
)

for token in ("auto422Timer", "ai60ListTimer"):
    if token in text:
        raise SystemExit(f"retired AutoLabel timer token remains in static/app.js: {token}")

for token in (
    "window.AutoLabelPollRuntime?.activate?.(state.annotationTasks60);",
    "window.AutoLabelPollRuntime?.deactivate?.();",
):
    if token not in text:
        raise SystemExit(f"expected explicit AutoLabel lifecycle handoff missing: {token}")

PATH.write_text(text, encoding="utf-8")
print("retired legacy AutoLabel polling owners from static/app.js")
