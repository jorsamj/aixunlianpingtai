from pathlib import Path

APP = Path("static/app.js")
RUNTIME = Path("static/modules/training-draft-runtime.js")
TEST = Path("tests/frontend/training-draft-runtime.test.mjs")
MAIN = Path("static/main.mjs")


def replace_exact(text: str, old: str, new: str, expected: int, label: str) -> str:
    count = text.count(old)
    if count == 0 and text.count(new) >= expected:
        print(f"{label} already migrated")
        return text
    if count != expected:
        raise SystemExit(f"expected {expected} {label} occurrence(s), found {count}")
    print(f"migrated {label}: {count}")
    return text.replace(old, new)


def migrate_runtime() -> None:
    text = RUNTIME.read_text(encoding="utf-8")
    old = """    sync,\n    update,\n    current() { return state().trainingDraft || sync(); },\n    inheritance() { return state().trainingDraftInheritance || inheritanceFor(state()); },"""
    new = """    sync,\n    update,\n    current() { return state().trainingDraft || sync(); },\n    materialIds() {\n      const draft = state().trainingDraft || sync();\n      return [...(draft?.materialIds || [])];\n    },\n    setMaterialIds(ids = []) {\n      const normalized = [...new Set((ids || []).map(value => String(value || '').trim()).filter(Boolean))];\n      return update({materialIds: normalized});\n    },\n    toggleMaterialId(id) {\n      const value = String(id || '').trim();\n      if (!value) return state().trainingDraft || sync();\n      const selected = new Set(runtime.materialIds());\n      if (selected.has(value)) selected.delete(value);\n      else selected.add(value);\n      return runtime.setMaterialIds([...selected]);\n    },\n    inheritance() { return state().trainingDraftInheritance || inheritanceFor(state()); },"""
    text = replace_exact(text, old, new, 1, "TrainingDraftRuntime material selection API")
    RUNTIME.write_text(text, encoding="utf-8")


def migrate_app() -> None:
    text = APP.read_text(encoding="utf-8")

    select_all_old = "window.trainSelectAll412=function(mode){const q=(document.getElementById('tr429Q')?.value||'').toLowerCase(),labs=[...(state.train429PickerLabels||new Set())],rows=(state.images||[]).filter(x=>isProcessed412(x)&&x.annotated&&(!q||String(x.filename).toLowerCase().includes(q))&&(!labs.length||labs.some(l=>(x.labels||[]).includes(l))));rows.forEach(x=>mode==='invert'?(state.train429Selected.has(x.id)?state.train429Selected.delete(x.id):state.train429Selected.add(x.id)):state.train429Selected.add(x.id));renderTrainPicker429()};"
    select_all_new = "window.trainSelectAll412=function(mode){const q=(document.getElementById('tr429Q')?.value||'').toLowerCase(),labs=[...(state.train429PickerLabels||new Set())],rows=(state.images||[]).filter(x=>isProcessed412(x)&&x.annotated&&(!q||String(x.filename).toLowerCase().includes(q))&&(!labs.length||labs.some(l=>(x.labels||[]).includes(l)))),selected=new Set(window.TrainingDraftRuntime?.materialIds?.()||[]);rows.forEach(x=>{const id=String(x.id);if(mode==='invert'){selected.has(id)?selected.delete(id):selected.add(id)}else selected.add(id)});window.TrainingDraftRuntime?.setMaterialIds?.([...selected]);renderTrainPicker429()};"
    text = replace_exact(text, select_all_old, select_all_new, 1, "picker select-all/invert")

    replacements = [
        ("state init", "  state.train429Selected=state.train429Selected||new Set();\n", "", 1),
        ("final 429 start reset", "});state.train429Selected=new Set();modal(`训练 · ${a.name}`", "});modal(`训练 · ${a.name}`", 1),
        ("summary/count reads", "${state.train429Selected.size} 张", "${window.TrainingDraftRuntime?.materialIds?.().length||0} 张", 2),
        ("selected label source", "function selectedLabels429(){const ids=state.train429Selected,l=new Set();", "function selectedLabels429(){const ids=new Set(window.TrainingDraftRuntime?.materialIds?.()||[]),l=new Set();", 1),
        ("picker selected state", "state.train429Selected.has(x.id)", "(window.TrainingDraftRuntime?.materialIds?.()||[]).includes(String(x.id))", 2),
        ("picker toggle", "window.toggleTrainImage429=function(id){state.train429Selected.has(id)?state.train429Selected.delete(id):state.train429Selected.add(id);renderTrainPicker429()};", "window.toggleTrainImage429=function(id){window.TrainingDraftRuntime?.toggleMaterialId?.(id);renderTrainPicker429()};", 1),
        ("quality direct ids", "const ids=[...state.train429Selected];", "const ids=window.TrainingDraftRuntime?.materialIds?.()||[];", 1),
        ("quality fallback ids", "const ids=[...(state.train429Selected||new Set())];", "const ids=window.TrainingDraftRuntime?.materialIds?.()||[];", 2),
        ("projected count", "const total=state.train429Selected?.size||0", "const total=window.TrainingDraftRuntime?.materialIds?.().length||0", 1),
        ("iteration wrapper reset", "pending=baseStartTraining417?.(aid);state.train429Selected=new Set();if(latest)", "pending=baseStartTraining417?.(aid);if(latest)", 1),
    ]
    for label, old, new, expected in replacements:
        text = replace_exact(text, old, new, expected, label)

    if "train429Selected" in text:
        lines = [line.strip() for line in text.splitlines() if "train429Selected" in line]
        raise SystemExit(f"train429Selected remains in active app.js: {lines[:10]}")

    APP.write_text(text, encoding="utf-8")


