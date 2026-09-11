from pathlib import Path

PATH = Path("static/app.js")
text = PATH.read_text(encoding="utf-8")

replacements = [
    (
        "  const freshState=()=>({mode:'random_test_from_training_pool',train:new Set(),test:new Set(),experiment:20,validation:20});\n  const splitState=()=>state.trainSplitV3||(state.trainSplitV3=freshState());",
        "  const splitState=()=>{\n    const draft=state.trainingDraft||{};\n    return {mode:draft.splitMode||'random_test_from_training_pool',train:new Set(draft.materialIds||[]),test:new Set(draft.testMaterialIds||[]),experiment:draft.experimentPercent??20,validation:draft.validationPercent??20};\n  };",
    ),
    (
        "    const s=splitState(),random=s.mode==='random_test_from_training_pool',labels=selectedLabels([...s.train]);state.train429Selected=s.train;",
        "    const s=splitState(),random=s.mode==='random_test_from_training_pool',labels=selectedLabels([...s.train]);",
    ),
    (
        ' oninput="state.trainSplitV3.experiment=Number(this.value)"',
        "",
    ),
    (
        ' oninput="state.trainSplitV3.validation=Number(this.value)"',
        "",
    ),
    (
        "    const s=splitState();state.trainMaterialPickerV3={role,selected:new Set(),labels:new Set(),query:'',page:1,pageSize:80};",
        "    state.trainMaterialPickerV3={role,selected:new Set(),labels:new Set(),query:'',page:1,pageSize:80};",
    ),
    (
        "  window.confirmTrainMaterialPickerV3=function(){const p=state.trainMaterialPickerV3;if(!p)return;const s=splitState();s[p.role]=new Set(p.selected);s[otherRole(p.role)].forEach(id=>s[p.role].has(id)&&s[otherRole(p.role)].delete(id));state.train429Selected=s.train;closeModal();setTimeout(renderSplit,20)};",
        "  window.confirmTrainMaterialPickerV3=function(){\n    const p=state.trainMaterialPickerV3;if(!p)return;\n    if(!window.TrainingDraftRuntime?.update)return toast('训练草稿模块尚未加载，请刷新后重试');\n    const current=splitState(),selected=[...p.selected].map(String),selectedSet=new Set(selected);\n    const patch=p.role==='test'?{materialIds:[...current.train].filter(id=>!selectedSet.has(String(id))),testMaterialIds:selected}:{materialIds:selected,testMaterialIds:[...current.test].filter(id=>!selectedSet.has(String(id)))};\n    window.TrainingDraftRuntime.update(patch);closeModal();setTimeout(renderSplit,20)\n  };",
    ),
    (
        "  window.setTrainSplitModeV3=mode=>{splitState().mode=mode;renderSplit()};",
        "  window.setTrainSplitModeV3=mode=>{\n    if(!window.TrainingDraftRuntime?.update)return toast('训练草稿模块尚未加载，请刷新后重试');\n    const splitMode=mode==='independent_test_set'?'independent_test_set':'random_test_from_training_pool';\n    window.TrainingDraftRuntime.update({splitMode,...(splitMode==='independent_test_set'?{}:{testMaterialIds:[]})});renderSplit()\n  };",
    ),
    (
        "    const result=await previousStart?.(aid);state.train428Config=state.train428Config||{};state.train428Config.device=state.trainingDevicesV3.recommended||'auto';state.trainSplitV3=freshState();state.train429Selected=state.trainSplitV3.train;[40,140,340,650].forEach(delay=>setTimeout(renderSplit,delay));return result",
        "    const result=await previousStart?.(aid);state.train428Config=state.train428Config||{};state.train428Config.device=state.trainingDevicesV3.recommended||'auto';[40,140,340,650].forEach(delay=>setTimeout(renderSplit,delay));return result",
    ),
]

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one match, found {count}: {old[:120]!r}")
    text = text.replace(old, new, 1)

# The active app.js must no longer contain any trainSplitV3 reads or writes after this migration.
if "trainSplitV3" in text:
    locations = [i for i, line in enumerate(text.splitlines(), 1) if "trainSplitV3" in line]
    raise SystemExit(f"trainSplitV3 still present in app.js at lines {locations}")

PATH.write_text(text, encoding="utf-8")
print("migrated final train-v3 split reads/writes to TrainingDraft")
