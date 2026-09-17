from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def patch_app() -> None:
    path = ROOT / "app.py"
    text = path.read_text(encoding="utf-8")
    if "external_algorithm_platform_router" in text:
        return

    replacements = [
        (
            '''@app.post("/api/v12/projects/{project_id}/algorithms")
def v12_create_algorithm(project_id: str, payload: AlgorithmReq):
    get_project(project_id)
    item = create_algorithm_asset(algorithms_file(project_id), payload.model_dump(), now_iso())
''',
            '''@app.post("/api/v12/projects/{project_id}/algorithms")
def v12_create_algorithm(project_id: str, payload: AlgorithmReq):
    get_project(project_id)
    assert_local_algorithm_create_allowed(DATA_DIR)
    item = create_algorithm_asset(algorithms_file(project_id), payload.model_dump(), now_iso())
''',
            "algorithm create guard",
        ),
        (
            '''@app.put("/api/v12/projects/{project_id}/algorithms/{algorithm_id}")
def v12_update_algorithm(project_id: str, algorithm_id: str, payload: AlgorithmReq):
    item = update_algorithm_asset(algorithms_file(project_id), algorithm_id, payload.model_dump(), now_iso())
''',
            '''@app.put("/api/v12/projects/{project_id}/algorithms/{algorithm_id}")
def v12_update_algorithm(project_id: str, algorithm_id: str, payload: AlgorithmReq):
    assert_algorithm_mutable(algorithms_file(project_id), algorithm_id)
    item = update_algorithm_asset(algorithms_file(project_id), algorithm_id, payload.model_dump(), now_iso())
''',
            "algorithm update guard",
        ),
        (
            '''@app.delete("/api/v12/projects/{project_id}/algorithms/{algorithm_id}")
def v12_delete_algorithm(project_id: str, algorithm_id: str):
    delete_algorithm_asset(algorithms_file(project_id), algorithm_id)
''',
            '''@app.delete("/api/v12/projects/{project_id}/algorithms/{algorithm_id}")
def v12_delete_algorithm(project_id: str, algorithm_id: str):
    assert_algorithm_mutable(algorithms_file(project_id), algorithm_id)
    delete_algorithm_asset(algorithms_file(project_id), algorithm_id)
''',
            "algorithm delete guard",
        ),
    ]
    for old, new, label in replacements:
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{label}: expected exactly one marker, found {count}")
        text = text.replace(old, new, 1)

    job_marker = '''        "asset_algorithm_name": (asset_algorithm or {}).get("name", ""),
'''
    job_insertion = '''        "asset_algorithm_name": (asset_algorithm or {}).get("name", ""),
        "asset_algorithm_source_type": (asset_algorithm or {}).get("source_type", "LOCAL"),
        "external_provider": (asset_algorithm or {}).get("provider_type", ""),
        "external_product_id": (asset_algorithm or {}).get("external_product_id", ""),
        "external_analysis_id": (asset_algorithm or {}).get("external_analysis_id", ""),
        "external_category_id": (asset_algorithm or {}).get("external_category_id", ""),
'''
    if text.count(job_marker) < 1:
        raise SystemExit("training external mapping marker not found")
    text = text.replace(job_marker, job_insertion, 1)

    bottom = '''from platform_core.material_batches import material_batch_router

app.include_router(material_batch_router(
    get_project, material_store, shared_task_repository, shared_task_artifacts,
))
'''
    external = '''from platform_core.external_algorithm_platform import (
    assert_algorithm_mutable,
    assert_local_algorithm_create_allowed,
    external_algorithm_platform_router,
)
from platform_core.material_batches import material_batch_router

app.include_router(external_algorithm_platform_router(
    data_dir=DATA_DIR,
    get_project=get_project,
    algorithms_file=algorithms_file,
    secret_store_factory=_v35_secret_store,
))
app.include_router(material_batch_router(
    get_project, material_store, shared_task_repository, shared_task_artifacts,
))
'''
    if text.count(bottom) != 1:
        raise SystemExit(f"router marker: expected exactly one marker, found {text.count(bottom)}")
    text = text.replace(bottom, external, 1)
    path.write_text(text, encoding="utf-8")


def patch_main() -> None:
    path = ROOT / "static" / "main.mjs"
    text = path.read_text(encoding="utf-8")
    if "installExternalAlgorithmPlatformRuntime" in text:
        return
    import_marker = "import {installAlgorithmListRuntime} from './modules/algorithm-list-runtime.js?v=422503';\n"
    import_replacement = import_marker + "import {installExternalAlgorithmPlatformRuntime} from './modules/external-algorithm-platform.js?v=63001';\n"
    if text.count(import_marker) != 1:
        raise SystemExit("main import marker mismatch")
    text = text.replace(import_marker, import_replacement, 1)

    runtime_marker = '''window.PlatformCore.runtime.algorithmListRuntime = algorithmListRuntime;

const trainingRecoveryRuntime = installTrainingRecoveryRuntime({
'''
    runtime_replacement = '''window.PlatformCore.runtime.algorithmListRuntime = algorithmListRuntime;

const externalAlgorithmPlatformRuntime = installExternalAlgorithmPlatformRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify,
  algorithmListRuntime,
});
window.PlatformCore.runtime.externalAlgorithmPlatformRuntime = externalAlgorithmPlatformRuntime;

const trainingRecoveryRuntime = installTrainingRecoveryRuntime({
'''
    if text.count(runtime_marker) != 1:
        raise SystemExit("main runtime marker mismatch")
    text = text.replace(runtime_marker, runtime_replacement, 1)
    path.write_text(text, encoding="utf-8")


def patch_index() -> None:
    path = ROOT / "static" / "index.html"
    text = path.read_text(encoding="utf-8")
    old = '<script type="module" src="/static/main.mjs?v=42.25.99"></script>'
    new = '<script type="module" src="/static/main.mjs?v=42.25.100"></script>'
    if new in text:
        return
    if text.count(old) != 1:
        raise SystemExit("index main cache marker mismatch")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    patch_app()
    patch_main()
    patch_index()
    print("external algorithm platform phase 1 migration applied")