def migrate_test() -> None:
    text = TEST.read_text(encoding="utf-8")
    marker = "test('legacy state is consumed once only when canonical draft is absent', () => {"
    if "material selection helpers mutate only canonical materialIds" not in text:
        if text.count(marker) != 1:
            raise SystemExit("training draft runtime test insertion marker missing")
        block = """test('material selection helpers mutate only canonical materialIds', () => {\n  setupDom();\n  const state = {\n    train429Selected: new Set(['legacy-only']),\n    trainingDraft: createTrainingDraft({\n      algorithmId: 'alg-1', materialIds: ['a', 'b'],\n      splitMode: 'random_test_from_training_pool', experimentPercent: 20,\n      validationPercent: 20, newLabelCodes: ['fire'],\n    }),\n    algorithms: [{id: 'alg-1', versions: []}],\n  };\n  globalThis.window = {fetch: async () => ({ok: true})};\n\n  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});\n  assert.deepEqual(runtime.materialIds(), ['a', 'b']);\n  runtime.toggleMaterialId('b');\n  assert.deepEqual(runtime.materialIds(), ['a']);\n  runtime.toggleMaterialId('c');\n  assert.deepEqual(runtime.materialIds(), ['a', 'c']);\n  runtime.setMaterialIds(['x', 'x', 'y']);\n  assert.deepEqual(state.trainingDraft.materialIds, ['x', 'y']);\n  assert.deepEqual([...state.train429Selected], ['legacy-only']);\n\n  cleanup(runtime);\n});\n\n"""
        text = text.replace(marker, block + marker, 1)
    TEST.write_text(text, encoding="utf-8")


def migrate_main() -> None:
    text = MAIN.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        "./modules/training-draft-runtime.js?v=422509",
        "./modules/training-draft-runtime.js?v=422510",
        1,
        "training draft runtime module cache",
    )
    MAIN.write_text(text, encoding="utf-8")


def main() -> None:
    migrate_runtime()
    migrate_app()
    migrate_test()
    migrate_main()
    print("train429Selected active mirror retirement complete")


if __name__ == "__main__":
    main()
