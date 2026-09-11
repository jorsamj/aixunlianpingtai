from pathlib import Path

APP = Path("static/app.js")

MIGRATIONS = (
    (
        "resource source",
        "const c=state.train428Config||(state.train428Config={}),report=state.trainingDevicesV3||{},options=report.options||[],field=document.createElement('section');",
        "const resource=state.trainingDraft?.resource||{},report=state.trainingDevicesV3||{},options=report.options||[],field=document.createElement('section');",
    ),
    (
        "device/gpu mirror writers",
        "panel.before(field);field.querySelector('#trV3Device').value=c.device||report.recommended||'auto';field.querySelector('#trV3GpuPolicy').value=c.gpu_policy||'auto';\n    field.querySelector('#trV3Device').addEventListener('change',event=>{c.device=event.target.value});\n    field.querySelector('#trV3GpuPolicy').addEventListener('change',event=>{c.gpu_policy=event.target.value});",
        "panel.before(field);field.querySelector('#trV3Device').value=resource.device||report.recommended||'auto';field.querySelector('#trV3GpuPolicy').value=resource.gpuPolicy||'auto';",
    ),
    (
        "resource strategy mirror writer",
        "field.querySelector('select').value=state.train428Config?.resource_strategy||'auto';\n      field.querySelector('select').addEventListener('change',event=>{state.train428Config=state.train428Config||{};state.train428Config.resource_strategy=event.target.value});",
        "field.querySelector('select').value=state.trainingDraft?.resource?.strategy||'auto';",
    ),
    (
        "recommended device mirror writer",
        "const result=await previousStart?.(aid);state.train428Config=state.train428Config||{};state.train428Config.device=state.trainingDevicesV3.recommended||'auto';[40,140,340,650].forEach(delay=>setTimeout(renderSplit,delay));return result",
        "const result=await previousStart?.(aid);const recommendedDevice=state.trainingDevicesV3.recommended||'auto';window.TrainingDraftRuntime?.update?.({resource:{device:recommendedDevice}});const deviceSelect=document.getElementById('trV3Device');if(deviceSelect)deviceSelect.value=recommendedDevice;[40,140,340,650].forEach(delay=>setTimeout(renderSplit,delay));return result",
    ),
)

FORBIDDEN = (
    "state.train428Config.resource_strategy=event.target.value",
    "c.device=event.target.value",
    "c.gpu_policy=event.target.value",
    "state.train428Config.device=state.trainingDevicesV3.recommended",
)


def main() -> None:
    text = APP.read_text(encoding="utf-8")
    changed = False
    for name, old, new in MIGRATIONS:
        old_count = text.count(old)
        new_count = text.count(new)
        if old_count == 0 and new_count == 1:
            print(f"{name} already migrated")
            continue
        if old_count != 1:
            raise SystemExit(f"expected exactly one {name} legacy snippet, found {old_count}")
        if new_count:
            raise SystemExit(f"{name} replacement already exists while legacy snippet remains")
        text = text.replace(old, new, 1)
        changed = True
        print(f"migrated {name}")

    leftovers = [token for token in FORBIDDEN if token in text]
    if leftovers:
        raise SystemExit(f"legacy train-v3 resource mirror writers remain: {leftovers}")

    if changed:
        APP.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
