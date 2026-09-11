from pathlib import Path

APP = Path("static/app.js")

START_OLD = "state.train428AlgorithmId=aid;state.train429Selected=new Set();state.train428Config=cfg429();modal("
START_NEW = "window.TrainingDraftRuntime?.update?.({algorithmId:String(aid),materialIds:[],testMaterialIds:[],splitMode:'random_test_from_training_pool',experimentPercent:20,validationPercent:20,newLabelCodes:[]});state.train429Selected=new Set();modal("

TARGET_OLD = "const c=cfg429();c.device=t?.type==='server'?'0':(t?.recommendation?.device||'cpu');state.train428Config=c;trainAlg429()"
TARGET_NEW = "const c=cfg429();c.device=t?.type==='server'?'0':(t?.recommendation?.device||'cpu');window.TrainingDraftRuntime?.update?.({config:c,resource:{device:c.device}});trainAlg429()"

ALG_OLD = "if(!c.model){const m=(t?.base_models||[])[0];c.model=m?.value||m?.label||''}state.train428Config=c;refreshTrain429()"
ALG_NEW = "if(!c.model){const m=(t?.base_models||[])[0];c.model=m?.value||m?.label||''}window.TrainingDraftRuntime?.update?.({config:c,resource:{batch:c.batch}});refreshTrain429()"

ITERATION_OLD = "state.iteration414?.[state.train428AlgorithmId]"
ITERATION_NEW = "state.iteration414?.[state.trainingDraft?.algorithmId]"

FORBIDDEN_ACTIVE = (
    "state.train428AlgorithmId=aid;state.train429Selected=new Set();state.train428Config=cfg429()",
    "c.device=t?.type==='server'?'0':(t?.recommendation?.device||'cpu');state.train428Config=c;trainAlg429()",
    "c.model=m?.value||m?.label||''}state.train428Config=c;refreshTrain429()",
    "state.iteration414?.[state.train428AlgorithmId]",
)


def replace_one(text: str, old: str, new: str, label: str) -> str:
    old_count = text.count(old)
    new_count = text.count(new)
    if old_count == 0 and new_count == 1:
        print(f"{label} already migrated")
        return text
    if old_count != 1:
        raise SystemExit(f"expected exactly one {label} legacy snippet, found {old_count}")
    if new_count:
        raise SystemExit(f"{label} replacement already exists while legacy snippet remains")
    print(f"migrated {label}")
    return text.replace(old, new, 1)


def main() -> None:
    text = APP.read_text(encoding="utf-8")
    text = replace_one(text, START_OLD, START_NEW, "final 429 training start mirrors")
    text = replace_one(text, TARGET_OLD, TARGET_NEW, "final 429 target config writer")
    text = replace_one(text, ALG_OLD, ALG_NEW, "final 429 engine config writer")
    text = replace_one(text, ITERATION_OLD, ITERATION_NEW, "iteration settings algorithm read")

    leftovers = [token for token in FORBIDDEN_ACTIVE if token in text]
    if leftovers:
        raise SystemExit(f"active legacy training mirror path remains: {leftovers}")

    APP.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
