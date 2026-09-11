from pathlib import Path

APP = Path("static/app.js")

DEAD_START = "  function usableTargets428(a){"
SETTINGS_START = "  window.openTrainSettings428=function(){"
SELECTED_TARGET_REPLACEMENT = "  function selectedTarget428(){const id=document.getElementById('tr429Target')?.value||document.getElementById('tr428Target')?.value||'';return(state.targets||[]).find(x=>String(x.id)===String(id))}\n\n"

OLD_CONFIG_READER = "function trainingConfig428(){const draft=state.trainingDraft||{},resource=draft.resource||{},legacy=state.train428Config||{},c=Object.assign(baseCfg428(),legacy,draft.config||{});if(resource.device&&resource.device!=='auto')c.device=resource.device;if(resource.batch!=null)c.batch=resource.batch;if(resource.workers!=null)c.workers=resource.workers;if(resource.cache!=null)c.cache=resource.cache===false?'False':resource.cache;if(resource.strategy)c.resource_strategy=resource.strategy;if(resource.gpuPolicy)c.gpu_policy=resource.gpuPolicy;return c}"
NEW_CONFIG_READER = "function trainingConfig428(){const draft=state.trainingDraft||{},resource=draft.resource||{},c=Object.assign(baseCfg428(),draft.config||{});if(resource.device&&resource.device!=='auto')c.device=resource.device;if(resource.batch!=null)c.batch=resource.batch;if(resource.workers!=null)c.workers=resource.workers;if(resource.cache!=null)c.cache=resource.cache===false?'False':resource.cache;if(resource.strategy)c.resource_strategy=resource.strategy;if(resource.gpuPolicy)c.gpu_policy=resource.gpuPolicy;return c}"

OLD_BASE_SAVE_TAIL = "state.train428Config=c;closeModal();refreshTrain428();toast('训练配置已应用')};"
NEW_BASE_SAVE_TAIL = "window.TrainingDraftRuntime?.update?.({config:c,resource:{batch:c.batch,workers:c.workers,cache:c.cache==='False'?false:c.cache}});closeModal();window.refreshTrain429?.();toast('训练配置已应用')};"

OLD_ADVANCED_SAVE_TAIL = "});state.train428Config=c;return baseSaveSettings415?.()};"
NEW_ADVANCED_SAVE_TAIL = "});window.TrainingDraftRuntime?.update?.({config:c});return baseSaveSettings415?.()};"


def replace_one(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0 and text.count(new) == 1:
        print(f"{label} already migrated")
        return text
    if count != 1:
        raise SystemExit(f"expected one {label}, found {count}")
    print(f"migrated {label}")
    return text.replace(old, new, 1)


def main() -> None:
    text = APP.read_text(encoding="utf-8")

    # The final 429 entrypoint overwrites the old 428 creation route. Keep only the
    # target lookup needed by the still-live settings base UI.
    start = text.find(DEAD_START)
    end = text.find(SETTINGS_START, start + 1 if start >= 0 else 0)
    if start >= 0:
        if end < 0:
            raise SystemExit("old 428 creation block end marker missing")
        block = text[start:end]
        required = [
            "window.openTrain428=function",
            "state.train428AlgorithmId=aid",
            "state.train428Config=baseCfg428()",
            "window.trainTargetChanged428=function",
            "window.trainAlgChanged428=function",
            "function refreshTrain428()",
        ]
        missing = [token for token in required if token not in block]
        if missing:
            raise SystemExit(f"old 428 block shape changed; missing {missing}")
        text = text[:start] + SELECTED_TARGET_REPLACEMENT + text[end:]
        print("retired unreachable 428 training creation block")
    elif SELECTED_TARGET_REPLACEMENT.strip() not in text:
        raise SystemExit("old 428 block already absent but canonical selected-target helper missing")

    text = replace_one(text, OLD_CONFIG_READER, NEW_CONFIG_READER, "canonical-only config reader")
    text = replace_one(text, "  state.train428Config=state.train428Config||null;\n", "", "train428Config state init")
    text = replace_one(text, OLD_BASE_SAVE_TAIL, NEW_BASE_SAVE_TAIL, "base settings canonical save")
    text = replace_one(text, OLD_ADVANCED_SAVE_TAIL, NEW_ADVANCED_SAVE_TAIL, "advanced settings canonical save")

    leftovers = [token for token in ("train428AlgorithmId", "train428Config") if token in text]
    if leftovers:
        lines = [line.strip() for line in text.splitlines() if any(token in line for token in leftovers)]
        raise SystemExit(f"active train428 mirrors remain in app.js: {leftovers}: {lines[:10]}")

    APP.write_text(text, encoding="utf-8")
    print("train428 active mirrors retired from static/app.js")


if __name__ == "__main__":
    main()
